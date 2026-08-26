"""إدارة المحادثات والرسائل — الملكية والعزل.

**قاعدة العزل:** كل دالة تأخذ ``actor`` وهو المستخدم الذي أثبت التوكن هويته،
وتشتق منه ``organization_id`` و ``user_id``. لا توجد دالة تقبل جهة ولا مالكًا
كمُعامل مستقل، فلا يمكن لمسار أن يمرّر جهة من جسم الطلب.

**المحادثة خاصة بصاحبها، لا بجهته.** هذا أضيق من قاعدة المشروع العامة: زميل
في الجهة نفسها — ولو كان مسؤولها — لا يقرأ محادثات غيره ولا يعدّلها. محادثة
موظف آخر تُعامل كغير موجودة (404) لا كممنوعة (403): «ممنوع» تؤكد وجودها.
"""

from __future__ import annotations

from ..core.config import settings
from .audit_service import record_for
from .audit_store import ACTION_CONVERSATION_DELETED
from .conversation_store import (
    DEFAULT_TITLE,
    Conversation,
    Message,
    Page,
    get_conversation_store,
    resolve_page,
)
from .user_store import User

#: أقصى طول لعنوان مشتق تلقائيًا من أول رسالة. عمود title يقبل ٣٠٠ حرفًا،
#: لكن العنوان يظهر في قائمة جانبية ضيقة فالطول المفيد أقصر بكثير.
AUTO_TITLE_MAX_CHARS = 60

#: عدد الرسائل السابقة التي تُمرَّر للمزود كسياق. سقفٌ لازم: محادثة طويلة
#: تتجاوز نافذة المودل وتكلّف أكثر بلا فائدة.
CONTEXT_MESSAGE_LIMIT = 20


class ConversationError(Exception):
    """خطأ في إدارة المحادثات، برسالة عربية صالحة للعرض."""


class ConversationNotFoundError(ConversationError):
    """المحادثة غير موجودة **لهذا الموظف**. تشمل محادثات غيره."""


def derive_title(first_message: str) -> str:
    """يشتق عنوانًا من أول رسالة في المحادثة.

    عنوان مأخوذ من السؤال يجعل القائمة الجانبية قابلة للتصفّح، بخلاف
    «محادثة جديدة» مكررة عشر مرات. يعود إلى العنوان الافتراضي إن كانت
    الرسالة فارغة بعد التنظيف.
    """
    cleaned = " ".join(first_message.split())
    if not cleaned:
        return DEFAULT_TITLE
    if len(cleaned) <= AUTO_TITLE_MAX_CHARS:
        return cleaned
    # القطع عند آخر مسافة حتى لا تنقطع كلمة في منتصفها.
    trimmed = cleaned[:AUTO_TITLE_MAX_CHARS].rsplit(" ", 1)[0]
    return f"{trimmed or cleaned[:AUTO_TITLE_MAX_CHARS]}…"


def create_conversation(*, actor: User, title: str | None = None) -> Conversation:
    """ينشئ محادثة جديدة يملكها ``actor``."""
    return get_conversation_store().create_conversation(
        organization_id=actor.organization_id,
        user_id=actor.id,
        title=(title or DEFAULT_TITLE).strip() or DEFAULT_TITLE,
    )


def get_conversation(*, actor: User, conversation_id: int) -> Conversation:
    """يقرأ محادثة يملكها ``actor``.

    Raises:
        ConversationNotFoundError: إذا لم توجد أو كانت لموظف آخر.
    """
    conversation = get_conversation_store().get_conversation(
        conversation_id=conversation_id,
        organization_id=actor.organization_id,
        user_id=actor.id,
    )
    if conversation is None:
        raise ConversationNotFoundError("المحادثة المطلوبة غير موجودة.")
    return conversation


def list_conversations(
    *, actor: User, limit: int | None = None, offset: int | None = None
) -> Page:
    """يعيد محادثات ``actor`` من الأحدث تعديلًا."""
    resolved_limit, resolved_offset = resolve_page(limit, offset)
    return get_conversation_store().list_conversations(
        organization_id=actor.organization_id,
        user_id=actor.id,
        limit=resolved_limit,
        offset=resolved_offset,
    )


def rename_conversation(
    *, actor: User, conversation_id: int, title: str
) -> Conversation:
    """يغيّر عنوان محادثة يملكها ``actor``.

    Raises:
        ConversationNotFoundError: إذا لم توجد أو كانت لموظف آخر.
    """
    renamed = get_conversation_store().rename_conversation(
        conversation_id=conversation_id,
        organization_id=actor.organization_id,
        user_id=actor.id,
        title=title.strip() or DEFAULT_TITLE,
    )
    if renamed is None:
        raise ConversationNotFoundError("المحادثة المطلوبة غير موجودة.")
    return renamed


def delete_conversation(*, actor: User, conversation_id: int) -> None:
    """يحذف محادثة يملكها ``actor`` ورسائلها معها.

    **حذف فعلي لا تعطيل**، بخلاف المستخدمين: المحادثة محتوى يملكه صاحبه وله
    أن يزيله، ولا يرتبط بها تاريخ يخص غيره.

    Raises:
        ConversationNotFoundError: إذا لم توجد أو كانت لموظف آخر.
    """
    deleted = get_conversation_store().delete_conversation(
        conversation_id=conversation_id,
        organization_id=actor.organization_id,
        user_id=actor.id,
    )
    if not deleted:
        raise ConversationNotFoundError("المحادثة المطلوبة غير موجودة.")

    record_for(
        actor,
        action=ACTION_CONVERSATION_DELETED,
        details=f"حذف المحادثة رقم {conversation_id}",
    )


def list_messages(
    *,
    actor: User,
    conversation_id: int,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    """يعيد رسائل محادثة يملكها ``actor``، بالترتيب الزمني الصاعد.

    ملكية المحادثة تُتحقَّق أولًا: دوال الرسائل في المخزن لا تعرف المالك.

    Raises:
        ConversationNotFoundError: إذا لم توجد أو كانت لموظف آخر.
    """
    get_conversation(actor=actor, conversation_id=conversation_id)
    resolved_limit, resolved_offset = resolve_page(limit, offset)
    return get_conversation_store().list_messages(
        conversation_id=conversation_id,
        organization_id=actor.organization_id,
        limit=resolved_limit,
        offset=resolved_offset,
    )


def context_messages(*, actor: User, conversation_id: int) -> list[Message]:
    """يعيد آخر رسائل المحادثة كسياق للمزود.

    السياق يأتي من المخزن لا من العميل: سياقٌ يرسله العميل يمكن تلفيقه، وهو
    الفرق بين محادثة محفوظة على السيرفر ومحادثة يرويها المتصفح.
    """
    return get_conversation_store().recent_messages(
        conversation_id=conversation_id,
        organization_id=actor.organization_id,
        limit=CONTEXT_MESSAGE_LIMIT,
    )


def record_exchange(
    *, actor: User, conversation_id: int, question: str, answer: str
) -> list[Message]:
    """يحفظ سؤال الموظف ورد الإيجنت في محادثته، بهذا الترتيب.

    الرسالتان تُحفظان **دفعة واحدة** حتى لا يبقى سؤال بلا جواب إن انقطعت
    العملية بينهما.
    """
    return get_conversation_store().add_messages(
        conversation_id=conversation_id,
        organization_id=actor.organization_id,
        entries=(("user", question), ("assistant", answer)),
    )


def ensure_conversation(
    *, actor: User, conversation_id: int | None, first_message: str
) -> Conversation:
    """يعيد المحادثة المطلوبة، أو ينشئ واحدة جديدة بعنوان مشتق من الرسالة.

    يستدعيه مسار ``/api/chat``: الموظف يكتب رسالة فتُفتح لها محادثة تلقائيًا
    بلا خطوة إنشاء منفصلة.

    Raises:
        ConversationNotFoundError: إذا مُرِّر معرّف محادثة لا يملكها ``actor``.
    """
    if conversation_id is not None:
        return get_conversation(actor=actor, conversation_id=conversation_id)
    return create_conversation(actor=actor, title=derive_title(first_message))


def page_bounds() -> tuple[int, int]:
    """حدود الترقيم المعلنة في التوثيق. للعرض في الـSchemas."""
    return settings.page_size_default, settings.page_size_max
