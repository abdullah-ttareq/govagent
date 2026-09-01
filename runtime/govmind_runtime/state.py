"""مراحل الـRuntime ورسائلها العربية.

**مصدر واحد للحالة.** الإضافة تقرأ المرحلة من `/health` لتعرف أي شاشة
تعرض، والواجهة تقرأها لتعرف ماذا تخبر المستخدم. لو كانت الرسائل مكتوبة في
كل موضع لاختلفت بينها.

الرسائل بالعربية وموجَّهة لموظف غير تقني: **لا منافذ ولا مسارات ولا أسماء
عمليات**. «جارٍ تجهيز المودل» لا «llama-server did not respond on :52431».
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum


class Phase(str, Enum):
    """مرحلة الـRuntime، بالترتيب الطبيعي للمرور بها."""

    #: يعمل ولم يُفعَّل الجهاز بعد — ينتظر رمز تركيب من الإضافة.
    AWAITING_ACTIVATION = "awaiting_activation"
    #: جارٍ تفعيل الجهاز على الاشتراك.
    ACTIVATING = "activating"
    #: مفعّل، والمودل لم يُنزَّل بعد.
    MODEL_MISSING = "model_missing"
    #: جارٍ تنزيل المودل.
    DOWNLOADING_MODEL = "downloading_model"
    #: جارٍ التحقق من سلامة المودل.
    VERIFYING_MODEL = "verifying_model"
    #: جارٍ تحميل المودل في الذاكرة.
    STARTING_MODEL = "starting_model"
    #: جاهز للاستخدام.
    READY = "ready"
    #: متوقّف بسبب الاشتراك أو إبطال الجهاز.
    BLOCKED = "blocked"
    #: خطأ يمكن للمستخدم إعادة المحاولة بعده.
    ERROR = "error"


#: الرسالة الافتراضية لكل مرحلة. تُستبدل برسالة أدقّ عند وجودها.
PHASE_MESSAGES: dict[Phase, str] = {
    Phase.AWAITING_ACTIVATION: "بانتظار تفعيل هذا الجهاز من إضافة GovMind.",
    Phase.ACTIVATING: "جارٍ تفعيل هذا الجهاز…",
    Phase.MODEL_MISSING: "بانتظار تنزيل المودل.",
    Phase.DOWNLOADING_MODEL: "جارٍ تنزيل المودل…",
    Phase.VERIFYING_MODEL: "جارٍ التحقق من سلامة المودل…",
    Phase.STARTING_MODEL: "جارٍ تجهيز المودل للعمل…",
    Phase.READY: "GovMind جاهز للاستخدام.",
    Phase.BLOCKED: "الاشتراك لا يسمح باستخدام GovMind حاليًا.",
    Phase.ERROR: "حدث خطأ. أعد المحاولة.",
}

#: المراحل التي تُعتبر «تقدّمًا جاريًا» — تعرض عندها الواجهة مؤشّرًا.
BUSY_PHASES = frozenset(
    {
        Phase.ACTIVATING,
        Phase.DOWNLOADING_MODEL,
        Phase.VERIFYING_MODEL,
        Phase.STARTING_MODEL,
    }
)


@dataclass
class RuntimeState:
    """حالة الـRuntime المشتركة بين الخيوط.

    كل تغيير يمرّ بـ:meth:`set`، والقراءة تُعيد لقطة — فلا يقرأ خيطٌ حالةً
    نصفها قديم ونصفها جديد.
    """

    phase: Phase = Phase.AWAITING_ACTIVATION
    message: str = PHASE_MESSAGES[Phase.AWAITING_ACTIVATION]
    #: نسبة التقدّم في التنزيل أو التحقق، أو ``None`` خارجهما.
    progress: int | None = None
    downloaded_bytes: int = 0
    total_bytes: int = 0
    #: اسم الجهاز كما سجّله الـBackend، للعرض في الواجهة.
    device_name: str | None = None
    subscription_status: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set(
        self,
        phase: Phase,
        message: str | None = None,
        *,
        progress: int | None = None,
        downloaded_bytes: int | None = None,
        total_bytes: int | None = None,
    ) -> None:
        with self._lock:
            self.phase = phase
            self.message = message or PHASE_MESSAGES[phase]
            # التقدّم يُصفَّر خارج مراحل التقدّم حتى لا يبقى شريط عالق.
            self.progress = progress if phase in BUSY_PHASES else None
            if downloaded_bytes is not None:
                self.downloaded_bytes = downloaded_bytes
            if total_bytes is not None:
                self.total_bytes = total_bytes

    def set_progress(self, percent: int, received: int, total: int) -> None:
        with self._lock:
            self.progress = percent
            self.downloaded_bytes = received
            self.total_bytes = total

    def snapshot(self) -> dict[str, object]:
        """لقطة متّسقة للعرض في `/health` وفي الواجهة."""
        with self._lock:
            return {
                "phase": self.phase.value,
                "message": self.message,
                "progress": self.progress,
                "downloaded_bytes": self.downloaded_bytes,
                "total_bytes": self.total_bytes,
                "device_name": self.device_name,
                "subscription_status": self.subscription_status,
                "is_ready": self.phase is Phase.READY,
                "needs_activation": self.phase is Phase.AWAITING_ACTIVATION,
            }
