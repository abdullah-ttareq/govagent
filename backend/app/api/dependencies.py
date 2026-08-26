"""اعتماديات مشتركة بين المسارات — أهمها التحقق من التوكن والاشتراك.

`CurrentUser` هي البوابة الوحيدة لهوية صاحب الطلب. أي مسار محمي يعلن
``user: CurrentUser`` فيحصل على مستخدم موثوق، ومنه ``organization_id`` الذي
تُقيَّد به الاستعلامات. **لا يُقرأ ``organization_id`` من جسم الطلب في أي مسار.**

`CurrentUser` تفحص كذلك **اشتراك الجهة** وترفض المنتهي والموقوف برسالة
تذكر تاريخ الانتهاء. أما `CurrentUserAllowingExpired` فتتخطى هذا الفحص
وحده، وتُستخدم في المسارات القليلة التي **يجب** أن تعمل على اشتراك منتهٍ:
قراءة الحساب، وتسجيل الخروج، وقراءة الاشتراك نفسه — لولاها لعرف المسؤول
أن شيئًا ممنوع بلا أن يعرف السبب ولا أن يستطيع الخروج.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..core.security import (
    ExpiredTokenError,
    InvalidTokenError,
    SecurityError,
    decode_access_token,
)
from ..services.auth_service import (
    AuthError,
    InactiveAccountError,
    resolve_current_user,
)
from ..services.subscription_service import (
    SubscriptionInactiveError,
    ensure_active,
)
from ..services.user_store import User

#: auto_error=False حتى تُصاغ رسالة غياب التوكن بالعربية بدل "Not authenticated".
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="JWT",
    description="ألصق رمز الدخول المُعاد من /api/auth/login",
)

#: كل ردود 401 هنا تحمل الترويسة القياسية التي تخبر العميل بنوع المصادقة.
_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


def get_current_user_allowing_expired(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> User:
    """يتحقق من التوكن ويعيد صاحبه، **بلا فحص اشتراك الجهة**.

    للمسارات التي يجب أن تعمل على اشتراك منتهٍ: قراءة الحساب، وتسجيل
    الخروج، وقراءة الاشتراك. لا تستخدمها في مسار يقدّم خدمة فعلية.

    Raises:
        HTTPException: 401 إذا غاب التوكن أو كان تالفًا أو منتهيًا أو لم يعد
            صاحبه موجودًا، و403 إذا كان الحساب معطّلًا، و503 إذا كان سر
            التوقيع غير مضبوط على السيرفر.
    """
    if credentials is None or not credentials.credentials.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "هذا المسار يتطلب تسجيل الدخول. أرسل رمز الدخول في ترويسة "
                "Authorization بالشكل: Bearer <token>."
            ),
            headers=_UNAUTHORIZED_HEADERS,
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except (ExpiredTokenError, InvalidTokenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers=_UNAUTHORIZED_HEADERS,
        ) from exc
    except SecurityError as exc:
        # سر التوقيع غير مضبوط: خلل في إعداد السيرفر لا في طلب المستخدم.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    try:
        return resolve_current_user(payload)
    except InactiveAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers=_UNAUTHORIZED_HEADERS,
        ) from exc


#: هوية موثوقة بلا فحص اشتراك — للمسارات القليلة المستثناة.
CurrentUserAllowingExpired = Annotated[
    User, Depends(get_current_user_allowing_expired)
]


def get_current_user(user: CurrentUserAllowingExpired) -> User:
    """يتحقق من التوكن ومن اشتراك الجهة معًا.

    الاشتراك يُقرأ في **كل** طلب لا عند تسجيل الدخول وحده: رمز يُصدر قبل
    الانتهاء بثوانٍ يبقى صالحًا ثماني ساعات، فالفحص عند الدخول وحده يترك
    الخدمة مفتوحة يوم عمل كامل بعد انتهاء الرخصة.

    Raises:
        HTTPException: 403 إذا كان اشتراك الجهة منتهيًا أو موقوفًا أو غير
            مسجّل، والرسالة تذكر تاريخ الانتهاء لا خطأً عامًا.
    """
    try:
        ensure_active(user.organization_id)
    except SubscriptionInactiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return user


#: تُستخدم في المسارات هكذا: ``def route(user: CurrentUser) -> ...``
CurrentUser = Annotated[User, Depends(get_current_user)]


def get_optional_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> User | None:  # noqa: D417
    """يعيد صاحب الطلب إن أرسل رمزًا، و``None`` إن لم يرسل.

    **الرمز المرسَل يُتحقق منه دائمًا:** الغياب مقبول، أما الرمز التالف أو
    المنتهي فيُرفض بـ401 كأي مسار محمي. تجاهل رمز خاطئ ومعاملة صاحبه كزائر
    يخفي الخطأ عن العميل ويجعل انتهاء الجلسة يبدو كأنه فقدان مفاجئ للبيانات.

    للمسارات التي تعمل بلا تسجيل دخول لكن تتصرف على بيانات الجهة إن وُجد:
    اليوم `/api/chat` وحده. يصير محميًا بالكامل في P2-03 عند ربط الحفظ.
    """
    if credentials is None or not credentials.credentials.strip():
        return None
    # الفحص الكامل بما فيه الاشتراك: المحادثة برمز استخدامٌ للخدمة.
    return get_current_user(get_current_user_allowing_expired(credentials))


#: تُستخدم هكذا: ``def route(user: OptionalCurrentUser) -> ...``
OptionalCurrentUser = Annotated[User | None, Depends(get_optional_current_user)]


def require_admin(user: CurrentUser) -> User:
    """يقصر المسار على مسؤول الجهة.

    للمسارات التي **لا معنى لها** لغير المسؤول أصلًا (كقائمة موظفي الجهة).
    المسارات التي يتغيّر سلوكها حسب الدور تعلن ``CurrentUser`` وتترك القرار
    لـ`directory_service`، حتى تبقى قواعد الدور في مكان واحد.

    Raises:
        HTTPException: 403 إذا لم يكن الدور admin.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="هذا الإجراء متاح لمسؤول الجهة فقط.",
        )
    return user


#: تُستخدم هكذا: ``def route(admin: AdminUser) -> ...``
AdminUser = Annotated[User, Depends(require_admin)]
