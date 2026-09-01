"""مسارات الحساب والاشتراك وتفعيل الجهاز وتحميل المثبّت.

Router رفيع عمدًا: لا شرط استحقاق يُفحص هنا، وإنما تُترجم أخطاء
`entitlement_service` إلى رموز HTTP. المنطق كله في الخدمة، فلا يمكن أن
ينسى مسارٌ فحصًا يفعله غيره.

**هوية صاحب الطلب من رمز Supabase وحده** (`auth.users`)، لا من رمز التطبيق
القديم ولا من جسم الطلب. الجهة تُقرأ من `profiles` بهذا المعرّف.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..core.config import settings
from ..core.device_id import DeviceIdError
from ..database.supabase import SupabaseError, SupabaseNotConfiguredError
from ..schemas.entitlements import (
    AccountLoginRequest,
    AccountOut,
    AccountSessionResponse,
    ActiveDeviceOut,
    DeviceActivateRequest,
    DeviceListResponse,
    DeviceVerifyRequest,
    InstallerDownloadRequest,
    InstallerDownloadResponse,
    SubscriptionStatusResponse,
)
from ..schemas.runtime import InstallationSessionResponse
from ..services import entitlement_service as entitlements
from ..services import installation_session_service as sessions
from ..services import installer_service
from ..services.entitlement_service import (
    Account,
    AccountNotProvisionedError,
    AdminRequiredError,
    DeviceActivation,
    DeviceLimitReachedError,
    DeviceMismatchError,
    DeviceNotActivatedError,
    DeviceNotFoundError,
    EntitlementError,
    Subscription,
    SubscriptionInactiveError,
    SubscriptionMissingError,
)
from ..services.installer_service import InstallerError, InstallerNotConfiguredError
from ..services.supabase_auth import (
    InvalidCredentialsError,
    InvalidSupabaseTokenError,
    SupabaseAuthError,
    SupabaseAuthNotConfiguredError,
    SupabaseIdentity,
    sign_in,
    verify_access_token,
)

router = APIRouter(prefix="/api/account", tags=["account"])

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="SupabaseJWT",
    description="رمز Supabase المُعاد من /api/account/login",
)

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


# ---------------------------------------------------------------------------
# الاعتماديات
# ---------------------------------------------------------------------------
def get_identity(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> SupabaseIdentity:
    """يتحقق من رمز Supabase ويعيد هوية صاحبه.

    Raises:
        HTTPException: 401 لرمز مفقود أو تالف أو منتهٍ، و503 إذا كان سرّ
            التحقق غير مضبوط على السيرفر.
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
        return verify_access_token(credentials.credentials)
    except InvalidSupabaseTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers=_UNAUTHORIZED_HEADERS,
        ) from exc
    except SupabaseAuthNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


CurrentIdentity = Annotated[SupabaseIdentity, Depends(get_identity)]


def _to_http(exc: EntitlementError) -> HTTPException:
    """يترجم خطأ الاستحقاق إلى رد HTTP واحد لا يختلف بين المسارات.

    الرسالة تُعرض على المستخدم كما هي، ولا تحمل تفصيلًا داخليًا.
    """
    if isinstance(exc, AccountNotProvisionedError):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, (SubscriptionMissingError, SubscriptionInactiveError)):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, AdminRequiredError):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, DeviceNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(
        exc, (DeviceLimitReachedError, DeviceMismatchError, DeviceNotActivatedError)
    ):
        # 409: الطلب سليم والهوية موثوقة، لكن حالة النظام تتعارض معه.
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


def get_account(identity: CurrentIdentity) -> Account:
    """يحمّل ملف عمل صاحب الرمز، أو يرفض بسبب واضح."""
    try:
        return entitlements.load_account(identity)
    except EntitlementError as exc:
        raise _to_http(exc) from exc
    except SupabaseNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


CurrentAccount = Annotated[Account, Depends(get_account)]


# ---------------------------------------------------------------------------
# التحويل إلى نماذج الرد
# ---------------------------------------------------------------------------
def _to_device_out(
    device: DeviceActivation, *, current_hash: str | None
) -> ActiveDeviceOut:
    return ActiveDeviceOut(
        id=device.id,
        device_name=device.device_name,
        activated_at=device.activated_at,
        last_seen_at=device.last_seen_at,
        revoked_at=device.revoked_at,
        # المقارنة تتم هنا ولا تخرج التجزئة نفسها في الرد.
        is_current_device=(
            current_hash is not None and device.device_id_hash == current_hash
        ),
    )


def _to_status_response(
    subscription: Subscription,
    device: DeviceActivation | None,
    *,
    current_hash: str | None = None,
) -> SubscriptionStatusResponse:
    reason = subscription.blocked_reason()
    is_current = (
        device is not None
        and current_hash is not None
        and device.device_id_hash == current_hash
    )
    return SubscriptionStatusResponse(
        status=subscription.status,
        seats=subscription.seats,
        starts_at=subscription.starts_at,
        expires_at=subscription.expires_at,
        is_usable=reason is None,
        blocked_reason=reason,
        device=(
            _to_device_out(device, current_hash=current_hash)
            if device is not None
            else None
        ),
        # يحتاج تفعيلًا إن لم يوجد جهاز، أو إن كان المفعّل جهازًا آخر.
        requires_activation=device is None or (current_hash is not None and not is_current),
    )


# ---------------------------------------------------------------------------
# تسجيل الدخول
# ---------------------------------------------------------------------------
@router.post(
    "/login",
    response_model=AccountSessionResponse,
    summary="تسجيل الدخول عبر Supabase Auth",
    responses={
        401: {"description": "البريد أو كلمة المرور غير صحيحة"},
        503: {"description": "خدمة المصادقة غير مهيّأة أو لا تستجيب"},
    },
)
def login(payload: AccountLoginRequest) -> AccountSessionResponse:
    """يسجّل الدخول ويعيد رمز Supabase.

    **يمرّ بالـBackend عمدًا** حتى لا تحمل الإضافة عنوان Supabase ولا مفتاحه:
    عنوان واحد مثبَّت وقت البناء هو كل ما تعرفه.

    الحساب غير المرتبط بجهة **يُسجَّل دخوله** ويُعاد بـ`account: null`، فتعرض
    الإضافة رسالة واضحة بدل أن يبدو الأمر فشلًا في كلمة المرور.
    """
    try:
        session = sign_in(payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers=_UNAUTHORIZED_HEADERS,
        ) from exc
    except SupabaseAuthNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except SupabaseAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    account_out: AccountOut | None = None
    try:
        account = entitlements.load_account(
            SupabaseIdentity(user_id=session.user_id, email=session.email)
        )
        account_out = AccountOut(
            email=account.email,
            full_name=account.full_name,
            role=account.role,  # type: ignore[arg-type]
            organization_id=account.organization_id,
        )
    except (EntitlementError, SupabaseError):
        # الدخول نجح والرمز صالح؛ نقص ملف العمل حالة تعرضها الإضافة برسالتها.
        account_out = None

    return AccountSessionResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
        account=account_out,
    )


@router.get(
    "/me",
    response_model=AccountOut,
    summary="بيانات الحساب الحالي",
    responses={401: {"description": "رمز مفقود أو منتهٍ"}},
)
def read_me(account: CurrentAccount) -> AccountOut:
    """يعيد ملف عمل صاحب الرمز. **يعمل ولو كان الاشتراك منتهيًا.**"""
    return AccountOut(
        email=account.email,
        full_name=account.full_name,
        role=account.role,  # type: ignore[arg-type]
        organization_id=account.organization_id,
    )


# ---------------------------------------------------------------------------
# الاشتراك
# ---------------------------------------------------------------------------
@router.get(
    "/subscription",
    response_model=SubscriptionStatusResponse,
    summary="حالة الاشتراك والجهاز المفعّل",
    responses={403: {"description": "الحساب غير مرتبط بجهة، أو لا اشتراك لها"}},
)
def read_subscription(account: CurrentAccount) -> SubscriptionStatusResponse:
    """يعيد حالة الاشتراك **ولو كان منتهيًا** — بل هذا أهم أوقات الحاجة إليه.

    منه تعرف الإضافة أي شاشة تعرض: التفعيل، أو التحميل، أو رسالة الانتهاء.
    """
    try:
        subscription = entitlements.load_subscription(account.organization_id)
        device = entitlements.active_device(subscription.id)
    except EntitlementError as exc:
        raise _to_http(exc) from exc
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return _to_status_response(subscription, device)


# ---------------------------------------------------------------------------
# الأجهزة
# ---------------------------------------------------------------------------
@router.post(
    "/devices/activate",
    response_model=SubscriptionStatusResponse,
    summary="تفعيل هذا الجهاز",
    responses={
        403: {"description": "الاشتراك لا يسمح بالخدمة"},
        409: {"description": "الحساب مفعّل على جهاز آخر"},
    },
)
def activate_device(
    payload: DeviceActivateRequest, account: CurrentAccount
) -> SubscriptionStatusResponse:
    """يفعّل الجهاز الحالي. **كل اشتراك لجهاز واحد فقط.**

    إعادة التفعيل من الجهاز نفسه تنجح ولا تفشل: الإضافة قد تعيد الطلب بعد
    انقطاع شبكة.
    """
    try:
        device = entitlements.activate_device(
            account,
            raw_device_id=payload.device_id,
            device_name=payload.device_name,
        )
        subscription = entitlements.load_subscription(account.organization_id)
    except DeviceIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except EntitlementError as exc:
        raise _to_http(exc) from exc
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return _to_status_response(
        subscription, device, current_hash=device.device_id_hash
    )


@router.post(
    "/devices/verify",
    response_model=SubscriptionStatusResponse,
    summary="التحقق من أن هذا الجهاز هو المفعّل",
    responses={
        403: {"description": "الاشتراك لا يسمح بالخدمة"},
        409: {"description": "لا جهاز مفعّلًا، أو المفعّل جهاز آخر"},
    },
)
def verify_device(
    payload: DeviceVerifyRequest, account: CurrentAccount
) -> SubscriptionStatusResponse:
    """يتأكد أن الطلب من الجهاز المفعّل، ويحدّث وقت آخر ظهور له."""
    try:
        device = entitlements.verify_device(
            account, raw_device_id=payload.device_id
        )
        subscription = entitlements.load_subscription(account.organization_id)
    except DeviceIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except EntitlementError as exc:
        raise _to_http(exc) from exc
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return _to_status_response(
        subscription, device, current_hash=device.device_id_hash
    )


@router.get(
    "/devices",
    response_model=DeviceListResponse,
    summary="سجل أجهزة الاشتراك (لمسؤول الجهة)",
    responses={403: {"description": "الإجراء لمسؤول الجهة فقط"}},
)
def list_devices(account: CurrentAccount) -> DeviceListResponse:
    """يعيد أجهزة اشتراك **جهة صاحب الطلب** — الفعّال والمبطل معًا."""
    if not account.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="عرض أجهزة الاشتراك متاح لمسؤول الجهة فقط.",
        )
    try:
        subscription = entitlements.load_subscription(account.organization_id)
        devices = entitlements.list_devices(subscription.id)
    except EntitlementError as exc:
        raise _to_http(exc) from exc
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return DeviceListResponse(
        devices=[_to_device_out(device, current_hash=None) for device in devices]
    )


@router.post(
    "/devices/{activation_id}/revoke",
    response_model=ActiveDeviceOut,
    summary="إلغاء تفعيل جهاز (لمسؤول الجهة)",
    responses={
        403: {"description": "الإجراء لمسؤول الجهة فقط"},
        404: {"description": "التفعيل غير موجود في جهة صاحب الطلب"},
    },
)
def revoke_device(activation_id: int, account: CurrentAccount) -> ActiveDeviceOut:
    """يبطل تفعيل جهاز فيفرغ المكان لجهاز بديل.

    **الجهة تُقرأ من حساب المسؤول لا من الطلب**، فلا يمكن إبطال تفعيل في
    جهة أخرى مهما كان المعرّف المرسل.
    """
    try:
        device = entitlements.revoke_device(account, activation_id=activation_id)
    except EntitlementError as exc:
        raise _to_http(exc) from exc
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return _to_device_out(device, current_hash=None)


# ---------------------------------------------------------------------------
# جلسة التركيب
# ---------------------------------------------------------------------------
@router.post(
    "/installation-session",
    response_model=InstallationSessionResponse,
    summary="إصدار رمز تركيب لمرة واحدة",
    responses={
        403: {"description": "الاشتراك لا يسمح بالتركيب"},
        503: {"description": "تعذّر الوصول إلى قاعدة البيانات"},
    },
)
def create_installation_session(
    account: CurrentAccount,
) -> InstallationSessionResponse:
    """يصدر رمزًا تسلّمه الإضافة إلى الـRuntime بعد التثبيت.

    **لماذا رمز بدل هوية جهاز من الإضافة؟** لأن المثبَّت على ويندوز لا
    يستطيع قراءة `chrome.storage.local`، ولأن هوية يولّدها المتصفح تموت
    بتغيّر ملف تعريفه على جهاز لم يتغيّر. الرمز ينقل الثقة مرة واحدة،
    ويولّد الـRuntime هويته بنفسه على الجهاز.

    ⚠️ **الرمز يظهر مرة واحدة**: يُخزَّن مجزّأً، فلا سبيل إلى استرجاعه.
    الإضافة تحفظه لدقائق التركيب ثم تمحوه.

    **لا يُطلب تفعيل جهاز مسبق:** هذا المسار هو ما يسبق التفعيل.
    """
    try:
        issued = sessions.issue_session(account)
    except EntitlementError as exc:
        raise _to_http(exc) from exc
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return InstallationSessionResponse(
        token=issued.token,
        expires_at=issued.expires_at,
        expires_in_minutes=settings.installation_token_ttl_minutes,
    )


# ---------------------------------------------------------------------------
# تحميل المثبّت
# ---------------------------------------------------------------------------
@router.post(
    "/installer/download-url",
    response_model=InstallerDownloadResponse,
    summary="رابط تحميل مؤقّت لمثبّت GovMind",
    responses={
        403: {"description": "الاشتراك لا يسمح بالتحميل"},
        409: {"description": "الطلب من جهاز غير مفعّل"},
        503: {"description": "تخزين Azure غير مهيّأ على السيرفر"},
    },
)
def installer_download_url(
    payload: InstallerDownloadRequest, account: CurrentAccount
) -> InstallerDownloadResponse:
    """يعيد رابط SAS قصير العمر بعد التأكد من **الشروط الأربعة**.

    1. الهوية موثوقة (رمز Supabase صالح).
    2. حالة الاشتراك `active` أو `trial`.
    3. الاشتراك لم ينتهِ تاريخه.
    4. الجهاز الطالب هو الجهاز المفعّل على الاشتراك.

    ⚠️ الرابط **لا يُعرض للمستخدم**: تمرّره الإضافة إلى `chrome.downloads`.
    وسلسلة اتصال Azure لا تخرج من السيرفر بأي حال.
    """
    try:
        entitlements.authorize_installer_download(
            account, raw_device_id=payload.device_id
        )
    except DeviceIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except EntitlementError as exc:
        raise _to_http(exc) from exc
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    try:
        link = installer_service.build_download_link()
    except InstallerNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except InstallerError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return InstallerDownloadResponse(
        download_url=link.url,
        file_name=link.file_name,
        expires_at=link.expires_at,
        expires_in_minutes=settings.download_link_ttl_minutes,
    )
