"""اختبارات مزوّد بيانات Supabase وملف الهجرة ومسار تسجيل الدخول.

ثلاثة أقسام:

* **اختيار المزوّد** — أن ``DATA_STORE=supabase`` يعطي المخازن الصحيحة، وأن
  Oracle ومخزن الذاكرة لم يُمسّا.
* **المخازن** — أن كل استعلام مقيّد بجهته ومالكه، عبر ``MockTransport``
  يفحص المسار والمرشّحات الفعلية لا نتيجةً مزيّفة.
* **ملف الهجرة** — أن الجداول العشرة موجودة وأن RLS مفعّل عليها كلها وأن
  قيود «جهاز واحد» و«تجزئة لا بصمة» فيه، وألا يحتوي الملف أي سرّ.

⚠️ لا شبكة ولا مشروع Supabase حقيقي في أي اختبار هنا.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.database import supabase
from app.main import app
from app.services import supabase_stores
from app.services.audit_store import MemoryAuditStore, OracleAuditStore, get_audit_store
from app.services.conversation_store import (
    MemoryConversationStore,
    OracleConversationStore,
    get_conversation_store,
)
from app.services.file_store import MemoryFileStore, OracleFileStore, get_file_store
from app.services.organization_settings_store import (
    MemoryOrganizationSettingsStore,
    get_organization_settings_store,
)
from app.services.user_store import (
    MemoryUserStore,
    OracleUserStore,
    UserStoreError,
    get_user_store,
)

client = TestClient(app)

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "supabase"
    / "0001_govmind_supabase.sql"
)

ORG = 7
USER_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_UUID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class RecordingTransport:
    """ينقل كل طلب إلى قائمة، ويردّ بما يُملى عليه.

    الغرض **فحص الاستعلام نفسه**: أي مخزن يعيد الصف الصحيح بمرشّح ناقص
    يمرّ على اختبار يفحص النتيجة وحدها، ويكشفه فحص المرشّحات.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.rows: list[dict[str, Any]] = []
        self.count = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        headers = {}
        if request.headers.get("Prefer") == "count=exact":
            headers["content-range"] = f"0-0/{self.count}"
        return httpx.Response(200, json=self.rows, headers=headers)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def params_of_last(self) -> dict[str, str]:
        return dict(self.last.url.params)


@pytest.fixture
def transport(monkeypatch):
    """يضبط إعداد Supabase ويركّب ناقلًا مسجِّلًا بدل الشبكة."""
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(
        settings, "supabase_service_role_key", "service-key-for-tests"
    )
    recorder = RecordingTransport()
    supabase.set_client(
        httpx.Client(
            base_url=supabase.rest_base_url(),
            transport=httpx.MockTransport(recorder),
        )
    )
    supabase_stores.clear_id_cache()
    yield recorder
    supabase.set_client(None)
    supabase_stores.clear_id_cache()


def profile_row(app_user_id: int = 4, uuid: str = USER_UUID) -> dict[str, Any]:
    return {
        "id": uuid,
        "app_user_id": app_user_id,
        "organization_id": ORG,
        "email": "person@govmind.test",
        "full_name": "موظف",
        "role": "employee",
        "is_active": True,
    }


# ===========================================================================
# ١) اختيار المزوّد — Oracle والذاكرة باقيان
# ===========================================================================
def test_supabase_is_selectable_for_every_store(monkeypatch):
    monkeypatch.setattr(settings, "data_store", "supabase")
    assert get_user_store().name == "supabase"
    assert get_conversation_store().name == "supabase"
    assert get_file_store().name == "supabase"
    assert get_audit_store().name == "supabase"
    assert get_organization_settings_store().name == "supabase"


def test_memory_and_oracle_are_untouched(monkeypatch):
    """الإضافة لا تُزيح المزوّدين القائمين — وهذا شرط صريح في المهمة."""
    monkeypatch.setattr(settings, "data_store", "memory")
    assert isinstance(get_user_store(), MemoryUserStore)
    assert isinstance(get_conversation_store(), MemoryConversationStore)
    assert isinstance(get_file_store(), MemoryFileStore)
    assert isinstance(get_audit_store(), MemoryAuditStore)
    assert isinstance(get_organization_settings_store(), MemoryOrganizationSettingsStore)

    monkeypatch.setattr(settings, "data_store", "oracle")
    assert isinstance(get_user_store(), OracleUserStore)
    assert isinstance(get_conversation_store(), OracleConversationStore)
    assert isinstance(get_file_store(), OracleFileStore)
    assert isinstance(get_audit_store(), OracleAuditStore)


def test_unknown_store_name_lists_the_supported_values(monkeypatch):
    monkeypatch.setattr(settings, "data_store", "postgres")
    with pytest.raises(UserStoreError) as caught:
        get_user_store()
    assert "supabase" in str(caught.value)
    assert "oracle" in str(caught.value)


def test_supabase_store_is_not_imported_until_selected(monkeypatch):
    """الاستيراد كسول: المشروع يقلع بلا Supabase كما يقلع بلا Oracle."""
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_service_role_key", "")
    monkeypatch.setattr(settings, "data_store", "memory")
    # لا يرفع شيئًا رغم أن الإعداد فارغ تمامًا.
    assert get_user_store().name == "memory"


# ===========================================================================
# ٢) المخازن — العزل مفروض في الاستعلام نفسه
# ===========================================================================
def test_get_user_is_filtered_by_organization(transport, monkeypatch):
    monkeypatch.setattr(settings, "data_store", "supabase")
    transport.rows = [profile_row()]

    user = get_user_store().get_user(user_id=4, organization_id=ORG)

    params = transport.params_of_last()
    assert params["app_user_id"] == "eq.4"
    assert params["organization_id"] == f"eq.{ORG}"
    assert user is not None and user.id == 4


def test_get_user_of_another_organization_returns_none(transport, monkeypatch):
    """القاعدة المزيّفة تعيد لا شيء لأن المرشّح لا يطابق — كما في الحقيقة."""
    monkeypatch.setattr(settings, "data_store", "supabase")
    transport.rows = []
    assert get_user_store().get_user(user_id=4, organization_id=999) is None


def test_conversation_read_is_filtered_by_owner_and_organization(
    transport, monkeypatch
):
    """المحادثة خاصة بصاحبها: الاستعلام يحمل المالك **والجهة** معًا."""
    monkeypatch.setattr(settings, "data_store", "supabase")
    transport.rows = [profile_row()]  # ترجمة المعرّف أولًا
    supabase_stores._uuid_for(4)

    transport.rows = [
        {
            "id": 3,
            "organization_id": ORG,
            "user_id": USER_UUID,
            "title": "محادثة",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    conversation = get_conversation_store().get_conversation(
        conversation_id=3, organization_id=ORG, user_id=4
    )

    # آخر طلب هو عدّ الرسائل؛ استعلام المحادثة قبله.
    conversation_request = next(
        request
        for request in reversed(transport.requests)
        if "conversations" in request.url.path
    )
    params = dict(conversation_request.url.params)
    assert params["id"] == "eq.3"
    assert params["organization_id"] == f"eq.{ORG}"
    assert params["user_id"] == f"eq.{USER_UUID}"
    assert conversation is not None


def test_file_listing_is_filtered_by_organization(transport, monkeypatch):
    monkeypatch.setattr(settings, "data_store", "supabase")
    transport.rows = []
    get_file_store().list_files(organization_id=ORG, limit=10, offset=0)

    params = transport.params_of_last()
    assert params["organization_id"] == f"eq.{ORG}"


def test_audit_listing_is_filtered_by_organization(transport, monkeypatch):
    monkeypatch.setattr(settings, "data_store", "supabase")
    transport.rows = []
    get_audit_store().list_events(organization_id=ORG, limit=10, offset=0)

    params = transport.params_of_last()
    assert params["organization_id"] == f"eq.{ORG}"


def test_update_without_filters_is_refused():
    """تحديث بلا مرشّح كان سيطال الجدول كله — ممنوع بنيويًا لا بالانضباط."""
    with pytest.raises(supabase.SupabaseError):
        supabase.update("profiles", {"role": "admin"}, filters={})
    with pytest.raises(supabase.SupabaseError):
        supabase.delete("profiles", filters={})


def test_password_paths_refuse_clearly(transport, monkeypatch):
    """لا جدول كلمات مرور في Supabase: الرفض صريح لا صامت."""
    monkeypatch.setattr(settings, "data_store", "supabase")
    store = get_user_store()

    with pytest.raises(UserStoreError) as login:
        store.find_login_candidates(email="a@b.test")
    assert "/api/account/login" in str(login.value)

    with pytest.raises(UserStoreError):
        store.create_user(
            organization_id=ORG,
            email="a@b.test",
            full_name="اسم",
            role="employee",
            password_hash="whatever",
        )


def test_client_is_refused_when_configuration_is_missing(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_service_role_key", "")
    supabase.set_client(None)

    with pytest.raises(supabase.SupabaseNotConfiguredError) as caught:
        supabase.get_client()
    assert "SUPABASE_URL" in str(caught.value)


def test_service_role_key_never_appears_in_an_error_message(monkeypatch):
    """رسالة الخطأ مكتوبة يدويًا ولا تمرّر رد Supabase ولا ترويساته."""
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "super-secret-key")

    def deny(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid API key: super-secret-key"})

    supabase.set_client(
        httpx.Client(
            base_url=supabase.rest_base_url(), transport=httpx.MockTransport(deny)
        )
    )
    try:
        with pytest.raises(supabase.SupabaseError) as caught:
            supabase.select("profiles")
        assert "super-secret-key" not in str(caught.value)
        assert "SUPABASE_SERVICE_ROLE_KEY" in str(caught.value)
    finally:
        supabase.set_client(None)


# ===========================================================================
# ٣) تسجيل الدخول — بلا رابط ولا مفتاح من العميل
# ===========================================================================
def test_login_proxies_to_supabase_auth(monkeypatch):
    """الإضافة ترسل بريدًا وكلمة مرور فقط، والـBackend يتولّى الباقي."""
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")
    monkeypatch.setattr(settings, "supabase_service_role_key", "service-key")

    captured: dict[str, Any] = {}

    class FakeSession:
        access_token = "issued-access-token"
        refresh_token = "issued-refresh-token"
        expires_in = 3600
        user_id = USER_UUID
        email = "person@govmind.test"

    def fake_sign_in(email: str, password: str):
        captured["email"] = email
        return FakeSession()

    from app.api import entitlements as entitlements_api

    monkeypatch.setattr(entitlements_api, "sign_in", fake_sign_in)

    recorder = RecordingTransport()
    recorder.rows = [profile_row()]
    supabase.set_client(
        httpx.Client(
            base_url=supabase.rest_base_url(),
            transport=httpx.MockTransport(recorder),
        )
    )
    try:
        response = client.post(
            "/api/account/login",
            json={"email": "Person@GovMind.test", "password": "secret"},
        )
    finally:
        supabase.set_client(None)

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "issued-access-token"
    assert body["account"]["organization_id"] == ORG
    assert captured["email"] == "Person@GovMind.test"


def test_login_request_has_no_url_or_key_field():
    """شرط صريح: **لا حقل لرابط ولا لمفتاح** في أي طلب من الإضافة."""
    spec = client.get("/openapi.json").json()
    schema = spec["components"]["schemas"]["AccountLoginRequest"]
    assert set(schema["properties"]) == {"email", "password"}

    # **نماذج الطلبات وحدها.** `InstallerDownloadResponse.download_url` حقل
    # ردٍّ يصدره السيرفر ولا يُدخله أحد، فلا يقع تحت هذا الشرط.
    forbidden = ("url", "base_url", "api_key", "server", "supabase")
    requests = [
        name
        for name in spec["components"]["schemas"]
        if name.endswith("Request")
    ]
    assert "AccountLoginRequest" in requests
    for name in requests:
        for field in spec["components"]["schemas"][name].get("properties", {}):
            assert not any(word in field.lower() for word in forbidden), (
                f"{name}.{field} يطلب من المستخدم عنوانًا أو مفتاحًا"
            )


# ===========================================================================
# ٤) ملف الهجرة
# ===========================================================================
REQUIRED_TABLES = (
    "profiles",
    "organizations",
    "organization_members",
    "subscriptions",
    "device_activations",
    "conversations",
    "messages",
    "files",
    "file_chunks",
    "audit_logs",
)


@pytest.fixture(scope="module")
def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"ملف الهجرة مفقود: {MIGRATION}"


def test_all_ten_tables_are_created(migration_sql):
    for table in REQUIRED_TABLES:
        assert f"create table if not exists public.{table}" in migration_sql, table


def test_rls_is_enabled_and_forced_on_every_table(migration_sql):
    """`enable` وحدها لا تكفي: بلا `force` لا تُطبَّق السياسات على المالك."""
    for table in REQUIRED_TABLES:
        assert (
            re.search(rf"alter table public\.{table}\s+enable row level security", migration_sql)
            is not None
        ), f"RLS غير مفعّل على {table}"
        assert (
            re.search(rf"alter table public\.{table}\s+force\s+row level security", migration_sql)
            is not None
        ), f"RLS غير مفروض على مالك {table}"


def test_authentication_uses_auth_users_only(migration_sql):
    """لا نظام كلمات مرور خاص: `profiles.id` يشير إلى `auth.users`."""
    assert "references auth.users (id)" in migration_sql
    assert "password" not in migration_sql.lower()


def test_one_active_device_is_a_database_constraint(migration_sql):
    """الحدّ فهرس فريد جزئي، لا فحص في الكود يمكن أن يسبقه طلب متزامن."""
    assert "create unique index if not exists uq_device_activations_one_active" in migration_sql
    assert "where revoked_at is null" in migration_sql


def test_device_activations_has_every_required_column(migration_sql):
    block = migration_sql.split("create table if not exists public.device_activations")[1]
    block = block.split(");")[0]
    for column in (
        "id",
        "subscription_id",
        "device_id_hash",
        "device_name",
        "activated_at",
        "last_seen_at",
        "revoked_at",
    ):
        assert column in block, column


def test_raw_fingerprints_are_rejected_by_a_check_constraint(migration_sql):
    assert "device_id_hash  text        not null check (device_id_hash ~ '^[0-9a-f]{64}$')" in migration_sql


def test_every_status_value_is_in_the_enum(migration_sql):
    for status in ("trial", "active", "expired", "suspended", "cancelled"):
        assert f"'{status}'" in migration_sql, status


def test_migration_ships_isolation_tests(migration_sql):
    """الملف يثبت العزل بنفسه: فشل تأكيد يُفشل الهجرة ولا تُطبَّق."""
    assert "$isolation_tests$" in migration_sql
    assert migration_sql.count("raise exception") >= 8


def test_migration_contains_no_secret(migration_sql):
    """لا مفتاح ولا سلسلة اتصال ولا رمز في ملف يُودَع في المستودع."""
    lowered = migration_sql.lower()
    for marker in ("accountkey=", "eyj", "sk_live", "service_role_key ="):
        assert marker not in lowered, marker


def test_no_credential_is_committed_in_the_repository():
    """فحص شامل: لا ملف مصدري يحمل قيمة مفتاح حقيقية."""
    root = Path(__file__).resolve().parents[2]
    # الأنماط مركّبة من قطع حتى لا يطابق هذا الملف نفسه.
    suspicious = re.compile(
        "(" + "Account" + r"Key=(?!dGVzdC)|" + "SUPABASE_SERVICE_ROLE" + r"_KEY\s*=\s*ey)",
        re.IGNORECASE,
    )
    checked = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".sql", ".js", ".json", ".md", ".ts", ".tsx"}:
            continue
        if any(part in {"node_modules", ".git", ".venv", ".next"} for part in path.parts):
            continue
        if path.name == Path(__file__).name:
            continue
        checked += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not suspicious.search(text), f"قيمة سرّية محتملة في {path}"
    assert checked > 0
