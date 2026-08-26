"""مسارات المحادثات والرسائل.

**كل مسار هنا يعمل على محادثات صاحب الرمز وحده.** لا يستقبل أي مسار جهة ولا
مالكًا: يُشتقان من الرمز داخل `conversation_service`. محادثة موظف آخر — ولو
كان زميلًا في الجهة نفسها — تعود **404 بلا بيانات**.
"""

from fastapi import APIRouter, HTTPException, Query, status

from ..schemas import (
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationOut,
    ConversationRenameRequest,
    MessageListResponse,
    MessageOut,
    PageMeta,
)
from ..services.conversation_service import (
    ConversationNotFoundError,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    list_messages,
    rename_conversation,
)
from ..services.conversation_store import Conversation, Message, Page
from .dependencies import CurrentUser

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

_NOT_FOUND = {"description": "المحادثة غير موجودة لصاحب الرمز"}
_UNAUTHORIZED = {"description": "رمز الدخول مفقود أو غير صالح"}


def _to_conversation_out(conversation: Conversation) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        message_count=conversation.message_count,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _to_message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
    )


def _page_meta(page: Page) -> PageMeta:
    return PageMeta(total=page.total, limit=page.limit, offset=page.offset)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
    summary="إنشاء محادثة",
    responses={401: _UNAUTHORIZED},
)
def add_conversation(
    payload: ConversationCreateRequest, user: CurrentUser
) -> ConversationOut:
    """ينشئ محادثة فارغة يملكها صاحب الرمز.

    لا يلزم استدعاؤه قبل المحادثة: `POST /api/chat` بلا `conversation_id`
    ينشئ محادثة تلقائيًا بعنوان مشتق من أول رسالة.
    """
    return _to_conversation_out(create_conversation(actor=user, title=payload.title))


@router.get(
    "",
    response_model=ConversationListResponse,
    summary="قائمة محادثات الموظف",
    responses={401: _UNAUTHORIZED},
)
def read_conversations(
    user: CurrentUser,
    limit: int | None = Query(None, ge=1, description="عدد المحادثات في الصفحة"),
    offset: int | None = Query(None, ge=0, description="عدد المحادثات المتجاوَزة"),
) -> ConversationListResponse:
    """يعيد محادثات صاحب الرمز من الأحدث تعديلًا.

    محادثات الزملاء لا تظهر هنا إطلاقًا، ولو كان صاحب الرمز مسؤول الجهة.
    """
    page = list_conversations(actor=user, limit=limit, offset=offset)
    return ConversationListResponse(
        conversations=[_to_conversation_out(item) for item in page.items],
        page=_page_meta(page),
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationOut,
    summary="قراءة محادثة",
    responses={401: _UNAUTHORIZED, 404: _NOT_FOUND},
)
def read_conversation(conversation_id: int, user: CurrentUser) -> ConversationOut:
    """يعيد بيانات محادثة يملكها صاحب الرمز."""
    try:
        return _to_conversation_out(
            get_conversation(actor=user, conversation_id=conversation_id)
        )
    except ConversationNotFoundError as exc:
        raise _not_found(exc) from exc


@router.patch(
    "/{conversation_id}",
    response_model=ConversationOut,
    summary="إعادة تسمية محادثة",
    responses={401: _UNAUTHORIZED, 404: _NOT_FOUND},
)
def edit_conversation(
    conversation_id: int, payload: ConversationRenameRequest, user: CurrentUser
) -> ConversationOut:
    """يغيّر عنوان محادثة يملكها صاحب الرمز."""
    try:
        return _to_conversation_out(
            rename_conversation(
                actor=user, conversation_id=conversation_id, title=payload.title
            )
        )
    except ConversationNotFoundError as exc:
        raise _not_found(exc) from exc


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="حذف محادثة",
    responses={401: _UNAUTHORIZED, 404: _NOT_FOUND},
)
def remove_conversation(conversation_id: int, user: CurrentUser) -> None:
    """يحذف محادثة يملكها صاحب الرمز **ورسائلها معها**.

    حذف فعلي لا تعطيل، بخلاف حسابات الموظفين: المحادثة محتوى يملكه صاحبه وله
    أن يزيله، ولا يرتبط بها تاريخ يخص غيره.
    """
    try:
        delete_conversation(actor=user, conversation_id=conversation_id)
    except ConversationNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="رسائل محادثة",
    responses={401: _UNAUTHORIZED, 404: _NOT_FOUND},
)
def read_messages(
    conversation_id: int,
    user: CurrentUser,
    limit: int | None = Query(None, ge=1, description="عدد الرسائل في الصفحة"),
    offset: int | None = Query(None, ge=0, description="عدد الرسائل المتجاوَزة"),
) -> MessageListResponse:
    """يعيد رسائل المحادثة **بالترتيب الزمني الصاعد** مع الترقيم.

    من الأقدم إلى الأحدث لأن المحادثة تُقرأ من أولها، و`offset=0` يعطي بدايتها.
    """
    try:
        page = list_messages(
            actor=user, conversation_id=conversation_id, limit=limit, offset=offset
        )
    except ConversationNotFoundError as exc:
        raise _not_found(exc) from exc

    return MessageListResponse(
        messages=[_to_message_out(item) for item in page.items],
        page=_page_meta(page),
    )
