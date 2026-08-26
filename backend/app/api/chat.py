"""نقطة المحادثة.

⚠️ **وضع انتقالي:** هذا المسار يقبل الطلبات **بلا رمز دخول** مؤقتًا،
ليبقى قابلًا للتجربة من الواجهة والإضافة قبل أن تضيفا تسجيل الدخول
(مهام PERSON_3 و PERSON_4). الطلب بلا رمز لا يحفظ محادثة ولا يبحث في
ملفات أي جهة، فلا تسريب فيه — لكنه يعني أن مزود المودل يُستهلك بلا
هوية ولا سجل تدقيق، وهذا غير مقبول على سيرفر جهة حقيقية.

**ما يجب فعله عند جاهزية الواجهة والإضافة:** استبدل `OptionalCurrentUser`
بـ`CurrentUser` في دالة `chat` أدناه، واحذف فرع «بلا رمز» وحقل `history`
من `ChatRequest`. عندها يصير كل تبادل محفوظًا بصاحبه بلا استثناء.
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
from .dependencies import OptionalCurrentUser

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
        401: {"description": "رمز الدخول المُرسل تالف أو منتهي الصلاحية"},
        404: {"description": "المحادثة المطلوبة غير موجودة لصاحب الرمز"},
        422: {"description": "أُرسل حقل history مع رمز دخول"},
        503: {"description": "تعذّر الوصول إلى مزود المودل"},
    },
)
def chat(payload: ChatRequest, user: OptionalCurrentUser) -> ChatResponse:
    """يستقبل رسالة الموظف ويعيد رد المزود المفعّل.

    **مع رمز الدخول** — وهو الوضع الكامل:

    * المحادثة تُفتح تلقائيًا إن لم يُمرَّر `conversation_id`، بعنوان مشتق من
      أول رسالة، ويُعاد معرّفها في الرد لتُستخدم في الرسائل التالية.
    * السياق يأتي من **الرسائل المحفوظة** لا من العميل، فلا يمكن تلفيقه.
    * سؤال الموظف ورد الإيجنت يُحفظان معًا في المحادثة بالترتيب الصحيح.
    * ملفات الجهة تُبحث وتُعاد مصادرها في `sources`.

    ⚠️ **بلا رمز — وضع انتقالي فقط:** يعمل المسار كما كان قبل P2-03 (لا
    محادثة ولا حفظ ولا بحث في الملفات، والسياق من حقل `history`)، ليبقى
    قابلًا للتجربة من الواجهة والإضافة قبل أن تضيفا تسجيل الدخول.
    **يجب أن يصير المسار محميًا بالكامل بعد ذلك** — لا استخدام للمودل بلا
    هوية ولا سجل تدقيق على سيرفر جهة حقيقية.

    فشل البحث في الملفات **لا يُفشل الطلب**. فشل المزود يصل كـ503 مع الرسالة
    العربية كما هي.
    """
    conversation_id: int | None = None
    history = payload.history

    # TODO(بعد ربط تسجيل الدخول في الواجهة والإضافة): اجعل الاعتمادية
    # CurrentUser بدل OptionalCurrentUser، واحذف فرع «بلا رمز» أدناه
    # وحقل history من ChatRequest.

    if user is not None:
        # سياق العميل يُرفض صراحةً لا يُتجاهل بصمت: السيرفر يحفظ المحادثة
        # الآن، وقبول سياق من الخارج يفتح باب تلفيق ما «قيل» سابقًا.
        if payload.history:
            raise HTTPException(
                status_code=422,
                detail=(
                    "لا تُرسل حقل history مع رمز الدخول. السياق يُقرأ من "
                    "المحادثة المحفوظة على السيرفر؛ أرسل conversation_id بدلًا "
                    "منه، أو اتركه فارغًا لبدء محادثة جديدة."
                ),
            )
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
        history = _stored_context(user, conversation_id)

    elif payload.conversation_id is not None:
        # بلا هوية لا ملكية، فلا سبيل للتحقق من أن المحادثة له.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="حفظ المحادثات يتطلب تسجيل الدخول أولًا.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        result = send_message(
            payload.message,
            history=history,
            organization_id=user.organization_id if user else None,
        )
    except ModelProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if user is not None and conversation_id is not None:
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
