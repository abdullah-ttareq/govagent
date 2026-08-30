"""مزود تجريبي يعمل محليًا بدون Oracle وبدون مودل حقيقي.

هذا هو المزود الافتراضي في بيئة التطوير، ويُستخدم لتشغيل المشروع واختباره.
"""

from .base import ChatMessage, ChatResult, ModelProvider, ensure_conversation

_PREVIEW_LIMIT = 200


class MockModelProvider(ModelProvider):
    """يعيد ردًا ثابتًا واضحًا يبيّن أن المزود تجريبي.

    يستقبل سياق المحادثة كاملًا مثل المزودات الحقيقية، ويذكر في رده عدد
    الرسائل السابقة حتى يظهر في الاختبار والواجهة أن السياق يصل فعلًا.
    """

    name = "mock"

    def generate(
        self, messages: list[ChatMessage], system_prompt: str
    ) -> ChatResult:
        conversation = ensure_conversation(messages)
        preview = conversation[-1].content.strip()
        if len(preview) > _PREVIEW_LIMIT:
            preview = preview[:_PREVIEW_LIMIT] + "…"

        previous = len(conversation) - 1
        context_note = (
            f"سياق المحادثة المستلم: {previous} رسالة سابقة.\n\n"
            if previous
            else ""
        )

        # النص الظاهر **عام عمدًا** ولا يذكر مزودًا بعينه: اسم المزود الذي
        # سيُربط لاحقًا قرارٌ لم يُحسم، وذكره في رد يراه الموظف يَعِد بما لم
        # يُتفق عليه. اختيار المزود يبقى في الإعداد لا في نصّ الرد.
        reply = (
            "رد تجريبي — سيتم ربط مزود الذكاء الاصطناعي في مرحلة الإعداد.\n\n"
            f"{context_note}"
            f"استلمت رسالتك: «{preview}»"
        )
        return ChatResult(reply=reply, provider=self.name)
