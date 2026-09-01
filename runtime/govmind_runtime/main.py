"""نقطة تشغيل GovMind Runtime — بوضعين.

* **بلا وسائط** ⇒ وضع الخدمة: يشغّل الخادم المحلي ولا يفتح شيئًا مرئيًا.
* **`--open`** ⇒ وضع الفتح: يجد الخدمة أو يبدأها، ثم يفتح واجهة GovMind
  في المتصفح، ثم ينتهي. هذا ما تستعمله الاختصارات وخانة ما بعد التثبيت.

**لماذا وضعان؟** كانت الاختصارات تشير إلى الخادم مباشرة، وهو بلا نافذة،
فلا يحدث للمستخدم شيء مرئي حين يضغطها — انظر `opener.py`.

الخادم يبدأ فورًا حتى تجده الإضافة، ثم يجهّز المودل في خيط منفصل: الإضافة
تستطلع `/health` وهي تنتظر، فحجب الخيط الرئيسي دقائق يجعلها تظنّ أن
الـRuntime لم يبدأ.
"""

from __future__ import annotations

import logging
import logging.handlers
import signal
import sys
import threading
import time

import uvicorn

from .api import LocalApi
from .config import RuntimeConfig, load_config
from .llama_supervisor import find_free_port
from .opener import find_running_port, open_ui
from .service import RuntimeService
from .single_instance import SingleInstance

logger = logging.getLogger("govmind_runtime")

#: كل كم ثانية يُعاد فحص الاستحقاق. ساعة: كافية لالتقاط إبطال أو انتهاء
#: اشتراك في وقت معقول، وقليلة بما لا يثقل الخدمة ولا شبكة الجهة.
ENTITLEMENT_INTERVAL_SECONDS = 3600


def configure_logging(config: RuntimeConfig) -> None:
    """سجلّ دوّار في مجلد البيانات.

    ⚠️ **لا يُسجَّل سرّ الجهاز ولا رمز التركيب ولا رابط SAS.** الوحدات
    التي تتعامل معها تكتب أوصافًا لا قيمًا.
    """
    config.log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        config.log_file, maxBytes=2 << 20, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # نافذة الطرفية غير موجودة في التشغيل المجمَّع، فالكتابة إليها تفشل.
    if not getattr(sys, "frozen", False):
        root.addHandler(logging.StreamHandler())


def entitlement_loop(service: RuntimeService, stop: threading.Event) -> None:
    """يعيد فحص الاشتراك دوريًا حتى الإيقاف.

    **لا يوقف الخدمة عند انقطاع الشبكة** — انظر `service.refresh_entitlement`.
    """
    while not stop.wait(ENTITLEMENT_INTERVAL_SECONDS):
        try:
            service.refresh_entitlement()
        except Exception:  # pragma: no cover - شبكة أمان
            logger.exception("فشل تحديث الاستحقاق الدوري")


def main(argv: list[str] | None = None) -> int:
    """يوزّع على الوضعين حسب الوسائط."""
    args = list(sys.argv[1:] if argv is None else argv)

    if "--open" in args:
        config = load_config()
        configure_logging(config)
        return open_ui()

    return run_service()


def run_service() -> int:
    """وضع الخدمة: خادم محلي واحد لا أكثر."""
    config = load_config()
    configure_logging(config)

    # ⚠️ **حارس النسخة الواحدة قبل أي شيء آخر.**
    # بدونه كان كل تشغيل يبدأ خادمًا على المنفذ التالي، فتراكمت على جهاز
    # اختبار خمس نسخ تستمع معًا لأن المستخدم ضغط الاختصار مرارًا ولم ير
    # شيئًا. المنفذ البديل لحالة «منفذ حجزه برنامج آخر» لا لحالة «GovMind
    # يعمل أصلًا».
    guard = SingleInstance()
    if guard.already_running:
        running = find_running_port()
        logger.info(
            "نسخة أخرى من GovMind تعمل بالفعل%s؛ لن تبدأ نسخة ثانية.",
            f" (منفذ {running})" if running else "",
        )
        return 0

    try:
        return _serve(config)
    finally:
        guard.release()


def _serve(config: RuntimeConfig) -> int:

    # منفذ حرّ ابتداءً من المفضَّل: تثبيت آخر أو برنامج غيره قد يحجزه،
    # والفشل بـ«المنفذ مشغول» يترك العميل بلا GovMind بلا سبب مفهوم.
    port = find_free_port(config.port)
    if port != config.port:
        logger.warning("المنفذ المفضَّل مشغول؛ سيُستعمل منفذ بديل.")
        config = RuntimeConfig(
            control_plane_url=config.control_plane_url,
            data_dir=config.data_dir,
            install_root=config.install_root,
            port=port,
        )

    service = RuntimeService(config)
    api = LocalApi(service, config)

    stop = threading.Event()

    def shutdown(*_args: object) -> None:
        logger.info("إيقاف GovMind Runtime…")
        stop.set()
        service.shutdown()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        handler = getattr(signal, name, None)
        if handler is not None:
            try:
                signal.signal(handler, shutdown)
            except (ValueError, OSError):  # pragma: no cover - خيط غير رئيسي
                pass

    # التجهيز في الخلفية: الخادم يجب أن يستجيب لـ`/health` فورًا.
    service.start_background_preparation()
    threading.Thread(
        target=entitlement_loop,
        args=(service, stop),
        name="govmind-entitlement",
        daemon=True,
    ).start()

    logger.info("GovMind Runtime يعمل على الاسترجاع المحلي.")
    try:
        uvicorn.run(
            api.app,
            # ⚠️ الاسترجاع المحلي وحده — لا `0.0.0.0` بحال.
            host="127.0.0.1",
            port=port,
            log_config=None,
            access_log=False,
        )
    finally:
        shutdown()
        # مهلة قصيرة لتنتهي العملية الابنة قبل خروج المفسّر.
        time.sleep(0.2)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
