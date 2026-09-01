"""مسارات يناديها **GovMind Runtime** على جهاز العميل.

تختلف عن `api/entitlements.py` في من يصادِق: تلك يناديها متصفح يحمل رمز
مستخدم من Supabase، وهذه يناديها برنامج على جهاز عميل **لا يملك رمز
مستخدم** — المستخدم سجّل دخوله في الإضافة لا في الخدمة.

**كيف يصادِق الـRuntime إذن؟**

* عند التفعيل: بـ**رمز تركيب لمرة واحدة** سلّمته إليه الإضافة.
* بعد التفعيل: بـ**سرّ جهازه** الذي ولّده هو على الجهاز. الـBackend يجزّئه
  بـ`DEVICE_HASH_PEPPER` ويطابقه بتفعيل قائم. السرّ الخام لا يُخزَّن ولا
  يُسجَّل، ولا يفتح شيئًا غير اشتراك هذا الجهاز بعينه.

⚠️ **لا مسار هنا يقبل معرّف جهة أو اشتراك من جسم الطلب.** كلاهما يُشتقّ من
التفعيل المطابق لسرّ الجهاز، فلا يستطيع Runtime أن يسأل عن اشتراك غيره.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from ..core.config import settings
from ..core.device_id import DeviceIdError, hash_device_id
from ..database.supabase import SupabaseError
from ..schemas.runtime import (
    ModelArtifactResponse,
    RuntimeActivateRequest,
    RuntimeActivationResponse,
    RuntimeEntitlementResponse,
)
from ..services import entitlement_service as entitlements
from ..services import installation_session_service as sessions
from ..services import installer_service
from ..services.entitlement_service import (
    DeviceActivation,
    EntitlementError,
    Subscription,
)
from ..services.installer_service import InstallerError, InstallerNotConfiguredError

router = APIRouter(prefix="/api/runtime", tags=["runtime"])

#: الترويسة التي يحمل بها الـRuntime سرّ جهازه. ليست `Authorization` عمدًا:
#: هي ليست رمز حامل قياسيًا، وتمييزها يمنع خلطها برمز مستخدم في أي وسيط.
DEVICE_HEADER = "X-GovMind-Device-Secret"


def _to_http(exc: EntitlementError) -> HTTPException:
    from ..services.entitlement_service import (
        AccountNotProvisionedError,
        DeviceLimitReachedError,
        DeviceMismatchError,
        DeviceNotActivatedError,
        SubscriptionInactiveError,
        SubscriptionMissingError,
    )
    from ..services.installation_session_service import (
        InvalidInstallationTokenError,
    )

    if isinstance(exc, InvalidInstallationTokenError):
        code = status.HTTP_401_UNAUTHORIZED
    elif isinstance(exc, DeviceLimitReachedError):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, (DeviceMismatchError, DeviceNotActivatedError)):
        code = status.HTTP_409_CONFLICT
    elif isinstance(
        exc,
        (
            SubscriptionInactiveError,
            SubscriptionMissingError,
            AccountNotProvisionedError,
        ),
    ):
        code = status.HTTP_403_FORBIDDEN
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


# ---------------------------------------------------------------------------
# مصادقة الـRuntime بسرّ جهازه
# ---------------------------------------------------------------------------
def get_activation(
    device_secret: Annotated[str | None, Header(alias=DEVICE_HEADER)] = None,
) -> tuple[DeviceActivation, Subscription]:
    """يطابق سرّ الجهاز بتفعيل فعّال، ويعيده مع اشتراكه.

    **مطابقة بالتجزئة لا بالسرّ**: القاعدة لا تحمل السرّ الخام أصلًا.

    Raises:
        HTTPException: 401 بلا سرّ أو بسرّ لا يطابق شيئًا، و403 إن أُبطل
            التفعيل أو لم يعد الاشتراك يسمح.
    """
    if not device_secret or not device_secret.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="هذا المسار يتطلب سرّ جهاز مفعَّل.",
        )

    try:
        device_hash = hash_device_id(device_secret)
    except DeviceIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    try:
        found = entitlements.find_activation_by_hash(device_hash)
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    if found is None:
        # مُبطَل أو لم يُفعَّل قط — لا يُفرَّق: كلاهما «فعّل جهازك من جديد».
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "هذا الجهاز غير مفعَّل على أي اشتراك. أعد التفعيل من إضافة "
                "GovMind في المتصفح."
            ),
        )
    return found


CurrentDevice = Annotated[
    tuple[DeviceActivation, Subscription], Depends(get_activation)
]


# ---------------------------------------------------------------------------
# التفعيل
# ---------------------------------------------------------------------------
@router.post(
    "/activate",
    response_model=RuntimeActivationResponse,
    summary="استهلاك رمز التركيب وتفعيل هذا الجهاز",
    responses={
        401: {"description": "رمز تركيب غير صالح أو منتهٍ أو مستعمَل"},
        403: {"description": "الاشتراك لا يسمح بالتفعيل"},
        409: {"description": "الاشتراك مفعّل على جهاز آخر"},
    },
)
def activate(payload: RuntimeActivateRequest) -> RuntimeActivationResponse:
    """يستبدل رمز التركيب بتفعيل جهاز.

    **العملية ذرّية في القاعدة**: استهلاك الرمز وإنشاء التفعيل ينجحان معًا
    أو يفشلان معًا. وجهاز ثانٍ يُرفض على الفهرس الفريد الجزئي لا على فحص
    في بايثون.

    ⚠️ `device_secret` سرّ ولّده الـRuntime على الجهاز. **يُجزَّأ فور وصوله،
    ولا يُخزَّن خامًا ولا يُسجَّل.**
    """
    try:
        activation = sessions.redeem(
            token=payload.token,
            raw_device_id=payload.device_secret,
            device_name=payload.device_name,
        )
        subscription = entitlements.load_subscription(activation.organization_id)
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

    return RuntimeActivationResponse(
        activation_id=activation.activation_id,
        status=subscription.status,
        expires_at=subscription.expires_at,
    )


# ---------------------------------------------------------------------------
# تحديث الاستحقاق
# ---------------------------------------------------------------------------
@router.get(
    "/entitlement",
    response_model=RuntimeEntitlementResponse,
    summary="حالة الاشتراك لهذا الجهاز",
    responses={
        401: {"description": "سرّ جهاز مفقود"},
        403: {"description": "الجهاز غير مفعّل أو أُبطل تفعيله"},
    },
)
def entitlement(current: CurrentDevice) -> RuntimeEntitlementResponse:
    """يتحقق الـRuntime بها دوريًا من أن اشتراكه ما زال يسمح بالخدمة.

    **تعيد الحالة ولا ترفض المنتهي بـ403**: الـRuntime يحتاج أن يعرف
    *لماذا* توقّف ليعرضه بالعربية، لا أن يرى خطأً عامًا.
    """
    device, subscription = current
    reason = subscription.blocked_reason()
    return RuntimeEntitlementResponse(
        status=subscription.status,
        expires_at=subscription.expires_at,
        is_usable=reason is None,
        blocked_reason=reason,
        device_name=device.device_name,
    )


# ---------------------------------------------------------------------------
# المودل
# ---------------------------------------------------------------------------
@router.get(
    "/model",
    response_model=ModelArtifactResponse,
    summary="رابط تنزيل المودل وبيانات التحقق منه",
    responses={
        403: {"description": "الجهاز غير مفعّل أو الاشتراك لا يسمح"},
        503: {"description": "تخزين المودل غير مهيّأ على السيرفر"},
    },
)
def model_artifact(current: CurrentDevice) -> ModelArtifactResponse:
    """يعيد رابط SAS قصير العمر مع **الحجم والتجزئة المتوقّعين**.

    التجزئة تُرسَل مع الرابط لا تُحزَم في الـRuntime: تغيير المودل يجب ألا
    يستلزم إصدارًا جديدًا من البرنامج.

    ⚠️ الرابط لا يُعرض للمستخدم ولا يُحفظ على القرص.
    """
    _, subscription = current
    reason = subscription.blocked_reason()
    if reason is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)

    try:
        link = installer_service.build_download_link(for_model=True)
    except InstallerNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except InstallerError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return ModelArtifactResponse(
        download_url=link.url,
        file_name=link.file_name,
        expires_at=link.expires_at,
        sha256=settings.azure_model_sha256.strip().lower(),
        size_bytes=int(settings.azure_model_size_bytes),
    )
