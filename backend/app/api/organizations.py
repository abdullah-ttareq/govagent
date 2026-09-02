"""مسارات الجهات.

القراءة والتعديل يمرّان بالتوكن، ويُقارَن المعرّف في المسار بجهة صاحب الطلب:
أي معرّف آخر يعود 404. الإنشاء وحده خارج التوكن — انظر شرحه عند `provision`.
"""

from fastapi import APIRouter, Header, HTTPException, status

from ..core.config import settings
from ..schemas import (
    ModelSettingsOut,
    ModelSettingsUpdateRequest,
    OrganizationCreatedResponse,
    OrganizationCreateRequest,
    OrganizationOut,
    OrganizationUpdateRequest,
    SubscriptionOut,
    SubscriptionUpdateRequest,
    UserOut,
)
from ..services.audit_service import record, record_for
from ..services.audit_store import (
    ACTION_MODEL_PROVIDER_CHANGED,
    ACTION_ORGANIZATION_PROVISIONED,
    ACTION_SUBSCRIPTION_CHANGED,
)
from ..services.model_settings_service import (
    ModelSettingsError,
    read_model_settings,
    update_model_settings,
)
from ..services.organization_settings_store import ModelSettings, Subscription
from ..services.subscription_service import (
    SubscriptionError,
    provision_subscription,
    read_subscription,
    seat_usage,
    update_subscription,
)
from ..services.directory_service import (
    NotFoundError,
    PermissionDeniedError,
    create_organization,
    get_organization,
    update_organization,
)
from ..services.user_store import DuplicateEmailError, DuplicateSlugError, Organization
from .dependencies import AdminUser, CurrentUser, CurrentUserAllowingExpired

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


def _to_organization_out(organization: Organization) -> OrganizationOut:
    return OrganizationOut(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        is_active=organization.is_active,
    )


def _require_provisioning_key(provided: str | None) -> None:
    """يتحقق من مفتاح التجهيز قبل إنشاء جهة جديدة.

    **المفتاح إلزامي دائمًا، بلا استثناء لبيئة التطوير.** المسار الوحيد الذي
    ينشئ جهة كاملة بمسؤول لها يجب ألا يكون مفتوحًا في أي وضع: بيئة تطوير
    مكشوفة على الشبكة، أو `APP_ENV` منسيّة على قيمتها الافتراضية عند النشر،
    تكفي لجعله بابًا مفتوحًا. التطوير المحلي لا يحتاجه أصلًا — مخزن الذاكرة
    مزروع بجهتين جاهزتين.

    المفتاح الفارغ **يعطّل المسار** ولا يصير قيمة تُقارَن: بدون هذا الفصل
    تطابق ترويسة فارغة مفتاحًا فارغًا ويمر الطلب.
    """
    configured = settings.provisioning_key.strip()

    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "تجهيز الجهات معطّل على هذا السيرفر لأن متغير PROVISIONING_KEY "
                "غير مضبوط. اضبطه في ملف .env بقيمة عشوائية طويلة ثم أعد "
                "تشغيل الخدمة."
            ),
        )

    # secrets.compare_digest تتفادى تسريب طول المفتاح عبر زمن المقارنة.
    # لا تُبلغ هنا إلا بمفتاح مضبوط غير فارغ، فالفراغ لا يطابق شيئًا.
    from secrets import compare_digest

    if provided is None or not compare_digest(provided.strip(), configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="مفتاح التجهيز غير صحيح أو مفقود.",
        )


@router.post(
    "",
    response_model=OrganizationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="تجهيز جهة جديدة ومسؤولها الأول",
    responses={
        401: {"description": "مفتاح التجهيز غير صحيح أو مفقود"},
        409: {"description": "المعرّف النصي مستخدم لجهة أخرى"},
        503: {"description": "مفتاح التجهيز غير مضبوط على السيرفر"},
    },
)
def provision(
    payload: OrganizationCreateRequest,
    x_provisioning_key: str | None = Header(
        None,
        alias="X-Provisioning-Key",
        description="مفتاح التجهيز كما في متغير PROVISIONING_KEY على السيرفر",
    ),
) -> OrganizationCreatedResponse:
    """ينشئ جهة جديدة ومسؤولها الأول معًا.

    **هذا المسار وحده لا يستخدم رمز الدخول**، ولا يمكن أن يستخدمه: الجهة
    الجديدة لا مستخدم فيها بعد ليأذن بإنشائها. يحرسه بدلًا من ذلك مفتاح
    التجهيز في ترويسة `X-Provisioning-Key`، وهو بيد من ينشر النظام على
    السيرفر لا بيد أي موظف.

    الجهة ومسؤولها يُنشآن معًا لأن جهة بلا مسؤول لا يمكن الدخول إليها إطلاقًا.
    """
    _require_provisioning_key(x_provisioning_key)

    try:
        organization, admin = create_organization(
            name=payload.name,
            slug=payload.slug,
            admin_email=payload.admin_email,
            admin_full_name=payload.admin_full_name,
            admin_password=payload.admin_password,
        )
    except (DuplicateSlugError, DuplicateEmailError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    # الاشتراك جزء من التجهيز: فحص الاشتراك مغلق الفشل، فجهة بلا اشتراك
    # لا يستطيع مسؤولها الدخول إليها إطلاقًا.
    provision_subscription(organization_id=organization.id)
    record(
        organization_id=organization.id,
        action=ACTION_ORGANIZATION_PROVISIONED,
        details=f"تجهيز الجهة «{organization.name}» ومسؤولها {admin.email}",
    )

    return OrganizationCreatedResponse(
        organization=_to_organization_out(organization),
        admin=UserOut(
            id=admin.id,
            email=admin.email,
            full_name=admin.full_name,
            role=admin.role,
            organization_id=admin.organization_id,
            organization_name=organization.name,
            is_active=admin.is_active,
        ),
    )


@router.get(
    "/{organization_id}",
    response_model=OrganizationOut,
    summary="قراءة بيانات الجهة",
    responses={
        401: {"description": "رمز الدخول مفقود أو غير صالح"},
        404: {"description": "المعرّف لا يخص جهة صاحب الطلب"},
    },
)
def read_organization(organization_id: int, user: CurrentUser) -> OrganizationOut:
    """يعيد بيانات جهة صاحب الطلب.

    أي معرّف غير جهة صاحب الطلب يعيد **404 بلا بيانات**، لا 403: الفرق أن
    «ممنوع» تؤكد أن الجهة موجودة، وهذه معلومة لا يستحقها.
    """
    try:
        return _to_organization_out(
            get_organization(actor=user, organization_id=organization_id)
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.patch(
    "/{organization_id}",
    response_model=OrganizationOut,
    summary="تعديل بيانات الجهة",
    responses={
        401: {"description": "رمز الدخول مفقود أو غير صالح"},
        403: {"description": "الإجراء متاح لمسؤول الجهة فقط"},
        404: {"description": "المعرّف لا يخص جهة صاحب الطلب"},
        409: {"description": "المعرّف النصي الجديد مستخدم لجهة أخرى"},
    },
)
def edit_organization(
    organization_id: int, payload: OrganizationUpdateRequest, user: CurrentUser
) -> OrganizationOut:
    """يعدّل اسم الجهة أو معرّفها النصي. لمسؤول الجهة فقط.

    الحقول المتروكة فارغة لا تتغيّر.
    """
    try:
        return _to_organization_out(
            update_organization(
                actor=user,
                organization_id=organization_id,
                name=payload.name,
                slug=payload.slug,
            )
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except DuplicateSlugError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


# ---------------------------------------------------------------------------
# الاشتراك والتراخيص
# ---------------------------------------------------------------------------
def _to_subscription_out(subscription: Subscription) -> SubscriptionOut:
    used, seats = seat_usage(subscription.organization_id)
    reason = subscription.blocked_reason()
    return SubscriptionOut(
        organization_id=subscription.organization_id,
        status=subscription.status,
        seats=seats,
        seats_used=used,
        seats_available=max(0, seats - used),
        starts_at=subscription.starts_at,
        expires_at=subscription.expires_at,
        is_usable=reason is None,
        blocked_reason=reason,
    )


@router.get(
    "/{organization_id}/subscription",
    response_model=SubscriptionOut,
    summary="قراءة اشتراك الجهة وتراخيصها",
    responses={
        401: {"description": "رمز الدخول مفقود أو غير صالح"},
        403: {"description": "الإجراء متاح لمسؤول الجهة فقط"},
        404: {"description": "المعرّف لا يخص جهة صاحب الطلب"},
    },
)
def read_organization_subscription(
    organization_id: int, user: CurrentUserAllowingExpired
) -> SubscriptionOut:
    """يعيد اشتراك جهة صاحب الطلب: مدته وحالته ومقاعده المستهلَكة.

    **يعمل ولو انتهى الاشتراك** — بل هذا أهم أوقات الحاجة إليه: المسؤول
    يفتحه ليعرف تاريخ الانتهاء وعدد المقاعد، لا ليُمنع من معرفتهما أيضًا.
    """
    if organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الجهة المطلوبة غير موجودة.",
        )
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="اشتراك الجهة متاح لمسؤول الجهة فقط.",
        )

    try:
        subscription = read_subscription(
            actor=user, organization_id=user.organization_id
        )
    except SubscriptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    return _to_subscription_out(subscription)


@router.patch(
    "/{organization_id}/subscription",
    response_model=SubscriptionOut,
    summary="تجديد اشتراك جهة أو تغيير تراخيصها",
    responses={
        401: {"description": "مفتاح التجهيز غير صحيح أو مفقود"},
        404: {"description": "لا يوجد اشتراك مسجّل لهذه الجهة"},
        422: {"description": "قيمة غير مقبولة"},
        503: {"description": "مفتاح التجهيز غير مضبوط على السيرفر"},
    },
)
def edit_organization_subscription(
    organization_id: int,
    payload: SubscriptionUpdateRequest,
    x_provisioning_key: str | None = Header(
        None,
        alias="X-Provisioning-Key",
        description="مفتاح التجهيز كما في متغير PROVISIONING_KEY على السيرفر",
    ),
) -> SubscriptionOut:
    """يجدّد اشتراك جهة أو يغيّر حالته أو عدد تراخيصه.

    **يحرسه مفتاح التجهيز لا رمز الدخول**، كإنشاء الجهة: تجديد الاشتراك
    وزيادة المقاعد قرار من يقدّم الخدمة لا من يستهلكها. لو مَلَكَه مسؤول
    الجهة لمنح نفسه مقاعد بلا حد ولمدّد اشتراكه بنفسه.
    """
    _require_provisioning_key(x_provisioning_key)

    try:
        subscription = update_subscription(
            organization_id=organization_id,
            status=payload.status,
            seats=payload.seats,
            starts_at=payload.starts_at,
            expires_at=payload.expires_at,
        )
    except SubscriptionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    record(
        organization_id=organization_id,
        action=ACTION_SUBSCRIPTION_CHANGED,
        details=(
            f"تحديث الاشتراك: الحالة {subscription.status}، "
            f"التراخيص {subscription.seats}، "
            f"الانتهاء {subscription.expires_at:%Y-%m-%d}"
        ),
    )
    return _to_subscription_out(subscription)


# ---------------------------------------------------------------------------
# مزود المودل
# ---------------------------------------------------------------------------
def _to_model_settings_out(chosen: ModelSettings) -> ModelSettingsOut:
    return ModelSettingsOut(
        organization_id=chosen.organization_id,
        provider=chosen.provider,
        updated_at=chosen.updated_at,
    )


@router.get(
    "/{organization_id}/model-settings",
    response_model=ModelSettingsOut,
    summary="قراءة مزود المودل المفعّل للجهة",
    responses={
        401: {"description": "رمز الدخول مفقود أو غير صالح"},
        403: {"description": "الإجراء متاح لمسؤول الجهة فقط"},
        404: {"description": "المعرّف لا يخص جهة صاحب الطلب"},
    },
)
def read_organization_model_settings(
    organization_id: int, admin: AdminUser
) -> ModelSettingsOut:
    """يعيد المزود الذي يجيب لهذه الجهة فعلًا.

    الجهة التي لم تختر مزودًا تُعاد بقيمة `MODEL_PROVIDER` العامة، لا بحقل
    فارغ: الواجهة تعرض ما يجيب فعلًا لا ما سُجّل في صف.
    """
    if organization_id != admin.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الجهة المطلوبة غير موجودة.",
        )
    return _to_model_settings_out(
        read_model_settings(actor=admin, organization_id=admin.organization_id)
    )


@router.patch(
    "/{organization_id}/model-settings",
    response_model=ModelSettingsOut,
    summary="اختيار مزود المودل للجهة",
    responses={
        401: {"description": "رمز الدخول مفقود أو غير صالح"},
        403: {"description": "الإجراء متاح لمسؤول الجهة فقط"},
        404: {"description": "المعرّف لا يخص جهة صاحب الطلب"},
        422: {"description": "اسم المزود غير مدعوم"},
    },
)
def edit_organization_model_settings(
    organization_id: int,
    payload: ModelSettingsUpdateRequest,
    admin: AdminUser,
) -> ModelSettingsOut:
    """يثبّت مزود المودل لجهة المسؤول.

    يُقرأ بعدها من القاعدة بدل `MODEL_PROVIDER` في كل محادثة لهذه الجهة.
    **اسم المزود فقط، بلا مفاتيح ولا أسرار.**
    """
    if organization_id != admin.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الجهة المطلوبة غير موجودة.",
        )

    try:
        chosen = update_model_settings(
            actor=admin,
            organization_id=admin.organization_id,
            provider=payload.provider,
        )
    except ModelSettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    record_for(
        admin,
        action=ACTION_MODEL_PROVIDER_CHANGED,
        details=f"تغيير مزود المودل إلى {chosen.provider}",
    )
    return _to_model_settings_out(chosen)
