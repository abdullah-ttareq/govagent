"""التسجيل الذاتي — إنشاء حساب ومساحة شخصية واشتراك تجريبي.

**النموذج فردي:** حساب واحد، اشتراك واحد، جهاز فعّال واحد. العميل لا
يُسأل عن اسم جهة ولا يرى مفردات المؤسسات ولا لقب «مسؤول». المساحة
(`organizations`) بنيةٌ داخلية يحتاجها عزل RLS ويولّدها هذا الملف.

**تسلسل لا يمكن جعله معاملة واحدة، فيُعوَّض بدلًا من ذلك.**

حساب `auth.users` يُنشأ عبر GoTrue (HTTP)، والجداول تُكتب عبر PostgREST.
لا معاملة تجمع الاثنين. فالترتيب:

1. أنشئ حساب المصادقة.
2. نادِ ``register_organization`` — وهي **ذرّية**: الجهة والملف والعضوية
   والاشتراك تنجح كلها أو لا شيء منها.
3. إن فشلت (٢) **احذف حساب المصادقة**. بدون هذا التعويض يبقى بريد محجوزًا
   بحساب لا جهة له: صاحبه لا يستطيع التسجيل من جديد ولا استعمال ما سجّله.

⚠️ **مفتاح `service_role` لا يخرج من هذه الطبقة.** الإضافة تنادي الـBackend
وحده، ولا تعرف عنوان Supabase ولا أي مفتاح.

⚠️ **رسائل الأخطاء عربية ومكتوبة يدويًا.** لا يمرّ نصّ خطأ من GoTrue ولا من
PostgreSQL إلى المستخدم: قد يحمل أسماء جداول أو تفاصيل إعداد.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..core.config import settings
from ..database import supabase
from ..database.supabase import SupabaseError
from .supabase_auth import (
    SupabaseAuthError,
    SupabaseAuthNotConfiguredError,
    SupabaseSession,
    sign_in,
)

logger = logging.getLogger(__name__)

#: مدة التجربة بالأيام ومقاعدها. **مقعد واحد** يطابق سياسة «جهاز واحد
#: لكل اشتراك»: حساب تجريبي واحد على جهاز واحد.
TRIAL_DAYS = 30
TRIAL_SEATS = 1


class RegistrationError(Exception):
    """خطأ تسجيل، برسالة عربية صالحة للعرض على المستخدم مباشرة."""


class EmailAlreadyRegisteredError(RegistrationError):
    """البريد مسجَّل مسبقًا."""


class WorkspaceConflictError(RegistrationError):
    """تصادم في المساحة الشخصية — لا يقع عمليًا، والقيد يحرسه.

    المعرّف مشتقّ من `uuid` المستخدم، فوقوعه يعني إعادة استعمال معرّف
    حساب. يبقى الفرع لأن الاعتماد على «لن يحدث» ليس حراسة.
    """


class WeakPasswordError(RegistrationError):
    """كلمة المرور لا تحقق سياسة المشروع."""


@dataclass(frozen=True)
class RegistrationResult:
    """نتيجة التسجيل.

    ``session`` موجودة إن أمكن تسجيل الدخول فورًا. إن كان المشروع يشترط
    تأكيد البريد فهي ``None`` و ``requires_email_confirmation`` صحيحة —
    والإضافة تعرض حينها رسالة تأكيد بدل أن تبدو العملية فاشلة.
    """

    user_id: str
    email: str
    organization_id: int
    subscription_id: int
    session: SupabaseSession | None
    requires_email_confirmation: bool


# ---------------------------------------------------------------------------
# المساحة الشخصية المخفية
# ---------------------------------------------------------------------------
# **العميل لا يُسأل عن جهة ولا يرى كلمة «جهة» في أي شاشة.** المنتج اشتراك
# فردي: حساب واحد، اشتراك واحد، جهاز فعّال واحد.
#
# لكن `organizations` يبقى في القاعدة لأن **كل سياسات RLS تقيس عليه**، فلكل
# حساب مساحة يولّدها الـBackend هنا.
def personal_slug(user_id: str) -> str:
    """معرّف نصي فريد للمساحة، مشتقّ من معرّف المستخدم.

    **مشتقّ من `auth.users.id` لا من اسم يكتبه العميل:** المعرّف `uuid`
    فريد بحكم تعريفه، فلا تصادم ولا حاجة إلى لاحقة عشوائية ولا إلى رفض
    «الاسم مستخدم» في وجه عميل لم يختر اسمًا أصلًا.
    """
    compact = "".join(character for character in (user_id or "").lower() if character in "0123456789abcdef")
    if len(compact) < 8:
        # معرّف غير متوقَّع الشكل: نعود إلى تجزئة تعطي الطول والثبات نفسيهما.
        compact = hashlib.sha256((user_id or "").encode("utf-8")).hexdigest()
    return f"u-{compact[:32]}"


def personal_workspace_name(full_name: str) -> str:
    """اسم المساحة كما يظهر **لمشغّل النظام في القاعدة**، لا للعميل.

    وصفي ليسهل على الدعم تمييز الصفوف، وبلا أي لقب إداري.
    """
    cleaned = " ".join((full_name or "").split()) or "عميل"
    return f"مساحة {cleaned}"[:200]


# ---------------------------------------------------------------------------
# GoTrue
# ---------------------------------------------------------------------------
def _auth_headers(key: str) -> dict[str, str]:
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _require_keys() -> tuple[str, str]:
    anon = (settings.supabase_anon_key or "").strip()
    service = (settings.supabase_service_role_key or "").strip()
    if not (settings.supabase_url or "").strip() or not anon or not service:
        raise SupabaseAuthNotConfiguredError(
            "التسجيل غير مهيّأ على هذا السيرفر. المتغيرات المطلوبة: "
            "SUPABASE_URL و SUPABASE_ANON_KEY و SUPABASE_SERVICE_ROLE_KEY."
        )
    return anon, service


def create_auth_user(email: str, password: str) -> tuple[str, SupabaseSession | None]:
    """ينشئ حساب المصادقة عبر مسار التسجيل العام.

    **المسار العام لا الإداري عمدًا:** المسار العام يحترم إعداد المشروع في
    تأكيد البريد. لو أنشأنا الحساب إداريًا وأكّدناه بأنفسنا لتجاوزنا سياسة
    أمنية يملكها من ينشر النظام لا نحن.

    Returns:
        (معرّف المستخدم، الجلسة إن أعادها المشروع فورًا).
    """
    anon, _ = _require_keys()

    try:
        response = httpx.post(
            f"{supabase.auth_base_url()}/signup",
            headers=_auth_headers(anon),
            json={"email": email.strip().lower(), "password": password},
            timeout=settings.supabase_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise RegistrationError(
            "تعذّر الوصول إلى خدمة الحسابات. تأكد من اتصالك بالإنترنت ثم أعد "
            "المحاولة."
        ) from exc

    if not response.is_success:
        raise _translate_signup_failure(response)

    payload: dict[str, Any] = response.json() or {}
    # GoTrue يعيد المستخدم في الجذر أو تحت "user" حسب النسخة والإعداد.
    user = payload.get("user") if isinstance(payload.get("user"), dict) else payload
    user_id = str((user or {}).get("id") or "").strip()
    if not user_id:
        raise RegistrationError(
            "رد خدمة الحسابات غير مكتمل. أعد المحاولة، وإن تكرر فتواصل "
            "مع الدعم."
        )

    session: SupabaseSession | None = None
    if payload.get("access_token"):
        session = SupabaseSession(
            access_token=str(payload.get("access_token") or ""),
            refresh_token=str(payload.get("refresh_token") or ""),
            expires_in=int(payload.get("expires_in") or 0),
            user_id=user_id,
            email=str((user or {}).get("email") or email).strip().lower(),
        )
    return user_id, session


def _translate_signup_failure(response: httpx.Response) -> RegistrationError:
    """يحوّل فشل GoTrue إلى خطأ عربي، بلا تمرير نصّه الخام."""
    detail = ""
    code = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(body.get("msg") or body.get("message") or body.get("error_description") or "")
            code = str(body.get("error_code") or body.get("code") or "")
    except Exception:
        detail = ""

    lowered = f"{code} {detail}".lower()

    if "already" in lowered and ("registered" in lowered or "exists" in lowered):
        return EmailAlreadyRegisteredError(
            "هذا البريد الإلكتروني مسجَّل مسبقًا. سجّل الدخول بدل إنشاء حساب جديد."
        )
    if "password" in lowered:
        return WeakPasswordError(
            "كلمة المرور لا تحقق الحد الأدنى للأمان. اختر كلمة أطول تجمع "
            "حروفًا وأرقامًا."
        )
    if response.status_code == 429:
        return RegistrationError(
            "محاولات تسجيل كثيرة خلال وقت قصير. انتظر قليلًا ثم أعد المحاولة."
        )
    if "email" in lowered and "invalid" in lowered:
        return RegistrationError("صيغة البريد الإلكتروني غير صحيحة.")

    logger.warning("فشل تسجيل غير مصنَّف من GoTrue: status=%s", response.status_code)
    return RegistrationError(
        "تعذّر إنشاء الحساب حاليًا. أعد المحاولة، وإن تكرر فراجع مسؤول النظام."
    )


def delete_auth_user(user_id: str) -> None:
    """يحذف حساب المصادقة — **تعويضًا عن فشل ما بعده**.

    فشل الحذف نفسه لا يُرفع إلى المستخدم: العملية فاشلة أصلًا ورسالتها
    ستُعرض، وإضافة خطأ ثانٍ لا تفيده. يُسجَّل ليُنظَّف يدويًا.
    """
    try:
        _, service = _require_keys()
    except SupabaseAuthNotConfiguredError:
        return

    try:
        httpx.delete(
            f"{supabase.auth_base_url()}/admin/users/{user_id}",
            headers=_auth_headers(service),
            timeout=settings.supabase_timeout_seconds,
        )
        logger.info("حُذف حساب المصادقة تعويضًا عن فشل التسجيل.")
    except httpx.HTTPError:
        logger.error(
            "تعذّر حذف حساب مصادقة بعد فشل التسجيل؛ قد يبقى بريد محجوزًا "
            "بلا جهة ويحتاج تنظيفًا يدويًا."
        )


# ---------------------------------------------------------------------------
# التسجيل
# ---------------------------------------------------------------------------
def register(
    *, full_name: str, email: str, password: str
) -> RegistrationResult:
    """ينشئ حسابًا ومساحة شخصية واشتراكًا تجريبيًا.

    **لا وسيط لاسم الجهة:** المساحة تُولَّد من معرّف الحساب بعد إنشائه.

    Raises:
        EmailAlreadyRegisteredError | WorkspaceConflictError |
        WeakPasswordError | RegistrationError: كلها برسائل عربية للعرض.
    """
    email = email.strip().lower()

    user_id, signup_session = create_auth_user(email, password)
    # بعد إنشاء الحساب لا قبله: المعرّف هو مصدر اشتقاق المساحة.
    slug = personal_slug(user_id)
    workspace_name = personal_workspace_name(full_name)

    # ---- الكتابات الأربع، ذرّية في القاعدة -----------------------------
    try:
        rows = supabase.rpc(
            "register_organization",
            {
                "p_user_id": user_id,
                "p_email": email,
                "p_full_name": full_name.strip(),
                "p_org_name": workspace_name,
                "p_org_slug": slug,
                "p_trial_days": TRIAL_DAYS,
                "p_seats": TRIAL_SEATS,
            },
        )
    except SupabaseError as exc:
        # ⚠️ **التعويض**: لا يبقى حساب مصادقة بلا جهة.
        delete_auth_user(user_id)
        raise _translate_registration_failure(exc) from exc
    except Exception:
        delete_auth_user(user_id)
        raise

    if not rows:
        delete_auth_user(user_id)
        raise RegistrationError(
            "تعذّر إكمال التسجيل. أعد المحاولة، وإن تكرر فتواصل مع الدعم."
        )

    row = rows[0]

    # ---- تسجيل الدخول التلقائي ----------------------------------------
    session = signup_session or _try_sign_in(email, password)

    return RegistrationResult(
        user_id=user_id,
        email=email,
        organization_id=int(row["out_organization_id"]),
        subscription_id=int(row["out_subscription_id"]),
        session=session,
        requires_email_confirmation=session is None,
    )


def _try_sign_in(email: str, password: str) -> SupabaseSession | None:
    """يحاول الدخول فورًا بعد التسجيل.

    الفشل هنا **ليس فشل تسجيل**: أشهر أسبابه أن المشروع يشترط تأكيد
    البريد. الحساب والجهة أُنشئا بنجاح، والإضافة تعرض رسالة تأكيد.
    """
    try:
        return sign_in(email, password)
    except (SupabaseAuthError, RegistrationError):
        logger.info("تعذّر الدخول التلقائي بعد التسجيل؛ يُرجَّح اشتراط تأكيد البريد.")
        return None


def _translate_registration_failure(exc: SupabaseError) -> RegistrationError:
    """يصنّف فشل الدالة الذرّية إلى خطأ عربي واضح."""
    detail = str(exc)

    if "organization_slug_taken" in detail:
        # لا يقع عمليًا (المعرّف مشتقّ من uuid). الرسالة لا تذكر «جهة»:
        # العميل لم يُدخل اسمًا فلا معنى لأن يُطلب منه تغييره.
        return WorkspaceConflictError(
            "تعذّر إكمال التسجيل بهذا الحساب. أعد المحاولة، وإن تكرر "
            "فتواصل مع الدعم."
        )
    if "email_already_registered" in detail:
        return EmailAlreadyRegisteredError(
            "هذا البريد الإلكتروني مسجَّل مسبقًا. سجّل الدخول بدل إنشاء حساب جديد."
        )
    if "23505" in detail:
        return EmailAlreadyRegisteredError(
            "البيانات المُدخلة مسجَّلة مسبقًا. سجّل الدخول بدل إنشاء حساب جديد."
        )

    logger.warning("فشل غير مصنَّف في دالة التسجيل.")
    return RegistrationError(
        "تعذّر إكمال التسجيل. أعد المحاولة، وإن تكرر فتواصل مع الدعم."
    )
