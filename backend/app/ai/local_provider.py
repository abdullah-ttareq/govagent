"""مزود مودل يعمل داخل سيرفر الجهة — غير منفذ بعد.

هذه واجهة مستقبلية فقط. لا يتم تحميل أو تشغيل أي مودل محلي في الـMVP الحالي.
"""

from .base import ChatResult, ModelProvider, ModelProviderError


class LocalModelProvider(ModelProvider):
    """يشغّل مودلًا مستضافًا ذاتيًا داخل شبكة الجهة.

    يُستخدم عندما ترفض الجهة إرسال أي بيانات خارج سيرفرها.
    التنفيذ خارج نطاق الـMVP الحالي.
    """

    name = "local"

    def generate(self, message: str, system_prompt: str) -> ChatResult:
        raise ModelProviderError(
            "المزود المحلي غير منفذ في الـMVP الحالي. "
            "استخدم MODEL_PROVIDER=mock للتشغيل المحلي."
        )
