"""حارس النسخة الواحدة — يمنع تراكم خوادم GovMind على الجهاز.

**المشكلة التي يحلّها.** كان كل تشغيل لـ`govmind-runtime.exe` يبدأ خادمًا
جديدًا: يجد المنفذ المفضَّل مشغولًا فينتقل إلى الذي يليه. النتيجة على جهاز
اختبار حقيقي كانت **خمس نسخ تستمع على 8765–8769 وتسع عمليات**، لأن
المستخدم ضغط الاختصار بضع مرات ولم ير شيئًا يفتح.

المنفذ البديل كان لحالة «منفذ حجزه برنامج آخر»، لا لحالة «GovMind يعمل
أصلًا». التمييز بينهما هو ما يفعله هذا الملف.

**Mutex مسمّى لا فحص منفذ.** فحص المنفذ يترك سباقًا: نسختان تفحصان معًا
فتجدانه حرًّا فتبدآن. الـMutex ذرّي على مستوى النواة: واحدة تملكه والباقي
يعرف فورًا أنه موجود.

النطاق `Local\\` لا `Global\\`: النسخ تعمل بحساب المستخدم، و`Global`
يحتاج صلاحية إضافية ويمنع مستخدمَين على الجهاز نفسه من تشغيل نسخته.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)

#: اسم فريد للتطبيق. تغييره يعني السماح بنسختين معًا — لا تفعل.
MUTEX_NAME = r"Local\GovMind.Runtime.SingleInstance.v1"

_ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """يحجز اسمًا على مستوى النظام، ويحرّره عند الخروج.

    مثال::

        guard = SingleInstance()
        if guard.already_running:
            return 0  # نسخة أخرى تعمل
    """

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self._handle = None
        self.already_running = False

        if sys.platform != "win32":
            # على غير ويندوز لا حارس. الـRuntime منتج ويندوز، والاختبارات
            # تعمل على أي نظام — وتشغيل نسختين فيها لا يضرّ.
            return

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [
                wintypes.LPVOID,
                wintypes.BOOL,
                wintypes.LPCWSTR,
            ]
            kernel32.CreateMutexW.restype = wintypes.HANDLE

            self._kernel32 = kernel32
            self._handle = kernel32.CreateMutexW(None, False, name)
            self.already_running = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
        except Exception:  # pragma: no cover - يستحيل على ويندوز سليم
            # فشل الحجز لا يمنع التشغيل: نسخة زائدة أهون من نسخة لا تعمل.
            logger.warning("تعذّر حجز حارس النسخة الواحدة؛ سيستمر التشغيل.")
            self._handle = None

    def release(self) -> None:
        """يحرّر الاسم. آمن الاستدعاء أكثر من مرة."""
        if self._handle:
            try:
                self._kernel32.CloseHandle(self._handle)
            except Exception:  # pragma: no cover
                pass
            self._handle = None

    def __enter__(self) -> SingleInstance:
        return self

    def __exit__(self, *args: object) -> bool:
        self.release()
        return False
