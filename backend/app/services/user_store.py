"""مخزن الجهات والمستخدمين خلف واجهة واحدة، يُختار من ``DATA_STORE``.

* ``memory`` (الافتراضي) — مخزن داخل ذاكرة العملية، مزروع بالجهتين
  التجريبيتين في ``mock-data/organizations.json``. يجعل تسجيل الدخول قابلًا
  للتشغيل والاختبار قبل توفّر Oracle، تمامًا كما يعمل ``MODEL_PROVIDER=mock``
  بلا OCI. **غير دائم:** يفرغ عند إعادة التشغيل، وللتطوير والعرض لا للإنتاج.
* ``oracle`` — جدولا ``organizations`` و ``users`` في قاعدة Oracle.

**قاعدة العزل:** لا توجد هنا دالة تقرأ مستخدمًا بمعرّفه وحده. كل قراءة بعد
تسجيل الدخول تأخذ ``organization_id`` وتُقيَّد به، والجهة تأتي من التوكن لا من
جسم الطلب. الاستثناء الوحيد هو البحث بالبريد وقت تسجيل الدخول، وهو قبل وجود
أي هوية موثوقة أصلًا، ويظل محميًا بكلمة المرور.

**تفرّد البريد عالمي، لا داخل الجهة (منذ مراجعة P2-02).** تسجيل الدخول يبحث
بالبريد قبل أن تُعرف الجهة، فلو تكرر بين جهتين لصار على النظام أن يخمّن
أيهما. التفرّد العالمي يجعل البحث يعيد صفًا واحدًا **بنيويًا**. يفرضه في
Oracle فهرس ``uq_users_email_lower``، وفي مخزن الذاكرة فحص في ``create_user``.

كلمة المرور الصريحة لا تمر من هنا إطلاقًا: المخزن يتعامل مع التجزئة فقط.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from ..core.config import settings

#: الدوران الوحيدان في الـMVP، مطابقان لقيد ck_users_role في المخطط.
UserRole = Literal["admin", "employee"]


class UserStoreError(Exception):
    """خطأ في مخزن المستخدمين، برسالة عربية صالحة للعرض."""


class DuplicateEmailError(UserStoreError):
    """البريد مستخدم في النظام (فهرس uq_users_email_lower — تفرّد عالمي)."""


class DuplicateSlugError(UserStoreError):
    """معرّف الجهة النصي مستخدم (قيد uq_organizations_slug)."""


@dataclass(frozen=True)
class Organization:
    """جهة حكومية مشتركة في النظام."""

    id: int
    name: str
    slug: str
    is_active: bool


@dataclass(frozen=True)
class User:
    """مستخدم كما يُعرض ويُمرَّر داخل التطبيق.

    **بلا ``password_hash`` عمدًا:** ما لا يحمله الكائن لا يمكن أن يتسرّب في
    رد أو سجل بالخطأ. التجزئة تُقرأ فقط عبر :class:`StoredUser` في مسار
    التحقق من كلمة المرور.
    """

    id: int
    organization_id: int
    email: str
    full_name: str
    role: str
    is_active: bool


@dataclass(frozen=True)
class StoredUser:
    """مستخدم مع تجزئة كلمته — للاستخدام داخل مسار المصادقة وحده."""

    user: User
    password_hash: str


def normalize_email(email: str) -> str:
    """يوحّد شكل البريد للمقارنة: بلا فراغات وبأحرف صغيرة."""
    return email.strip().lower()


class UserStore(ABC):
    """واجهة قراءة الجهات والمستخدمين."""

    name: str = "base"

    @abstractmethod
    def find_login_candidates(self, *, email: str) -> list[StoredUser]:
        """يعيد المستخدمين المطابقين للبريد، لتسجيل الدخول وحده.

        التفرّد العالمي يجعلها تعيد صفًا واحدًا على الأكثر. تعيد **قائمة** لا
        قيمة مفردة عمدًا: لو حملت قاعدة قديمة بريدًا مكررًا (قبل إضافة فهرس
        ``uq_users_email_lower``) وجب أن يرى مسار المصادقة التكرار ليرفضه، لا
        أن يُخفى خلف اختيار صامت لأول صف.
        """
        raise NotImplementedError

    @abstractmethod
    def email_is_taken(self, email: str) -> bool:
        """هل البريد مستخدم في **أي** جهة؟ التفرّد عالمي لا داخل الجهة."""
        raise NotImplementedError

    @abstractmethod
    def get_user(self, *, user_id: int, organization_id: int) -> User | None:
        """يقرأ مستخدمًا داخل جهته. لا يمكن قراءة مستخدم من جهة أخرى."""
        raise NotImplementedError

    @abstractmethod
    def get_organization(self, organization_id: int) -> Organization | None:
        """يقرأ جهة بمعرّفها."""
        raise NotImplementedError

    @abstractmethod
    def get_organization_by_slug(self, slug: str) -> Organization | None:
        """يقرأ جهة بمعرّفها النصي. للتحقق من التفرّد عند الإنشاء."""
        raise NotImplementedError

    @abstractmethod
    def create_organization(self, *, name: str, slug: str) -> Organization:
        """ينشئ جهة جديدة.

        Raises:
            DuplicateSlugError: إذا كان المعرّف النصي مستخدمًا.
        """
        raise NotImplementedError

    @abstractmethod
    def update_organization(
        self,
        *,
        organization_id: int,
        name: str | None = None,
        slug: str | None = None,
    ) -> Organization | None:
        """يحدّث الحقول الممرَّرة فقط، ويعيد None إن لم توجد الجهة.

        ``None`` تعني «لا تغيّر هذا الحقل»، وهي غير ملتبسة لأن الحقلين نصّان
        إلزاميان في المخطط ولا يصحّ إفراغهما.

        Raises:
            DuplicateSlugError: إذا كان المعرّف النصي الجديد مستخدمًا.
        """
        raise NotImplementedError

    @abstractmethod
    def list_users(self, *, organization_id: int) -> list[User]:
        """يعيد مستخدمي جهة واحدة مرتبين بالمعرّف."""
        raise NotImplementedError

    @abstractmethod
    def count_active_users(self, *, organization_id: int) -> int:
        """يعيد عدد المستخدمين **النشطين** في الجهة.

        هو المقاعد المستهلَكة من اشتراكها: لا يوجد جدول تراخيص منفصل
        في الـMVP. الحساب على النشطين وحدهم، فحساب معطَّل لا يشغل مقعدًا.
        """
        raise NotImplementedError

    @abstractmethod
    def find_user_by_email(self, *, organization_id: int, email: str) -> User | None:
        """يبحث عن مستخدم بالبريد **داخل جهة واحدة**، للتحقق من التفرّد."""
        raise NotImplementedError

    @abstractmethod
    def create_user(
        self,
        *,
        organization_id: int,
        email: str,
        full_name: str,
        role: str,
        password_hash: str,
    ) -> User:
        """ينشئ مستخدمًا داخل الجهة المحددة.

        Raises:
            DuplicateEmailError: إذا كان البريد مستخدمًا في **أي** جهة.
        """
        raise NotImplementedError

    @abstractmethod
    def update_user(
        self,
        *,
        user_id: int,
        organization_id: int,
        full_name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
    ) -> User | None:
        """يحدّث الحقول الممرَّرة فقط **داخل الجهة**.

        يعيد None إن لم يوجد المستخدم في هذه الجهة — لا يُفرَّق بين «غير موجود»
        و«موجود في جهة أخرى»، فكلاهما لا يعني شيئًا لصاحب الطلب.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# المخزن المحلي
# ---------------------------------------------------------------------------
#: الجهات التجريبية الثلاث، منسوخة من mock-data/organizations.json وهو
#: المرجع. لا تُقرأ من الملف مباشرة لأن صورة الـDocker تنسخ backend/app
#: فقط، فالتطابق يدوي ويجب أن يبقى حرفيًا.
#:
#: بيانات خيالية بالكامل على نطاق ‎.test‎ — لا أشخاص ولا جهات حقيقية.
#:
#: **لماذا ثلاث؟** جهتان باشتراك فعّال لإثبات عزل البيانات بينهما — ولا
#: يمكن إثباته بجهة لا يُسجَّل الدخول إليها — وجهة ثالثة باشتراك منتهٍ
#: لاختبار منع الاستخدام. حالات الاشتراك في organization_settings_store.
_SEED_ORGANIZATIONS: tuple[dict, ...] = (
    {
        "id": 1,
        "name": "هيئة الخدمات الرقمية",
        "slug": "digital-services",
        "is_active": True,
        "users": (
            ("admin@digital-services.test", "سارة العتيبي", "admin", True),
            ("n.alharbi@digital-services.test", "نورة الحربي", "employee", True),
            ("f.alqahtani@digital-services.test", "فيصل القحطاني", "employee", True),
        ),
    },
    {
        "id": 2,
        "name": "مركز التخطيط العمراني",
        "slug": "urban-planning",
        "is_active": True,
        "users": (
            ("admin@urban-planning.test", "ماجد الشمري", "admin", True),
            ("l.aldosari@urban-planning.test", "لمياء الدوسري", "employee", True),
            # معطّل عمدًا: يثبت أن الحساب المعطّل لا يستطيع تسجيل الدخول
            # ولا يشغل مقعدًا من تراخيص الجهة.
            ("s.alzahrani@urban-planning.test", "سلطان الزهراني", "employee", False),
        ),
    },
    {
        # اشتراكها منتهٍ عمدًا — انظر organization_settings_store.
        "id": 3,
        "name": "هيئة الأرشيف الوطني",
        "slug": "national-archive",
        "is_active": True,
        "users": (
            ("admin@national-archive.test", "عبدالله الغامدي", "admin", True),
            ("r.alanzi@national-archive.test", "ريم العنزي", "employee", True),
        ),
    },
)


#: تجزئة كلمة مرور الزرع، محفوظة لكل عملية ومفتاحها كلمة المرور نفسها.
#: bcrypt بطيئة عمدًا (~0.3 ثانية)، والزرع يتكرر بعد كل ``reset()`` في
#: الاختبارات. القيمة الناتجة واحدة في الحالتين، فالحفظ لا يغيّر شيئًا سوى
#: إسقاط مئات التجزئات المتطابقة. لا يُفرَّغ مع المخزن لأنه لا يحمل حالة.
_seed_hash_cache: dict[str, str] = {}


class MemoryUserStore(UserStore):
    """جهات ومستخدمون داخل ذاكرة العملية، للتطوير والاختبار فقط."""

    name = "memory"

    #: الحالة على مستوى الصنف حتى تشترك فيها كل النسخ داخل العملية.
    _organizations: dict[int, Organization] = {}
    _users: dict[int, StoredUser] = {}
    _next_organization_id: int = 1
    _next_user_id: int = 1
    _seeded: bool = False
    _lock = threading.Lock()

    def _ensure_seeded(self) -> None:
        """يزرع البيانات التجريبية عند أول استخدام فقط.

        الزرع كسول لا عند الاستيراد: تجزئة bcrypt بطيئة عمدًا، فلا داعي
        لدفع ثمنها في كل عملية لا تسجّل دخولًا أصلًا.
        """
        if MemoryUserStore._seeded:
            return

        from ..core.security import hash_password

        with MemoryUserStore._lock:
            if MemoryUserStore._seeded:
                return

            # تجزئة واحدة لكل المستخدمين: كلمة المرور نفسها، و bcrypt مكلفة.
            password = settings.dev_seed_password
            shared_hash = _seed_hash_cache.get(password)
            if shared_hash is None:
                shared_hash = hash_password(password)
                _seed_hash_cache[password] = shared_hash

            organizations: dict[int, Organization] = {}
            users: dict[int, StoredUser] = {}
            next_user_id = 1

            for entry in _SEED_ORGANIZATIONS:
                organizations[entry["id"]] = Organization(
                    id=entry["id"],
                    name=entry["name"],
                    slug=entry["slug"],
                    is_active=entry["is_active"],
                )
                for email, full_name, role, is_active in entry["users"]:
                    users[next_user_id] = StoredUser(
                        user=User(
                            id=next_user_id,
                            organization_id=entry["id"],
                            email=email,
                            full_name=full_name,
                            role=role,
                            is_active=is_active,
                        ),
                        password_hash=shared_hash,
                    )
                    next_user_id += 1

            MemoryUserStore._organizations = organizations
            MemoryUserStore._users = users
            MemoryUserStore._next_organization_id = max(organizations) + 1
            MemoryUserStore._next_user_id = next_user_id
            MemoryUserStore._seeded = True

    def find_login_candidates(self, *, email: str) -> list[StoredUser]:
        self._ensure_seeded()
        wanted = normalize_email(email)
        return [
            stored
            for stored in MemoryUserStore._users.values()
            if normalize_email(stored.user.email) == wanted
        ]

    def email_is_taken(self, email: str) -> bool:
        self._ensure_seeded()
        wanted = normalize_email(email)
        return any(
            normalize_email(stored.user.email) == wanted
            for stored in MemoryUserStore._users.values()
        )

    def get_user(self, *, user_id: int, organization_id: int) -> User | None:
        self._ensure_seeded()
        stored = MemoryUserStore._users.get(user_id)
        # شرط الجهة يُفحص هنا لا في المستدعي: العزل لا يُترك لانضباط النداء.
        if stored is None or stored.user.organization_id != organization_id:
            return None
        return stored.user

    def get_organization(self, organization_id: int) -> Organization | None:
        self._ensure_seeded()
        return MemoryUserStore._organizations.get(organization_id)

    def get_organization_by_slug(self, slug: str) -> Organization | None:
        self._ensure_seeded()
        wanted = slug.strip().lower()
        for organization in MemoryUserStore._organizations.values():
            if organization.slug == wanted:
                return organization
        return None

    def create_organization(self, *, name: str, slug: str) -> Organization:
        self._ensure_seeded()
        normalized = slug.strip().lower()

        with MemoryUserStore._lock:
            if any(
                organization.slug == normalized
                for organization in MemoryUserStore._organizations.values()
            ):
                raise DuplicateSlugError(
                    f"المعرّف النصي «{normalized}» مستخدم لجهة أخرى. اختر غيره."
                )

            organization = Organization(
                id=MemoryUserStore._next_organization_id,
                name=name.strip(),
                slug=normalized,
                is_active=True,
            )
            MemoryUserStore._organizations[organization.id] = organization
            MemoryUserStore._next_organization_id += 1
        return organization

    def update_organization(
        self,
        *,
        organization_id: int,
        name: str | None = None,
        slug: str | None = None,
    ) -> Organization | None:
        self._ensure_seeded()
        normalized = slug.strip().lower() if slug is not None else None

        with MemoryUserStore._lock:
            current = MemoryUserStore._organizations.get(organization_id)
            if current is None:
                return None

            if normalized is not None and any(
                other.slug == normalized and other.id != organization_id
                for other in MemoryUserStore._organizations.values()
            ):
                raise DuplicateSlugError(
                    f"المعرّف النصي «{normalized}» مستخدم لجهة أخرى. اختر غيره."
                )

            updated = Organization(
                id=current.id,
                name=current.name if name is None else name.strip(),
                slug=current.slug if normalized is None else normalized,
                is_active=current.is_active,
            )
            MemoryUserStore._organizations[organization_id] = updated
        return updated

    def list_users(self, *, organization_id: int) -> list[User]:
        self._ensure_seeded()
        return sorted(
            (
                stored.user
                for stored in MemoryUserStore._users.values()
                if stored.user.organization_id == organization_id
            ),
            key=lambda user: user.id,
        )

    def count_active_users(self, *, organization_id: int) -> int:
        self._ensure_seeded()
        return sum(
            1
            for stored in MemoryUserStore._users.values()
            if stored.user.organization_id == organization_id
            and stored.user.is_active
        )

    def find_user_by_email(self, *, organization_id: int, email: str) -> User | None:
        self._ensure_seeded()
        wanted = normalize_email(email)
        for stored in MemoryUserStore._users.values():
            if (
                stored.user.organization_id == organization_id
                and normalize_email(stored.user.email) == wanted
            ):
                return stored.user
        return None

    def create_user(
        self,
        *,
        organization_id: int,
        email: str,
        full_name: str,
        role: str,
        password_hash: str,
    ) -> User:
        self._ensure_seeded()
        normalized = normalize_email(email)

        with MemoryUserStore._lock:
            # الفحص عالمي لا داخل الجهة: يقابل فهرس uq_users_email_lower في
            # Oracle، ويمنع بريدًا لا يستطيع تسجيل الدخول به صاحبه بلا لبس.
            for stored in MemoryUserStore._users.values():
                if normalize_email(stored.user.email) == normalized:
                    raise DuplicateEmailError(
                        f"البريد «{normalized}» مسجّل بالفعل في النظام. "
                        "البريد فريد على مستوى النظام كله لأنه هوية الدخول."
                    )

            user = User(
                id=MemoryUserStore._next_user_id,
                organization_id=organization_id,
                email=normalized,
                full_name=full_name.strip(),
                role=role,
                is_active=True,
            )
            MemoryUserStore._users[user.id] = StoredUser(
                user=user, password_hash=password_hash
            )
            MemoryUserStore._next_user_id += 1
        return user

    def update_user(
        self,
        *,
        user_id: int,
        organization_id: int,
        full_name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
    ) -> User | None:
        self._ensure_seeded()

        with MemoryUserStore._lock:
            stored = MemoryUserStore._users.get(user_id)
            # شرط الجهة هنا لا في المستدعي: العزل لا يُترك لانضباط النداء.
            if stored is None or stored.user.organization_id != organization_id:
                return None

            current = stored.user
            updated = User(
                id=current.id,
                organization_id=current.organization_id,
                email=current.email,
                full_name=(
                    current.full_name if full_name is None else full_name.strip()
                ),
                role=current.role if role is None else role,
                is_active=current.is_active if is_active is None else is_active,
            )
            MemoryUserStore._users[user_id] = StoredUser(
                user=updated,
                password_hash=(
                    stored.password_hash if password_hash is None else password_hash
                ),
            )
        return updated

    @classmethod
    def reset(cls) -> None:
        """يفرغ المخزن ليُزرع من جديد. للاختبارات."""
        with cls._lock:
            cls._organizations = {}
            cls._users = {}
            cls._next_organization_id = 1
            cls._next_user_id = 1
            cls._seeded = False


# ---------------------------------------------------------------------------
# مخزن Oracle
# ---------------------------------------------------------------------------
class OracleUserStore(UserStore):
    """يقرأ الجهات والمستخدمين من جدولي organizations و users."""

    name = "oracle"

    def find_login_candidates(self, *, email: str) -> list[StoredUser]:
        from ..database.users import find_users_by_email

        return find_users_by_email(email=normalize_email(email))

    def email_is_taken(self, email: str) -> bool:
        from ..database.users import email_exists

        return email_exists(normalize_email(email))

    def get_user(self, *, user_id: int, organization_id: int) -> User | None:
        from ..database.users import fetch_user

        return fetch_user(user_id=user_id, organization_id=organization_id)

    def get_organization(self, organization_id: int) -> Organization | None:
        from ..database.users import fetch_organization

        return fetch_organization(organization_id)

    def get_organization_by_slug(self, slug: str) -> Organization | None:
        from ..database.users import fetch_organization_by_slug

        return fetch_organization_by_slug(slug.strip().lower())

    def create_organization(self, *, name: str, slug: str) -> Organization:
        from ..database.users import insert_organization

        return insert_organization(name=name.strip(), slug=slug.strip().lower())

    def update_organization(
        self,
        *,
        organization_id: int,
        name: str | None = None,
        slug: str | None = None,
    ) -> Organization | None:
        from ..database.users import update_organization_row

        return update_organization_row(
            organization_id=organization_id,
            name=name.strip() if name is not None else None,
            slug=slug.strip().lower() if slug is not None else None,
        )

    def list_users(self, *, organization_id: int) -> list[User]:
        from ..database.users import fetch_users

        return fetch_users(organization_id=organization_id)

    def count_active_users(self, *, organization_id: int) -> int:
        from ..database.users import count_active_users

        return count_active_users(organization_id=organization_id)

    def find_user_by_email(self, *, organization_id: int, email: str) -> User | None:
        from ..database.users import fetch_user_by_email

        return fetch_user_by_email(
            organization_id=organization_id, email=normalize_email(email)
        )

    def create_user(
        self,
        *,
        organization_id: int,
        email: str,
        full_name: str,
        role: str,
        password_hash: str,
    ) -> User:
        from ..database.users import insert_user

        return insert_user(
            organization_id=organization_id,
            email=normalize_email(email),
            full_name=full_name.strip(),
            role=role,
            password_hash=password_hash,
        )

    def update_user(
        self,
        *,
        user_id: int,
        organization_id: int,
        full_name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
    ) -> User | None:
        from ..database.users import update_user_row

        return update_user_row(
            user_id=user_id,
            organization_id=organization_id,
            full_name=full_name.strip() if full_name is not None else None,
            role=role,
            is_active=is_active,
            password_hash=password_hash,
        )


_STORES: dict[str, type[UserStore]] = {
    "memory": MemoryUserStore,
    "oracle": OracleUserStore,
}

#: يُستورد كسولًا: وحدة Supabase تقرأ إعداداتها وتفتح عميل HTTP عند الاستخدام
#: لا عند الاستيراد، فيبقى المشروع يقلع بلا Supabase أصلًا — كما يقلع بلا
#: Oracle. لهذا لا يظهر الصنف في ``_STORES`` مباشرة.
def _supabase_store() -> type[UserStore]:
    from .supabase_stores import SupabaseUserStore

    return SupabaseUserStore


#: القيم المقبولة لـDATA_STORE.
SUPPORTED_DATA_STORES: tuple[str, ...] = tuple(sorted({*_STORES, "supabase"}))



def get_user_store(name: str | None = None) -> UserStore:
    """يعيد مخزن المستخدمين المفعّل.

    Raises:
        UserStoreError: إذا كان الاسم غير مدعوم.
    """
    store_name = (name or settings.data_store or "memory").strip().lower()
    if store_name == "supabase":
        return _supabase_store()()
    store_class = _STORES.get(store_name)
    if store_class is None:
        supported = "، ".join(SUPPORTED_DATA_STORES)
        raise UserStoreError(
            f"DATA_STORE='{store_name}' غير مدعوم. القيم المدعومة: {supported}."
        )
    return store_class()
