"""جلسات التركيب — نقل الثقة من الإضافة إلى الـRuntime برمز لمرة واحدة.

**المشكلة:** الإضافة تعرف من المستخدم وأن اشتراكه فعّال، والـRuntime هو من
سيملك هوية الجهاز. لا يستطيع أحدهما أن يسلّم الآخر هوية دائمة: تخزين
المتصفح معزول عن نظام الملفات، وأي هوية تولّدها الإضافة تموت بتغيّر ملف
تعريف المتصفح على جهاز لم يتغيّر.

**الحل:** رمز عشوائي قصير العمر يُستعمل **مرة واحدة**. الإضافة تطلبه، ثم
تسلّمه إلى الـRuntime على ``127.0.0.1``، فيستبدله الـRuntime بتفعيل جهاز
يحمل هويةً ولّدها هو على الجهاز.

⚠️ **الرمز الخام لا يُخزَّن ولا يُسجَّل.** يعود مرة واحدة في رد إصداره،
ويُخزَّن SHA-256 له وحده. من يقرأ القاعدة لا يستطيع انتحال أي رمز.

**بلا مِلح مع التجزئة هنا، بخلاف بصمة الجهاز:** المِلح يلزم حين يكون
المُجزَّأ قابلًا للتخمين بجدول مسبق. رمزٌ عشوائي ٢٥٦ بت لا يُخمَّن، فإضافة
مِلح تضيف سرًّا يجب حفظه بلا أن تزيد أمانًا.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..core.config import settings
from ..core.device_id import hash_device_id
from ..database import supabase
from ..database.supabase import SupabaseError
from .entitlement_service import (
    Account,
    DeviceLimitReachedError,
    EntitlementError,
    SubscriptionInactiveError,
    ensure_serviceable,
    load_subscription,
)

logger = logging.getLogger(__name__)

#: عدد بايتات العشوائية في الرمز. ٣٢ بايت = ٢٥٦ بت.
TOKEN_BYTES = 32


class InstallationSessionError(EntitlementError):
    """خطأ في جلسة التركيب، برسالة عربية صالحة للعرض."""


class InvalidInstallationTokenError(InstallationSessionError):
    """رمز خاطئ أو منتهٍ أو مستعمَل — **لا يُفرَّق بينها**."""


@dataclass(frozen=True)
class IssuedSession:
    """رمز تركيب صادر. ``token`` يخرج مرة واحدة ولا يُخزَّن."""

    token: str
    expires_at: datetime


@dataclass(frozen=True)
class RedeemedActivation:
    """نتيجة استهلاك الرمز."""

    activation_id: int
    subscription_id: int
    organization_id: int
    user_id: str


def hash_token(token: str) -> str:
    """SHA-256 للرمز، ست عشرية بأحرف صغيرة كما يشترط قيد العمود."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def issue_session(account: Account) -> IssuedSession:
    """يصدر رمز تركيب لصاحب حساب اشتراكه فعّال.

    Raises:
        SubscriptionMissingError | SubscriptionInactiveError: اشتراك لا يسمح.
        SupabaseError: تعذّر الوصول إلى القاعدة.
    """
    subscription = ensure_serviceable(load_subscription(account.organization_id))

    # `token_urlsafe` يعتمد على `secrets` أي مولّد النظام العشوائي — لا
    # `random` الذي يمكن التنبؤ بمخرجاته من عدد قليل من العيّنات.
    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = datetime.now(UTC) + timedelta(
        minutes=max(1, settings.installation_token_ttl_minutes)
    )

    supabase.insert(
        "installation_sessions",
        {
            "user_id": account.user_id,
            "organization_id": account.organization_id,
            "subscription_id": subscription.id,
            "token_hash": hash_token(token),
            "expires_at": expires_at.isoformat(),
        },
    )

    # تنظيف الرموز القديمة عند كل إصدار — لا مهمة مجدولة ولا صف يعيش شهورًا.
    # فشله لا يعني شيئًا لصاحب الطلب، فلا يُسقط العملية.
    try:
        supabase.rpc("purge_expired_installation_sessions", {})
    except SupabaseError:
        logger.warning("تعذّر تنظيف جلسات التركيب المنتهية", exc_info=True)

    return IssuedSession(token=token, expires_at=expires_at)


def redeem(
    *, token: str, raw_device_id: str, device_name: str
) -> RedeemedActivation:
    """يستهلك الرمز وينشئ تفعيل الجهاز **في عملية ذرّية واحدة**.

    الذرّية من دالة ``redeem_installation_session`` في القاعدة، لا من ترتيب
    النداءات هنا: عبر PostgREST لا توجد معاملة تمتدّ عبر طلبين، فطلبان
    متتاليان يتركان نافذة إمّا تحرق رمزًا بلا تفعيل أو تفعّل بلا حرق الرمز.

    ⚠️ ``raw_device_id`` سرّ الجهاز الخام. **يُجزَّأ هنا فورًا ولا يخرج ولا
    يُسجَّل**، ولا تصل القاعدة إلا تجزئته.

    Raises:
        InvalidInstallationTokenError: رمز خاطئ أو منتهٍ أو مستعمَل.
        SubscriptionInactiveError: الاشتراك لم يعد يسمح بالخدمة.
        DeviceLimitReachedError: جهاز آخر مفعّل على الاشتراك.
        DeviceIdError: سرّ الجهاز غير صالح أو المِلح غير مضبوط.
    """
    device_hash = hash_device_id(raw_device_id)

    try:
        rows = supabase.rpc(
            "redeem_installation_session",
            {
                "p_token_hash": hash_token(token),
                "p_device_hash": device_hash,
                "p_device_name": (device_name or "").strip()[:120] or "جهاز غير مسمّى",
            },
        )
    except SupabaseError as exc:
        raise _translate(exc) from exc

    if not rows:
        raise InvalidInstallationTokenError(
            "رمز التركيب غير صالح أو انتهت صلاحيته. أعد الخطوات من الإضافة."
        )

    row = rows[0]
    return RedeemedActivation(
        activation_id=int(row["out_activation_id"]),
        subscription_id=int(row["out_subscription_id"]),
        organization_id=int(row["out_organization_id"]),
        user_id=str(row["out_user_id"]),
    )


def _translate(exc: SupabaseError) -> EntitlementError:
    """يحوّل خطأ القاعدة إلى خطأ مجال برسالة عربية.

    الرموز تأتي من ``raise ... using errcode`` داخل دالة القاعدة، ومن قيود
    الجداول نفسها. النص الإنجليزي الخام لا يصل المستخدم أبدًا.
    """
    detail = str(exc)

    if "invalid_installation_token" in detail or "28000" in detail:
        return InvalidInstallationTokenError(
            "رمز التركيب غير صالح أو انتهت صلاحيته. أعد الخطوات من الإضافة."
        )
    if "subscription_not_serviceable" in detail or "22023" in detail:
        return SubscriptionInactiveError(
            "اشتراكك لا يسمح بتفعيل جهاز حاليًا."
        )
    if "23505" in detail or "مستخدمة مسبقًا" in detail:
        return DeviceLimitReachedError(
            "حسابك مفعّل حاليًا على جهاز آخر. اشتراكك يعمل على جهاز واحد "
            "فقط، ويمكنك استبدال الجهاز السابق من نافذة GovMind."
        )
    return InstallationSessionError(
        "تعذّر إتمام التفعيل. أعد المحاولة، وإن تكرر فتواصل مع الدعم."
    )
