"""سجل التدقيق: أحداث مهمة تُضاف ولا تُعدَّل ولا تُحذف.

**سجل إضافة فقط (append-only).** لا توجد هنا دالة تعديل ولا حذف عمدًا: سجلٌ
يمكن تنقيحه لا يصلح دليلًا على ما جرى.

* ``memory`` (الافتراضي) — داخل ذاكرة العملية، غير دائم.
* ``oracle`` — جدول ``audit_logs``.

**قاعدة العزل:** كل قراءة مقيّدة بـ``organization_id``، ولا توجد دالة تقرأ
السجل كله. القراءة لمسؤول الجهة وحده — يفرضه `audit_service`.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime

from ..core.config import settings
from .conversation_store import Page

#: أسماء الأحداث المسجَّلة. الأسماء مطابقة لأمثلة المخطط في
#: database/schema.sql حيثما ذُكرت، حتى لا يختلف الاسم بين الجدول والكود.
ACTION_LOGIN = "login"
ACTION_USER_CREATED = "user_created"
ACTION_USER_DISABLED = "user_disabled"
ACTION_CONVERSATION_DELETED = "conversation_deleted"
ACTION_FILE_UPLOADED = "file_uploaded"
ACTION_FILE_DELETED = "file_deleted"
ACTION_MODEL_PROVIDER_CHANGED = "model_provider_changed"
ACTION_SUBSCRIPTION_CHANGED = "subscription_changed"
ACTION_ORGANIZATION_PROVISIONED = "organization_provisioned"

KNOWN_ACTIONS: tuple[str, ...] = (
    ACTION_LOGIN,
    ACTION_USER_CREATED,
    ACTION_USER_DISABLED,
    ACTION_CONVERSATION_DELETED,
    ACTION_FILE_UPLOADED,
    ACTION_FILE_DELETED,
    ACTION_MODEL_PROVIDER_CHANGED,
    ACTION_SUBSCRIPTION_CHANGED,
    ACTION_ORGANIZATION_PROVISIONED,
)

#: حدّا العمودين في المخطط. القصّ هنا أفضل من رفض الحدث: سجلٌ مقصوص خير من
#: عملية تفشل لأن وصفها طال.
MAX_ACTION_LENGTH = 60
MAX_DETAILS_LENGTH = 1000


class AuditStoreError(Exception):
    """خطأ في سجل التدقيق، برسالة عربية صالحة للعرض."""


@dataclass(frozen=True)
class AuditEvent:
    """حدث واحد في السجل."""

    id: int
    organization_id: int
    #: قد يكون None لأحداث تسبق وجود مستخدم (تجهيز جهة).
    user_id: int | None
    action: str
    details: str | None
    created_at: datetime


class AuditStore(ABC):
    """واجهة كتابة السجل وقراءته."""

    name: str = "base"

    @abstractmethod
    def append(
        self,
        *,
        organization_id: int,
        user_id: int | None,
        action: str,
        details: str | None,
    ) -> AuditEvent:
        """يضيف حدثًا. لا مقابل له في التعديل ولا في الحذف."""
        raise NotImplementedError

    @abstractmethod
    def list_events(
        self,
        *,
        organization_id: int,
        action: str | None,
        user_id: int | None,
        limit: int,
        offset: int,
    ) -> Page:
        """يعيد أحداث جهة واحدة من الأحدث، مع إمكان التصفية."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# المخزن المحلي
# ---------------------------------------------------------------------------
class MemoryAuditStore(AuditStore):
    """سجل داخل ذاكرة العملية، للتطوير والاختبار فقط.

    **غير دائم:** يفرغ عند إعادة التشغيل، فلا يصلح سجل تدقيق حقيقي. على
    السيرفر يلزم ``DATA_STORE=oracle``.
    """

    name = "memory"

    _events: list[AuditEvent] = []
    _next_id: int = 1
    _lock = threading.Lock()

    def append(
        self,
        *,
        organization_id: int,
        user_id: int | None,
        action: str,
        details: str | None,
    ) -> AuditEvent:
        with MemoryAuditStore._lock:
            event = AuditEvent(
                id=MemoryAuditStore._next_id,
                organization_id=organization_id,
                user_id=user_id,
                action=action[:MAX_ACTION_LENGTH],
                details=None if details is None else details[:MAX_DETAILS_LENGTH],
                created_at=datetime.now(UTC),
            )
            MemoryAuditStore._events.append(event)
            MemoryAuditStore._next_id += 1
        return event

    def list_events(
        self,
        *,
        organization_id: int,
        action: str | None,
        user_id: int | None,
        limit: int,
        offset: int,
    ) -> Page:
        with MemoryAuditStore._lock:
            matches = [
                event
                for event in MemoryAuditStore._events
                if event.organization_id == organization_id
                and (action is None or event.action == action)
                and (user_id is None or event.user_id == user_id)
            ]
        # الأحدث أولًا، والمعرّف يحسم التساوي فلا يتقلب الترتيب بين صفحتين.
        matches.sort(key=lambda event: (event.created_at, event.id), reverse=True)
        return Page(
            items=matches[offset : offset + limit],
            total=len(matches),
            limit=limit,
            offset=offset,
        )

    @classmethod
    def reset(cls) -> None:
        """يفرغ السجل. للاختبارات ولإعادة التشغيل النظيفة."""
        with cls._lock:
            cls._events = []
            cls._next_id = 1


# ---------------------------------------------------------------------------
# مخزن Oracle
# ---------------------------------------------------------------------------
class OracleAuditStore(AuditStore):
    """سجل في جدول audit_logs."""

    name = "oracle"

    def append(
        self,
        *,
        organization_id: int,
        user_id: int | None,
        action: str,
        details: str | None,
    ) -> AuditEvent:
        from ..database.audit import insert_event

        return insert_event(
            organization_id=organization_id,
            user_id=user_id,
            action=action[:MAX_ACTION_LENGTH],
            details=None if details is None else details[:MAX_DETAILS_LENGTH],
        )

    def list_events(
        self,
        *,
        organization_id: int,
        action: str | None,
        user_id: int | None,
        limit: int,
        offset: int,
    ) -> Page:
        from ..database.audit import fetch_events

        return fetch_events(
            organization_id=organization_id,
            action=action,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )


_STORES: dict[str, type[AuditStore]] = {
    "memory": MemoryAuditStore,
    "oracle": OracleAuditStore,
}

#: يُستورد كسولًا: وحدة Supabase تقرأ إعداداتها وتفتح عميل HTTP عند الاستخدام
#: لا عند الاستيراد، فيبقى المشروع يقلع بلا Supabase أصلًا — كما يقلع بلا
#: Oracle. لهذا لا يظهر الصنف في ``_STORES`` مباشرة.
def _supabase_store() -> type[AuditStore]:
    from .supabase_stores import SupabaseAuditStore

    return SupabaseAuditStore


#: القيم المقبولة لـDATA_STORE.
SUPPORTED_DATA_STORES: tuple[str, ...] = tuple(sorted({*_STORES, "supabase"}))



def get_audit_store(name: str | None = None) -> AuditStore:
    """يعيد مخزن السجل المفعّل.

    Raises:
        AuditStoreError: إذا كان الاسم غير مدعوم.
    """
    store_name = (name or settings.data_store or "memory").strip().lower()
    if store_name == "supabase":
        return _supabase_store()()
    store_class = _STORES.get(store_name)
    if store_class is None:
        supported = "، ".join(SUPPORTED_DATA_STORES)
        raise AuditStoreError(
            f"DATA_STORE='{store_name}' غير مدعوم. القيم المدعومة: {supported}."
        )
    return store_class()
