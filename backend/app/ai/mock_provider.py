"""مزود تجريبي يعمل محليًا بدون Oracle وبدون مودل حقيقي.

هذا هو المزود الافتراضي في بيئة التطوير، ويُستخدم لتشغيل المشروع واختباره.
"""

from .base import ChatResult, ModelProvider


class MockModelProvider(ModelProvider):
    """يعيد ردًا ثابتًا واضحًا يبيّن أن المزود تجريبي."""

    name = "mock"

    def generate(self, message: str, system_prompt: str) -> ChatResult:
        preview = message.strip()
        if len(preview) > 200:
            preview = preview[:200] + "…"

        reply = (
            "[رد تجريبي من Mock Provider — لا يوجد مودل حقيقي متصل]\n\n"
            f"استلمت رسالتك: «{preview}»\n\n"
            "عند ضبط MODEL_PROVIDER=oracle سيتم توجيه الطلب إلى OCI Generative AI."
        )
        return ChatResult(reply=reply, provider=self.name)
