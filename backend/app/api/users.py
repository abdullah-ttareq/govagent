"""مسارات المستخدمين داخل الجهة.

**كل مسار هنا يعمل داخل جهة صاحب الطلب حصرًا.** لا يوجد في أي طلب حقل
``organization_id``، ولا يستقبل أي مسار جهة كمُعامل: الجهة تُشتق من التوكن
داخل `directory_service`. مستخدم من جهة أخرى يعود **404 بلا بيانات**.
"""

from fastapi import APIRouter, HTTPException, status

from ..core.security import SecurityError
from ..schemas import (
    UserCreateRequest,
    UserListResponse,
    UserOut,
    UserUpdateRequest,
)
from ..services.directory_service import (
    DirectoryError,
    NotFoundError,
    PermissionDeniedError,
    create_user,
    deactivate_user,
    get_user,
    list_users,
    update_user,
)
from ..services.subscription_service import (
    SeatLimitReachedError,
    SubscriptionError,
    SubscriptionInactiveError,
)
from ..services.user_store import DuplicateEmailError, User, get_user_store
from .dependencies import AdminUser, CurrentUser

router = APIRouter(prefix="/api/users", tags=["users"])


def _to_user_out(user: User) -> UserOut:
    organization = get_user_store().get_organization(user.organization_id)
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        organization_id=user.organization_id,
        organization_name=organization.name if organization else None,
        is_active=user.is_active,
    )


def _http_error(exc: Exception) -> HTTPException:
    """يترجم أخطاء الخدمة إلى رموز HTTP بشكل موحّد."""
    if isinstance(exc, NotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        )
    if isinstance(exc, DuplicateEmailError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )
    if isinstance(exc, SeatLimitReachedError):
        # 409 لا 403: المورد مستنفد، لا الصلاحية ناقصة. تعطيل موظف
        # آخر يحل المشكلة بلا تغيير في دور الطالب.
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )
    if isinstance(exc, SubscriptionInactiveError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        )
    # كلمة مرور مرفوضة أو دور غير مقبول: خطأ في المُدخَل لا في الصلاحية.
    return HTTPException(
        status_code=422, detail=str(exc)
    )


@router.get(
    "",
    response_model=UserListResponse,
    summary="قائمة موظفي الجهة",
    responses={
        401: {"description": "رمز الدخول مفقود أو غير صالح"},
        403: {"description": "الإجراء متاح لمسؤول الجهة فقط"},
    },
)
def read_users(admin: AdminUser) -> UserListResponse:
    """يعيد موظفي جهة المسؤول وحدها.

    الموظف العادي لا يرى زملاءه: يقرأ نفسه من `/api/auth/me` أو بمعرّفه.
    """
    users = list_users(actor=admin)
    return UserListResponse(
        users=[_to_user_out(user) for user in users], total=len(users)
    )


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="إضافة موظف إلى الجهة",
    responses={
        401: {"description": "رمز الدخول مفقود أو غير صالح"},
        403: {"description": "الإجراء متاح لمسؤول الجهة فقط"},
        409: {"description": "البريد مسجّل في النظام، أو التراخيص مستنفدة"},
        422: {"description": "كلمة مرور أو دور غير مقبول"},
    },
)
def add_user(payload: UserCreateRequest, admin: AdminUser) -> UserOut:
    """ينشئ موظفًا **في جهة المسؤول**.

    الجهة تأتي من رمز الدخول، فلا يمكن إنشاء موظف في جهة أخرى بأي شكل.
    كلمة المرور تُجزَّأ بـbcrypt ولا تُخزَّن صريحة.
    """
    try:
        user = create_user(
            actor=admin,
            email=payload.email,
            full_name=payload.full_name,
            role=payload.role,
            password=payload.password,
        )
    except (
        DuplicateEmailError,
        PermissionDeniedError,
        DirectoryError,
        SecurityError,
        SubscriptionError,
    ) as exc:
        raise _http_error(exc) from exc

    return _to_user_out(user)


@router.get(
    "/{user_id}",
    response_model=UserOut,
    summary="قراءة بيانات موظف",
    responses={
        401: {"description": "رمز الدخول مفقود أو غير صالح"},
        403: {"description": "موظف يحاول قراءة بيانات زميل"},
        404: {"description": "المستخدم غير موجود في جهة صاحب الطلب"},
    },
)
def read_user(user_id: int, user: CurrentUser) -> UserOut:
    """يعيد بيانات موظف: المسؤول أي موظف في جهته، والموظف نفسه فقط.

    مستخدم من جهة أخرى يعود 404 بلا بيانات — لا يُكشف وجوده من عدمه.
    """
    try:
        return _to_user_out(get_user(actor=user, user_id=user_id))
    except DirectoryError as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    summary="تعديل بيانات موظف",
    responses={
        401: {"description": "رمز الدخول مفقود أو غير صالح"},
        403: {"description": "تجاوز لحدود الدور"},
        404: {"description": "المستخدم غير موجود في جهة صاحب الطلب"},
        409: {"description": "إعادة التفعيل تتجاوز عدد التراخيص"},
        422: {"description": "كلمة مرور أو دور غير مقبول"},
    },
)
def edit_user(
    user_id: int, payload: UserUpdateRequest, user: CurrentUser
) -> UserOut:
    """يعدّل بيانات موظف.

    * **المسؤول:** كل الحقول، على أي موظف في جهته.
    * **الموظف:** اسمه وكلمة مروره على نفسه فقط.

    المسؤول لا يغيّر دوره ولا يعطّل حسابه بنفسه، منعًا لإقفال الإدارة على
    الجهة. البريد غير قابل للتعديل — هو هوية الدخول ومرجع سجل التدقيق.
    """
    try:
        updated = update_user(
            actor=user,
            user_id=user_id,
            full_name=payload.full_name,
            role=payload.role,
            is_active=payload.is_active,
            password=payload.password,
        )
    except (DirectoryError, SecurityError, SubscriptionError) as exc:
        raise _http_error(exc) from exc

    return _to_user_out(updated)


@router.delete(
    "/{user_id}",
    response_model=UserOut,
    summary="تعطيل حساب موظف",
    responses={
        401: {"description": "رمز الدخول مفقود أو غير صالح"},
        403: {"description": "الإجراء متاح لمسؤول الجهة فقط، ولا يشمل حسابه"},
        404: {"description": "المستخدم غير موجود في جهة صاحب الطلب"},
    },
)
def disable_user(user_id: int, admin: AdminUser) -> UserOut:
    """يعطّل حساب موظف في جهة المسؤول.

    **تعطيل لا حذف:** الصف مرتبط بمحادثاته وملفاته وسجل تدقيقه، وحذفه يترك
    تاريخًا بلا صاحب. الحساب المعطّل يُمنع من تسجيل الدخول ومن كل مسار محمي،
    ويمكن إعادة تفعيله بـ`PATCH /api/users/{user_id}` بـ`is_active=true`.
    """
    try:
        return _to_user_out(deactivate_user(actor=admin, user_id=user_id))
    except DirectoryError as exc:
        raise _http_error(exc) from exc
