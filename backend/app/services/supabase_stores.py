"""تنفيذ مخازن البيانات فوق Supabase — قيمة ``DATA_STORE=supabase``.

Oracle ومخزن الذاكرة **باقيان كما هما**؛ هذه إضافة ثالثة تُختار بمتغير
البيئة نفسه. كل صنف هنا يحقّق الواجهة المجرّدة نفسها التي يحقّقها نظيره
في Oracle، فلا يعلم أي مستدعٍ بأيّها يعمل.

--------------------------------------------------------------------------
جسر المعرّفات: ``app_user_id`` العددي ← ``profiles.id`` الـ``uuid``
--------------------------------------------------------------------------
واجهات المخازن في هذا المشروع تتعامل مع ``user_id: int``، بينما جداول
Supabase تربط المستخدم بـ``uuid`` لأنه معرّف ``auth.users`` ولا خيار فيه.
عمود ``profiles.app_user_id`` هو الجسر، و :func:`_uuid_for` تترجم بينهما مع
ذاكرة تخزين مؤقت: الربط ثابت مدى حياة الصف (كلا العمودين مفتاح لا يتغيّر)،
فقراءته مرة واحدة لكل مستخدم تكفي.

--------------------------------------------------------------------------
⚠️ المصادقة **ليست** من هذه المخازن
--------------------------------------------------------------------------
مخطط Supabase **لا يحتوي عمود كلمة مرور**: المصادقة كلها في ``auth.users``
كما يقتضي التصميم. لذلك ترفع :class:`SupabaseUserStore` خطأً واضحًا في
مسار تسجيل الدخول القديم بدل أن تعيد تجزئة فارغة يقارنها النظام بصمت.
مسار الدخول في وضع Supabase هو ``POST /api/account/login`` — انظر
`services/supabase_auth.py`.

**العزل يُفرض هنا كذلك لا في القاعدة وحدها:** كل استعلام أدناه مقيّد
بـ``organization_id`` أو ``user_id``، تمامًا كما في مخزن Oracle. سياسات RLS
خط دفاع ثانٍ، لا بديل عن تقييد الاستعلام.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from ..database import supabase
from ..database.supabase import (
    UNIQUE_VIOLATION,
    SupabaseConstraintError,
    SupabaseError,
)
from .audit_store import AuditEvent, AuditStore, AuditStoreError
from .conversation_store import (
    Conversation,
    ConversationStore,
    ConversationStoreError,
    Message,
    Page,
)
from .file_store import FileRecord, FileStore, FileStoreError
from .organization_settings_store import (
    ModelSettings,
    OrganizationSettingsStore,
    Subscription,
)
from .user_store import (
    DuplicateEmailError,
    DuplicateSlugError,
    Organization,
    StoredUser,
    User,
    UserStore,
    UserStoreError,
    normalize_email,
)

#: رسالة واحدة لكل مسار يحتاج كلمة مرور — لا وجود لها في مخطط Supabase.
_AUTH_MOVED = (
    "في وضع DATA_STORE=supabase تتم المصادقة عبر Supabase Auth ولا يوجد "
    "في القاعدة جدول كلمات مرور. استخدم مسار /api/account/login."
)


def _parse_moment(value: Any) -> datetime:
    """يحوّل طابع PostgREST الزمني إلى ``datetime`` واعٍ بـUTC."""
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value or "").strip()
        if not text:
            return datetime.now(UTC)
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(UTC)
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# جسر المعرّفات
# ---------------------------------------------------------------------------
_uuid_cache: dict[int, str] = {}
_app_id_cache: dict[str, int] = {}
_cache_lock = threading.Lock()


def clear_id_cache() -> None:
    """يفرّغ ذاكرة ترجمة المعرّفات — للاختبارات ولإعادة التهيئة."""
    with _cache_lock:
        _uuid_cache.clear()
        _app_id_cache.clear()


def _uuid_for(app_user_id: int) -> str:
    """يترجم المعرّف العددي إلى ``uuid`` المستخدم في Supabase.

    Raises:
        UserStoreError: إذا لم يوجد ملف بهذا المعرّف.
    """
    cached = _uuid_cache.get(app_user_id)
    if cached is not None:
        return cached

    row = supabase.select_one(
        "profiles", columns="id,app_user_id", filters={"app_user_id": f"eq.{app_user_id}"}
    )
    if row is None:
        raise UserStoreError("المستخدم المطلوب غير موجود في قاعدة Supabase.")

    value = str(row["id"])
    with _cache_lock:
        _uuid_cache[app_user_id] = value
        _app_id_cache[value] = app_user_id
    return value


def _remember(row: dict[str, Any]) -> None:
    """يخزّن ربط المعرّفين من صف ``profiles`` قُرئ لسبب آخر."""
    try:
        app_id = int(row["app_user_id"])
        value = str(row["id"])
    except (KeyError, TypeError, ValueError):
        return
    with _cache_lock:
        _uuid_cache[app_id] = value
        _app_id_cache[value] = app_id


# ---------------------------------------------------------------------------
# الجهات والمستخدمون
# ---------------------------------------------------------------------------
_PROFILE_COLUMNS = (
    "id,app_user_id,organization_id,email,full_name,role,is_active"
)
_ORG_COLUMNS = "id,name,slug,is_active"


def _to_organization(row: dict[str, Any]) -> Organization:
    return Organization(
        id=int(row["id"]),
        name=str(row["name"]),
        slug=str(row["slug"]),
        is_active=bool(row.get("is_active", True)),
    )


def _to_user(row: dict[str, Any]) -> User:
    _remember(row)
    return User(
        id=int(row["app_user_id"]),
        organization_id=int(row["organization_id"]),
        email=str(row["email"]),
        full_name=str(row["full_name"]),
        role=str(row.get("role") or "employee"),
        is_active=bool(row.get("is_active", True)),
    )


class SupabaseUserStore(UserStore):
    """الجهات والمستخدمون في جدولي ``organizations`` و ``profiles``."""

    name = "supabase"

    # -- المصادقة: غير مدعومة هنا عمدًا --------------------------------
    def find_login_candidates(self, *, email: str) -> list[StoredUser]:
        """**ترفع دائمًا.** لا تجزئة كلمة مرور في مخطط Supabase.

        الرفض الصريح أفضل من قائمة فارغة: الفارغة تظهر للمستخدم كـ«بيانات
        دخول خاطئة» فيظل يجرّب كلمة مروره الصحيحة بلا أن يعرف أن المسار
        نفسه هو الخطأ.
        """
        raise UserStoreError(_AUTH_MOVED)

    def create_user(
        self,
        *,
        organization_id: int,
        email: str,
        full_name: str,
        role: str,
        password_hash: str,
    ) -> User:
        """**ترفع دائمًا.** إنشاء الحساب يتم في ``auth.users`` أولًا.

        الملف في ``profiles`` يُنشأ بعده مرتبطًا بمعرّفه، وهي عملية تجهيز
        يقوم بها من ينشر النظام لا مسار داخل التطبيق.
        """
        raise UserStoreError(
            "إنشاء المستخدمين في وضع Supabase يتم من لوحة Supabase "
            "(Authentication) ثم ربط الحساب بجهته في جدول profiles. "
            + _AUTH_MOVED
        )

    # -- القراءة والتعديل ------------------------------------------------
    def email_is_taken(self, email: str) -> bool:
        return (
            supabase.select_one(
                "profiles",
                columns="id",
                filters={"email": f"eq.{normalize_email(email)}"},
            )
            is not None
        )

    def get_user(self, *, user_id: int, organization_id: int) -> User | None:
        row = supabase.select_one(
            "profiles",
            columns=_PROFILE_COLUMNS,
            # شرط الجهة في الاستعلام نفسه: العزل لا يُترك لانضباط المستدعي.
            filters={
                "app_user_id": f"eq.{user_id}",
                "organization_id": f"eq.{organization_id}",
            },
        )
        return _to_user(row) if row else None

    def get_organization(self, organization_id: int) -> Organization | None:
        row = supabase.select_one(
            "organizations",
            columns=_ORG_COLUMNS,
            filters={"id": f"eq.{organization_id}"},
        )
        return _to_organization(row) if row else None

    def get_organization_by_slug(self, slug: str) -> Organization | None:
        row = supabase.select_one(
            "organizations",
            columns=_ORG_COLUMNS,
            filters={"slug": f"eq.{slug.strip().lower()}"},
        )
        return _to_organization(row) if row else None

    def create_organization(self, *, name: str, slug: str) -> Organization:
        try:
            row = supabase.insert(
                "organizations", {"name": name.strip(), "slug": slug.strip().lower()}
            )
        except SupabaseConstraintError as exc:
            if exc.code == UNIQUE_VIOLATION:
                raise DuplicateSlugError(
                    f"المعرّف النصي «{slug.strip().lower()}» مستخدم لجهة أخرى. "
                    "اختر غيره."
                ) from exc
            raise
        return _to_organization(row)

    def update_organization(
        self,
        *,
        organization_id: int,
        name: str | None = None,
        slug: str | None = None,
    ) -> Organization | None:
        values: dict[str, Any] = {"updated_at": _now_iso()}
        if name is not None:
            values["name"] = name.strip()
        if slug is not None:
            values["slug"] = slug.strip().lower()

        try:
            rows = supabase.update(
                "organizations", values, filters={"id": f"eq.{organization_id}"}
            )
        except SupabaseConstraintError as exc:
            if exc.code == UNIQUE_VIOLATION:
                raise DuplicateSlugError(
                    "المعرّف النصي الجديد مستخدم لجهة أخرى. اختر غيره."
                ) from exc
            raise
        return _to_organization(rows[0]) if rows else None

    def list_users(self, *, organization_id: int) -> list[User]:
        rows = supabase.select(
            "profiles",
            columns=_PROFILE_COLUMNS,
            filters={"organization_id": f"eq.{organization_id}"},
            order="app_user_id.asc",
        )
        return [_to_user(row) for row in rows]

    def count_active_users(self, *, organization_id: int) -> int:
        return supabase.count(
            "profiles",
            filters={
                "organization_id": f"eq.{organization_id}",
                "is_active": "is.true",
            },
        )

    def find_user_by_email(
        self, *, organization_id: int, email: str
    ) -> User | None:
        row = supabase.select_one(
            "profiles",
            columns=_PROFILE_COLUMNS,
            filters={
                "organization_id": f"eq.{organization_id}",
                "email": f"eq.{normalize_email(email)}",
            },
        )
        return _to_user(row) if row else None

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
        if password_hash is not None:
            raise UserStoreError(
                "تغيير كلمة المرور في وضع Supabase يتم عبر Supabase Auth. "
                + _AUTH_MOVED
            )

        values: dict[str, Any] = {"updated_at": _now_iso()}
        if full_name is not None:
            values["full_name"] = full_name.strip()
        if role is not None:
            values["role"] = role
        if is_active is not None:
            values["is_active"] = is_active

        try:
            rows = supabase.update(
                "profiles",
                values,
                filters={
                    "app_user_id": f"eq.{user_id}",
                    "organization_id": f"eq.{organization_id}",
                },
            )
        except SupabaseConstraintError as exc:
            if exc.code == UNIQUE_VIOLATION:
                raise DuplicateEmailError(
                    "البريد الإلكتروني مستخدم في النظام."
                ) from exc
            raise
        return _to_user(rows[0]) if rows else None


# ---------------------------------------------------------------------------
# الاشتراك وإعدادات المودل
# ---------------------------------------------------------------------------
class SupabaseOrganizationSettingsStore(OrganizationSettingsStore):
    """اشتراك الجهة في جدول ``subscriptions``.

    **إعدادات المودل ليست في مخطط Supabase**: اختيار المزود صار إعداد
    تشغيل على جهاز العميل لا صفًّا في قاعدة مركزية، بعد أن صار المودل يعمل
    محليًا. الدالتان تعيدان ``None`` وترفعان خطأً واضحًا عند محاولة الكتابة
    بدل أن تكتبا في جدول غير موجود.
    """

    name = "supabase"

    _SUBSCRIPTION_COLUMNS = "organization_id,status,seats,starts_at,expires_at"

    def get_subscription(self, organization_id: int) -> Subscription | None:
        row = supabase.select_one(
            "subscriptions",
            columns=self._SUBSCRIPTION_COLUMNS,
            filters={"organization_id": f"eq.{organization_id}"},
        )
        if row is None:
            return None
        return Subscription(
            organization_id=int(row["organization_id"]),
            status=str(row["status"]),
            seats=int(row["seats"]),
            starts_at=_parse_moment(row["starts_at"]),
            expires_at=_parse_moment(row["expires_at"]),
        )

    def upsert_subscription(
        self,
        *,
        organization_id: int,
        status: str,
        seats: int,
        starts_at: datetime,
        expires_at: datetime,
    ) -> Subscription:
        values = {
            "status": status,
            "seats": seats,
            "starts_at": starts_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "updated_at": _now_iso(),
        }
        rows = supabase.update(
            "subscriptions",
            values,
            filters={"organization_id": f"eq.{organization_id}"},
        )
        if not rows:
            rows = [
                supabase.insert(
                    "subscriptions", {"organization_id": organization_id, **values}
                )
            ]
        row = rows[0]
        return Subscription(
            organization_id=int(row["organization_id"]),
            status=str(row["status"]),
            seats=int(row["seats"]),
            starts_at=_parse_moment(row["starts_at"]),
            expires_at=_parse_moment(row["expires_at"]),
        )

    def get_model_settings(self, organization_id: int) -> ModelSettings | None:
        return None

    def set_model_settings(
        self, *, organization_id: int, provider: str
    ) -> ModelSettings:
        raise SupabaseError(
            "اختيار مزود المودل لا يُحفظ في Supabase: المودل يعمل على جهاز "
            "العميل، ويُضبط من متغير MODEL_PROVIDER على ذلك الجهاز."
        )


# ---------------------------------------------------------------------------
# سجل التدقيق
# ---------------------------------------------------------------------------
class SupabaseAuditStore(AuditStore):
    """سجل التدقيق في جدول ``audit_logs``. **إضافة فقط.**"""

    name = "supabase"

    _COLUMNS = "id,organization_id,user_id,action,metadata,created_at"

    def _to_event(self, row: dict[str, Any]) -> AuditEvent:
        metadata = row.get("metadata") or {}
        details = metadata.get("details") if isinstance(metadata, dict) else None
        raw_user = row.get("user_id")
        return AuditEvent(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            # الجدول يخزّن uuid؛ الواجهة تتعامل بالمعرّف العددي.
            user_id=_app_id_cache.get(str(raw_user)) if raw_user else None,
            action=str(row["action"]),
            details=str(details) if details else None,
            created_at=_parse_moment(row["created_at"]),
        )

    def append(
        self,
        *,
        organization_id: int,
        user_id: int | None,
        action: str,
        details: str | None = None,
    ) -> AuditEvent:
        row_values: dict[str, Any] = {
            "organization_id": organization_id,
            "action": action.strip(),
            "metadata": {"details": details} if details else {},
        }
        if user_id is not None:
            row_values["user_id"] = _uuid_for(user_id)

        try:
            row = supabase.insert("audit_logs", row_values)
        except SupabaseError as exc:
            raise AuditStoreError(str(exc)) from exc
        return self._to_event(row)

    def list_events(
        self,
        *,
        organization_id: int,
        action: str | None = None,
        user_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page:
        filters = {"organization_id": f"eq.{organization_id}"}
        if action:
            filters["action"] = f"eq.{action}"
        if user_id is not None:
            filters["user_id"] = f"eq.{_uuid_for(user_id)}"

        total = supabase.count("audit_logs", filters=filters)
        rows = supabase.select(
            "audit_logs",
            columns=self._COLUMNS,
            filters=filters,
            order="created_at.desc",
            limit=limit,
            offset=offset,
        )
        return Page(
            items=[self._to_event(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )


# ---------------------------------------------------------------------------
# المحادثات والرسائل
# ---------------------------------------------------------------------------
class SupabaseConversationStore(ConversationStore):
    """المحادثات والرسائل في جدولي ``conversations`` و ``messages``."""

    name = "supabase"

    _CONVERSATION_COLUMNS = (
        "id,organization_id,user_id,title,created_at,updated_at"
    )
    _MESSAGE_COLUMNS = "id,conversation_id,organization_id,role,content,created_at"

    def _to_conversation(
        self, row: dict[str, Any], *, app_user_id: int
    ) -> Conversation:
        conversation_id = int(row["id"])
        return Conversation(
            id=conversation_id,
            organization_id=int(row["organization_id"]),
            user_id=app_user_id,
            title=str(row["title"]),
            created_at=_parse_moment(row["created_at"]),
            updated_at=_parse_moment(row["updated_at"]),
            message_count=supabase.count(
                "messages", filters={"conversation_id": f"eq.{conversation_id}"}
            ),
        )

    def _to_message(self, row: dict[str, Any]) -> Message:
        return Message(
            id=int(row["id"]),
            conversation_id=int(row["conversation_id"]),
            organization_id=int(row["organization_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            created_at=_parse_moment(row["created_at"]),
        )

    def create_conversation(
        self, *, organization_id: int, user_id: int, title: str
    ) -> Conversation:
        row = supabase.insert(
            "conversations",
            {
                "organization_id": organization_id,
                "user_id": _uuid_for(user_id),
                "title": title.strip() or "محادثة جديدة",
            },
        )
        return self._to_conversation(row, app_user_id=user_id)

    def get_conversation(
        self, *, conversation_id: int, organization_id: int, user_id: int
    ) -> Conversation | None:
        row = supabase.select_one(
            "conversations",
            columns=self._CONVERSATION_COLUMNS,
            # الملكية والجهة شرطان في الاستعلام: «غير موجودة» و«يملكها غيرك»
            # نتيجتهما واحدة، ولا يُفرَّق بينهما لصاحب الطلب.
            filters={
                "id": f"eq.{conversation_id}",
                "organization_id": f"eq.{organization_id}",
                "user_id": f"eq.{_uuid_for(user_id)}",
            },
        )
        return self._to_conversation(row, app_user_id=user_id) if row else None

    def list_conversations(
        self, *, organization_id: int, user_id: int, limit: int, offset: int
    ) -> Page:
        filters = {
            "organization_id": f"eq.{organization_id}",
            "user_id": f"eq.{_uuid_for(user_id)}",
        }
        total = supabase.count("conversations", filters=filters)
        rows = supabase.select(
            "conversations",
            columns=self._CONVERSATION_COLUMNS,
            filters=filters,
            order="updated_at.desc",
            limit=limit,
            offset=offset,
        )
        return Page(
            items=[
                self._to_conversation(row, app_user_id=user_id) for row in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    def rename_conversation(
        self,
        *,
        conversation_id: int,
        organization_id: int,
        user_id: int,
        title: str,
    ) -> Conversation | None:
        rows = supabase.update(
            "conversations",
            {"title": title.strip(), "updated_at": _now_iso()},
            filters={
                "id": f"eq.{conversation_id}",
                "organization_id": f"eq.{organization_id}",
                "user_id": f"eq.{_uuid_for(user_id)}",
            },
        )
        return (
            self._to_conversation(rows[0], app_user_id=user_id) if rows else None
        )

    def delete_conversation(
        self, *, conversation_id: int, organization_id: int, user_id: int
    ) -> bool:
        # الرسائل تُحذف بـon delete cascade في المخطط، فلا حذف يدوي لها.
        rows = supabase.delete(
            "conversations",
            filters={
                "id": f"eq.{conversation_id}",
                "organization_id": f"eq.{organization_id}",
                "user_id": f"eq.{_uuid_for(user_id)}",
            },
        )
        return bool(rows)

    def add_messages(
        self,
        *,
        conversation_id: int,
        organization_id: int,
        entries: Sequence[tuple[str, str]],
    ) -> list[Message]:
        if not entries:
            return []

        owner = supabase.select_one(
            "conversations",
            columns="id,user_id",
            filters={
                "id": f"eq.{conversation_id}",
                "organization_id": f"eq.{organization_id}",
            },
        )
        if owner is None:
            raise ConversationStoreError("المحادثة المطلوبة غير موجودة.")

        saved: list[Message] = []
        for role, content in entries:
            row = supabase.insert(
                "messages",
                {
                    "conversation_id": conversation_id,
                    "organization_id": organization_id,
                    "user_id": owner["user_id"],
                    "role": role,
                    "content": content,
                },
            )
            saved.append(self._to_message(row))

        supabase.update(
            "conversations",
            {"updated_at": _now_iso()},
            filters={"id": f"eq.{conversation_id}"},
        )
        return saved

    def list_messages(
        self, *, conversation_id: int, organization_id: int, limit: int, offset: int
    ) -> Page:
        filters = {
            "conversation_id": f"eq.{conversation_id}",
            "organization_id": f"eq.{organization_id}",
        }
        total = supabase.count("messages", filters=filters)
        rows = supabase.select(
            "messages",
            columns=self._MESSAGE_COLUMNS,
            filters=filters,
            order="created_at.asc,id.asc",
            limit=limit,
            offset=offset,
        )
        return Page(
            items=[self._to_message(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def recent_messages(
        self, *, conversation_id: int, organization_id: int, limit: int
    ) -> list[Message]:
        # تُقرأ تنازليًا لأخذ الأحدث، ثم تُقلب لتعود بالترتيب الزمني الصاعد
        # كما يتوقّعها بناء السياق.
        rows = supabase.select(
            "messages",
            columns=self._MESSAGE_COLUMNS,
            filters={
                "conversation_id": f"eq.{conversation_id}",
                "organization_id": f"eq.{organization_id}",
            },
            order="created_at.desc,id.desc",
            limit=limit,
        )
        return [self._to_message(row) for row in reversed(rows)]


# ---------------------------------------------------------------------------
# الملفات
# ---------------------------------------------------------------------------
class SupabaseFileStore(FileStore):
    """البيانات الوصفية للملفات في جدول ``files``."""

    name = "supabase"

    _COLUMNS = (
        "id,organization_id,user_id,conversation_id,filename,storage_path,"
        "content_type,size_bytes,status,created_at"
    )

    def _to_record(self, row: dict[str, Any]) -> FileRecord:
        raw_user = str(row.get("user_id") or "")
        return FileRecord(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            user_id=_app_id_cache.get(raw_user, 0),
            conversation_id=(
                int(row["conversation_id"])
                if row.get("conversation_id") is not None
                else None
            ),
            original_name=str(row["filename"]),
            storage_path=str(row["storage_path"]),
            mime_type=str(row["content_type"]),
            size_bytes=int(row["size_bytes"]),
            status=str(row["status"]),
            created_at=_parse_moment(row["created_at"]),
        )

    def create_file(
        self,
        *,
        organization_id: int,
        user_id: int,
        conversation_id: int | None,
        original_name: str,
        storage_path: str,
        mime_type: str,
        size_bytes: int,
    ) -> FileRecord:
        try:
            row = supabase.insert(
                "files",
                {
                    "organization_id": organization_id,
                    "user_id": _uuid_for(user_id),
                    "conversation_id": conversation_id,
                    "filename": original_name,
                    "storage_path": storage_path,
                    "content_type": mime_type,
                    "size_bytes": size_bytes,
                    "status": "uploaded",
                },
            )
        except SupabaseError as exc:
            raise FileStoreError(str(exc)) from exc
        # المعرّف العددي معروف للمستدعي وإن لم يكن في ذاكرة الترجمة بعد.
        return replace(self._to_record(row), user_id=user_id)

    def get_file(self, *, file_id: int, organization_id: int) -> FileRecord | None:
        row = supabase.select_one(
            "files",
            columns=self._COLUMNS,
            filters={
                "id": f"eq.{file_id}",
                "organization_id": f"eq.{organization_id}",
            },
        )
        return self._to_record(row) if row else None

    def list_files(
        self,
        *,
        organization_id: int,
        uploaded_by: int | None = None,
        conversation_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page:
        filters = {"organization_id": f"eq.{organization_id}"}
        if uploaded_by is not None:
            filters["user_id"] = f"eq.{_uuid_for(uploaded_by)}"
        if conversation_id is not None:
            filters["conversation_id"] = f"eq.{conversation_id}"

        total = supabase.count("files", filters=filters)
        rows = supabase.select(
            "files",
            columns=self._COLUMNS,
            filters=filters,
            order="created_at.desc,id.desc",
            limit=limit,
            offset=offset,
        )
        return Page(
            items=[self._to_record(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def set_status(
        self, *, file_id: int, organization_id: int, status: str
    ) -> FileRecord | None:
        rows = supabase.update(
            "files",
            {"status": status, "updated_at": _now_iso()},
            filters={
                "id": f"eq.{file_id}",
                "organization_id": f"eq.{organization_id}",
            },
        )
        return self._to_record(rows[0]) if rows else None

    def delete_file(self, *, file_id: int, organization_id: int) -> bool:
        rows = supabase.delete(
            "files",
            filters={
                "id": f"eq.{file_id}",
                "organization_id": f"eq.{organization_id}",
            },
        )
        return bool(rows)
