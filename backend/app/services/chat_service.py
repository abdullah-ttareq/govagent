"""منطق المحادثة — يفصل الـRoutes عن مزود المودل."""

from ..ai import SYSTEM_PROMPT, get_model_provider
from ..schemas import ChatResponse


def send_message(message: str) -> ChatResponse:
    """يمرر رسالة الموظف إلى المزود المفعّل ويعيد الرد.

    لاحقًا (مهام BE-05/BE-06) سيحفظ هذا المنطق الرسالة والرد في قاعدة البيانات
    ضمن محادثة تخص الموظف وجهته.
    """
    provider = get_model_provider()
    result = provider.generate(message=message, system_prompt=SYSTEM_PROMPT)
    return ChatResponse(reply=result.reply, provider=result.provider)
