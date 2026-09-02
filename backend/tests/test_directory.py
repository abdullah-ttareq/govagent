"""اختبارات إدارة الجهات والمستخدمين وصلاحيات الدور (مهمة P2-02).

اختبارات العزل بين الجهات في tests/test_isolation.py.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.user_store import MemoryUserStore, get_user_store

client = TestClient(app)

ADMIN_A = "admin@digital-services.test"
EMPLOYEE_A = "n.alharbi@digital-services.test"
OTHER_EMPLOYEE_A = "f.alqahtani@digital-services.test"
ORG_A = 1


@pytest.fixture(autouse=True)
def clean_store():
    MemoryUserStore.reset()
    yield
    MemoryUserStore.reset()


def auth_header(email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": settings.dev_seed_password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_a() -> dict[str, str]:
    return auth_header(ADMIN_A)


@pytest.fixture
def employee_a() -> dict[str, str]:
    return auth_header(EMPLOYEE_A)


def user_id_of(email: str, headers: dict[str, str]) -> int:
    listing = client.get("/api/users", headers=headers).json()["users"]
    return next(user["id"] for user in listing if user["email"] == email)


# ---------------------------------------------------------------------------
# تجهيز الجهات
# ---------------------------------------------------------------------------
NEW_ORG = {
    "name": "وزارة التجربة",
    "slug": "test-ministry",
    "admin_email": "admin@test-ministry.test",
    "admin_full_name": "خالد المطيري",
    "admin_password": "Provision@2026",
}

PROVISIONING_KEY = "a-configured-provisioning-key"
KEY_HEADER = {"X-Provisioning-Key": PROVISIONING_KEY}


@pytest.fixture
def provisioning_enabled(monkeypatch) -> dict[str, str]:
    """يضبط مفتاح التجهيز ويعيد ترويسته.

    المفتاح إلزامي في كل البيئات، فلا يعمل المسار بدون هذه التهيئة.
    """
    monkeypatch.setattr(settings, "provisioning_key", PROVISIONING_KEY)
    return KEY_HEADER


def provision(payload: dict, headers: dict[str, str] | None = None):
    return client.post("/api/organizations", json=payload, headers=headers)


def test_provisioning_creates_the_organization_and_its_first_admin(
    provisioning_enabled,
):
    response = provision(NEW_ORG, provisioning_enabled)

    assert response.status_code == 201
    body = response.json()
    assert body["organization"]["slug"] == "test-ministry"
    assert body["organization"]["is_active"] is True
    assert body["admin"]["role"] == "admin"
    assert body["admin"]["organization_id"] == body["organization"]["id"]

    # الجهة قابلة للاستخدام فورًا: مسؤولها يستطيع الدخول.
    login = client.post(
        "/api/auth/login",
        json={
            "email": NEW_ORG["admin_email"],
            "password": NEW_ORG["admin_password"],
        },
    )
    assert login.status_code == 200


def test_provisioning_response_never_contains_the_password(provisioning_enabled):
    body = provision(NEW_ORG, provisioning_enabled).text
    assert NEW_ORG["admin_password"] not in body


def test_provisioning_rejects_a_duplicate_slug(provisioning_enabled):
    duplicate = {**NEW_ORG, "slug": "digital-services"}
    response = provision(duplicate, provisioning_enabled)

    assert response.status_code == 409
    assert "مستخدم لجهة أخرى" in response.json()["detail"]


def test_provisioning_rejects_a_malformed_slug(provisioning_enabled):
    response = provision({**NEW_ORG, "slug": "Bad Slug!"}, provisioning_enabled)
    assert response.status_code == 422


def test_provisioning_rejects_a_short_password(provisioning_enabled):
    response = provision({**NEW_ORG, "admin_password": "123"}, provisioning_enabled)
    assert response.status_code == 422


def test_provisioning_rejects_a_wrong_or_missing_key(provisioning_enabled):
    assert provision(NEW_ORG).status_code == 401
    assert provision(NEW_ORG, {"X-Provisioning-Key": "wrong-key"}).status_code == 401
    assert provision(NEW_ORG, provisioning_enabled).status_code == 201


@pytest.mark.parametrize("app_env", ["development", "production", "staging"])
def test_provisioning_is_disabled_without_a_key_in_every_environment(
    monkeypatch, app_env
):
    """مسار ينشئ جهة كاملة بمسؤول لها لا يُترك مفتوحًا في أي بيئة.

    بيئة تطوير مكشوفة على الشبكة، أو APP_ENV منسيّة على قيمتها الافتراضية عند
    النشر، تكفي لجعله بابًا مفتوحًا لو استُثنيت.
    """
    monkeypatch.setattr(settings, "provisioning_key", "")
    monkeypatch.setattr(settings, "app_env", app_env)

    response = provision(NEW_ORG)

    assert response.status_code == 503
    assert "PROVISIONING_KEY" in response.json()["detail"]
    # ولم تُنشأ الجهة فعلًا.
    assert get_user_store().get_organization_by_slug(NEW_ORG["slug"]) is None


@pytest.mark.parametrize(
    "headers",
    [
        None,
        {"X-Provisioning-Key": ""},
        {"X-Provisioning-Key": "   "},
        {"X-Provisioning-Key": "anything"},
    ],
    ids=["no-header", "empty-header", "blank-header", "arbitrary-header"],
)
def test_an_empty_configured_key_never_matches_any_header(monkeypatch, headers):
    """المفتاح الفارغ يعطّل المسار ولا يصير قيمة تُقارَن.

    بدون هذا الفصل تطابق ترويسة فارغة مفتاحًا فارغًا ويمر الطلب.
    """
    monkeypatch.setattr(settings, "provisioning_key", "")
    monkeypatch.setattr(settings, "app_env", "development")

    response = provision(NEW_ORG, headers)

    assert response.status_code == 503
    assert get_user_store().get_organization_by_slug(NEW_ORG["slug"]) is None


def test_a_whitespace_only_key_also_disables_the_route(monkeypatch):
    """مفتاح من فراغات في .env لا يُحسب مفتاحًا مضبوطًا."""
    monkeypatch.setattr(settings, "provisioning_key", "    ")
    monkeypatch.setattr(settings, "app_env", "development")

    assert provision(NEW_ORG).status_code == 503
    assert provision(NEW_ORG, {"X-Provisioning-Key": "    "}).status_code == 503


def test_provisioning_rejects_an_email_used_in_another_organization(
    provisioning_enabled,
):
    """بريد المسؤول فريد عالميًا كذلك، ولا يُترك للجهة الجديدة أن تكرره."""
    response = provision(
        {**NEW_ORG, "admin_email": "admin@digital-services.test"},
        provisioning_enabled,
    )

    assert response.status_code == 409
    assert "مسجّل بالفعل في النظام" in response.json()["detail"]
    # ولم تُنشأ جهة بلا مسؤول: الفشل قبل إنشاء الجهة لا بعده.
    assert get_user_store().get_organization_by_slug(NEW_ORG["slug"]) is None


# ---------------------------------------------------------------------------
# قراءة الجهة وتعديلها
# ---------------------------------------------------------------------------
def test_any_role_can_read_its_own_organization(employee_a):
    response = client.get(f"/api/organizations/{ORG_A}", headers=employee_a)

    assert response.status_code == 200
    assert response.json()["name"] == "هيئة الخدمات الرقمية"


def test_admin_can_rename_its_own_organization(admin_a):
    response = client.patch(
        f"/api/organizations/{ORG_A}",
        json={"name": "هيئة الخدمات الرقمية المطوّرة"},
        headers=admin_a,
    )

    assert response.status_code == 200
    assert response.json()["name"] == "هيئة الخدمات الرقمية المطوّرة"
    # الحقول المتروكة فارغة لا تتغيّر.
    assert response.json()["slug"] == "digital-services"


def test_employee_cannot_edit_the_organization(employee_a):
    response = client.patch(
        f"/api/organizations/{ORG_A}", json={"name": "اسم آخر"}, headers=employee_a
    )

    assert response.status_code == 403
    assert "مسؤول الجهة" in response.json()["detail"]


def test_organization_slug_must_stay_unique(admin_a):
    response = client.patch(
        f"/api/organizations/{ORG_A}", json={"slug": "urban-planning"}, headers=admin_a
    )

    assert response.status_code == 409


def test_organization_routes_require_a_token():
    assert client.get(f"/api/organizations/{ORG_A}").status_code == 401
    assert client.patch(f"/api/organizations/{ORG_A}", json={}).status_code == 401


# ---------------------------------------------------------------------------
# قائمة الموظفين وإنشاؤهم
# ---------------------------------------------------------------------------
def test_admin_lists_only_its_own_organization(admin_a):
    response = client.get("/api/users", headers=admin_a)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {user["organization_id"] for user in body["users"]} == {ORG_A}


def test_employee_cannot_list_users(employee_a):
    response = client.get("/api/users", headers=employee_a)

    assert response.status_code == 403
    assert "مسؤول الجهة" in response.json()["detail"]


def test_admin_creates_a_user_in_its_own_organization(admin_a):
    response = client.post(
        "/api/users",
        json={
            "email": "new.employee@digital-services.test",
            "full_name": "بدر الشهري",
            "role": "employee",
            "password": "Employee@2026",
        },
        headers=admin_a,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["organization_id"] == ORG_A
    assert body["role"] == "employee"
    assert body["is_active"] is True

    login = client.post(
        "/api/auth/login",
        json={
            "email": "new.employee@digital-services.test",
            "password": "Employee@2026",
        },
    )
    assert login.status_code == 200


def test_created_user_ignores_any_organization_id_in_the_body(admin_a):
    """شرط الإنجاز: organization_id لا يُقرأ من جسم الطلب في أي مسار."""
    response = client.post(
        "/api/users",
        json={
            "email": "sneaky@digital-services.test",
            "full_name": "محاولة تجاوز",
            "role": "employee",
            "password": "Employee@2026",
            # حقل دخيل: الـschema تتجاهله، والجهة تأتي من الرمز وحده.
            "organization_id": 2,
        },
        headers=admin_a,
    )

    assert response.status_code == 201
    assert response.json()["organization_id"] == ORG_A


def test_employee_cannot_create_users(employee_a):
    response = client.post(
        "/api/users",
        json={
            "email": "x@digital-services.test",
            "full_name": "س ص",
            "role": "employee",
            "password": "Employee@2026",
        },
        headers=employee_a,
    )
    assert response.status_code == 403


def test_duplicate_email_in_the_same_organization_is_refused(admin_a):
    response = client.post(
        "/api/users",
        json={
            "email": ADMIN_A,
            "full_name": "تكرار",
            "role": "employee",
            "password": "Employee@2026",
        },
        headers=admin_a,
    )

    assert response.status_code == 409
    assert "مسجّل بالفعل" in response.json()["detail"]


def test_an_email_used_in_another_organization_is_refused(admin_a):
    """البريد هوية دخول فريدة على مستوى النظام، لا داخل الجهة فقط.

    لو سُمح بالتكرار لصار على تسجيل الدخول أن يخمّن أي الحسابين يقصد صاحب
    البريد — وهو ما لا يجوز في نظام قائم على عزل الجهات.
    """
    response = client.post(
        "/api/users",
        json={
            "email": "admin@urban-planning.test",
            "full_name": "اسم مختلف",
            "role": "employee",
            "password": "Employee@2026",
        },
        headers=admin_a,
    )

    assert response.status_code == 409
    assert "مسجّل بالفعل في النظام" in response.json()["detail"]
    # ولم يُنشأ شيء في جهة صاحب الطلب.
    assert (
        get_user_store().find_user_by_email(
            organization_id=ORG_A, email="admin@urban-planning.test"
        )
        is None
    )


def test_email_uniqueness_ignores_letter_case(admin_a):
    """Ahmad@x و ahmad@x بريد واحد: التفرّد غير حسّاس لحالة الأحرف."""
    response = client.post(
        "/api/users",
        json={
            "email": "ADMIN@Urban-Planning.TEST",
            "full_name": "اختلاف حالة الأحرف",
            "role": "employee",
            "password": "Employee@2026",
        },
        headers=admin_a,
    )

    assert response.status_code == 409


def test_a_duplicate_email_never_reaches_the_store(admin_a, monkeypatch):
    """الرفض قبل الكتابة: المخزن لا يُستدعى أصلًا لإنشاء بريد مكرر."""

    def boom(self, **_kwargs):
        raise AssertionError("لا يجوز محاولة إنشاء مستخدم ببريد مكرر")

    monkeypatch.setattr(MemoryUserStore, "create_user", boom)

    response = client.post(
        "/api/users",
        json={
            "email": "admin@urban-planning.test",
            "full_name": "اسم مختلف",
            "role": "employee",
            "password": "Employee@2026",
        },
        headers=admin_a,
    )
    assert response.status_code == 409


def test_short_password_is_refused_when_creating_a_user(admin_a):
    response = client.post(
        "/api/users",
        json={
            "email": "weak@digital-services.test",
            "full_name": "كلمة ضعيفة",
            "role": "employee",
            "password": "123",
        },
        headers=admin_a,
    )
    assert response.status_code == 422


def test_unknown_role_is_refused(admin_a):
    response = client.post(
        "/api/users",
        json={
            "email": "root@digital-services.test",
            "full_name": "دور مخترع",
            "role": "superadmin",
            "password": "Employee@2026",
        },
        headers=admin_a,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# قراءة موظف وتعديله
# ---------------------------------------------------------------------------
def test_admin_reads_any_user_in_its_organization(admin_a):
    user_id = user_id_of(EMPLOYEE_A, admin_a)
    response = client.get(f"/api/users/{user_id}", headers=admin_a)

    assert response.status_code == 200
    assert response.json()["email"] == EMPLOYEE_A


def test_employee_reads_only_itself(admin_a, employee_a):
    own_id = user_id_of(EMPLOYEE_A, admin_a)
    colleague_id = user_id_of(OTHER_EMPLOYEE_A, admin_a)

    assert client.get(f"/api/users/{own_id}", headers=employee_a).status_code == 200

    forbidden = client.get(f"/api/users/{colleague_id}", headers=employee_a)
    assert forbidden.status_code == 403
    assert "موظف آخر" in forbidden.json()["detail"]


def test_employee_updates_its_own_name_and_password(admin_a, employee_a):
    own_id = user_id_of(EMPLOYEE_A, admin_a)

    response = client.patch(
        f"/api/users/{own_id}",
        json={"full_name": "نورة الحربي المحدّث", "password": "NewPass@2026"},
        headers=employee_a,
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "نورة الحربي المحدّث"

    # كلمة المرور الجديدة تعمل، والقديمة لم تعد تعمل.
    assert (
        client.post(
            "/api/auth/login",
            json={"email": EMPLOYEE_A, "password": "NewPass@2026"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/login",
            json={"email": EMPLOYEE_A, "password": settings.dev_seed_password},
        ).status_code
        == 401
    )


def test_employee_cannot_promote_itself(admin_a, employee_a):
    own_id = user_id_of(EMPLOYEE_A, admin_a)

    response = client.patch(
        f"/api/users/{own_id}", json={"role": "admin"}, headers=employee_a
    )

    assert response.status_code == 403
    assert "مسؤول الجهة فقط" in response.json()["detail"]
    # والدور لم يتغيّر فعلًا.
    assert client.get(f"/api/users/{own_id}", headers=admin_a).json()["role"] == (
        "employee"
    )


def test_employee_cannot_edit_a_colleague(admin_a, employee_a):
    colleague_id = user_id_of(OTHER_EMPLOYEE_A, admin_a)

    response = client.patch(
        f"/api/users/{colleague_id}", json={"full_name": "تغيير"}, headers=employee_a
    )
    assert response.status_code == 403


def test_admin_changes_a_role_in_its_organization(admin_a):
    user_id = user_id_of(EMPLOYEE_A, admin_a)

    response = client.patch(
        f"/api/users/{user_id}", json={"role": "admin"}, headers=admin_a
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_admin_cannot_change_its_own_role_or_status(admin_a):
    own_id = user_id_of(ADMIN_A, admin_a)

    demote = client.patch(
        f"/api/users/{own_id}", json={"role": "employee"}, headers=admin_a
    )
    assert demote.status_code == 403
    assert "بنفسك" in demote.json()["detail"]

    disable = client.patch(
        f"/api/users/{own_id}", json={"is_active": False}, headers=admin_a
    )
    assert disable.status_code == 403


def test_admin_may_still_rename_itself(admin_a):
    own_id = user_id_of(ADMIN_A, admin_a)

    response = client.patch(
        f"/api/users/{own_id}", json={"full_name": "سارة العتيبي"}, headers=admin_a
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# التعطيل
# ---------------------------------------------------------------------------
def test_admin_deactivates_a_user_who_can_no_longer_log_in(admin_a):
    user_id = user_id_of(EMPLOYEE_A, admin_a)

    response = client.delete(f"/api/users/{user_id}", headers=admin_a)

    assert response.status_code == 200
    assert response.json()["is_active"] is False

    blocked = client.post(
        "/api/auth/login",
        json={"email": EMPLOYEE_A, "password": settings.dev_seed_password},
    )
    assert blocked.status_code == 403
    assert "معطّل" in blocked.json()["detail"]


def test_deactivation_keeps_the_record_and_allows_reactivation(admin_a):
    user_id = user_id_of(EMPLOYEE_A, admin_a)
    client.delete(f"/api/users/{user_id}", headers=admin_a)

    # الصف باقٍ، لا محذوف — تاريخه من محادثات وملفات يبقى له صاحب.
    assert client.get(f"/api/users/{user_id}", headers=admin_a).status_code == 200

    reactivated = client.patch(
        f"/api/users/{user_id}", json={"is_active": True}, headers=admin_a
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True


def test_admin_cannot_deactivate_itself(admin_a):
    own_id = user_id_of(ADMIN_A, admin_a)

    response = client.delete(f"/api/users/{own_id}", headers=admin_a)

    assert response.status_code == 403
    assert "بنفسك" in response.json()["detail"]


def test_employee_cannot_deactivate_anyone(admin_a, employee_a):
    colleague_id = user_id_of(OTHER_EMPLOYEE_A, admin_a)
    assert client.delete(f"/api/users/{colleague_id}", headers=employee_a).status_code == 403


def test_user_routes_require_a_token():
    assert client.get("/api/users").status_code == 401
    assert client.post("/api/users", json={}).status_code == 401
    assert client.get("/api/users/1").status_code == 401
    assert client.patch("/api/users/1", json={}).status_code == 401
    assert client.delete("/api/users/1").status_code == 401


def test_a_deactivated_user_token_stops_working(admin_a, employee_a):
    """رمز أُصدر قبل التعطيل لا يبقى صالحًا: الحساب يُقرأ في كل طلب."""
    user_id = user_id_of(EMPLOYEE_A, admin_a)
    assert client.get("/api/auth/me", headers=employee_a).status_code == 200

    client.delete(f"/api/users/{user_id}", headers=admin_a)

    response = client.get("/api/auth/me", headers=employee_a)
    assert response.status_code == 403
    assert "معطّل" in response.json()["detail"]
