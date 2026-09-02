"""مسارات المصادقة: تسجيل الدخول، بيانات الحساب، تسجيل الخروج.

Router رفيع عمدًا: لا منطق هنا سوى ترجمة أخطاء الخدمة إلى رموز HTTP. التحقق
من كلمة المرور وإصدار التوكن في `services/auth_service.py` و `core/security.py`.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from ..schemas import LoginRequest, LogoutResponse, TokenResponse, UserOut
from ..services.auth_service import (
    AuthenticatedSession,
    ConflictingAccountsError,
    InactiveAccountError,
    InvalidCredentialsError,
    login as login_user,
)
from ..services.subscription_service import SubscriptionInactiveError
from ..services.user_store import User, UserStoreError, get_user_store
from .dependencies import CurrentUserAllowingExpired

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _to_user_out(user: User, organization_name: str | None) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        organization_id=user.organization_id,
        organization_name=organization_name,
        is_active=user.is_active,
    )


def _to_token_response(session: AuthenticatedSession) -> TokenResponse:
    remaining = session.expires_at - datetime.now(UTC)
    return TokenResponse(
        access_token=session.access_token,
        token_type="bearer",
        # max(0, ...) احتياطًا حتى لا تُعاد مدة سالبة لو تأخر الرد.
        expires_in=max(0, int(remaining.total_seconds())),
        user=_to_user_out(
            session.user,
            session.organization.name if session.organization else None,
        ),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="تسجيل الدخول وإصدار رمز الوصول",
    responses={
        401: {"description": "البريد أو كلمة المرور غير صحيحة"},
        403: {"description": "الحساب معطّل أو اشتراك الجهة منتهٍ"},
        409: {"description": "البريد مسجّل على أكثر من حساب — بيانات متعارضة"},
    },
)
def login(payload: LoginRequest) -> TokenResponse:
    """يتحقق من البريد وكلمة المرور ويعيد رمز دخول صالحًا.

    الرمز يحمل معرّف المستخدم وجهته ودوره، ويُرسل في الطلبات التالية بترويسة
    ``Authorization: Bearer <token>``.

    **لا يُطلب معرّف الجهة:** البريد هوية دخول فريدة على مستوى النظام،
    فالبحث به يعطي حسابًا واحدًا أو لا شيء. لا يوجد مسار يختار حسابًا من بين
    عدة حسابات متطابقة البريد — التكرار (لو وُجد في قاعدة سبقت فهرس التفرّد)
    **يوقف الدخول** بـ409 ولا يُخمَّن فيه.

    البريد غير المسجّل وكلمة المرور الخاطئة يعطيان الرد نفسه عمدًا، حتى لا
    يُستدل من الرد على الحسابات الموجودة في النظام.
    """
    try:
        session = login_user(email=payload.email, password=payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (InactiveAccountError, SubscriptionInactiveError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except ConflictingAccountsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except UserStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return _to_token_response(session)


@router.get(
    "/me",
    response_model=UserOut,
    summary="بيانات الحساب الحالي",
    responses={
        401: {"description": "رمز الدخول مفقود أو تالف أو منتهي الصلاحية"},
        403: {"description": "الحساب معطّل"},
    },
)
def read_current_user(user: CurrentUserAllowingExpired) -> UserOut:
    """يعيد بيانات صاحب رمز الدخول.

    تستخدمها الواجهة للتحقق من صلاحية الجلسة عند فتح التطبيق، ولعرض اسم
    الموظف وجهته ودوره.

    **يعمل ولو انتهى اشتراك الجهة**، بخلاف بقية المسارات المحمية: الواجهة
    تحتاج أن تعرف من صاحب الجلسة لتعرض له سبب المنع، لا أن تُمنع من
    معرفة ذلك أيضًا.
    """
    organization = get_user_store().get_organization(user.organization_id)
    return _to_user_out(user, organization.name if organization else None)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="تسجيل الخروج",
    responses={401: {"description": "رمز الدخول مفقود أو غير صالح"}},
)
def logout(user: CurrentUserAllowingExpired) -> LogoutResponse:
    """ينهي الجلسة من طرف العميل.

    **الرمز موقّع وبلا حالة على السيرفر، فلا يُلغى بهذا النداء**؛ يبقى صالحًا
    حتى تنتهي مدته. مسؤولية العميل حذفه من التخزين فورًا. إلغاء الرموز قبل
    انتهائها يحتاج قائمة إبطال، وهي خارج نطاق الـMVP.

    يتطلب رمزًا صالحًا، **ويعمل ولو انتهى اشتراك الجهة**: منع الموظف من
    الخروج لأن اشتراك جهته انتهى لا معنى له.
    """
    return LogoutResponse(
        detail=f"تم تسجيل خروج {user.full_name}. احذف رمز الدخول من جهازك."
    )
