"""إدارة عملية `llama-server` — البديل الكامل عن LM Studio.

`llama-server` هو خادم llama.cpp الرسمي (رخصة MIT). يعرض واجهة متوافقة مع
OpenAI، فيتحدّث إليه مزوّد المودل بالمنطق نفسه الذي كان يتحدّث به إلى LM
Studio — **من غير أن يرى العميل LM Studio ولا يحتاج تثبيتها**.

⚠️ **يُربط بـ`127.0.0.1` وحده وعلى منفذ عشوائي غير معلن.** لا يُذكر منفذه
للعميل ولا يُوثَّق: هو تفصيل داخلي، وربطه بـ`0.0.0.0` كان سيعرض مودلًا بلا
مصادقة لكل جهاز على الشبكة.

**بلا نافذة طرفية:** `CREATE_NO_WINDOW` — العميل يجب ألا يرى نافذة سوداء.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

#: أقصى انتظار لجاهزية المودل. تحميل مودل بالجيجابايتات من قرص بطيء قد
#: يستغرق دقائق، و**الإعلان عن الجاهزية قبل اكتمال التحميل** يعطي المستخدم
#: واجهة تفشل أول سؤال.
READY_TIMEOUT_SECONDS = 600.0

#: الفاصل بين محاولات فحص الجاهزية.
POLL_INTERVAL_SECONDS = 1.0

#: مهلة إيقاف العملية الابنة قبل إنهائها قسرًا.
STOP_GRACE_SECONDS = 10.0


class SupervisorError(Exception):
    """خطأ في تشغيل المودل، برسالة عربية صالحة للعرض."""


@dataclass(frozen=True)
class LlamaOptions:
    """خيارات تشغيل الخادم."""

    model_path: Path
    context_size: int = 8192
    threads: int = 0  # 0 = يقرّرها llama.cpp حسب المعالج
    extra_args: tuple[str, ...] = ()


def find_free_port(preferred: int = 0, *, attempts: int = 20) -> int:
    """يعيد منفذًا حرًّا على الاسترجاع المحلي.

    يُفتح مقبس فعلي ويُغلق: سؤال النظام أدقّ من قائمة منافذ محفوظة، لأن
    المنفذ قد يُحجز بين الفحص والاستعمال.
    """
    if preferred:
        for candidate in range(preferred, preferred + attempts):
            if _is_free(candidate):
                return candidate

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


class LlamaSupervisor:
    """يبدأ `llama-server` وينتظر جاهزيته ويوقفه نظيفًا."""

    def __init__(self, executable: Path, options: LlamaOptions) -> None:
        self._executable = Path(executable)
        self._options = options
        self._process: subprocess.Popen | None = None
        self._port: int | None = None
        self._lock = threading.Lock()
        self._last_error: str | None = None

    # -- الحالة ---------------------------------------------------------
    @property
    def port(self) -> int | None:
        return self._port

    @property
    def base_url(self) -> str | None:
        """عنوان الواجهة المتوافقة مع OpenAI، أو ``None`` إن لم يعمل."""
        return f"http://127.0.0.1:{self._port}/v1" if self._port else None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # -- التشغيل --------------------------------------------------------
    def _preflight(self) -> None:
        if not self._executable.is_file():
            raise SupervisorError(
                "ملفات تشغيل المودل ناقصة من هذا التثبيت. أعد تثبيت GovMind."
            )
        model = self._options.model_path
        if not model.is_file():
            raise SupervisorError(
                "ملف المودل غير موجود. أكمل تنزيل المودل من نافذة GovMind."
            )
        if model.stat().st_size == 0:
            raise SupervisorError(
                "ملف المودل فارغ أو تالف. أعد تنزيله من نافذة GovMind."
            )

    def _command(self, port: int) -> list[str]:
        command = [
            str(self._executable),
            "--model",
            str(self._options.model_path),
            # ⚠️ الاسترجاع المحلي وحده. لا `0.0.0.0` بحال.
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--ctx-size",
            str(self._options.context_size),
        ]
        if self._options.threads > 0:
            command += ["--threads", str(self._options.threads)]
        command += list(self._options.extra_args)
        return command

    def start(self, *, ready_timeout: float = READY_TIMEOUT_SECONDS) -> str:
        """يبدأ الخادم وينتظر جاهزيته، ويعيد عنوانه المحلي.

        Raises:
            SupervisorError: إذا نقصت الملفات أو مات الخادم أو لم يجهز.
        """
        with self._lock:
            if self.is_running() and self._port:
                return self.base_url  # type: ignore[return-value]

            self._preflight()
            self._last_error = None
            port = find_free_port(0)

            creation_flags = 0
            if sys.platform == "win32":
                # بلا نافذة سوداء، وفي مجموعة عمليات مستقلة حتى لا يقتل
                # Ctrl+C في الطرفية عمليةً ابنة يديرها الـRuntime.
                creation_flags = (
                    subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                )

            logger.info("بدء تشغيل محرّك المودل على منفذ محلي.")
            try:
                self._process = subprocess.Popen(
                    self._command(port),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    creationflags=creation_flags,
                    cwd=str(self._executable.parent),
                    env={**os.environ},
                )
            except OSError as exc:
                raise SupervisorError(
                    "تعذّر تشغيل محرّك المودل على هذا الجهاز. أعد تثبيت GovMind."
                ) from exc

            self._port = port

        try:
            self._wait_until_ready(port, ready_timeout)
        except SupervisorError:
            self.stop()
            raise
        return self.base_url  # type: ignore[return-value]

    def _wait_until_ready(self, port: int, timeout: float) -> None:
        """يستطلع `/health` حتى يستجيب، أو يفشل برسالة تشرح السبب."""
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{port}/health"

        while time.monotonic() < deadline:
            if not self.is_running():
                self._last_error = self._read_stderr()
                raise SupervisorError(
                    "توقّف محرّك المودل أثناء التحميل. قد لا تكفي ذاكرة الجهاز "
                    "لهذا المودل، أو يكون الملف تالفًا."
                )
            try:
                response = httpx.get(url, timeout=3.0)
                if response.status_code == 200:
                    logger.info("محرّك المودل جاهز.")
                    return
            except httpx.HTTPError:
                pass  # لم يبدأ الاستماع بعد — متوقّع في أول ثوانٍ.
            time.sleep(POLL_INTERVAL_SECONDS)

        self._last_error = self._read_stderr()
        raise SupervisorError(
            "استغرق تحميل المودل وقتًا أطول من المتوقّع ولم يجهز. أعد تشغيل "
            "GovMind، وإن تكرر فراجع مسؤول النظام."
        )

    def _read_stderr(self) -> str | None:
        """يقرأ آخر ما كتبه الخادم — **للسجل لا للعرض**."""
        if self._process is None or self._process.stderr is None:
            return None
        try:
            data = self._process.stderr.read()
        except Exception:
            return None
        if not data:
            return None
        text = data.decode("utf-8", errors="replace").strip()
        logger.error("مخرجات محرّك المودل عند الفشل: %s", text[-2000:])
        return text[-2000:]

    # -- الإيقاف --------------------------------------------------------
    def stop(self) -> None:
        """يوقف العملية الابنة. آمن الاستدعاء ولو لم تكن تعمل.

        **لا تُترك عملية يتيمة**: `llama-server` يحجز الذاكرة وملف المودل،
        فبقاؤه بعد إغلاق الـRuntime يمنع إعادة التشغيل ويستهلك الجهاز.
        """
        with self._lock:
            process = self._process
            self._process = None
            self._port = None

        if process is None or process.poll() is not None:
            return

        logger.info("إيقاف محرّك المودل.")
        try:
            process.terminate()
            process.wait(timeout=STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            logger.warning("محرّك المودل لم يستجب للإيقاف؛ سيُنهى قسرًا.")
            process.kill()
            try:
                process.wait(timeout=STOP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:  # pragma: no cover
                logger.error("تعذّر إنهاء محرّك المودل.")
        except Exception:  # pragma: no cover
            logger.warning("خطأ أثناء إيقاف محرّك المودل.", exc_info=True)

    def restart(self) -> str:
        """يوقف ثم يبدأ. يستعمله مسار «أعد تشغيل المودل»."""
        self.stop()
        return self.start()
