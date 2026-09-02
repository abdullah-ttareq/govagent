"""نقطة المحادثة.

**المسار محمي بالكامل:** كل طلب يتطلب رمز دخول صالحًا واشتراكًا ساريًا،
فلا يُستهلك مزود المودل بلا هوية ولا سجل تدقيق. الطلب بلا رمز يعيد **401**
بالغلاف العربي الموحّد.

**جهة الموظف تُقرأ من الرمز وحده** ولا تُقبل من جسم الطلب في أي حال، وهو
أساس عزل البيانات بين الجهات: بحث الملفات وحفظ المحادثة يقعان في نطاق تلك
الجهة لا غير.

**السياق يأتي من الرسائل المحفوظة على السيرفر** لا من العميل: حقل `history`
حُذف من `ChatRequest` لأن سياقًا يرسله المتصفح يمكن تلفيقه.
"""

from fastapi import APIRouter, HTTPException, status

from ..ai import ModelProviderError
from ..schemas import ChatMessageIn, ChatRequest, ChatResponse
from ..services import send_message
from ..services.conversation_service import (
    ConversationNotFoundError,
    context_messages,
    ensure_conversation,
    record_exchange,
)
from ..services.user_store import User
from .dependencies import CurrentUser

router = APIRouter(prefix="/api", tags=["chat"])


def _stored_context(user: User, conversation_id: int) -> list[ChatMessageIn]:
    """يحوّل رسائل المحادثة المحفوظة إلى سياق يفهمه المزود."""
    return [
        ChatMessageIn(role=message.role, content=message.content)
        for message in context_messages(actor=user, conversation_id=conversation_id)
    ]


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="إرسال رسالة إلى الإيجنت",
    responses={
        401: {"description": "رمز الدخول مفقود أو تالف أو منتهي الصلاحية"},
        403: {"description": "الحساب معطّل أو اشتراك الجهة منتهٍ"},
        404: {"description": "المحادثة المطلوبة غير موجودة لصاحب الرمز"},
        503: {"description": "تعذّر الوصول إلى مزود المودل"},
    },
)
def chat(payload: ChatRequest, user: CurrentUser) -> ChatResponse:
    """يستقبل رسالة الموظف ويعيد رد المزود المفعّل.

    * المحادثة تُفتح تلقائيًا إن لم يُمرَّر `conversation_id`، بعنوان مشتق من
      أول رسالة، ويُعاد معرّفها في الرد لتُستخدم في الرسائل التالية.
    * **السياق يأتي من الرسائل المحفوظة** لا من العميل، فلا يمكن تلفيقه.
    * سؤال الموظف ورد الإيجنت يُحفظان معًا في المحادثة بالترتيب الصحيح.
    * ملفات **جهة صاحب الرمز** تُبحث وتُعاد مصادرها في `sources`.

    فشل البحث في الملفات **لا يُفشل الطلب**. فشل المزود يصل كـ503 مع الرسالة
    العربية كما هي.
    """
    try:
        conversation = ensure_conversation(
            actor=user,
            conversation_id=payload.conversation_id,
            first_message=payload.message,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    conversation_id = conversation.id

    try:
        result = send_message(
            payload.message,
            history=_stored_context(user, conversation_id),
            # الجهة من الرمز وحده — لا من جسم الطلب.
            organization_id=user.organization_id,
        )
    except ModelProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    # الحفظ بعد نجاح المزود: تبادل بلا جواب لا يُحفظ نصفه.
    record_exchange(
        actor=user,
        conversation_id=conversation_id,
        question=payload.message,
        answer=result.reply,
    )

    return ChatResponse(
        reply=result.reply,
        provider=result.provider,
        sources=result.sources,
        conversation_id=conversation_id,
    )
