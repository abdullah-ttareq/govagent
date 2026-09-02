"""منطق تسجيل الدخول والتحقق من هوية صاحب الطلب.

يفصل الـRouter عن المخزن وعن التشفير: `api/auth.py` لا يعرف كيف تُجزَّأ كلمة
المرور ولا كيف يُوقَّع التوكن، وهذا الملف لا يعرف شيئًا عن HTTP.

**مبدأ عدم كشف المستخدمين:** بريد غير مسجّل وكلمة مرور خاطئة يعطيان الرسالة
نفسها والزمن نفسه، فلا يُستدل من الرد على وجود حساب من عدمه.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..core.security import (
    TokenPayload,
    create_access_token,
    verify_password,
    waste_password_comparison,
)
from .audit_service import record
from .audit_store import ACTION_LOGIN
from .subscription_service import (
    SubscriptionInactiveError,
    ensure_active,
)
from .user_store import Organization, User, get_user_store, normalize_email

#: رسالة واحدة لكل فشل في التعرّف على الحساب أو في كلمة المرور.
_GENERIC_FAILURE = "البريد الإلكتروني أو كلمة المرور غير صحيحة."


class AuthError(Exception):
    """فشل في المصادقة، برسالة عربية صالحة للعرض مباشرة."""


class InvalidCredentialsError(AuthError):
    """بريد غير مسجّل أو كلمة مرور خاطئة — لا يُفرَّق بينهما في الرد."""


class InactiveAccountError(AuthError):
    """الحساب أو الجهة معطّلة. تُرفع بعد نجاح كلمة المرور فقط."""


class ConflictingAccountsError(AuthError):
    """البريد نفسه على أكثر من حساب — حالة بيانات فاسدة لا يجوز التخمين فيها.

    التفرّد العالمي (فهرس ``uq_users_email_lower``) يمنع هذه الحالة. تبقى
    معالَجة هنا لأن قاعدة أُنشئت قبل الفهرس قد تحمل تكرارًا، وحينها **يُرفض
    الدخول** ولا يُختار أحد الحسابين عشوائيًا.
    """


@dataclass(frozen=True)
class AuthenticatedSession:
    """نتيجة تسجيل دخول ناجح."""

    user: User
    organization: Organization | None
    access_token: str
    expires_at: datetime


def login(*, email: str, password: str) -> AuthenticatedSession:
    """يتحقق من بيانات الدخول ويصدر توكنًا.

    البريد هوية دخول **فريدة على مستوى النظام**، فالبحث به يعطي حسابًا واحدًا
    أو لا شيء. لا يُطلب معرّف الجهة عند الدخول، ولا يوجد مسار يختار حسابًا من
    بين عدة حسابات متطابقة البريد.

    Args:
        email: بريد الموظف.
        password: كلمة المرور الصريحة — تُستهلك هنا ولا تُخزَّن ولا تُسجَّل.

    Raises:
        InvalidCredentialsError: بريد غير مسجّل أو كلمة مرور خاطئة.
        InactiveAccountError: الحساب أو الجهة معطّلة.
        ConflictingAccountsError: البريد على أكثر من حساب في قاعدة سبقت فهرس
            التفرّد — يُرفض الدخول ولا يُخمَّن.
        SubscriptionInactiveError: اشتراك الجهة منتهٍ أو موقوف أو غير مسجّل،
            والرسالة تذكر تاريخ الانتهاء.
    """
    store = get_user_store()
    candidates = store.find_login_candidates(email=email)

    if not candidates:
        # مقارنة وهمية حتى يستغرق الرد زمن تحقق bcrypt سواء وُجد البريد أم لا.
        waste_password_comparison()
        raise InvalidCredentialsError(_GENERIC_FAILURE)

    if len(candidates) > 1:
        # لا نفحص كلمة المرور ولا نختار: أي اختيار هنا قد يدخل الموظف على
        # جهة ليست جهته، وهو أسوأ من رفض الدخول.
        organizations = sorted(
            {
                organization.slug
                for candidate in candidates
                if (
                    organization := store.get_organization(
                        candidate.user.organization_id
                    )
                )
                is not None
            }
        )
        raise ConflictingAccountsError(
            f"البريد «{normalize_email(email)}» مسجّل على أكثر من حساب "
            f"({'، '.join(organizations)})، وتسجيل الدخول متوقف حتى تُعالَج "
            "هذه الازدواجية. راجع مسؤول النظام."
        )

    stored = candidates[0]
    if not verify_password(password, stored.password_hash):
        raise InvalidCredentialsError(_GENERIC_FAILURE)

    organization = store.get_organization(stored.user.organization_id)

    # يُفحص التعطيل بعد نجاح كلمة المرور فقط: من لا يملكها لا يستحق أن يعرف
    # أن الحساب موجود ومعطّل.
    if not stored.user.is_active:
        raise InactiveAccountError(
            "هذا الحساب معطّل. راجع مسؤول النظام في جهتك لإعادة تفعيله."
        )
    if organization is not None and not organization.is_active:
        raise InactiveAccountError(
            f"جهة «{organization.name}» غير مفعّلة في النظام حاليًا. "
            "راجع مسؤول النظام."
        )

    # الاشتراك بعد كلمة المرور: تاريخ انتهاء اشتراك جهة معلومةٌ لا تُكشف
    # لمن لا يملك حسابًا فيها.
    ensure_active(stored.user.organization_id)

    token, expires_at = create_access_token(
        user_id=stored.user.id,
        organization_id=stored.user.organization_id,
        role=stored.user.role,
    )
    record(
        organization_id=stored.user.organization_id,
        user_id=stored.user.id,
        action=ACTION_LOGIN,
        details=f"تسجيل دخول {stored.user.email}",
    )
    return AuthenticatedSession(
        user=stored.user,
        organization=organization,
        access_token=token,
        expires_at=expires_at,
    )


def resolve_current_user(payload: TokenPayload) -> User:
    """يحوّل حمولة التوكن إلى مستخدم حقيقي، ويرفض ما لم يعد صالحًا.

    التوكن الصالح توقيعًا لا يكفي: الحساب قد يكون حُذف أو عُطّل أو نُقل بعد
    إصداره، فتُعاد قراءته من المخزن في كل طلب.

    Raises:
        InvalidCredentialsError: إذا لم يعد المستخدم موجودًا في جهته.
        InactiveAccountError: إذا عُطّل الحساب بعد إصدار التوكن.
    """
    store = get_user_store()
    user = store.get_user(
        user_id=payload.user_id, organization_id=payload.organization_id
    )
    if user is None:
        raise InvalidCredentialsError(
            "لم يعد هذا الحساب موجودًا. سجّل الدخول من جديد."
        )
    if not user.is_active:
        raise InactiveAccountError(
            "هذا الحساب معطّل. راجع مسؤول النظام في جهتك لإعادة تفعيله."
        )
    return user
