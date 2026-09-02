"""فتح واجهة GovMind — الجزء الذي كان مفقودًا.

**العطل الذي يعالجه هذا الملف.** كان اختصار «GovMind» في قائمة ابدأ وعلى
سطح المكتب، وكذلك خانة «تشغيل GovMind الآن» بعد التثبيت، تشير كلها إلى
`govmind-runtime.exe` — وهو **خادم بلا نافذة** (`console=False`). فيبدأ
ويحجز منفذًا ويجلس صامتًا. لا متصفح يُفتح، ولا نافذة تظهر، ولا خطأ يُعرض.
المستخدم يضغط الاختصار فلا يحدث شيء **مرئي** إطلاقًا.

لم يكن في الشيفرة كلها استدعاء واحد يفتح متصفحًا.

**الحل: دوران للملف التنفيذي نفسه.**

* بلا وسائط  → وضع الخدمة: يشغّل الخادم ولا يفتح شيئًا (يستعمله بدء
  التشغيل التلقائي).
* `--open`   → وضع الفتح: يجد الخدمة أو يبدأها، ينتظر جاهزيتها، ثم يفتح
  المتصفح على عنوانها المحلي، ثم **ينتهي**.

الاختصارات وخانة ما بعد التثبيت تستعمل `--open`.

⚠️ **لا يكتب المستخدم عنوانًا ولا منفذًا.** العنوان يُكتشف هنا.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

import httpx

logger = logging.getLogger(__name__)

#: المنافذ التي يجرّبها الـRuntime بالترتيب — نفس القائمة في الإضافة.
CANDIDATE_PORTS: tuple[int, ...] = (8765, 8766, 8767, 8768, 8769)

#: مهلة فحص منفذ واحد. منفذ مغلق يُعرف فورًا.
PROBE_TIMEOUT = 1.0

#: أقصى انتظار لبدء الخدمة بعد إطلاقها. الإقلاع البارد يشمل فكّ ضغط
#: PyInstaller وتحميل uvicorn، وقد يبلغ عشرات الثواني على قرص بطيء.
START_TIMEOUT = 60.0

POLL_INTERVAL = 0.5


def find_running_port() -> int | None:
    """يعيد منفذ خدمة GovMind العاملة، أو ``None``.

    التوقيع في الرد ضروري: منفذ قد يشغله برنامج آخر يردّ ٢٠٠ على أي مسار،
    وفتح متصفح عليه يعرض شيئًا ليس GovMind.
    """
    for port in CANDIDATE_PORTS:
        try:
            response = httpx.get(
                f"http://127.0.0.1:{port}/health", timeout=PROBE_TIMEOUT
            )
            if response.status_code == 200:
                body = response.json()
                if body.get("service") == "govmind-runtime":
                    return port
        except Exception:
            continue
    return None


def _service_command() -> list[str]:
    """أمر تشغيل الخدمة، مجمَّعةً كانت أو من المصدر."""
    if getattr(sys, "frozen", False):
        # الملف التنفيذي نفسه، بلا وسائط ⇒ وضع الخدمة.
        return [sys.executable]
    return [sys.executable, "-m", "govmind_runtime"]


def start_service() -> None:
    """يطلق الخدمة في الخلفية منفصلةً عن هذه العملية.

    `DETACHED_PROCESS` مهم: بدونه تموت الخدمة بموت المُطلِق، والمُطلِق هنا
    ينتهي بعد ثوانٍ بمجرد أن يفتح المتصفح.
    """
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = (
            subprocess.CREATE_NO_WINDOW  # بلا نافذة سوداء
            | subprocess.DETACHED_PROCESS  # تعيش بعد انتهائنا
        )

    logger.info("تشغيل خدمة GovMind في الخلفية.")
    subprocess.Popen(
        _service_command(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creation_flags,
        close_fds=True,
    )


def wait_for_service(timeout: float = START_TIMEOUT) -> int | None:
    """ينتظر استجابة الخدمة ويعيد منفذها، أو ``None`` عند انتهاء المهلة."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        port = find_running_port()
        if port is not None:
            return port
        time.sleep(POLL_INTERVAL)
    return None


def open_browser(port: int) -> None:
    """يفتح المتصفح الافتراضي على واجهة GovMind.

    `os.startfile` هو ما يفتح الرابط بالمتصفح الافتراضي على ويندوز بلا أي
    حزمة إضافية. `webbrowser` بديل لبقية الأنظمة وللاختبارات.
    """
    url = f"http://127.0.0.1:{port}/"
    logger.info("فتح واجهة GovMind.")
    if sys.platform == "win32" and hasattr(os, "startfile"):
        os.startfile(url)  # noqa: S606 - عنوان محلي نبنيه نحن
        return

    import webbrowser

    webbrowser.open(url)


def open_ui() -> int:
    """وضع `--open`: يضمن أن الخدمة تعمل ثم يفتح الواجهة.

    Returns:
        رمز خروج العملية: صفر عند النجاح.
    """
    port = find_running_port()

    if port is None:
        start_service()
        port = wait_for_service()

    if port is None:
        # لم تبدأ الخدمة. **رسالة مرئية** لا صمت: الصمت هو العطل الأصلي.
        _report_failure(
            "تعذّر تشغيل GovMind على هذا الجهاز.\n\n"
            "أعد تشغيل الحاسب ثم جرّب مرة أخرى. إن تكرر الأمر فتواصل مع "
            "الدعم، وأرفق ملف السجل:\n"
            r"%ProgramData%\GovMind\logs\runtime.log"
        )
        return 1

    open_browser(port)
    return 0


def _report_failure(message: str) -> None:
    """يعرض الفشل للمستخدم بنافذة، ويسجّله.

    ⚠️ **الفشل الصامت هو العطل الذي نصلحه.** برنامجٌ لا يفتح ولا يقول لماذا
    يترك المستخدم يضغط الاختصار مرارًا — وهو ما حدث فعلًا.
    """
    logger.error(message.replace("\n", " "))
    if sys.platform != "win32":
        print(message, file=sys.stderr)
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None, message, "GovMind", 0x10 | 0x40000  # MB_ICONERROR | MB_TOPMOST
        )
    except Exception:  # pragma: no cover
        print(message, file=sys.stderr)
