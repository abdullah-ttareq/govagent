"""اختبارات الاشتراك والتراخيص وإعدادات المودل وسجل التدقيق (مهمة P2-04)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.audit_store import MemoryAuditStore
from app.services.conversation_store import MemoryConversationStore
from app.services.file_store import MemoryFileStore
from app.services.organization_settings_store import (
    MemoryOrganizationSettingsStore,
    Subscription,
    get_organization_settings_store,
)
from app.services.retrieval import MemoryChunkStore
from app.services.user_store import MemoryUserStore

client = TestClient(app)

#: جهتان فعّالتان لاختبارات العزل، وثالثة اشتراكها منتهٍ في البذرة نفسها
#: — مطابقة لـmock-data/organizations.json.
ORG_A, ORG_B, ORG_EXPIRED = 1, 2, 3
ADMIN_A = "admin@digital-services.test"
EMPLOYEE_A = "n.alharbi@digital-services.test"
ADMIN_B = "admin@urban-planning.test"
ADMIN_EXPIRED = "admin@national-archive.test"
EMPLOYEE_EXPIRED = "r.alanzi@national-archive.test"

PROVISIONING_KEY = "a-configured-provisioning-key"
KEY_HEADER = {"X-Provisioning-Key": PROVISIONING_KEY}

_STORES = (
    MemoryUserStore,
    MemoryConversationStore,
    MemoryFileStore,
    MemoryOrganizationSettingsStore,
    MemoryAuditStore,
)


@pytest.fixture(autouse=True)
def clean_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    for store in _STORES:
        store.reset()
    MemoryChunkStore.clear()
    yield
    for store in _STORES:
        store.reset()
    MemoryChunkStore.clear()


def auth_header(email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": settings.dev_seed_password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin() -> dict[str, str]:
    return auth_header(ADMIN_A)


@pytest.fixture
def employee() -> dict[str, str]:
    return auth_header(EMPLOYEE_A)


@pytest.fixture
def provisioning(monkeypatch) -> dict[str, str]:
    monkeypatch.setattr(settings, "provisioning_key", PROVISIONING_KEY)
    return KEY_HEADER


def set_subscription(
    organization_id: int,
    *,
    status: str = "active",
    seats: int = 10,
    days_left: int = 365,
) -> Subscription:
    """يضبط اشتراك جهة مباشرة في المخزن، لتهيئة الاختبار."""
    now = datetime.now(UTC)
    return get_organization_settings_store().upsert_subscription(
        organization_id=organization_id,
        status=status,
        seats=seats,
        starts_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=days_left),
    )


def expire(organization_id: int, *, days_ago: int = 30) -> Subscription:
    """يجعل اشتراك جهة منتهيًا منذ عدد من الأيام."""
    now = datetime.now(UTC)
    return get_organization_settings_store().upsert_subscription(
        organization_id=organization_id,
        status="active",  # الحالة لم تُحدَّث، والتاريخ وحده يحسم
        seats=10,
        starts_at=now - timedelta(days=400),
        expires_at=now - timedelta(days=days_ago),
    )


def expiry_text(organization_id: int) -> str:
    subscription = get_organization_settings_store().get_subscription(organization_id)
    return subscription.expires_at.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# ٠) حالات الجهات المزروعة — مطابقة لـmock-data/organizations.json
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("organization_id", "seats"), [(ORG_A, 10), (ORG_B, 5)]
)
def test_seeded_active_organizations_are_usable(organization_id, seats):
    """الجهتان الأوليان فعّالتان دائمًا — عليهما تقوم اختبارات العزل.

    تواريخ البذرة ثابتة لتطابق mock-data، وهذا الاختبار حارسها: إن اقترب
    تاريخ ٢٠٣٠ فشل هنا بوضوح، بدل أن تتعطّل عشرات الاختبارات بلا سبب ظاهر.
    """
    subscription = get_organization_settings_store().get_subscription(
        organization_id
    )

    assert subscription.status == "active"
    assert subscription.seats == seats
    assert subscription.blocked_reason() is None


def test_the_seeded_expired_organization_is_blocked():
    """الجهة الثالثة اشتراكها منتهٍ في البذرة نفسها، بلا تهيئة في الاختبار."""
    subscription = get_organization_settings_store().get_subscription(
        ORG_EXPIRED
    )

    assert subscription.status == "expired"
    assert subscription.expires_at.strftime("%Y-%m-%d") == "2025-06-30"
    assert subscription.blocked_reason() is not None


@pytest.mark.parametrize("email", [ADMIN_EXPIRED, EMPLOYEE_EXPIRED])
def test_a_user_of_the_expired_organization_gets_the_real_message(email):
    """المطلوب: رسالة انتهاء الاشتراك الفعلية بتاريخ البذرة، لا خطأ عام."""
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": settings.dev_seed_password},
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail == (
        "انتهى اشتراك جهتك بتاريخ 2025-06-30. "
        "راجع مسؤول النظام في جهتك لتجديد الاشتراك قبل متابعة الاستخدام."
    )
    assert "access_token" not in response.text


def test_the_two_active_organizations_stay_available_for_isolation():
    """الجهة المنتهية مفردة عمدًا حتى تبقى الجهتان الأوليان قابلتين للدخول."""
    for email in (ADMIN_A, ADMIN_B):
        response = client.post(
            "/api/auth/login",
            json={"email": email, "password": settings.dev_seed_password},
        )
        assert response.status_code == 200, email


def test_renewing_the_expired_organization_restores_access(provisioning):
    future = (datetime.now(UTC) + timedelta(days=90)).isoformat()
    renewed = client.patch(
        f"/api/organizations/{ORG_EXPIRED}/subscription",
        json={"status": "active", "expires_at": future},
        headers=provisioning,
    )
    assert renewed.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={"email": ADMIN_EXPIRED, "password": settings.dev_seed_password},
    )
    assert login.status_code == 200


# ---------------------------------------------------------------------------
# ١) شرط الإنجاز: اشتراك منتهٍ يمنع برسالة تذكر تاريخ الانتهاء
# ---------------------------------------------------------------------------
def test_login_is_blocked_when_the_subscription_expired():
    """شرط الإنجاز الأول: الرسالة تذكر تاريخ الانتهاء لا خطأً عامًا."""
    expire(ORG_A)
    expected_date = expiry_text(ORG_A)

    response = client.post(
        "/api/auth/login",
        json={"email": ADMIN_A, "password": settings.dev_seed_password},
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "انتهى اشتراك جهتك" in detail
    assert expected_date in detail
    assert "access_token" not in response.text


def test_a_token_issued_before_expiry_stops_working():
    """الفحص في كل طلب لا عند الدخول وحده: الرمز يعيش ٨ ساعات."""
    headers = auth_header(ADMIN_A)
    assert client.get("/api/users", headers=headers).status_code == 200

    expire(ORG_A)

    response = client.get("/api/users", headers=headers)
    assert response.status_code == 403
    assert expiry_text(ORG_A) in response.json()["detail"]


@pytest.mark.parametrize(
    "path",
    ["/api/users", "/api/conversations", "/api/files", "/api/audit-logs"],
)
def test_every_protected_route_is_blocked_when_expired(path):
    headers = auth_header(ADMIN_A)
    expire(ORG_A)

    response = client.get(path, headers=headers)
    assert response.status_code == 403
    assert "انتهى اشتراك جهتك" in response.json()["detail"]


def test_chat_is_blocked_when_expired():
    headers = auth_header(EMPLOYEE_A)
    expire(ORG_A)

    response = client.post(
        "/api/chat", json={"message": "سؤال"}, headers=headers
    )
    assert response.status_code == 403
    assert "انتهى اشتراك جهتك" in response.json()["detail"]


def test_a_suspended_subscription_blocks_with_its_own_message():
    set_subscription(ORG_A, status="suspended")

    response = client.post(
        "/api/auth/login",
        json={"email": ADMIN_A, "password": settings.dev_seed_password},
    )

    assert response.status_code == 403
    assert "موقوف" in response.json()["detail"]


def test_an_organization_without_a_subscription_is_blocked():
    """فشل مغلق: رخصة غائبة ليست رخصة مفتوحة."""
    # قراءة أولًا حتى يجري الزرع الكسول، وإلا أُعيد زرع الصف بعد حذفه.
    get_organization_settings_store().get_subscription(ORG_A)
    MemoryOrganizationSettingsStore._subscriptions.pop(ORG_A, None)

    response = client.post(
        "/api/auth/login",
        json={"email": ADMIN_A, "password": settings.dev_seed_password},
    )

    assert response.status_code == 403
    assert "لا يوجد اشتراك مسجّل" in response.json()["detail"]


def test_expiry_of_one_organization_does_not_touch_the_other():
    expire(ORG_A)

    blocked = client.post(
        "/api/auth/login",
        json={"email": ADMIN_A, "password": settings.dev_seed_password},
    )
    allowed = client.post(
        "/api/auth/login",
        json={"email": ADMIN_B, "password": settings.dev_seed_password},
    )

    assert blocked.status_code == 403
    assert allowed.status_code == 200


# ---------------------------------------------------------------------------
# ٢) المسارات التي يجب أن تعمل على اشتراك منتهٍ
# ---------------------------------------------------------------------------
def test_me_logout_and_subscription_still_work_when_expired():
    """لولا هذه لعرف المسؤول أن شيئًا ممنوع بلا أن يعرف السبب."""
    headers = auth_header(ADMIN_A)
    expire(ORG_A)

    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 200

    subscription = client.get(
        f"/api/organizations/{ORG_A}/subscription", headers=headers
    )
    assert subscription.status_code == 200
    body = subscription.json()
    assert body["is_usable"] is False
    assert expiry_text(ORG_A) in body["blocked_reason"]


# ---------------------------------------------------------------------------
# ٣) شرط الإنجاز: تجاوز المقاعد يُرفض ولا يُنشئ المستخدم
# ---------------------------------------------------------------------------
def new_employee(index: int) -> dict:
    return {
        "email": f"employee{index}@digital-services.test",
        "full_name": f"موظف {index}",
        "role": "employee",
        "password": "Employee@2026",
    }


def test_creating_a_user_beyond_the_seat_limit_is_refused(admin):
    """شرط الإنجاز الثاني: يُرفض ولا يُنشئ المستخدم."""
    # الجهة فيها ٣ نشطين أصلًا، فمقعد واحد شاغر من أربعة.
    set_subscription(ORG_A, seats=4)

    assert (
        client.post("/api/users", json=new_employee(1), headers=admin).status_code
        == 201
    )

    refused = client.post("/api/users", json=new_employee(2), headers=admin)

    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert "عدد تراخيص جهتك 4" in detail
    assert "4 من 4" in detail
    # ولم يُنشأ المستخدم فعلًا.
    listing = client.get("/api/users", headers=admin).json()
    assert listing["total"] == 4
    assert new_employee(2)["email"] not in {u["email"] for u in listing["users"]}


def test_disabling_a_user_frees_a_seat(admin):
    set_subscription(ORG_A, seats=3)
    assert client.post("/api/users", json=new_employee(1), headers=admin).status_code == 409

    employee_id = next(
        user["id"]
        for user in client.get("/api/users", headers=admin).json()["users"]
        if user["email"] == EMPLOYEE_A
    )
    client.delete(f"/api/users/{employee_id}", headers=admin)

    assert client.post("/api/users", json=new_employee(1), headers=admin).status_code == 201


def test_reactivating_a_user_also_needs_a_free_seat(admin):
    """لولا هذا الفحص لأمكن تجاوز الحد بتعطيل حساب ثم تفعيل غيره."""
    set_subscription(ORG_A, seats=3)
    employee_id = next(
        user["id"]
        for user in client.get("/api/users", headers=admin).json()["users"]
        if user["email"] == EMPLOYEE_A
    )

    client.delete(f"/api/users/{employee_id}", headers=admin)
    assert client.post("/api/users", json=new_employee(1), headers=admin).status_code == 201

    # المقاعد ممتلئة الآن، فإعادة التفعيل تُرفض كإنشاء موظف جديد.
    response = client.patch(
        f"/api/users/{employee_id}", json={"is_active": True}, headers=admin
    )
    assert response.status_code == 409
    assert "تراخيص" in response.json()["detail"]


def test_the_subscription_route_reports_seat_usage(admin):
    set_subscription(ORG_A, seats=6)

    body = client.get(
        f"/api/organizations/{ORG_A}/subscription", headers=admin
    ).json()

    assert body["seats"] == 6
    assert body["seats_used"] == 3
    assert body["seats_available"] == 3
    assert body["is_usable"] is True
    assert body["blocked_reason"] is None


def test_an_employee_cannot_read_the_subscription(employee):
    response = client.get(
        f"/api/organizations/{ORG_A}/subscription", headers=employee
    )
    assert response.status_code == 403
    assert "مسؤول الجهة" in response.json()["detail"]


def test_the_subscription_of_another_organization_is_not_readable(admin):
    response = client.get(
        f"/api/organizations/{ORG_B}/subscription", headers=admin
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# ٤) تجديد الاشتراك محروس بمفتاح التجهيز
# ---------------------------------------------------------------------------
def test_renewing_a_subscription_requires_the_provisioning_key(provisioning, admin):
    expire(ORG_A)

    # مسؤول الجهة لا يستطيع تجديد اشتراكه بنفسه.
    without_key = client.patch(
        f"/api/organizations/{ORG_A}/subscription",
        json={"seats": 100},
        headers=admin,
    )
    assert without_key.status_code == 401

    renewed = client.patch(
        f"/api/organizations/{ORG_A}/subscription",
        json={
            "status": "active",
            "seats": 20,
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
        headers=provisioning,
    )
    assert renewed.status_code == 200
    assert renewed.json()["seats"] == 20
    assert renewed.json()["is_usable"] is True

    # وتسجيل الدخول يعمل من جديد.
    assert (
        client.post(
            "/api/auth/login",
            json={"email": ADMIN_A, "password": settings.dev_seed_password},
        ).status_code
        == 200
    )


def test_a_provisioned_organization_gets_a_working_subscription(provisioning):
    """جهة بلا اشتراك لا يستطيع مسؤولها الدخول، فالتجهيز ينشئه معها."""
    response = client.post(
        "/api/organizations",
        json={
            "name": "وزارة التجربة",
            "slug": "test-ministry",
            "admin_email": "admin@test-ministry.test",
            "admin_full_name": "خالد المطيري",
            "admin_password": "Provision@2026",
        },
        headers=provisioning,
    )
    assert response.status_code == 201

    login = client.post(
        "/api/auth/login",
        json={"email": "admin@test-ministry.test", "password": "Provision@2026"},
    )
    assert login.status_code == 200


# ---------------------------------------------------------------------------
# ٥) مزود المودل لكل جهة
# ---------------------------------------------------------------------------
def test_an_organization_without_a_choice_falls_back_to_the_env_variable(admin):
    body = client.get(
        f"/api/organizations/{ORG_A}/model-settings", headers=admin
    ).json()
    assert body["provider"] == settings.model_provider


def test_the_chosen_provider_is_used_instead_of_the_env_variable(
    admin, employee, monkeypatch
):
    """الجهة تختار مزودها، ويُقرأ من القاعدة بدل MODEL_PROVIDER."""
    monkeypatch.setattr(settings, "model_provider", "mock")

    chosen = client.patch(
        f"/api/organizations/{ORG_A}/model-settings",
        json={"provider": "local"},
        headers=admin,
    )
    assert chosen.status_code == 200
    assert chosen.json()["provider"] == "local"

    # المحادثة صارت تستخدم local، ورسالته «غير منفذ» تصل كـ503.
    response = client.post(
        "/api/chat", json={"message": "سؤال"}, headers=employee
    )
    assert response.status_code == 503
    assert "غير منفذ" in response.json()["detail"]


def test_one_organizations_provider_does_not_affect_another(admin):
    client.patch(
        f"/api/organizations/{ORG_A}/model-settings",
        json={"provider": "local"},
        headers=admin,
    )

    other = client.post(
        "/api/chat",
        json={"message": "سؤال"},
        headers=auth_header(ADMIN_B),
    )
    assert other.status_code == 200
    assert other.json()["provider"] == "mock"


def test_an_unsupported_provider_is_refused(admin):
    response = client.patch(
        f"/api/organizations/{ORG_A}/model-settings",
        json={"provider": "gemini"},
        headers=admin,
    )
    assert response.status_code == 422
    assert "غير مدعوم" in response.json()["detail"]


def test_an_employee_cannot_change_the_provider(employee):
    response = client.patch(
        f"/api/organizations/{ORG_A}/model-settings",
        json={"provider": "local"},
        headers=employee,
    )
    assert response.status_code == 403
