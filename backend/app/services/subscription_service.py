"""الاشتراك والتراخيص: فحص الصلاحية وحد المقاعد.

**فحص الاشتراك يمر على كل طلب محمي وعلى تسجيل الدخول.** لذلك تُعزَل هذه
الدوال في وحدة صغيرة يستوردها `api/dependencies` و `auth_service` بلا سحب
منطق إدارة الجهات كله.

**فشل مغلق (fail closed):** جهة بلا صف اشتراك **تُمنع**، لا تُسمح. رخصة
غائبة ليست رخصة مفتوحة، وصفٌ ناقص في القاعدة يجب أن يظهر كمنع واضح لا كسماح
صامت. التجهيز ينشئ الاشتراك مع الجهة، فالحالة لا تقع في المسار الطبيعي.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..core.config import settings
from .organization_settings_store import (
    SUBSCRIPTION_STATUSES,
    Subscription,
    get_organization_settings_store,
)
from .user_store import User, get_user_store

#: رسالة الجهة التي لا صف اشتراك لها. تُوجَّه للمستخدم لا للمطوّر.
_MISSING_SUBSCRIPTION = (
    "لا يوجد اشتراك مسجّل لجهتك في النظام، فلا يمكن استخدام الخدمة. "
    "راجع مسؤول النظام لتفعيل اشتراك الجهة."
)


class SubscriptionError(Exception):
    """خطأ متعلق بالاشتراك، برسالة عربية صالحة للعرض."""


class SubscriptionInactiveError(SubscriptionError):
    """اشتراك الجهة منتهٍ أو موقوف أو غير مسجّل."""


class SeatLimitReachedError(SubscriptionError):
    """عدد المستخدمين النشطين بلغ عدد التراخيص."""


def get_subscription(organization_id: int) -> Subscription | None:
    """يقرأ اشتراك الجهة كما هو، بلا حكم على صلاحيته."""
    return get_organization_settings_store().get_subscription(organization_id)


def ensure_active(organization_id: int) -> Subscription:
    """يتحقق من صلاحية اشتراك الجهة، أو يرفع خطأً برسالة تشرح السبب.

    Raises:
        SubscriptionInactiveError: منتهٍ أو موقوف أو لم يبدأ أو غير مسجّل،
            والرسالة تذكر **تاريخ الانتهاء** لا خطأً عامًا.
    """
    subscription = get_subscription(organization_id)
    if subscription is None:
        raise SubscriptionInactiveError(_MISSING_SUBSCRIPTION)

    reason = subscription.blocked_reason()
    if reason is not None:
        raise SubscriptionInactiveError(reason)
    return subscription


def seat_usage(organization_id: int) -> tuple[int, int]:
    """يعيد (المقاعد المستهلَكة، إجمالي المقاعد) للجهة.

    المستهلَك = عدد المستخدمين النشطين؛ لا يوجد جدول تراخيص منفصل في الـMVP.
    """
    used = get_user_store().count_active_users(organization_id=organization_id)
    subscription = get_subscription(organization_id)
    return used, (subscription.seats if subscription else 0)


def ensure_seat_available(organization_id: int) -> None:
    """يتحقق من وجود مقعد شاغر قبل تفعيل مستخدم جديد أو معطَّل.

    يُستدعى عند **إنشاء** موظف وعند **إعادة تفعيل** حساب معطّل: الثانية تشغل
    مقعدًا كالأولى، ولو فُحص الإنشاء وحده لأمكن تجاوز الحد بتعطيل ثم تفعيل.

    Raises:
        SubscriptionInactiveError: إذا كان اشتراك الجهة غير صالح.
        SeatLimitReachedError: إذا لم يبق مقعد شاغر، والرسالة تذكر العددين.
    """
    subscription = ensure_active(organization_id)
    used = get_user_store().count_active_users(organization_id=organization_id)

    if used >= subscription.seats:
        raise SeatLimitReachedError(
            f"عدد تراخيص جهتك {subscription.seats}، وجميعها مستخدَمة حاليًا "
            f"({used} من {subscription.seats}). عطّل حساب موظف غير نشط أو "
            "راجع مسؤول النظام لزيادة عدد التراخيص."
        )


def default_subscription_window() -> tuple[datetime, datetime]:
    """يعيد (البداية، النهاية) لاشتراك جهة جُهّزت للتو."""
    now = datetime.now(UTC)
    return now, now + timedelta(days=settings.subscription_default_days)


def provision_subscription(
    *, organization_id: int, seats: int | None = None
) -> Subscription:
    """ينشئ اشتراك جهة جديدة عند تجهيزها.

    يُستدعى من مسار التجهيز وحده: جهة بلا اشتراك لا يستطيع أحد الدخول إليها،
    لأن الفحص مغلق الفشل.
    """
    starts_at, expires_at = default_subscription_window()
    return get_organization_settings_store().upsert_subscription(
        organization_id=organization_id,
        status="active",
        seats=seats or settings.subscription_default_seats,
        starts_at=starts_at,
        expires_at=expires_at,
    )


def update_subscription(
    *,
    organization_id: int,
    status: str | None = None,
    seats: int | None = None,
    starts_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> Subscription:
    """يعدّل اشتراك جهة قائمة. الحقول المتروكة فارغة لا تتغيّر.

    **ليست عملية داخل التطبيق:** تجديد الاشتراك وزيادة المقاعد قرار من يقدّم
    الخدمة لا من يستهلكها. لو مَلَكَه مسؤول الجهة لمنح نفسه مقاعد بلا حد.
    يحرسها مفتاح التجهيز في مسار الـAPI — انظر `api/organizations.py`.

    Raises:
        SubscriptionError: إذا لم يوجد اشتراك للجهة، أو كانت القيم غير مقبولة.
    """
    current = get_subscription(organization_id)
    if current is None:
        raise SubscriptionError(
            "لا يوجد اشتراك مسجّل لهذه الجهة. جهّزها أولًا عبر مسار التجهيز."
        )

    if status is not None and status not in SUBSCRIPTION_STATUSES:
        raise SubscriptionError(
            f"حالة الاشتراك «{status}» غير مقبولة. القيم المقبولة: "
            f"{'، '.join(SUBSCRIPTION_STATUSES)}."
        )
    if seats is not None and seats < 1:
        raise SubscriptionError("عدد التراخيص يجب أن يكون واحدًا على الأقل.")

    return get_organization_settings_store().upsert_subscription(
        organization_id=organization_id,
        status=current.status if status is None else status,
        seats=current.seats if seats is None else seats,
        starts_at=current.starts_at if starts_at is None else starts_at,
        expires_at=current.expires_at if expires_at is None else expires_at,
    )


def read_subscription(*, actor: User, organization_id: int) -> Subscription:
    """يقرأ اشتراك جهة صاحب الطلب. لمسؤول الجهة.

    **يعمل ولو كان الاشتراك منتهيًا** — بل هذا أهم أوقات الحاجة إليه: المسؤول
    يفتحه ليعرف تاريخ الانتهاء وعدد المقاعد. الحراسة في مسار الـAPI.

    Raises:
        SubscriptionError: إذا لم يوجد اشتراك للجهة.
    """
    subscription = get_subscription(organization_id)
    if subscription is None:
        raise SubscriptionError(_MISSING_SUBSCRIPTION)
    return subscription
