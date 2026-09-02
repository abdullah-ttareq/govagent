"""إدارة الجهات والمستخدمين — منطق الصلاحيات وعزل البيانات.

**قاعدة العزل (أهم ما في هذا الملف):** كل دالة هنا تأخذ ``actor`` وهو المستخدم
الذي أثبت التوكن هويته، وتشتق منه ``organization_id``. لا توجد دالة واحدة تقبل
``organization_id`` كمُعامل مستقل، فلا يمكن لمسار أن يمرّر جهة من جسم الطلب
حتى لو أراد. الفصل بنيوي لا اتفاقي.

**قاعدة عدم التسريب:** سجل جهة أخرى يُعامل كغير موجود (404) لا كممنوع (403).
الفرق مهم: «ممنوع» تؤكد أن السجل موجود، وهذه معلومة عن جهة أخرى.

قواعد الدور:

* ``admin`` — يدير مستخدمي جهته فقط: إنشاء، قراءة، تعديل، تعطيل.
* ``employee`` — يرى نفسه فقط، ويعدّل اسمه وكلمة مروره فقط.
"""

from __future__ import annotations

from ..core.security import hash_password
from .audit_service import record_for
from .audit_store import ACTION_USER_CREATED, ACTION_USER_DISABLED
from .subscription_service import ensure_seat_available
from .user_store import (
    DuplicateEmailError,
    Organization,
    User,
    get_user_store,
    normalize_email,
)

#: الدوران المقبولان، مطابقان لقيد ck_users_role في المخطط.
ALLOWED_ROLES: tuple[str, ...] = ("admin", "employee")


class DirectoryError(Exception):
    """خطأ في إدارة الجهات أو المستخدمين، برسالة عربية صالحة للعرض."""


class NotFoundError(DirectoryError):
    """السجل غير موجود **في جهة صاحب الطلب**. تشمل سجلات الجهات الأخرى."""


class PermissionDeniedError(DirectoryError):
    """صاحب الطلب داخل جهته لكن دوره لا يسمح بهذه العملية."""


# ---------------------------------------------------------------------------
# الجهات
# ---------------------------------------------------------------------------
def create_organization(
    *, name: str, slug: str, admin_email: str, admin_full_name: str, admin_password: str
) -> tuple[Organization, User]:
    """ينشئ جهة جديدة ومسؤولها الأول معًا.

    الاثنان معًا عمدًا: جهة بلا مسؤول لا يمكن الدخول إليها إطلاقًا، فيصير
    إنشاؤها وحدها صفًا ميتًا في القاعدة.

    **هذه العملية خارج نطاق التوكن**: لا وجود لمستخدم بعد ليأذن بها، فتحرسها
    مفتاح التجهيز في مسار الـAPI. انظر `api/organizations.py`.

    Raises:
        DuplicateSlugError: إذا كان المعرّف النصي مستخدمًا.
        DuplicateEmailError: إذا كان بريد المسؤول مسجّلًا في **أي** جهة.
        SecurityError: إذا كانت كلمة مرور المسؤول غير مقبولة.
    """
    store = get_user_store()

    # الفحصان قبل إنشاء الجهة: بريد مرفوض أو كلمة مرور مرفوضة يجب ألا تترك
    # جهة بلا مسؤول، وهي جهة لا يمكن الدخول إليها إطلاقًا.
    if store.email_is_taken(admin_email):
        raise DuplicateEmailError(
            f"البريد «{normalize_email(admin_email)}» مسجّل بالفعل في النظام. "
            "البريد فريد على مستوى النظام كله لأنه هوية الدخول."
        )
    password_hash = hash_password(admin_password)

    organization = store.create_organization(name=name, slug=slug)
    admin = store.create_user(
        organization_id=organization.id,
        email=admin_email,
        full_name=admin_full_name,
        role="admin",
        password_hash=password_hash,
    )
    return organization, admin


def get_organization(*, actor: User, organization_id: int) -> Organization:
    """يقرأ جهة صاحب الطلب.

    Raises:
        NotFoundError: إذا كان المعرّف لجهة أخرى — لا يُكشف وجودها من عدمه.
    """
    if organization_id != actor.organization_id:
        raise NotFoundError("الجهة المطلوبة غير موجودة.")

    organization = get_user_store().get_organization(actor.organization_id)
    if organization is None:
        raise NotFoundError("الجهة المطلوبة غير موجودة.")
    return organization


def update_organization(
    *,
    actor: User,
    organization_id: int,
    name: str | None = None,
    slug: str | None = None,
) -> Organization:
    """يحدّث بيانات جهة صاحب الطلب. للمسؤول فقط.

    ``is_active`` ليست من الحقول القابلة للتعديل هنا عمدًا: تعطيل الجهة من
    داخلها يقفل الباب على كل موظفيها ومسؤوليها بلا طريق للعودة.

    Raises:
        NotFoundError: إذا كان المعرّف لجهة أخرى.
        PermissionDeniedError: إذا لم يكن صاحب الطلب مسؤولًا.
        DuplicateSlugError: إذا كان المعرّف النصي الجديد مستخدمًا.
    """
    # ترتيب الفحص مقصود: الجهة الأخرى تُنكَر قبل النظر في الدور، حتى لا يفرّق
    # الرد بين «جهة أخرى» و«دور غير كافٍ».
    if organization_id != actor.organization_id:
        raise NotFoundError("الجهة المطلوبة غير موجودة.")
    _require_admin(actor, "تعديل بيانات الجهة")

    updated = get_user_store().update_organization(
        organization_id=actor.organization_id, name=name, slug=slug
    )
    if updated is None:
        raise NotFoundError("الجهة المطلوبة غير موجودة.")
    return updated


# ---------------------------------------------------------------------------
# المستخدمون
# ---------------------------------------------------------------------------
def _require_admin(actor: User, action: str) -> None:
    if actor.role != "admin":
        raise PermissionDeniedError(
            f"{action} متاح لمسؤول الجهة فقط. راجع مسؤول النظام في جهتك."
        )


def _load_user_in_scope(actor: User, user_id: int) -> User:
    """يقرأ مستخدمًا داخل جهة صاحب الطلب، أو يرفع NotFoundError."""
    user = get_user_store().get_user(
        user_id=user_id, organization_id=actor.organization_id
    )
    if user is None:
        raise NotFoundError("المستخدم المطلوب غير موجود.")
    return user


def list_users(*, actor: User) -> list[User]:
    """يعيد مستخدمي جهة صاحب الطلب. للمسؤول فقط.

    الموظف لا يرى زملاءه: يقرأ نفسه عبر ``/api/auth/me`` أو بمعرّفه.

    Raises:
        PermissionDeniedError: إذا لم يكن صاحب الطلب مسؤولًا.
    """
    _require_admin(actor, "عرض قائمة موظفي الجهة")
    return get_user_store().list_users(organization_id=actor.organization_id)


def get_user(*, actor: User, user_id: int) -> User:
    """يقرأ مستخدمًا: المسؤول أي موظف في جهته، والموظف نفسه فقط.

    Raises:
        NotFoundError: إذا كان المستخدم في جهة أخرى أو غير موجود.
        PermissionDeniedError: إذا حاول موظف قراءة زميل له.
    """
    user = _load_user_in_scope(actor, user_id)
    if actor.role != "admin" and user.id != actor.id:
        raise PermissionDeniedError("لا تملك صلاحية عرض بيانات موظف آخر.")
    return user


def create_user(
    *, actor: User, email: str, full_name: str, role: str, password: str
) -> User:
    """ينشئ موظفًا **داخل جهة صاحب الطلب**. للمسؤول فقط.

    الجهة تأتي من ``actor`` لا من جسم الطلب، فلا يمكن إنشاء مستخدم في جهة أخرى.

    Raises:
        PermissionDeniedError: إذا لم يكن صاحب الطلب مسؤولًا.
        DirectoryError: إذا كان الدور غير مقبول.
        DuplicateEmailError: إذا كان البريد مسجّلًا في **أي** جهة.
        SubscriptionInactiveError: إذا كان اشتراك الجهة غير صالح.
        SeatLimitReachedError: إذا لم يبق مقعد شاغر في تراخيص الجهة.
        SecurityError: إذا كانت كلمة المرور غير مقبولة.
    """
    _require_admin(actor, "إضافة موظف جديد")
    _validate_role(role)

    store = get_user_store()
    # فحص مسبق عالمي لا داخل الجهة: البريد هوية الدخول وهو فريد على مستوى
    # النظام. المخزن يفرضه أيضًا (فهرس في Oracle وفحص في مخزن الذاكرة)، وهذا
    # الفحص من أجل رسالة واضحة قبل تجزئة كلمة المرور المكلفة.
    if store.email_is_taken(email):
        raise DuplicateEmailError(
            f"البريد «{normalize_email(email)}» مسجّل بالفعل في النظام. "
            "البريد فريد على مستوى النظام كله لأنه هوية الدخول."
        )

    # المقاعد قبل التجزئة المكلفة: طلبٌ سيُرفض لا يستحق ثمن bcrypt.
    ensure_seat_available(actor.organization_id)

    created = store.create_user(
        organization_id=actor.organization_id,
        email=email,
        full_name=full_name,
        role=role,
        password_hash=hash_password(password),
    )
    record_for(
        actor,
        action=ACTION_USER_CREATED,
        details=f"إنشاء الموظف {created.email} بدور {created.role}",
    )
    return created


def update_user(
    *,
    actor: User,
    user_id: int,
    full_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    password: str | None = None,
) -> User:
    """يحدّث مستخدمًا داخل جهة صاحب الطلب.

    * المسؤول: كل الحقول، على أي موظف في جهته.
    * الموظف: ``full_name`` و ``password`` على نفسه فقط.

    المسؤول لا يغيّر دوره ولا حالته بنفسه: لو كان المسؤول الوحيد في الجهة
    لأقفل الإدارة على نفسه بلا طريق للعودة.

    Raises:
        NotFoundError: إذا كان المستخدم في جهة أخرى أو غير موجود.
        PermissionDeniedError: إذا تجاوز الدور صلاحيته.
        SecurityError: إذا كانت كلمة المرور الجديدة غير مقبولة.
    """
    target = _load_user_in_scope(actor, user_id)
    is_self = target.id == actor.id
    changes_privileges = role is not None or is_active is not None

    if actor.role != "admin":
        if not is_self:
            raise PermissionDeniedError("لا تملك صلاحية تعديل بيانات موظف آخر.")
        if changes_privileges:
            raise PermissionDeniedError(
                "تغيير الدور أو حالة التفعيل متاح لمسؤول الجهة فقط."
            )
    elif is_self and changes_privileges:
        raise PermissionDeniedError(
            "لا يمكنك تغيير دورك أو تعطيل حسابك بنفسك. اطلب ذلك من مسؤول آخر "
            "في جهتك."
        )

    if role is not None:
        _validate_role(role)

    # إعادة تفعيل حساب معطّل تشغل مقعدًا كإنشاء موظف جديد. لولا هذا
    # الفحص لأمكن تجاوز حد التراخيص بتعطيل حساب ثم تفعيل غيره.
    if is_active is True and not target.is_active:
        ensure_seat_available(actor.organization_id)

    updated = get_user_store().update_user(
        user_id=user_id,
        organization_id=actor.organization_id,
        full_name=full_name,
        role=role,
        is_active=is_active,
        password_hash=None if password is None else hash_password(password),
    )
    if updated is None:
        raise NotFoundError("المستخدم المطلوب غير موجود.")
    return updated


def deactivate_user(*, actor: User, user_id: int) -> User:
    """يعطّل موظفًا في جهة صاحب الطلب. للمسؤول فقط.

    **تعطيل لا حذف:** الصف مرتبط بمحادثاته وملفاته وسجل تدقيقه بمفاتيح أجنبية،
    وحذفه يترك تاريخًا بلا صاحب. الحساب المعطّل يُمنع من تسجيل الدخول ومن كل
    مسار محمي.

    Raises:
        NotFoundError: إذا كان المستخدم في جهة أخرى أو غير موجود.
        PermissionDeniedError: إذا لم يكن صاحب الطلب مسؤولًا أو حاول تعطيل نفسه.
    """
    _require_admin(actor, "تعطيل حساب موظف")
    target = _load_user_in_scope(actor, user_id)

    if target.id == actor.id:
        raise PermissionDeniedError(
            "لا يمكنك تعطيل حسابك بنفسك. اطلب ذلك من مسؤول آخر في جهتك."
        )

    updated = get_user_store().update_user(
        user_id=user_id, organization_id=actor.organization_id, is_active=False
    )
    if updated is None:
        raise NotFoundError("المستخدم المطلوب غير موجود.")

    record_for(
        actor,
        action=ACTION_USER_DISABLED,
        details=f"تعطيل حساب الموظف {updated.email}",
    )
    return updated


def _validate_role(role: str) -> None:
    if role not in ALLOWED_ROLES:
        raise DirectoryError(
            f"الدور «{role}» غير مقبول. القيم المقبولة: "
            f"{'، '.join(ALLOWED_ROLES)}."
        )
