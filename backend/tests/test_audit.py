"""اختبارات سجل التدقيق (مهمة P2-04).

**شرط الإنجاز الثالث:** الأحداث تظهر في السجل مرتبطة بالجهة الصحيحة.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.audit_store import (
    ACTION_CONVERSATION_DELETED,
    ACTION_FILE_DELETED,
    ACTION_FILE_UPLOADED,
    ACTION_LOGIN,
    ACTION_MODEL_PROVIDER_CHANGED,
    ACTION_USER_CREATED,
    ACTION_USER_DISABLED,
    MemoryAuditStore,
)
from app.services.conversation_store import MemoryConversationStore
from app.services.file_store import MemoryFileStore
from app.services.organization_settings_store import (
    MemoryOrganizationSettingsStore,
)
from app.services.retrieval import MemoryChunkStore
from app.services.user_store import MemoryUserStore

client = TestClient(app)

ADMIN_A = "admin@digital-services.test"
EMPLOYEE_A = "n.alharbi@digital-services.test"
ADMIN_B = "admin@urban-planning.test"

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


def actions_in(headers: dict[str, str]) -> list[str]:
    listing = client.get("/api/audit-logs", headers=headers).json()
    return [event["action"] for event in listing["events"]]


# ---------------------------------------------------------------------------
# الأحداث المسجَّلة
# ---------------------------------------------------------------------------
def test_login_is_recorded(admin):
    events = client.get("/api/audit-logs", headers=admin).json()["events"]

    assert events
    assert events[0]["action"] == ACTION_LOGIN
    assert ADMIN_A in events[0]["details"]
    assert events[0]["user_id"]


def test_creating_and_disabling_a_user_are_recorded(admin):
    created = client.post(
        "/api/users",
        json={
            "email": "new@digital-services.test",
            "full_name": "موظف جديد",
            "role": "employee",
            "password": "Employee@2026",
        },
        headers=admin,
    ).json()
    client.delete(f"/api/users/{created['id']}", headers=admin)

    recorded = actions_in(admin)
    assert ACTION_USER_CREATED in recorded
    assert ACTION_USER_DISABLED in recorded


def test_deleting_a_conversation_is_recorded(employee, admin):
    conversation_id = client.post(
        "/api/chat", json={"message": "سؤال"}, headers=employee
    ).json()["conversation_id"]
    client.delete(f"/api/conversations/{conversation_id}", headers=employee)

    assert ACTION_CONVERSATION_DELETED in actions_in(admin)


def test_uploading_and_deleting_a_file_are_recorded(employee, admin):
    uploaded = client.post(
        "/api/files",
        files={"file": ("ميزانية.txt", "محتوى تجريبي".encode(), "text/plain")},
        headers=employee,
    ).json()["file"]
    client.delete(f"/api/files/{uploaded['id']}", headers=employee)

    recorded = actions_in(admin)
    assert ACTION_FILE_UPLOADED in recorded
    assert ACTION_FILE_DELETED in recorded


def test_changing_the_model_provider_is_recorded(admin):
    client.patch(
        "/api/organizations/1/model-settings",
        json={"provider": "local"},
        headers=admin,
    )

    assert ACTION_MODEL_PROVIDER_CHANGED in actions_in(admin)


def test_events_carry_the_actor_and_a_readable_detail(admin):
    client.post(
        "/api/users",
        json={
            "email": "detail@digital-services.test",
            "full_name": "موظف",
            "role": "employee",
            "password": "Employee@2026",
        },
        headers=admin,
    )

    listing = client.get(
        "/api/audit-logs", params={"action": ACTION_USER_CREATED}, headers=admin
    ).json()

    assert listing["page"]["total"] == 1
    event = listing["events"][0]
    assert "detail@digital-services.test" in event["details"]
    assert event["user_id"]
    assert event["created_at"]


# ---------------------------------------------------------------------------
# شرط الإنجاز: الأحداث مرتبطة بالجهة الصحيحة
# ---------------------------------------------------------------------------
def test_the_log_never_crosses_organizations(admin):
    """شرط الإنجاز الثالث."""
    admin_b = auth_header(ADMIN_B)

    listing_a = client.get("/api/audit-logs", headers=admin).json()
    listing_b = client.get("/api/audit-logs", headers=admin_b).json()

    # كل جهة ترى تسجيل دخول مسؤولها وحده.
    details_a = " ".join(event["details"] or "" for event in listing_a["events"])
    details_b = " ".join(event["details"] or "" for event in listing_b["events"])

    assert ADMIN_A in details_a and ADMIN_A not in details_b
    assert ADMIN_B in details_b and ADMIN_B not in details_a


def test_an_action_in_one_organization_does_not_appear_in_another(admin):
    admin_b = auth_header(ADMIN_B)
    client.post(
        "/api/users",
        json={
            "email": "only-in-a@digital-services.test",
            "full_name": "موظف",
            "role": "employee",
            "password": "Employee@2026",
        },
        headers=admin,
    )

    assert ACTION_USER_CREATED in actions_in(admin)
    assert ACTION_USER_CREATED not in actions_in(admin_b)
    assert "only-in-a" not in client.get("/api/audit-logs", headers=admin_b).text


# ---------------------------------------------------------------------------
# الصلاحيات والترقيم
# ---------------------------------------------------------------------------
def test_an_employee_cannot_read_the_log(employee):
    response = client.get("/api/audit-logs", headers=employee)
    assert response.status_code == 403
    assert "مسؤول الجهة" in response.json()["detail"]


def test_the_log_requires_a_token():
    assert client.get("/api/audit-logs").status_code == 401


def test_the_log_is_newest_first_and_paginated(admin):
    for index in range(3):
        client.post(
            "/api/users",
            json={
                "email": f"paged{index}@digital-services.test",
                "full_name": f"موظف {index}",
                "role": "employee",
                "password": "Employee@2026",
            },
            headers=admin,
        )

    page = client.get(
        "/api/audit-logs",
        params={"action": ACTION_USER_CREATED, "limit": 2},
        headers=admin,
    ).json()

    assert page["page"] == {"total": 3, "limit": 2, "offset": 0}
    assert "paged2" in page["events"][0]["details"]
    assert "paged1" in page["events"][1]["details"]


def test_filtering_by_user_is_scoped_to_the_organization(admin, employee):
    conversation_id = client.post(
        "/api/chat", json={"message": "سؤال"}, headers=employee
    ).json()["conversation_id"]
    client.delete(f"/api/conversations/{conversation_id}", headers=employee)

    employee_id = client.get("/api/auth/me", headers=employee).json()["id"]
    listing = client.get(
        "/api/audit-logs", params={"user_id": employee_id}, headers=admin
    ).json()

    assert listing["events"]
    assert {event["user_id"] for event in listing["events"]} == {employee_id}


def test_a_failing_audit_store_never_breaks_the_operation(
    admin, monkeypatch, caplog
):
    """تعذُّر كتابة سطر في السجل لا يمنع العمل، لكنه لا يمر صامتًا."""

    def boom(self, **_kwargs):
        raise RuntimeError("تعذّر الاتصال بـuser=govagent password=secret")

    monkeypatch.setattr(MemoryAuditStore, "append", boom)

    with caplog.at_level(logging.WARNING, logger="app.services.audit_service"):
        response = client.post(
            "/api/users",
            json={
                "email": "resilient@digital-services.test",
                "full_name": "موظف",
                "role": "employee",
                "password": "Employee@2026",
            },
            headers=admin,
        )

    # العملية الأصلية نجحت.
    assert response.status_code == 201

    # والفشل ظهر تحذيرًا واضحًا في سجل التطبيق.
    warnings = [
        item for item in caplog.records if item.levelno == logging.WARNING
    ]
    assert warnings
    message = warnings[0].getMessage()
    assert "سجل التدقيق" in message
    assert ACTION_USER_CREATED in message
    assert "organization_id=1" in message
    assert "RuntimeError" in message


def test_the_audit_warning_carries_no_sensitive_data(admin, monkeypatch, caplog):
    """التحذير بلا details وبلا نص الاستثناء: الأول يحمل بريدًا، والثاني
    قد يحمل بيانات اتصال القاعدة.
    """

    def boom(self, **_kwargs):
        raise RuntimeError("ORA-01017 user=govagent password=super-secret")

    monkeypatch.setattr(MemoryAuditStore, "append", boom)

    with caplog.at_level(logging.WARNING, logger="app.services.audit_service"):
        client.post(
            "/api/users",
            json={
                "email": "secret.person@digital-services.test",
                "full_name": "موظف",
                "role": "employee",
                "password": "Employee@2026",
            },
            headers=admin,
        )

    logged = " ".join(item.getMessage() for item in caplog.records)

    # لا بريد الموظف، ولا كلمة مروره، ولا بيانات اتصال القاعدة.
    assert "secret.person" not in logged
    assert "Employee@2026" not in logged
    assert "super-secret" not in logged
    assert "ORA-01017" not in logged
