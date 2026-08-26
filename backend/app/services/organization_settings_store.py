"""إعدادات الجهة الإدارية: الاشتراك ومزود المودل.

كلاهما **صف واحد لكل جهة** (قيدا ``uq_subscriptions_org`` و
``uq_model_settings_org``)، ويُقرآن في كل طلب تقريبًا، فجُمعا في مخزن واحد.

* ``memory`` (الافتراضي) — داخل ذاكرة العملية، مزروع بالجهتين التجريبيتين.
* ``oracle`` — جدولا ``subscriptions`` و ``model_settings``.

**قاعدة العزل:** كل دالة تأخذ ``organization_id``، ولا توجد دالة تقرأ اشتراكًا
ولا إعدادات بلا جهة.

**لا تُخزَّن هنا أي مفاتيح ولا أسرار**، كما ينص المخطط: بيانات اعتماد OCI تبقى
في متغيرات البيئة على السيرفر، خارج القاعدة وخارج المستودع.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime

from ..core.config import settings

#: حالات الاشتراك، مطابقة لقيد ck_subscriptions_status في المخطط.
SUBSCRIPTION_STATUSES: tuple[str, ...] = ("active", "expired", "suspended")


class OrganizationSettingsError(Exception):
    """خطأ في إعدادات الجهة، برسالة عربية صالحة للعرض."""


def as_utc(moment: datetime) -> datetime:
    """يجعل الطابع الزمني واعيًا بالمنطقة الزمنية قبل أي مقارنة.

    عمود ``TIMESTAMP`` في Oracle بلا منطقة زمنية، فيعود من الدرايفر ساذجًا،
    بينما مخزن الذاكرة ينتج طوابع بـUTC. مقارنة الاثنين مباشرةً ترفع
    ``TypeError``، وهي عطل يظهر على السيرفر فقط لا في التطوير.
    """
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Subscription:
    """اشتراك جهة واحدة: مدته وعدد مقاعده."""

    organization_id: int
    status: str
    #: عدد التراخيص. المستخدَم منها = عدد المستخدمين النشطين في الجهة.
    seats: int
    starts_at: datetime
    expires_at: datetime

    def blocked_reason(self, *, now: datetime | None = None) -> str | None:
        """يعيد سبب منع الاستخدام بالعربية، أو ``None`` إن كان الاشتراك صالحًا.

        يُفحص الحقلان معًا لا أحدهما: ``status`` قد يكون ``active`` بينما
        ``expires_at`` قد مضى (لا يوجد Trigger يحدّث الحالة تلقائيًا — انظر
        تعليق المخطط)، و ``suspended`` يمنع ولو كان التاريخ في المستقبل.
        """
        moment = now or datetime.now(UTC)
        expires = as_utc(self.expires_at)
        expiry_text = expires.strftime("%Y-%m-%d")

        if self.status == "suspended":
            return (
                "اشتراك جهتك موقوف حاليًا. راجع مسؤول النظام في جهتك لإعادة "
                "تفعيله."
            )
        if self.status == "expired" or expires <= moment:
            return (
                f"انتهى اشتراك جهتك بتاريخ {expiry_text}. "
                "راجع مسؤول النظام في جهتك لتجديد الاشتراك قبل متابعة الاستخدام."
            )
        if as_utc(self.starts_at) > moment:
            starts_text = as_utc(self.starts_at).strftime("%Y-%m-%d")
            return (
                f"اشتراك جهتك لم يبدأ بعد؛ يبدأ بتاريخ {starts_text}. "
                "راجع مسؤول النظام في جهتك."
            )
        return None


@dataclass(frozen=True)
class ModelSettings:
    """مزود المودل الذي اختارته الجهة."""

    organization_id: int
    provider: str
    updated_at: datetime


class OrganizationSettingsStore(ABC):
    """واجهة قراءة وكتابة اشتراك الجهة وإعدادات مودلها."""

    name: str = "base"

    @abstractmethod
    def get_subscription(self, organization_id: int) -> Subscription | None:
        """يقرأ اشتراك الجهة، أو None إن لم يوجد صف لها."""
        raise NotImplementedError

    @abstractmethod
    def upsert_subscription(
        self,
        *,
        organization_id: int,
        status: str,
        seats: int,
        starts_at: datetime,
        expires_at: datetime,
    ) -> Subscription:
        """ينشئ اشتراك الجهة أو يستبدله. صف واحد لكل جهة."""
        raise NotImplementedError

    @abstractmethod
    def get_model_settings(self, organization_id: int) -> ModelSettings | None:
        """يقرأ إعدادات مودل الجهة، أو None إن لم تختر شيئًا بعد."""
        raise NotImplementedError

    @abstractmethod
    def set_model_settings(
        self, *, organization_id: int, provider: str
    ) -> ModelSettings:
        """يثبّت مزود المودل للجهة. صف واحد لكل جهة."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# المخزن المحلي
# ---------------------------------------------------------------------------
#: اشتراكات الجهات الثلاث، **مطابقة لـ`mock-data/organizations.json`
#: حرفيًا**: الحالة والمقاعد والتواريخ. لا انحراف بين المصدرين.
#:
#: جهتان فعّالتان (١ و ٢) لإثبات عزل البيانات — ولا يمكن إثباته بجهة لا
#: يُسجَّل الدخول إليها — وجهة ثالثة (٣) اشتراكها منتهٍ لاختبار منع
#: الاستخدام. إفراد جهة للانتهاء يجعل الحالتين قابلتين للاختبار معًا.
#:
#: التواريخ ثابتة لا نسبية حتى تطابق الملف. تاريخ ٢٠٣٠ للفعّالتين بعيد
#: بما يكفي، ويحرسه اختبار يفشل إن اقترب — انظر
#: test_seeded_active_organizations_are_usable في tests/test_subscriptions.py.
_SEED_SUBSCRIPTIONS: tuple[dict, ...] = (
    {
        "organization_id": 1,
        "status": "active",
        "seats": 10,
        "starts_at": datetime(2025, 1, 1, tzinfo=UTC),
        "expires_at": datetime(2030, 1, 1, tzinfo=UTC),
    },
    {
        "organization_id": 2,
        "status": "active",
        "seats": 5,
        "starts_at": datetime(2025, 1, 1, tzinfo=UTC),
        "expires_at": datetime(2030, 1, 1, tzinfo=UTC),
    },
    {
        "organization_id": 3,
        "status": "expired",
        "seats": 5,
        "starts_at": datetime(2024, 7, 1, tzinfo=UTC),
        "expires_at": datetime(2025, 6, 30, tzinfo=UTC),
    },
)


class MemoryOrganizationSettingsStore(OrganizationSettingsStore):
    """اشتراكات وإعدادات داخل ذاكرة العملية، للتطوير والاختبار فقط."""

    name = "memory"

    _subscriptions: dict[int, Subscription] = {}
    _model_settings: dict[int, ModelSettings] = {}
    _seeded: bool = False
    _lock = threading.Lock()

    def _ensure_seeded(self) -> None:
        if MemoryOrganizationSettingsStore._seeded:
            return
        with MemoryOrganizationSettingsStore._lock:
            if MemoryOrganizationSettingsStore._seeded:
                return
            MemoryOrganizationSettingsStore._subscriptions = {
                entry["organization_id"]: Subscription(**entry)
                for entry in _SEED_SUBSCRIPTIONS
            }
            # لا إعدادات مودل مزروعة: الجهة التي لم تختر شيئًا تعود إلى
            # MODEL_PROVIDER، وهو المسار الافتراضي الذي يجب أن يبقى مُختبَرًا.
            MemoryOrganizationSettingsStore._model_settings = {}
            MemoryOrganizationSettingsStore._seeded = True

    def get_subscription(self, organization_id: int) -> Subscription | None:
        self._ensure_seeded()
        return MemoryOrganizationSettingsStore._subscriptions.get(organization_id)

    def upsert_subscription(
        self,
        *,
        organization_id: int,
        status: str,
        seats: int,
        starts_at: datetime,
        expires_at: datetime,
    ) -> Subscription:
        self._ensure_seeded()
        subscription = Subscription(
            organization_id=organization_id,
            status=status,
            seats=seats,
            starts_at=starts_at,
            expires_at=expires_at,
        )
        with MemoryOrganizationSettingsStore._lock:
            MemoryOrganizationSettingsStore._subscriptions[organization_id] = (
                subscription
            )
        return subscription

    def get_model_settings(self, organization_id: int) -> ModelSettings | None:
        self._ensure_seeded()
        return MemoryOrganizationSettingsStore._model_settings.get(organization_id)

    def set_model_settings(
        self, *, organization_id: int, provider: str
    ) -> ModelSettings:
        self._ensure_seeded()
        chosen = ModelSettings(
            organization_id=organization_id,
            provider=provider,
            updated_at=datetime.now(UTC),
        )
        with MemoryOrganizationSettingsStore._lock:
            MemoryOrganizationSettingsStore._model_settings[organization_id] = chosen
        return chosen

    @classmethod
    def reset(cls) -> None:
        """يفرغ المخزن ليُزرع من جديد. للاختبارات."""
        with cls._lock:
            cls._subscriptions = {}
            cls._model_settings = {}
            cls._seeded = False


# ---------------------------------------------------------------------------
# مخزن Oracle
# ---------------------------------------------------------------------------
class OracleOrganizationSettingsStore(OrganizationSettingsStore):
    """اشتراكات وإعدادات في جدولي subscriptions و model_settings."""

    name = "oracle"

    def get_subscription(self, organization_id: int) -> Subscription | None:
        from ..database.organization_settings import fetch_subscription

        return fetch_subscription(organization_id)

    def upsert_subscription(
        self,
        *,
        organization_id: int,
        status: str,
        seats: int,
        starts_at: datetime,
        expires_at: datetime,
    ) -> Subscription:
        from ..database.organization_settings import save_subscription

        return save_subscription(
            organization_id=organization_id,
            status=status,
            seats=seats,
            starts_at=starts_at,
            expires_at=expires_at,
        )

    def get_model_settings(self, organization_id: int) -> ModelSettings | None:
        from ..database.organization_settings import fetch_model_settings

        return fetch_model_settings(organization_id)

    def set_model_settings(
        self, *, organization_id: int, provider: str
    ) -> ModelSettings:
        from ..database.organization_settings import save_model_settings

        return save_model_settings(
            organization_id=organization_id, provider=provider
        )


_STORES: dict[str, type[OrganizationSettingsStore]] = {
    "memory": MemoryOrganizationSettingsStore,
    "oracle": OracleOrganizationSettingsStore,
}


def get_organization_settings_store(
    name: str | None = None,
) -> OrganizationSettingsStore:
    """يعيد مخزن إعدادات الجهة المفعّل.

    Raises:
        OrganizationSettingsError: إذا كان الاسم غير مدعوم.
    """
    store_name = (name or settings.data_store or "memory").strip().lower()
    store_class = _STORES.get(store_name)
    if store_class is None:
        supported = "، ".join(sorted(_STORES))
        raise OrganizationSettingsError(
            f"DATA_STORE='{store_name}' غير مدعوم. القيم المدعومة: {supported}."
        )
    return store_class()
