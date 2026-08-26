"""قراءة الجهات والمستخدمين من جدولي organizations و users.

**قاعدة العزل:** كل قراءة لمستخدم بعد تسجيل الدخول مقيّدة بـ`organization_id`،
ولا توجد هنا دالة تقرأ مستخدمًا بمعرّفه وحده. الاستثناء هو البحث بالبريد وقت
تسجيل الدخول — قبله لا توجد هوية موثوقة أصلًا، والحماية فيه بكلمة المرور.

كل القيم تُمرَّر كمتغيرات مربوطة (`:name`) لا بدمج نصي، فلا مجال لحقن SQL.
الاتصال كسول: هذا الملف لا يفتح شيئًا حتى يُستدعى فعلًا.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .oracle import get_connection

if TYPE_CHECKING:  # يُستورد للتلميح النوعي فقط.
    # الاتجاه دائمًا services ← database، وعكسه وقت التشغيل استيراد دائري.
    from ..services.user_store import Organization, StoredUser, User

#: أعمدة المستخدم بالترتيب المستخدَم في كل الاستعلامات أدناه.
_USER_COLUMNS = """
    u.id, u.organization_id, u.email, u.full_name,
    u.role, u.is_active, u.password_hash
"""

# البريد فريد على مستوى النظام (فهرس uq_users_email_lower)، فيطابق صفًا واحدًا
# على الأكثر. يبقى الاستعلام بلا FETCH FIRST عمدًا: لو حملت قاعدة قديمة بريدًا
# مكررًا وجب أن يظهر التكرار لمسار المصادقة ليرفضه، لا أن يُقصّ بصمت فيُختار
# «أول مستخدم». LOWER على الطرفين لأن التفرّد نفسه غير حساس لحالة الأحرف.
_FIND_USERS_BY_EMAIL = f"""
    SELECT {_USER_COLUMNS}
      FROM users u
     WHERE LOWER(u.email) = :email
     ORDER BY u.id
"""

_EMAIL_EXISTS = """
    SELECT 1
      FROM users u
     WHERE LOWER(u.email) = :email
     FETCH FIRST 1 ROWS ONLY
"""

# شرط الجهة جزء من الاستعلام لا مرشِّح بعده: لا يمكن لهذه الدالة أن تعيد
# مستخدمًا من جهة أخرى حتى لو مُرِّر معرّف صحيح لمستخدم فيها.
_FETCH_USER = f"""
    SELECT {_USER_COLUMNS}
      FROM users u
     WHERE u.id = :user_id
       AND u.organization_id = :organization_id
"""

_FETCH_ORGANIZATION = """
    SELECT o.id, o.name, o.slug, o.is_active
      FROM organizations o
     WHERE o.id = :organization_id
"""

_FETCH_ORGANIZATION_BY_SLUG = """
    SELECT o.id, o.name, o.slug, o.is_active
      FROM organizations o
     WHERE LOWER(o.slug) = :slug
"""

_INSERT_ORGANIZATION = """
    INSERT INTO organizations (name, slug)
    VALUES (:name, :slug)
    RETURNING id INTO :new_id
"""

# COALESCE يجعل NULL تعني «لا تغيّر»: الحقلان NOT NULL في المخطط، فلا قيمة
# مشروعة منهما NULL ولا التباس في المعنى. updated_at مسؤولية الـBackend —
# لا Trigger في المخطط عمدًا.
_UPDATE_ORGANIZATION = """
    UPDATE organizations
       SET name       = COALESCE(:name, name),
           slug       = COALESCE(:slug, slug),
           updated_at = SYSTIMESTAMP
     WHERE id = :organization_id
"""

_FETCH_USERS = f"""
    SELECT {_USER_COLUMNS}
      FROM users u
     WHERE u.organization_id = :organization_id
     ORDER BY u.id
"""

# المقاعد المستهلَكة: النشطون وحدهم، فحساب معطَّل لا يشغل ترخيصًا.
_COUNT_ACTIVE_USERS = """
    SELECT COUNT(*)
      FROM users u
     WHERE u.organization_id = :organization_id
       AND u.is_active = 1
"""

_FETCH_USER_BY_EMAIL = f"""
    SELECT {_USER_COLUMNS}
      FROM users u
     WHERE u.organization_id = :organization_id
       AND LOWER(u.email) = :email
"""

_INSERT_USER = """
    INSERT INTO users (organization_id, email, full_name, role, password_hash)
    VALUES (:organization_id, :email, :full_name, :role, :password_hash)
    RETURNING id INTO :new_id
"""

# شرط الجهة في عبارة الكتابة نفسها لا في فحص سابق: صف جهة أخرى لا يمكن أن
# يتغيّر بهذه العبارة حتى لو مُرِّر معرّفه.
_UPDATE_USER = """
    UPDATE users
       SET full_name     = COALESCE(:full_name, full_name),
           role          = COALESCE(:role, role),
           is_active     = COALESCE(:is_active, is_active),
           password_hash = COALESCE(:password_hash, password_hash),
           updated_at    = SYSTIMESTAMP
     WHERE id = :user_id
       AND organization_id = :organization_id
"""

#: رمز Oracle لانتهاك قيد التفرّد.
_UNIQUE_VIOLATION = "ORA-00001"


def _row_to_stored_user(row) -> StoredUser:
    """يحوّل صف استعلام إلى StoredUser."""
    from ..services.user_store import StoredUser, User

    return StoredUser(
        user=User(
            id=int(row[0]),
            organization_id=int(row[1]),
            email=row[2],
            full_name=row[3],
            role=row[4],
            is_active=bool(row[5]),
        ),
        password_hash=row[6],
    )


def find_users_by_email(*, email: str) -> list[StoredUser]:
    """يعيد المستخدمين المطابقين للبريد، لمسار تسجيل الدخول وحده.

    Args:
        email: البريد بأحرف صغيرة وبلا فراغات.

    Returns:
        قائمة فيها صف واحد على الأكثر. أكثر من صف يعني بيانات متعارضة سبقت
        فهرس التفرّد، ومسار المصادقة يرفض الدخول حينها بدل أن يخمّن.
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(_FIND_USERS_BY_EMAIL, {"email": email})
            rows = cursor.fetchall()

    return [_row_to_stored_user(row) for row in rows]


def email_exists(email: str) -> bool:
    """هل البريد مستخدم في **أي** جهة؟ التفرّد عالمي لا داخل الجهة."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(_EMAIL_EXISTS, {"email": email})
            return cursor.fetchone() is not None


def fetch_user(*, user_id: int, organization_id: int) -> User | None:
    """يقرأ مستخدمًا **داخل جهته**، أو None إن لم يوجد فيها."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _FETCH_USER,
                {"user_id": user_id, "organization_id": organization_id},
            )
            row = cursor.fetchone()

    return _row_to_stored_user(row).user if row else None


def fetch_user_by_email(*, organization_id: int, email: str) -> User | None:
    """يقرأ مستخدمًا بالبريد **داخل جهة واحدة**، للتحقق من التفرّد."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _FETCH_USER_BY_EMAIL,
                {"organization_id": organization_id, "email": email},
            )
            row = cursor.fetchone()

    return _row_to_stored_user(row).user if row else None


def count_active_users(*, organization_id: int) -> int:
    """يعيد عدد المستخدمين النشطين في جهة واحدة."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _COUNT_ACTIVE_USERS, {"organization_id": organization_id}
            )
            row = cursor.fetchone()
    return int(row[0]) if row else 0


def fetch_users(*, organization_id: int) -> list[User]:
    """يعيد مستخدمي جهة واحدة. لا يوجد شكل من هذا الاستعلام بلا شرط الجهة."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(_FETCH_USERS, {"organization_id": organization_id})
            rows = cursor.fetchall()

    return [_row_to_stored_user(row).user for row in rows]


def _row_to_organization(row) -> Organization:
    from ..services.user_store import Organization

    return Organization(
        id=int(row[0]), name=row[1], slug=row[2], is_active=bool(row[3])
    )


def fetch_organization(organization_id: int) -> Organization | None:
    """يقرأ جهة بمعرّفها، أو None إن لم توجد."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _FETCH_ORGANIZATION, {"organization_id": organization_id}
            )
            row = cursor.fetchone()

    return _row_to_organization(row) if row else None


def fetch_organization_by_slug(slug: str) -> Organization | None:
    """يقرأ جهة بمعرّفها النصي، أو None إن لم توجد."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(_FETCH_ORGANIZATION_BY_SLUG, {"slug": slug})
            row = cursor.fetchone()

    return _row_to_organization(row) if row else None


# ---------------------------------------------------------------------------
# الكتابة
# ---------------------------------------------------------------------------
def _returned_id(variable) -> int:
    """يقرأ المعرّف من متغير RETURNING.

    الدرايفر يعيد قائمة لعبارات DML، وقيمة مفردة في حالات أخرى.
    """
    value = variable.getvalue()
    if isinstance(value, list):
        value = value[0]
    return int(value)


def _translate_unique_violation(exc: Exception, *, email: str | None = None) -> None:
    """يحوّل ORA-00001 إلى خطأ مجال مفهوم، أو يترك الاستثناء كما هو.

    القيود المعنية: uq_users_email_lower (تفرّد البريد عالميًا) و
    uq_users_org_email (تفرّده داخل الجهة) و uq_organizations_slug.
    """
    from ..services.user_store import DuplicateEmailError, DuplicateSlugError

    raw = str(exc)
    if _UNIQUE_VIOLATION not in raw:
        return

    lowered = raw.lower()
    if "uq_users_email_lower" in lowered or "uq_users_org_email" in lowered:
        target = f"«{email}»" if email else "المُدخَل"
        raise DuplicateEmailError(
            f"البريد {target} مسجّل بالفعل في النظام. "
            "البريد فريد على مستوى النظام كله لأنه هوية الدخول."
        ) from exc
    if "uq_organizations_slug" in lowered:
        raise DuplicateSlugError(
            "المعرّف النصي مستخدم لجهة أخرى. اختر غيره."
        ) from exc


def insert_organization(*, name: str, slug: str) -> Organization:
    """ينشئ جهة ويعيدها بمعرّفها المولَّد.

    Raises:
        DuplicateSlugError: إذا كان المعرّف النصي مستخدمًا.
    """
    from ..services.user_store import Organization

    with get_connection() as connection:
        with connection.cursor() as cursor:
            new_id = cursor.var(int)
            try:
                cursor.execute(
                    _INSERT_ORGANIZATION,
                    {"name": name, "slug": slug, "new_id": new_id},
                )
            except Exception as exc:
                _translate_unique_violation(exc)
                raise
            organization_id = _returned_id(new_id)
        connection.commit()

    return Organization(id=organization_id, name=name, slug=slug, is_active=True)


def update_organization_row(
    *, organization_id: int, name: str | None = None, slug: str | None = None
) -> Organization | None:
    """يحدّث الحقول غير الفارغة ويعيد الجهة بعد التحديث، أو None إن لم توجد.

    Raises:
        DuplicateSlugError: إذا كان المعرّف النصي الجديد مستخدمًا.
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    _UPDATE_ORGANIZATION,
                    {
                        "organization_id": organization_id,
                        "name": name,
                        "slug": slug,
                    },
                )
            except Exception as exc:
                _translate_unique_violation(exc)
                raise
            if cursor.rowcount == 0:
                return None
        connection.commit()

    return fetch_organization(organization_id)


def insert_user(
    *,
    organization_id: int,
    email: str,
    full_name: str,
    role: str,
    password_hash: str,
) -> User:
    """ينشئ مستخدمًا داخل جهة ويعيده بمعرّفه المولَّد.

    Raises:
        DuplicateEmailError: إذا كان البريد مسجّلًا في الجهة نفسها.
    """
    from ..services.user_store import User

    with get_connection() as connection:
        with connection.cursor() as cursor:
            new_id = cursor.var(int)
            try:
                cursor.execute(
                    _INSERT_USER,
                    {
                        "organization_id": organization_id,
                        "email": email,
                        "full_name": full_name,
                        "role": role,
                        "password_hash": password_hash,
                        "new_id": new_id,
                    },
                )
            except Exception as exc:
                _translate_unique_violation(exc, email=email)
                raise
            user_id = _returned_id(new_id)
        connection.commit()

    return User(
        id=user_id,
        organization_id=organization_id,
        email=email,
        full_name=full_name,
        role=role,
        is_active=True,
    )


def update_user_row(
    *,
    user_id: int,
    organization_id: int,
    full_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    password_hash: str | None = None,
) -> User | None:
    """يحدّث الحقول غير الفارغة **داخل الجهة**، ويعيد المستخدم بعد التحديث.

    يعيد None إن لم يطابق أي صف — سواء لأن المستخدم غير موجود أو لأنه في جهة
    أخرى. لا يُفرَّق بين الحالتين.
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _UPDATE_USER,
                {
                    "user_id": user_id,
                    "organization_id": organization_id,
                    "full_name": full_name,
                    "role": role,
                    # عمود NUMBER(1) في المخطط، فتُمرَّر رقمًا لا منطقيًا.
                    "is_active": None if is_active is None else int(is_active),
                    "password_hash": password_hash,
                },
            )
            if cursor.rowcount == 0:
                return None
        connection.commit()

    return fetch_user(user_id=user_id, organization_id=organization_id)
