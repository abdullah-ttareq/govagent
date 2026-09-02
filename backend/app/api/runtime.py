"""مسارات يناديها **GovMind Runtime** على جهاز العميل.

تختلف عن `api/entitlements.py` في من يصادِق: تلك يناديها متصفح يحمل رمز
مستخدم من Supabase، وهذه يناديها برنامج على جهاز عميل **لا يملك رمز
مستخدم** — المستخدم سجّل دخوله في الإضافة لا في الخدمة.

**كيف يصادِق الـRuntime إذن؟**

* عند التفعيل: بـ**رمز تركيب لمرة واحدة** سلّمته إليه الإضافة.
* بعد التفعيل: بـ**بيان اعتماد يصدره هذا السيرفر** لحظةَ نجاح الاستبدال،
  ويعود مرة واحدة في رد `/activate`. القاعدة لا تحمل إلا SHA-256 له.

⚠️ **لم يعد سرّ الجهاز الذي يولّده الـRuntime مقبولًا للمصادقة.** كان
مقبولًا، وكان ذلك خطأً في نموذج الثقة: مصدر القيمة هو الطرف غير الموثوق،
فهي معرّف جهاز لا بيان اعتماد. يبقى السرّ **هويةً** يقوم عليها قيد «جهاز
فعّال واحد» واستبدال الجهاز، ولا يصادق به أي مسار.

⚠️ **كل طلب هنا يمرّ بالفحوص الثلاثة معًا** في دالة قاعدة واحدة: البيان
فعّال، والجهاز مفعّل، والاشتراك `trial`/`active` ولم ينتهِ تاريخه.

⚠️ **لا مسار هنا يقبل معرّف جهة أو اشتراك من جسم الطلب.** كلاهما يُشتقّ من
التفعيل المطابق لبيان الاعتماد، فلا يستطيع Runtime أن يسأل عن اشتراك غيره.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status

from ..core.config import settings
from ..core.device_id import DeviceIdError
from ..database.supabase import SupabaseError
from ..ai import ChatMessage, get_model_provider
from ..ai.base import ModelProviderError
from ..ai.system_prompt import build_system_prompt
from ..schemas.runtime import (
    ModelArtifactResponse,
    RuntimeActivateRequest,
    RuntimeActivationResponse,
    RuntimeChatRequest,
    RuntimeChatResponse,
    RuntimeEntitlementResponse,
)
from ..services import device_credential_service as credentials
from ..services import entitlement_service as entitlements
from ..services import installation_session_service as sessions
from ..services import installer_service
from ..services.device_credential_service import (
    DeviceCredentialIssueError,
    DeviceCredentialRejectedError,
)
from ..services.entitlement_service import (
    DeviceActivation,
    EntitlementError,
    Subscription,
)
from ..services.installer_service import InstallerError, InstallerNotConfiguredError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runtime", tags=["runtime"])

#: الترويسة التي يحمل بها الـRuntime بيان اعتماده. ليست `Authorization`
#: عمدًا: هي ليست رمز حامل قياسيًا، وتمييزها يمنع خلطها برمز مستخدم في أي
#: وسيط أو سجلّ.
CREDENTIAL_HEADER = "X-GovMind-Device-Credential"

#: ⚠️ **الترويسة القديمة لم تعد تصادق شيئًا.** تُذكر هنا لتوثيق أنها أُلغيت،
#: ويحرس ذلك اختبارٌ يرسلها ويتوقع الرفض.
LEGACY_DEVICE_SECRET_HEADER = "X-GovMind-Device-Secret"


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
# مصادقة الـRuntime ببيان اعتماده
# ---------------------------------------------------------------------------
def get_activation(
    device_credential: Annotated[
        str | None, Header(alias=CREDENTIAL_HEADER)
    ] = None,
) -> tuple[DeviceActivation, Subscription]:
    """يصادق بيان اعتماد الجهاز ويعيد الجهاز مع اشتراكه.

    **مطابقة بالتجزئة لا بالقيمة**: القاعدة لا تحمل القيمة الخام أصلًا.

    **الفحوص الثلاثة تقع في القاعدة في جملة واحدة** — البيان فعّال، والجهاز
    مفعّل، والاشتراك سارٍ. جمعها هناك يمنع نافذةً بين قراءتين ويمنع أن
    ينسى مسارٌ جديد أحدها.

    ⚠️ **رفض واحد لكل الأسباب**: مجهول، مُدوَّر، جهاز مُبطَل أو مستبدَل،
    اشتراك منتهٍ أو موقوف أو ملغى. التفريق يخبر من يجرّب القيم أيّها كان
    صحيحًا يومًا.

    Raises:
        HTTPException: 401 بلا بيان اعتماد، و403 لبيان لا يجتاز الفحوص،
            و503 إن تعذّر الوصول إلى القاعدة.
    """
    return _authenticate(device_credential, require_serviceable=True)


def get_activation_for_status(
    device_credential: Annotated[
        str | None, Header(alias=CREDENTIAL_HEADER)
    ] = None,
) -> tuple[DeviceActivation, Subscription]:
    """كسابقتها، **إلا أنها لا ترفض اشتراكًا لا يسمح بالخدمة**.

    ⚠️ **لمسار الإخبار وحده** (`/entitlement`). ذلك المسار يجيب عن «هل
    أستطيع العمل؟ وإن لا، فلماذا؟»، والـRuntime يعرض السبب بالعربية على
    شاشة العميل. رفضُه بـ403 يترك العميل أمام «ممنوع» بلا سبب ولا إجراء.

    ⚠️ **وبيان الاعتماد والجهاز يُفحصان كما هما**: جهاز أُبطل أو استُبدل لا
    يعرف حتى حالةَ اشتراك لم يعد يخصّه.
    """
    return _authenticate(device_credential, require_serviceable=False)


def _authenticate(
    device_credential: str | None, *, require_serviceable: bool
) -> tuple[DeviceActivation, Subscription]:
    if not device_credential or not device_credential.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="هذا المسار يتطلب بيان اعتماد جهاز مرتبط.",
        )

    try:
        return credentials.authenticate(
            device_credential, require_serviceable=require_serviceable
        )
    except DeviceCredentialRejectedError as exc:
        # ⚠️ **٤٠١ لا ٤٠٣، والفرق ليس تجميليًا.**
        #
        # ٤٠١ = «لم أقبل بيان اعتمادك»، و٤٠٣ = «قبلته ولا يسمح لك اشتراكك».
        # الـRuntime يبني عليهما فعلين مختلفين: الأول يمحو الربط ويطلب ربطًا
        # جديدًا من الإضافة، والثاني يعرض سبب المنع ويبقي الربط. خلطُهما كان
        # يجعل جهازًا استُبدل يقول لصاحبه «اشتراكك لا يسمح» — وهو غير صحيح،
        # ولا مخرج منه.
        #
        # المصادقة الصارمة تجمع الشرطين في جملة واحدة، فرفضُها لا يقول
        # أيّهما اختلّ. **الاستعلام الثاني يقع على مسار الفشل وحده** ويسأل
        # سؤالًا واحدًا: أهو الاشتراك أم البيان؟
        if require_serviceable:
            raise _classify_rejection(device_credential, exc) from exc
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


def _classify_rejection(
    device_credential: str, original: DeviceCredentialRejectedError
) -> HTTPException:
    """يحسم سبب الرفض: اشتراك لا يسمح (٤٠٣) أم بيان غير مقبول (٤٠١).

    ⚠️ **لا يوسّع ما يُقبل.** الفحص الثاني يمرّ بالدالة نفسها بالراية
    اللينة، وهي تشترط بيانًا فعّالًا وجهازًا مفعَّلًا كما تشترطهما الصارمة؛
    الفرق شرط الاشتراك وحده. فنجاحُه يعني يقينًا أن الاشتراك هو المانع.
    """
    try:
        _, subscription = credentials.authenticate(
            device_credential, require_serviceable=False
        )
    except DeviceCredentialRejectedError:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(original)
        )
    except SupabaseError as exc:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )

    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        # رسالة الاشتراك تحمل السبب والتاريخ، فتُعرض كما هي.
        detail=subscription.blocked_reason()
        or "اشتراكك لا يسمح باستخدام GovMind حاليًا.",
    )


CurrentDevice = Annotated[
    tuple[DeviceActivation, Subscription], Depends(get_activation)
]

#: هوية لمسار الإخبار — تُفحص كاملةً إلا شرط صلاحية الاشتراك.
CurrentDeviceForStatus = Annotated[
    tuple[DeviceActivation, Subscription], Depends(get_activation_for_status)
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

    ⚠️ `device_secret` **هوية** الجهاز التي ولّدها الـRuntime، لا بيان
    اعتماد: يقوم عليها قيد «جهاز فعّال واحد» واستبدال الجهاز. تُجزَّأ فور
    وصولها ولا تُخزَّن خامًا ولا تُسجَّل، **ولا يصادق بها أي مسار**.

    ⚠️ **بيان الاعتماد يُولَّد هنا، على السيرفر**، بعد نجاح الاستبدال —
    وهي اللحظة الوحيدة التي يملك فيها السيرفر إثباتًا أن صاحب الاشتراك
    أذن لهذا الجهاز. ويعود في هذا الرد **مرة واحدة**؛ إعادة الاستبدال
    تُصدر بيانًا جديدًا وتُبطل السابق.
    """
    try:
        activation = sessions.redeem(
            token=payload.token,
            raw_device_id=payload.device_secret,
            device_name=payload.device_name,
        )
        subscription = entitlements.load_subscription(activation.organization_id)
        issued = credentials.issue(activation.activation_id)
    except DeviceIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except DeviceCredentialIssueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
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
        # ⚠️ خروجه الوحيد. لا يُسجَّل هنا ولا في أي وسيط.
        device_credential=issued.credential,
    )


# ---------------------------------------------------------------------------
# تحديث الاستحقاق
# ---------------------------------------------------------------------------
@router.get(
    "/entitlement",
    response_model=RuntimeEntitlementResponse,
    summary="حالة الاشتراك لهذا الجهاز",
    responses={
        401: {"description": "بيان اعتماد مفقود أو مرفوض أو لجهاز أُبطل"},
        403: {"description": "الاشتراك لا يسمح بالخدمة"},
    },
)
def entitlement(current: CurrentDeviceForStatus) -> RuntimeEntitlementResponse:
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
        # بريد صاحب الاشتراك ليعرضه التطبيق المثبَّت. **بلا اسم جهة ولا
        # دور**: المنتج حساب فردي واحد.
        account_email=entitlements.load_owner_email(subscription.organization_id),
    )


# ---------------------------------------------------------------------------
# المحادثة — يناديها GovMind على جهاز العميل
# ---------------------------------------------------------------------------
@router.post(
    "/chat",
    response_model=RuntimeChatResponse,
    summary="محادثة لجهاز مرتبط",
    responses={
        401: {"description": "بيان اعتماد مفقود أو مرفوض أو لجهاز أُبطل"},
        403: {"description": "الاشتراك لا يسمح بالخدمة"},
        503: {"description": "المزوّد غير متاح — الرسالة تشرح السبب"},
    },
)
def chat(payload: RuntimeChatRequest, current: CurrentDevice) -> RuntimeChatResponse:
    """يمرّر رسالة الجهاز المرتبط إلى المزوّد المفعَّل ويعيد الرد.

    **لماذا يمرّ الطلب بالسيرفر بدل أن ينادي الجهاز المزوّد مباشرة؟**
    لأن بيانات اعتماد المزوّد سرّ سيرفر. وضعُها على جهاز عميل يعني نشرها:
    يجب افتراض أن العميل يقرأ كل بايت في برنامجه. فالجهاز يصادق بـ**بيان
    اعتماده هو**، والسيرفر يحمل مفتاح المزوّد ولا يخرجه.

    ⚠️ **الفحوص الثلاثة تسبق أي استدلال** — `CurrentDevice` تفرضها في
    دالة قاعدة واحدة: البيان فعّال، والجهاز مفعّل، والاشتراك `trial` أو
    `active` ولم ينتهِ. فلا يستهلك جهازٌ مبطَل أو اشتراكٌ منتهٍ حصةً
    مدفوعة.

    ⚠️ **تعليمات النظام يبنيها السيرفر**، ولا تُقبل من الجهاز: قبولها
    يجعل حدود الإيجنت كلها قابلة للإلغاء من عميل معدَّل.

    ⚠️ **لا يُسجَّل نصّ الرسالة ولا الرد ولا بيان الاعتماد.** ما يُسجَّل عدد
    الرسائل واسم المزوّد.
    """
    device, _subscription = current

    conversation = [
        ChatMessage(role=item.role, content=item.content)
        for item in payload.history
    ]
    conversation.append(ChatMessage(role="user", content=payload.message))

    provider = get_model_provider()
    logger.info(
        "محادثة من جهاز مرتبط: activation=%s provider=%s رسائل=%d",
        device.id,
        provider.name,
        len(conversation),
    )

    try:
        # ⚠️ **بلا بحث في ملفات**: هذا المسار لجهاز لا لجهة، ولا ملفات
        # مرفوعة له. سياقٌ فارغ يعني إيجنتًا يجيب من معرفته العامة.
        result = provider.generate(
            messages=conversation, system_prompt=build_system_prompt("")
        )
    except ModelProviderError as exc:
        # رسالة المزوّد عربية وتقول ما يُفعل — تُمرَّر كما هي.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return RuntimeChatResponse(
        reply=result.reply,
        provider=result.provider,
        # ⚠️ **يُعلن صراحةً.** التطبيق على الجهاز يعرض ذلك للعميل، فلا
        # يبقى ادّعاء أن المعالجة محلية حين لا تكون كذلك.
        cloud=_is_cloud(provider),
    )


def _is_cloud(provider: Any) -> bool:
    """هل يرسل هذا المزوّد نصّ المحادثة خارج السيرفر؟

    يُقرأ من تسمية المزوّد نفسها لا من قائمة أسماء هنا: قائمةٌ ثانية
    تُنسى عند إضافة مزوّد ثالث، والتسمية يراها من يكتبه.
    """
    return "سحاب" in getattr(provider, "PRODUCT_LABEL", "")


# ---------------------------------------------------------------------------
# المودل
# ---------------------------------------------------------------------------
@router.get(
    "/model",
    response_model=ModelArtifactResponse,
    summary="رابط تنزيل المودل وبيانات التحقق منه",
    responses={
        401: {"description": "بيان اعتماد مفقود أو مرفوض أو لجهاز أُبطل"},
        403: {"description": "الاشتراك لا يسمح بالخدمة"},
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
