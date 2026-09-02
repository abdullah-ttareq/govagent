"""الاستحقاق: الاشتراك، وتفعيل الجهاز الواحد، والإذن بتحميل المثبّت.

هذه الوحدة هي **المرجع الوحيد** للسؤال «هل يستحق هذا المستخدم على هذا
الجهاز أن يستعمل GovMind الآن؟». مسارات الـAPI رفيعة فوقها ولا تكرّر شرطًا
منها، فلا يمكن أن ينسى مسارٌ فحصًا يفعله غيره.

**فشل مغلق (fail closed)** كما في `subscription_service`: حساب بلا ملف،
وجهة بلا اشتراك، وجهاز بلا تفعيل — كلها **تمنع**. الغياب ليس إذنًا.

**جهاز واحد لكل اشتراك.** الحدّ يفرضه فهرس فريد جزئي في القاعدة، لا الكود
هنا: طلبان متزامنان لتفعيل جهازين ينجح أحدهما ويفشل الآخر بخطأ تفرّد تترجمه
هذه الوحدة إلى رسالة «الحساب مفعّل على جهاز آخر». الفحص المسبق هنا لتحسين
الرسالة لا لفرض الحدّ.

⚠️ **البصمة الخام لا تدخل هذه الوحدة إلا لتُجزّأ فورًا** — انظر
`core/device_id`. لا تُخزَّن ولا تُسجَّل ولا تخرج في أي رد.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..core.device_id import hash_device_id
from ..database import supabase
from ..database.supabase import (
    UNIQUE_VIOLATION,
    SupabaseConstraintError,
    SupabaseError,
)
from .supabase_auth import SupabaseIdentity

#: الحالتان اللتان تسمحان بالخدمة. الثلاث الباقية تمنع لأسباب مختلفة.
SERVICE_STATUSES: tuple[str, ...] = ("trial", "active")

#: كل الحالات المقبولة في العمود، مطابقة للنوع المعدود في المخطط.
SUBSCRIPTION_STATUSES: tuple[str, ...] = (
    "trial",
    "active",
    "expired",
    "suspended",
    "cancelled",
)


# ---------------------------------------------------------------------------
# الأخطاء — كل واحد يقابل ردًّا واحدًا في طبقة الـAPI
# ---------------------------------------------------------------------------
class EntitlementError(Exception):
    """خطأ استحقاق، برسالة عربية صالحة للعرض على المستخدم مباشرة."""


class AccountNotProvisionedError(EntitlementError):
    """للحساب هوية في `auth.users` لكن لا ملف عمل له في `profiles`."""


class SubscriptionMissingError(EntitlementError):
    """لا صف اشتراك لجهة المستخدم — يُمنع، لا يُسمح."""


class SubscriptionInactiveError(EntitlementError):
    """الاشتراك منتهٍ أو موقوف أو ملغى أو لم يبدأ بعد."""


class DeviceLimitReachedError(EntitlementError):
    """الاشتراك مفعّل على جهاز آخر، ولا يُسمح بأكثر من جهاز فعّال."""


class DeviceNotActivatedError(EntitlementError):
    """لا جهاز مفعّلًا على هذا الاشتراك بعد."""


class DeviceMismatchError(EntitlementError):
    """الجهاز الطالب ليس الجهاز المفعّل على هذا الاشتراك."""


class DeviceNotFoundError(EntitlementError):
    """التفعيل المطلوب غير موجود **في نطاق صاحب الطلب**."""


class AdminRequiredError(EntitlementError):
    """الإجراء لمسؤول الجهة وحده."""


# ---------------------------------------------------------------------------
# النماذج
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Account:
    """ملف عمل المستخدم كما هو في `profiles`."""

    user_id: str
    app_user_id: int
    organization_id: int
    email: str
    full_name: str
    role: str
    is_active: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass(frozen=True)
class Subscription:
    """اشتراك جهة واحدة."""

    id: int
    organization_id: int
    status: str
    seats: int
    starts_at: datetime
    expires_at: datetime

    def blocked_reason(self, *, now: datetime | None = None) -> str | None:
        """سبب المنع بالعربية، أو ``None`` إن كان الاشتراك يسمح بالخدمة.

        **الحالة والتاريخ يُفحصان معًا لا أحدهما:** لا Trigger في القاعدة
        يحوّل `active` إلى `expired` عند مرور التاريخ، فحالةٌ سارية مع
        تاريخ ماضٍ اشتراكٌ منتهٍ فعلًا.
        """
        moment = now or datetime.now(UTC)
        expiry_text = self.expires_at.strftime("%Y-%m-%d")

        if self.status == "suspended":
            return (
                "اشتراكك موقوف حاليًا. تواصل مع الدعم لإعادة تفعيله."
            )
        if self.status == "cancelled":
            return "اشتراكك ملغى. جدّد اشتراكك للمتابعة."
        if self.status == "expired" or self.expires_at <= moment:
            return (
                f"انتهى اشتراكك بتاريخ {expiry_text}. جدّد اشتراكك "
                "لمتابعة الاستخدام."
            )
        if self.status not in SERVICE_STATUSES:
            return "اشتراكك لا يسمح باستخدام الخدمة حاليًا. تواصل مع الدعم."
        if self.starts_at > moment:
            starts_text = self.starts_at.strftime("%Y-%m-%d")
            return (
                f"اشتراكك لم يبدأ بعد؛ يبدأ بتاريخ {starts_text}."
            )
        return None

    @property
    def is_serviceable(self) -> bool:
        return self.blocked_reason() is None


@dataclass(frozen=True)
class DeviceActivation:
    """تفعيل جهاز واحد على اشتراك.

    ⚠️ ``device_id_hash`` تجزئة لا بصمة، **ولا تخرج في أي رد للعميل**:
    من يعرف التجزئة يستطيع انتحال الجهاز أمام أي فحص يقارنها.
    """

    id: int
    subscription_id: int
    device_id_hash: str
    device_name: str
    activated_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


# ---------------------------------------------------------------------------
# تحويل صفوف Supabase
# ---------------------------------------------------------------------------
def _parse_timestamp(value: Any) -> datetime:
    """يحوّل طابع PostgreSQL الزمني إلى ``datetime`` واعٍ بـUTC.

    كل مقارنات الصلاحية تتم على طوابع واعية؛ طابع ساذج يقارَن بواعٍ يرفع
    ``TypeError`` — عطلٌ يظهر على السيرفر وحده لا في التطوير.
    """
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value or "").strip()
        if not text:
            raise SupabaseError("صف ناقص من Supabase: طابع زمني مفقود.")
        # PostgREST يعيد أحيانًا "Z" وأحيانًا "+00:00".
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SupabaseError(
                "طابع زمني غير مفهوم في رد Supabase."
            ) from exc
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _to_account(row: dict[str, Any]) -> Account:
    return Account(
        user_id=str(row["id"]),
        app_user_id=int(row["app_user_id"]),
        organization_id=int(row["organization_id"]),
        email=str(row.get("email") or ""),
        full_name=str(row.get("full_name") or ""),
        role=str(row.get("role") or "employee"),
        is_active=bool(row.get("is_active", True)),
    )


def _to_subscription(row: dict[str, Any]) -> Subscription:
    return Subscription(
        id=int(row["id"]),
        organization_id=int(row["organization_id"]),
        status=str(row["status"]),
        seats=int(row.get("seats") or 0),
        starts_at=_parse_timestamp(row["starts_at"]),
        expires_at=_parse_timestamp(row["expires_at"]),
    )


def _to_device(row: dict[str, Any]) -> DeviceActivation:
    revoked = row.get("revoked_at")
    return DeviceActivation(
        id=int(row["id"]),
        subscription_id=int(row["subscription_id"]),
        device_id_hash=str(row["device_id_hash"]),
        device_name=str(row.get("device_name") or ""),
        activated_at=_parse_timestamp(row["activated_at"]),
        last_seen_at=_parse_timestamp(row["last_seen_at"]),
        revoked_at=_parse_timestamp(revoked) if revoked else None,
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# القراءة
# ---------------------------------------------------------------------------
def load_account(identity: SupabaseIdentity) -> Account:
    """يقرأ ملف عمل صاحب الرمز.

    Raises:
        AccountNotProvisionedError: لا ملف له، أو ملفه معطّل.
    """
    row = supabase.select_one(
        "profiles",
        columns="id,app_user_id,organization_id,email,full_name,role,is_active",
        filters={"id": f"eq.{identity.user_id}"},
    )
    if row is None:
        raise AccountNotProvisionedError(
            "حسابك غير مكتمل التجهيز. أعد تسجيل الدخول، وإن تكرر الأمر "
            "فتواصل مع الدعم."
        )

    account = _to_account(row)
    if not account.is_active:
        raise AccountNotProvisionedError(
            "حسابك معطّل حاليًا. تواصل مع الدعم."
        )
    return account


def load_subscription(organization_id: int) -> Subscription:
    """يقرأ اشتراك الجهة كما هو، بلا حكم على صلاحيته.

    Raises:
        SubscriptionMissingError: لا صف اشتراك للجهة — **يُمنع**.
    """
    row = supabase.select_one(
        "subscriptions",
        columns="id,organization_id,status,seats,starts_at,expires_at",
        filters={"organization_id": f"eq.{organization_id}"},
    )
    if row is None:
        raise SubscriptionMissingError(
            "لا يوجد اشتراك مرتبط بحسابك، فلا يمكن استخدام الخدمة. "
            "تواصل مع الدعم."
        )
    return _to_subscription(row)


def ensure_serviceable(subscription: Subscription) -> Subscription:
    """يرفع خطأً إن كان الاشتراك لا يسمح بالخدمة.

    Raises:
        SubscriptionInactiveError: والرسالة تذكر السبب وتاريخ الانتهاء.
    """
    reason = subscription.blocked_reason()
    if reason is not None:
        raise SubscriptionInactiveError(reason)
    return subscription


def active_device(subscription_id: int) -> DeviceActivation | None:
    """يعيد الجهاز الفعّال على الاشتراك، أو ``None`` إن لم يوجد.

    الفهرس الفريد الجزئي يضمن أن الصفوف غير المبطلة صفٌّ واحد على الأكثر.
    """
    row = supabase.select_one(
        "device_activations",
        columns=(
            "id,subscription_id,device_id_hash,device_name,"
            "activated_at,last_seen_at,revoked_at"
        ),
        filters={
            "subscription_id": f"eq.{subscription_id}",
            "revoked_at": "is.null",
        },
    )
    return _to_device(row) if row else None


# ⚠️ **حُذفت `find_activation_by_hash` ولا يجوز أن تعود.**
#
# كانت مصادقة الـRuntime: تطابق تجزئةَ سرٍّ **ولّده الـRuntime نفسه** بتفعيل
# قائم. أي برنامج على جهاز العميل يستطيع توليد سرّ، والسيرفر كان يقبل أوّل
# من يصل ما دام يطابق تجزئة مخزّنة — فالقيمة معرّفُ جهاز لا بيانَ اعتماد.
#
# البديل `device_credential_service.authenticate`: بيان يصدره **السيرفر**
# عند استبدال جلسة تركيب صالحة، ويُفحص مع الجهاز والاشتراك في جملة SQL
# واحدة. و`device_id_hash` يبقى هويّةً يقوم عليها قيد «جهاز فعّال واحد»
# واستبدالُ الجهاز — **ولا يصادق شيئًا**.


def load_owner_email(organization_id: int) -> str:
    """بريد صاحب الاشتراك، أو نصّ فارغ إن تعذّرت قراءته.

    **لِمَ يحتاجه الـRuntime؟** ليعرض التطبيق المثبَّت اسم الحساب الذي رُبط
    به الجهاز، فلا يظنّ العميل أنه دخل بحساب آخر. البريد بريده هو، ولا
    يخرج إلى غير الجهاز المرتبط بحسابه.

    ⚠️ **لا يُرفع خطأ عند الغياب**: هذه معلومة عرض لا شرط استحقاق، وحجب
    التطبيق لأن سطر ملف عمل ناقص عقوبة بلا سبب.
    """
    try:
        rows = supabase.select(
            "profiles",
            columns="email",
            filters={"organization_id": f"eq.{organization_id}"},
            # ترتيب ثابت: مساحة العمل في هذا المنتج لحساب واحد، والترتيب
            # يجعل النتيجة محسومة لو بقي صفّ قديم من بيانات سابقة.
            order="created_at.asc",
            limit=1,
        )
    except SupabaseError:
        return ""
    return str((rows[0] if rows else {}).get("email") or "")


def list_devices(subscription_id: int) -> list[DeviceActivation]:
    """يعيد سجل أجهزة الاشتراك كله — الفعّال والمبطل — للمسؤول."""
    rows = supabase.select(
        "device_activations",
        columns=(
            "id,subscription_id,device_id_hash,device_name,"
            "activated_at,last_seen_at,revoked_at"
        ),
        filters={"subscription_id": f"eq.{subscription_id}"},
        order="activated_at.desc",
    )
    return [_to_device(row) for row in rows]


# ---------------------------------------------------------------------------
# تفعيل الجهاز والتحقق منه
# ---------------------------------------------------------------------------
def _touch_last_seen(device: DeviceActivation) -> DeviceActivation:
    """يحدّث ``last_seen_at`` ولا يُفشل العملية إن تعذّر.

    الحقل معلومة تشغيلية للمسؤول لا شرط استحقاق، ففشل كتابته يجب ألا يمنع
    مستخدمًا مستحقًّا من الخدمة.
    """
    try:
        rows = supabase.update(
            "device_activations",
            {"last_seen_at": _now_iso()},
            filters={"id": f"eq.{device.id}"},
        )
    except SupabaseError:
        return device
    return _to_device(rows[0]) if rows else device


def activate_device(
    account: Account, *, raw_device_id: str, device_name: str
) -> DeviceActivation:
    """يفعّل الجهاز الحالي على اشتراك جهة المستخدم.

    **العملية مُعادة التنفيذ (idempotent):** إعادة التفعيل من الجهاز نفسه
    تعيد التفعيل القائم وتحدّث ``last_seen_at`` بدل أن تفشل — الإضافة قد
    تعيد الطلب بعد انقطاع شبكة، ولا يصح أن يبدو ذلك خطأً للمستخدم.

    Raises:
        SubscriptionMissingError | SubscriptionInactiveError: اشتراك لا يسمح.
        DeviceLimitReachedError: الاشتراك مفعّل على جهاز آخر.
        DeviceIdError: بصمة غير صالحة أو مِلح غير مضبوط.
    """
    subscription = ensure_serviceable(load_subscription(account.organization_id))
    device_hash = hash_device_id(raw_device_id)

    existing = active_device(subscription.id)
    if existing is not None:
        if existing.device_id_hash == device_hash:
            return _touch_last_seen(existing)
        raise DeviceLimitReachedError(
            f"حسابك مفعّل حاليًا على جهاز آخر ({existing.device_name}). "
            "اشتراكك يعمل على جهاز واحد فقط، ويمكنك استبدال الجهاز السابق "
            "بهذا الجهاز من نافذة GovMind."
        )

    name = (device_name or "").strip() or "جهاز غير مسمّى"
    try:
        row = supabase.insert(
            "device_activations",
            {
                "subscription_id": subscription.id,
                "device_id_hash": device_hash,
                "device_name": name[:120],
            },
        )
    except SupabaseConstraintError as exc:
        if exc.code == UNIQUE_VIOLATION:
            # سبق جهازٌ آخر هذا الطلب بين الفحص والإدراج. القاعدة رفضت،
            # وهي المرجع لا الفحص أعلاه.
            raise DeviceLimitReachedError(
                "حسابك مفعّل حاليًا على جهاز آخر. اشتراكك يعمل على جهاز "
                "واحد فقط، ويمكنك استبدال الجهاز السابق من نافذة GovMind."
            ) from exc
        raise
    return _to_device(row)


def _verify_against(
    subscription: Subscription, raw_device_id: str
) -> DeviceActivation:
    """جوهر التحقق، على اشتراك **سبق** التأكد من صلاحيته.

    مفصولة عن :func:`verify_device` حتى لا يعيد مسار التحميل قراءة الاشتراك
    وفحصه مرتين في الطلب الواحد.
    """
    device_hash = hash_device_id(raw_device_id)

    current = active_device(subscription.id)
    if current is None:
        raise DeviceNotActivatedError(
            "لم يُفعَّل أي جهاز على حسابك بعد. فعّل هذا الجهاز للمتابعة."
        )
    if current.device_id_hash != device_hash:
        raise DeviceMismatchError(
            f"حسابك مفعّل على جهاز آخر ({current.device_name})، وليس على هذا "
            "الجهاز. يمكنك استبدال الجهاز السابق بهذا الجهاز من نافذة GovMind."
        )
    return _touch_last_seen(current)


def verify_device(account: Account, *, raw_device_id: str) -> DeviceActivation:
    """يتحقق من أن الجهاز الطالب هو الجهاز المفعّل، ويحدّث آخر ظهور له.

    Raises:
        SubscriptionMissingError | SubscriptionInactiveError: اشتراك لا يسمح.
        DeviceNotActivatedError: لا جهاز مفعّلًا بعد.
        DeviceMismatchError: جهاز آخر هو المفعّل.
    """
    subscription = ensure_serviceable(load_subscription(account.organization_id))
    return _verify_against(subscription, raw_device_id)


def replace_device(
    account: Account, *, raw_device_id: str, device_name: str
) -> tuple[DeviceActivation, bool]:
    """يبطل الجهاز الفعّال ويفعّل الجهاز الحالي **في عملية ذرّية واحدة**.

    **يفعلها صاحب الحساب بنفسه** — لا مسؤول يوافق. التحقق من كلمة المرور
    يتم في طبقة الـAPI قبل النداء؛ هذه الدالة تفترض أن الهوية أُثبتت.

    الذرّية من دالة ``replace_device_activation`` في القاعدة: «أبطل ثم
    فعّل» عبر طلبين يتركان نافذة يخرج منها العميل بلا جهاز فعّال، أو
    يخرج منها جهازان.

    Returns:
        (التفعيل الجديد، هل استُبدل جهاز سابق فعلًا؟)

    Raises:
        SubscriptionMissingError | SubscriptionInactiveError: اشتراك لا يسمح.
        DeviceLimitReachedError: سباق نادر أفلت من القفل وردّه القيد.
        DeviceIdError: بصمة غير صالحة أو مِلح غير مضبوط.
    """
    subscription = ensure_serviceable(load_subscription(account.organization_id))
    device_hash = hash_device_id(raw_device_id)

    try:
        rows = supabase.rpc(
            "replace_device_activation",
            {
                "p_subscription_id": subscription.id,
                "p_device_hash": device_hash,
                "p_device_name": (device_name or "").strip()[:120] or "جهاز غير مسمّى",
            },
        )
    except SupabaseError as exc:
        detail = str(exc)
        if "23505" in detail:
            # طلبان متزامنان: القيد ردّ الثاني. الحالة سليمة — جهاز واحد.
            raise DeviceLimitReachedError(
                "جرت محاولة استبدال أخرى في اللحظة نفسها. أعد المحاولة."
            ) from exc
        if "subscription_not_serviceable" in detail:
            raise SubscriptionInactiveError(
                "اشتراكك لا يسمح بتفعيل جهاز حاليًا."
            ) from exc
        raise

    if not rows:
        raise EntitlementError(
            "تعذّر استبدال الجهاز. أعد المحاولة، وإن تكرر فتواصل مع الدعم."
        )

    row = rows[0]
    activation = supabase.select_one(
        "device_activations",
        columns=(
            "id,subscription_id,device_id_hash,device_name,"
            "activated_at,last_seen_at,revoked_at"
        ),
        filters={"id": f"eq.{int(row['out_activation_id'])}"},
    )
    if activation is None:
        raise EntitlementError("تعذّر قراءة حالة الجهاز بعد الاستبدال.")

    return _to_device(activation), bool(row.get("out_replaced"))


def revoke_device(admin: Account, *, activation_id: int) -> DeviceActivation:
    """يبطل تفعيل جهاز. **لمسؤول الجهة، وداخل جهته وحدها.**

    الصف يبقى في القاعدة ولا يُحذف: تاريخ الأجهزة جزء من سجل الاشتراك،
    وملء ``revoked_at`` يخرجه من الفهرس الجزئي فيصير مكان جهاز جديد شاغرًا.

    Raises:
        AdminRequiredError: صاحب الطلب ليس مسؤولًا.
        DeviceNotFoundError: التفعيل غير موجود **أو ليس في جهته** — لا
            يُفرَّق بين الحالتين، فكلاهما لا يعني شيئًا لصاحب الطلب.
    """
    if not admin.is_admin:
        raise AdminRequiredError("إلغاء تفعيل الأجهزة متاح لصاحب الاشتراك فقط.")

    # الاشتراك يُقرأ من جهة المسؤول لا من الطلب: بهذا لا يمكن أن يبطل تفعيلًا
    # في جهة أخرى مهما كان المعرّف الذي أرسله.
    subscription = load_subscription(admin.organization_id)

    row = supabase.select_one(
        "device_activations",
        columns=(
            "id,subscription_id,device_id_hash,device_name,"
            "activated_at,last_seen_at,revoked_at"
        ),
        filters={
            "id": f"eq.{activation_id}",
            "subscription_id": f"eq.{subscription.id}",
        },
    )
    if row is None:
        raise DeviceNotFoundError("تفعيل الجهاز المطلوب غير موجود.")

    device = _to_device(row)
    if not device.is_active:
        # مُبطَل أصلًا: النتيجة هي المطلوبة، فلا داعي لخطأ.
        return device

    rows = supabase.update(
        "device_activations",
        {"revoked_at": _now_iso()},
        filters={"id": f"eq.{device.id}", "revoked_at": "is.null"},
    )
    return _to_device(rows[0]) if rows else device


# ---------------------------------------------------------------------------
# الإذن بالتحميل
# ---------------------------------------------------------------------------
def authorize_installer_download(
    account: Account, *, raw_device_id: str
) -> tuple[Subscription, DeviceActivation | None]:
    """يفحص شروط تحميل المثبّت ويعيد الاشتراك والجهاز المفعّل إن وُجد.

    الشروط، بالترتيب الذي تُفحص به:

    1. الهوية موثوقة — تحقَّق منها المسار قبل الوصول إلى هنا.
    2. الحساب مرتبط بجهة ونشط — ``load_account``.
    3. حالة الاشتراك ``active`` أو ``trial`` ولم ينتهِ تاريخه.
    4. **لا جهاز آخر** يشغل خانة الاشتراك.

    ⚠️ **الشرط الرابع كان «الجهاز الطالب هو المفعّل»، وكان يقفل النظام.**

    هوية الجهاز التي تُفعَّل يولّدها الـRuntime على الحاسب، والـRuntime
    **داخل المثبّت**. فاشتراط تفعيلٍ سابقٍ للتحميل كان يعني: لا تنزيل بلا
    تفعيل، ولا تفعيل بلا الملف الذي لا يُنزَّل — دائرة لا مخرج منها لأول
    جهاز. وقد كانت الإضافة تكسرها بتفعيل **بصمة المتصفح** العشوائية، فتشغل
    الخانةَ الوحيدة بهويةٍ لا يملكها الـRuntime، فيُردّ تفعيله بعد التثبيت
    بـ23505 ويبقى الحساب عالقًا بلا برنامج يعمل.

    ما يحميه الاشتراط الجديد أدقّ وأصدق: المثبّت **ملف واحد لكل العملاء**
    لا سرّ فيه، والرابط أصلًا قصير العمر ومحمي برمز الحساب. الذي يجب منعه
    هو أن يسحب **حاسبٌ ثانٍ** المثبّت بينما اشتراك صاحبه يعمل على حاسب
    آخر — وهذا ما يفعله الفرع أدناه.

    Returns:
        (الاشتراك، الجهاز المفعّل) و``None`` مكان الجهاز في أول تثبيت.

    Raises:
        SubscriptionMissingError | SubscriptionInactiveError: اشتراك لا يسمح.
        DeviceMismatchError: جهاز آخر يشغل خانة الاشتراك.
    """
    subscription = ensure_serviceable(load_subscription(account.organization_id))

    current = active_device(subscription.id)
    if current is None:
        # أول تثبيت: لا جهاز بعد، والـRuntime هو من سيفعّل نفسه بعد التركيب.
        return subscription, None

    if current.device_id_hash != hash_device_id(raw_device_id):
        raise DeviceMismatchError(
            f"حسابك مفعّل على جهاز آخر ({current.device_name})، وليس على هذا "
            "الجهاز. يمكنك استبدال الجهاز السابق بهذا الجهاز من نافذة GovMind."
        )
    return subscription, _touch_last_seen(current)
