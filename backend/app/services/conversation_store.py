"""مخزن المحادثات ورسائلها خلف واجهة واحدة، يُختار من ``DATA_STORE``.

* ``memory`` (الافتراضي) — داخل ذاكرة العملية. يجعل المحادثات قابلة للتشغيل
  والاختبار قبل توفّر Oracle. **غير دائم:** يفرغ عند إعادة التشغيل.
* ``oracle`` — جدولا ``conversations`` و ``messages``.

**قاعدة العزل — أضيق من بقية المشروع:** المحادثة خاصة **بصاحبها** لا بجهته.
كل دالة هنا تأخذ ``organization_id`` و ``user_id`` معًا، ولا توجد دالة واحدة
تقرأ محادثة بمعرّفها وحده. زميل في الجهة نفسها لا يرى محادثات غيره.

الرسائل تُقيَّد بالمحادثة وبالجهة؛ ملكية المحادثة تُتحقَّق قبلها في
`conversation_service`، وهو المسار الوحيد الذي يصل إلى دوال الرسائل.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from ..core.config import settings

#: صاحب الرسالة، مطابق لقيد ck_messages_role في المخطط.
MessageRole = Literal["user", "assistant"]

#: العنوان الافتراضي، مطابق للقيمة الافتراضية في عمود conversations.title.
DEFAULT_TITLE = "محادثة جديدة"


class ConversationStoreError(Exception):
    """خطأ في مخزن المحادثات، برسالة عربية صالحة للعرض."""


@dataclass(frozen=True)
class Conversation:
    """محادثة واحدة يملكها موظف داخل جهته."""

    id: int
    organization_id: int
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime
    #: عدد رسائلها. يُحسب عند القراءة ولا يُخزَّن عمودًا.
    message_count: int = 0


@dataclass(frozen=True)
class Message:
    """رسالة واحدة داخل محادثة."""

    id: int
    conversation_id: int
    organization_id: int
    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True)
class Page:
    """صفحة نتائج مع إجماليها، لبناء الترقيم في الواجهة."""

    items: list
    total: int
    limit: int
    offset: int


def resolve_page(limit: int | None, offset: int | None) -> tuple[int, int]:
    """يضبط حدود الترقيم داخل المدى المسموح.

    السقف إلزامي: طلب ``limit=100000`` على محادثة طويلة يسحب المحادثة كاملة
    إلى الذاكرة وإلى الرد.
    """
    resolved_limit = settings.page_size_default if limit is None else limit
    resolved_limit = max(1, min(resolved_limit, settings.page_size_max))
    return resolved_limit, max(0, offset or 0)


class ConversationStore(ABC):
    """واجهة تخزين المحادثات والرسائل."""

    name: str = "base"

    @abstractmethod
    def create_conversation(
        self, *, organization_id: int, user_id: int, title: str
    ) -> Conversation:
        """ينشئ محادثة يملكها هذا الموظف داخل جهته."""
        raise NotImplementedError

    @abstractmethod
    def get_conversation(
        self, *, conversation_id: int, organization_id: int, user_id: int
    ) -> Conversation | None:
        """يقرأ محادثة **لصاحبها داخل جهته**، أو None.

        لا يُفرَّق بين «غير موجودة» و«يملكها غيرك»: كلاهما None.
        """
        raise NotImplementedError

    @abstractmethod
    def list_conversations(
        self, *, organization_id: int, user_id: int, limit: int, offset: int
    ) -> Page:
        """يعيد محادثات الموظف من الأحدث تعديلًا، مع إجمالي عددها."""
        raise NotImplementedError

    @abstractmethod
    def rename_conversation(
        self, *, conversation_id: int, organization_id: int, user_id: int, title: str
    ) -> Conversation | None:
        """يغيّر عنوان محادثة الموظف، أو None إن لم يملكها."""
        raise NotImplementedError

    @abstractmethod
    def delete_conversation(
        self, *, conversation_id: int, organization_id: int, user_id: int
    ) -> bool:
        """يحذف محادثة الموظف ورسائلها. يعيد False إن لم يملكها."""
        raise NotImplementedError

    @abstractmethod
    def add_messages(
        self,
        *,
        conversation_id: int,
        organization_id: int,
        entries: Sequence[tuple[str, str]],
    ) -> list[Message]:
        """يضيف رسائل بالترتيب الممرَّر ويحدّث updated_at للمحادثة.

        تُضاف **دفعة واحدة** لا رسالة رسالة: سؤال الموظف ورد الإيجنت تبادل
        واحد، وحفظه على خطوتين يترك سؤالًا بلا جواب إن انقطع بينهما.

        Args:
            entries: أزواج (الدور، المحتوى) بالترتيب الزمني المطلوب.
        """
        raise NotImplementedError

    @abstractmethod
    def list_messages(
        self, *, conversation_id: int, organization_id: int, limit: int, offset: int
    ) -> Page:
        """يعيد رسائل محادثة بالترتيب الزمني الصاعد، مع إجمالي عددها."""
        raise NotImplementedError

    @abstractmethod
    def recent_messages(
        self, *, conversation_id: int, organization_id: int, limit: int
    ) -> list[Message]:
        """يعيد آخر ``limit`` رسالة بالترتيب الزمني الصاعد، كسياق للمزود."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# المخزن المحلي
# ---------------------------------------------------------------------------
class MemoryConversationStore(ConversationStore):
    """محادثات ورسائل داخل ذاكرة العملية، للتطوير والاختبار فقط."""

    name = "memory"

    #: الحالة على مستوى الصنف حتى تشترك فيها كل النسخ داخل العملية.
    _conversations: dict[int, Conversation] = {}
    _messages: dict[int, list[Message]] = {}
    _next_conversation_id: int = 1
    _next_message_id: int = 1
    _lock = threading.Lock()

    def _owned(
        self, conversation_id: int, organization_id: int, user_id: int
    ) -> Conversation | None:
        conversation = MemoryConversationStore._conversations.get(conversation_id)
        if conversation is None:
            return None
        # الشرطان معًا: الجهة وحدها لا تكفي لأن المحادثة خاصة بصاحبها.
        if (
            conversation.organization_id != organization_id
            or conversation.user_id != user_id
        ):
            return None
        return conversation

    def _with_count(self, conversation: Conversation) -> Conversation:
        count = len(MemoryConversationStore._messages.get(conversation.id, ()))
        return Conversation(
            id=conversation.id,
            organization_id=conversation.organization_id,
            user_id=conversation.user_id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            message_count=count,
        )

    def create_conversation(
        self, *, organization_id: int, user_id: int, title: str
    ) -> Conversation:
        now = datetime.now(UTC)
        with MemoryConversationStore._lock:
            conversation = Conversation(
                id=MemoryConversationStore._next_conversation_id,
                organization_id=organization_id,
                user_id=user_id,
                title=title,
                created_at=now,
                updated_at=now,
            )
            MemoryConversationStore._conversations[conversation.id] = conversation
            MemoryConversationStore._messages[conversation.id] = []
            MemoryConversationStore._next_conversation_id += 1
        return conversation

    def get_conversation(
        self, *, conversation_id: int, organization_id: int, user_id: int
    ) -> Conversation | None:
        with MemoryConversationStore._lock:
            conversation = self._owned(conversation_id, organization_id, user_id)
            return None if conversation is None else self._with_count(conversation)

    def list_conversations(
        self, *, organization_id: int, user_id: int, limit: int, offset: int
    ) -> Page:
        with MemoryConversationStore._lock:
            owned = [
                self._with_count(conversation)
                for conversation in MemoryConversationStore._conversations.values()
                if conversation.organization_id == organization_id
                and conversation.user_id == user_id
            ]
        # الأحدث تعديلًا أولًا، والمعرّف يحسم التساوي فلا يتقلب الترتيب.
        owned.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return Page(
            items=owned[offset : offset + limit],
            total=len(owned),
            limit=limit,
            offset=offset,
        )

    def rename_conversation(
        self, *, conversation_id: int, organization_id: int, user_id: int, title: str
    ) -> Conversation | None:
        with MemoryConversationStore._lock:
            current = self._owned(conversation_id, organization_id, user_id)
            if current is None:
                return None
            renamed = Conversation(
                id=current.id,
                organization_id=current.organization_id,
                user_id=current.user_id,
                title=title,
                created_at=current.created_at,
                updated_at=datetime.now(UTC),
            )
            MemoryConversationStore._conversations[conversation_id] = renamed
            return self._with_count(renamed)

    def delete_conversation(
        self, *, conversation_id: int, organization_id: int, user_id: int
    ) -> bool:
        with MemoryConversationStore._lock:
            if self._owned(conversation_id, organization_id, user_id) is None:
                return False
            del MemoryConversationStore._conversations[conversation_id]
            # الرسائل تذهب مع محادثتها، كما يفعل ON DELETE CASCADE في المخطط.
            MemoryConversationStore._messages.pop(conversation_id, None)
            return True

    def add_messages(
        self,
        *,
        conversation_id: int,
        organization_id: int,
        entries: Sequence[tuple[str, str]],
    ) -> list[Message]:
        now = datetime.now(UTC)
        with MemoryConversationStore._lock:
            conversation = MemoryConversationStore._conversations.get(conversation_id)
            if conversation is None or conversation.organization_id != organization_id:
                raise ConversationStoreError("المحادثة المطلوبة غير موجودة.")

            created: list[Message] = []
            for role, content in entries:
                message = Message(
                    id=MemoryConversationStore._next_message_id,
                    conversation_id=conversation_id,
                    organization_id=organization_id,
                    role=role,
                    content=content,
                    created_at=now,
                )
                MemoryConversationStore._messages[conversation_id].append(message)
                MemoryConversationStore._next_message_id += 1
                created.append(message)

            MemoryConversationStore._conversations[conversation_id] = Conversation(
                id=conversation.id,
                organization_id=conversation.organization_id,
                user_id=conversation.user_id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=now,
            )
        return created

    def _owned_messages(
        self, conversation_id: int, organization_id: int
    ) -> list[Message]:
        conversation = MemoryConversationStore._conversations.get(conversation_id)
        if conversation is None or conversation.organization_id != organization_id:
            return []
        return list(MemoryConversationStore._messages.get(conversation_id, ()))

    def list_messages(
        self, *, conversation_id: int, organization_id: int, limit: int, offset: int
    ) -> Page:
        with MemoryConversationStore._lock:
            messages = self._owned_messages(conversation_id, organization_id)
        # الترتيب بالمعرّف كذلك: رسالتا التبادل الواحد تحملان الوقت نفسه.
        messages.sort(key=lambda item: (item.created_at, item.id))
        return Page(
            items=messages[offset : offset + limit],
            total=len(messages),
            limit=limit,
            offset=offset,
        )

    def recent_messages(
        self, *, conversation_id: int, organization_id: int, limit: int
    ) -> list[Message]:
        with MemoryConversationStore._lock:
            messages = self._owned_messages(conversation_id, organization_id)
        messages.sort(key=lambda item: (item.created_at, item.id))
        return messages[-limit:] if limit > 0 else []

    @classmethod
    def reset(cls) -> None:
        """يفرغ المخزن. للاختبارات ولإعادة التشغيل النظيفة."""
        with cls._lock:
            cls._conversations = {}
            cls._messages = {}
            cls._next_conversation_id = 1
            cls._next_message_id = 1


# ---------------------------------------------------------------------------
# مخزن Oracle
# ---------------------------------------------------------------------------
class OracleConversationStore(ConversationStore):
    """محادثات ورسائل في جدولي conversations و messages."""

    name = "oracle"

    def create_conversation(
        self, *, organization_id: int, user_id: int, title: str
    ) -> Conversation:
        from ..database.conversations import insert_conversation

        return insert_conversation(
            organization_id=organization_id, user_id=user_id, title=title
        )

    def get_conversation(
        self, *, conversation_id: int, organization_id: int, user_id: int
    ) -> Conversation | None:
        from ..database.conversations import fetch_conversation

        return fetch_conversation(
            conversation_id=conversation_id,
            organization_id=organization_id,
            user_id=user_id,
        )

    def list_conversations(
        self, *, organization_id: int, user_id: int, limit: int, offset: int
    ) -> Page:
        from ..database.conversations import fetch_conversations

        return fetch_conversations(
            organization_id=organization_id,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )

    def rename_conversation(
        self, *, conversation_id: int, organization_id: int, user_id: int, title: str
    ) -> Conversation | None:
        from ..database.conversations import update_conversation_title

        return update_conversation_title(
            conversation_id=conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            title=title,
        )

    def delete_conversation(
        self, *, conversation_id: int, organization_id: int, user_id: int
    ) -> bool:
        from ..database.conversations import delete_conversation_row

        return delete_conversation_row(
            conversation_id=conversation_id,
            organization_id=organization_id,
            user_id=user_id,
        )

    def add_messages(
        self,
        *,
        conversation_id: int,
        organization_id: int,
        entries: Sequence[tuple[str, str]],
    ) -> list[Message]:
        from ..database.conversations import insert_messages

        return insert_messages(
            conversation_id=conversation_id,
            organization_id=organization_id,
            entries=entries,
        )

    def list_messages(
        self, *, conversation_id: int, organization_id: int, limit: int, offset: int
    ) -> Page:
        from ..database.conversations import fetch_messages

        return fetch_messages(
            conversation_id=conversation_id,
            organization_id=organization_id,
            limit=limit,
            offset=offset,
        )

    def recent_messages(
        self, *, conversation_id: int, organization_id: int, limit: int
    ) -> list[Message]:
        from ..database.conversations import fetch_recent_messages

        return fetch_recent_messages(
            conversation_id=conversation_id,
            organization_id=organization_id,
            limit=limit,
        )


_STORES: dict[str, type[ConversationStore]] = {
    "memory": MemoryConversationStore,
    "oracle": OracleConversationStore,
}


def get_conversation_store(name: str | None = None) -> ConversationStore:
    """يعيد مخزن المحادثات المفعّل.

    Raises:
        ConversationStoreError: إذا كان الاسم غير مدعوم.
    """
    store_name = (name or settings.data_store or "memory").strip().lower()
    store_class = _STORES.get(store_name)
    if store_class is None:
        supported = "، ".join(sorted(_STORES))
        raise ConversationStoreError(
            f"DATA_STORE='{store_name}' غير مدعوم. القيم المدعومة: {supported}."
        )
    return store_class()
