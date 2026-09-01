"""تنسيق عمل الـRuntime: التفعيل ثم المودل ثم التشغيل.

هذه الوحدة هي **المنطق**، و`api.py` غلاف HTTP رفيع فوقها. الفصل يجعل كل
مسار التفعيل والتنزيل قابلًا للاختبار بلا خادم HTTP ولا منافذ.

**ترتيب الإقلاع:**

1. هل يوجد سرّ جهاز؟ لا ⇒ ``AWAITING_ACTIVATION`` وانتظار رمز من الإضافة.
2. نعم ⇒ اسأل الـBackend عن الاستحقاق. ممنوع ⇒ ``BLOCKED``.
3. مسموح ⇒ هل المودل مثبَّت ومُتحقَّق منه؟ لا ⇒ نزّله.
4. نعم ⇒ شغّل `llama-server` وانتظر جاهزيته ⇒ ``READY``.

**بلا إنترنت أثناء تحديث الاستحقاق:** الـRuntime **لا يتوقف**. اشتراك
تحقّقنا منه قبل ساعة لا يصير باطلًا لأن الشبكة انقطعت الآن، ومنعُ موظف من
العمل بسبب شبكته عقوبةٌ على غير ذنب. يُسجَّل التعذّر ويُعاد المحاولة.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .config import RuntimeConfig
from .control_plane import (
    ControlPlaneClient,
    ControlPlaneError,
    OfflineError,
    SubscriptionBlockedError,
)
from .identity import DeviceIdentity, IdentityError
from .llama_supervisor import LlamaOptions, LlamaSupervisor, SupervisorError
from .model_store import (
    DownloadCancelled,
    ModelArtifact,
    ModelError,
    ModelStore,
)
from .state import Phase, RuntimeState

logger = logging.getLogger(__name__)


def describe_platform() -> str:
    """اسم وصفي للجهاز — **بلا اسم مستخدم ولا معرّف عتاد**."""
    import platform

    release = platform.release() or ""
    return f"حاسب ويندوز {release}".strip()


class RuntimeService:
    """يجمع الهوية والاستحقاق والمودل والمحرّك في مسار واحد."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        identity: DeviceIdentity | None = None,
        control_plane: ControlPlaneClient | None = None,
        model_store: ModelStore | None = None,
        supervisor: LlamaSupervisor | None = None,
    ) -> None:
        self.config = config
        self.state = RuntimeState()

        self._identity = identity or DeviceIdentity(config.data_dir)
        self._control = control_plane or ControlPlaneClient(config.control_plane_url)
        self._models = model_store or ModelStore(
            model_path=config.model_path, part_path=config.part_path
        )
        self._supervisor = supervisor or LlamaSupervisor(
            config.llama_server, LlamaOptions(model_path=config.model_path)
        )
        # ⚠️ `RLock` لا `Lock`: مسار التفعيل المُعاد يستدعي
        # `start_background_preparation` وهو **داخل** القفل، وقفلٌ غير قابل
        # لإعادة الدخول يتجمّد هناك.
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None

    # ------------------------------------------------------------------
    # الهوية
    # ------------------------------------------------------------------
    @property
    def is_activated(self) -> bool:
        try:
            return self._identity.load() is not None
        except IdentityError:
            return False

    def _device_secret(self) -> str | None:
        try:
            return self._identity.load()
        except IdentityError as exc:
            self.state.set(Phase.ERROR, str(exc))
            return None

    # ------------------------------------------------------------------
    # التفعيل
    # ------------------------------------------------------------------
    def activate(self, token: str) -> dict[str, object]:
        """يستبدل رمز التركيب بتفعيل جهاز.

        **يولّد السرّ محليًا أولًا**، فلا يعرف أحد خارج الجهاز قيمته. ولو فشل
        التفعيل يُحذف السرّ الجديد: الاحتفاظ به يترك هوية بلا تفعيل، فيظنّ
        الإقلاع التالي أن الجهاز مفعَّل ويفشل بلا سبب مفهوم.

        Raises:
            ControlPlaneError: بفروعه — رمز مرفوض أو جهاز آخر أو انقطاع.
        """
        with self._lock:
            existing = self._device_secret()
            if existing is not None:
                # مفعَّل أصلًا: العملية مُعادة التنفيذ، والإضافة قد تعيد
                # الإرسال بعد انقطاع بين النجاح ووصول الرد.
                logger.info("طلب تفعيل لجهاز مفعَّل مسبقًا — يُتجاهل بلا خطأ.")
                self._resume_after_activation()
                return self.state.snapshot()

            self.state.set(Phase.ACTIVATING)
            secret = self._identity.create()

            try:
                self._control.activate(
                    token=token,
                    device_secret=secret,
                    device_name=describe_platform(),
                )
            except ControlPlaneError:
                # لا تبقَ هوية بلا تفعيل.
                self._identity.clear()
                self.state.set(Phase.AWAITING_ACTIVATION)
                raise

        logger.info("فُعِّل هذا الجهاز بنجاح.")
        self._resume_after_activation()
        return self.state.snapshot()

    def _resume_after_activation(self) -> None:
        """يبدأ تجهيز المودل في خيط منفصل بعد نجاح التفعيل."""
        self.start_background_preparation()

    # ------------------------------------------------------------------
    # الاستحقاق
    # ------------------------------------------------------------------
    def refresh_entitlement(self) -> bool:
        """يحدّث حالة الاشتراك. يعيد ``True`` إن كان يسمح بالخدمة.

        **الانقطاع ليس منعًا:** تعذّر الوصول يعيد ``True`` ويُسجَّل، فلا
        يتوقف موظف عن العمل لأن شبكته انقطعت.
        """
        secret = self._device_secret()
        if secret is None:
            self.state.set(Phase.AWAITING_ACTIVATION)
            return False

        try:
            entitlement = self._control.entitlement(secret)
        except OfflineError:
            logger.warning("تعذّر تحديث الاستحقاق (لا اتصال) — يستمر العمل.")
            return True
        except SubscriptionBlockedError as exc:
            self.state.set(Phase.BLOCKED, str(exc))
            self._supervisor.stop()
            return False
        except ControlPlaneError as exc:
            # جهاز أُبطل تفعيله: يتوقف المودل ويعود إلى انتظار تفعيل جديد.
            logger.warning("رفض الاستحقاق: %s", exc)
            self._supervisor.stop()
            self.state.set(Phase.BLOCKED, str(exc))
            return False

        self.state.device_name = entitlement.device_name
        self.state.subscription_status = entitlement.status

        if not entitlement.is_usable:
            self._supervisor.stop()
            self.state.set(
                Phase.BLOCKED,
                entitlement.blocked_reason
                or "الاشتراك لا يسمح باستخدام GovMind حاليًا.",
            )
            return False
        return True

    # ------------------------------------------------------------------
    # المودل
    # ------------------------------------------------------------------
    def download_model(self) -> None:
        """ينزّل المودل ويتحقق منه، محدّثًا الحالة خطوة بخطوة."""
        secret = self._device_secret()
        if secret is None:
            self.state.set(Phase.AWAITING_ACTIVATION)
            return

        self.state.set(Phase.DOWNLOADING_MODEL, progress=0)
        try:
            info = self._control.model_artifact(secret)
        except ControlPlaneError as exc:
            self.state.set(Phase.ERROR, str(exc))
            return

        artifact = ModelArtifact(
            download_url=info.download_url,
            file_name=info.file_name,
            sha256=info.sha256,
            size_bytes=info.size_bytes,
        )

        def on_download(progress) -> None:
            self.state.set_progress(
                progress.percent, progress.received, progress.total
            )

        try:
            self._models.download(artifact, on_progress=on_download)
        except DownloadCancelled as exc:
            self.state.set(Phase.MODEL_MISSING, str(exc))
            return
        except ModelError as exc:
            self.state.set(Phase.ERROR, str(exc))
            return

        self.state.set(Phase.VERIFYING_MODEL)
        self.start_model()

    def cancel_download(self) -> None:
        """يلغي التنزيل الجاري. ما نُزّل يبقى ليُستأنف."""
        self._models.cancel()

    # ------------------------------------------------------------------
    # المحرّك
    # ------------------------------------------------------------------
    def start_model(self) -> None:
        """يشغّل `llama-server` وينتظر جاهزيته."""
        if not self._models.is_installed():
            self.state.set(Phase.MODEL_MISSING)
            return

        self.state.set(Phase.STARTING_MODEL)
        try:
            self._supervisor.start()
        except SupervisorError as exc:
            self.state.set(Phase.ERROR, str(exc))
            return
        self.state.set(Phase.READY)

    def stop_model(self) -> None:
        self._supervisor.stop()
        self.state.set(Phase.MODEL_MISSING, "أُوقف المودل.")

    def restart_model(self) -> None:
        self._supervisor.stop()
        self.start_model()

    @property
    def model_base_url(self) -> str | None:
        """عنوان المحرّك المتوافق مع OpenAI — **داخلي، لا يُعرض للعميل**."""
        return self._supervisor.base_url

    # ------------------------------------------------------------------
    # الإقلاع
    # ------------------------------------------------------------------
    def prepare(self) -> None:
        """المسار الكامل من الإقلاع إلى الجاهزية.

        يُستدعى في خيط منفصل: تحميل مودل بالجيجابايتات قد يستغرق دقائق،
        وحجب خيط الخادم طوالها يجعل `/health` نفسه لا يستجيب — وهو ما
        تستطلعه الإضافة لتعرف أن الـRuntime يعمل.
        """
        if not self.is_activated:
            self.state.set(Phase.AWAITING_ACTIVATION)
            return

        if not self.refresh_entitlement():
            return

        if not self._models.is_installed():
            self.download_model()
            return

        self.start_model()

    def start_background_preparation(self) -> None:
        """يبدأ :meth:`prepare` في خيط، ولا يبدأ ثانيًا إن كان يعمل."""
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._guarded_prepare, name="govmind-prepare", daemon=True
            )
            self._worker.start()

    def _guarded_prepare(self) -> None:
        try:
            self.prepare()
        except Exception as exc:  # pragma: no cover - شبكة أمان
            logger.exception("فشل تجهيز الـRuntime")
            self.state.set(
                Phase.ERROR,
                "حدث خطأ غير متوقع أثناء التجهيز. أعد تشغيل GovMind.",
            )
            del exc

    def shutdown(self) -> None:
        """إيقاف نظيف — **لا تُترك عملية ابنة يتيمة**."""
        self._supervisor.stop()
