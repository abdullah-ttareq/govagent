"""رحلات كاملة عبر المسارات مجتمعة (مهمة P2-05).

الاختبارات الأخرى تفحص كل مجال وحده. هذا الملف يصل بينها: تجهيز جهة ← دخول
← إضافة موظف ← محادثة ← رفع ملف ← استشهاد بمصدر ← سجل تدقيق. عيوب التكامل
بين مهام P2-01 حتى P2-04 تظهر هنا لا في اختبارات المجال الواحد.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.audit_store import (
    ACTION_FILE_UPLOADED,
    ACTION_LOGIN,
    ACTION_USER_CREATED,
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

PROVISIONING_KEY = "an-end-to-end-provisioning-key"
KEY_HEADER = {"X-Provisioning-Key": PROVISIONING_KEY}

BUDGET_TEXT = (
    "تقرير الميزانية السنوية للجهة.\n\n"
    "بلغت مصروفات التشغيل مبلغ مليون ريال خلال السنة المالية.\n\n"
    "وتشمل الميزانية بند الصيانة وبند التدريب."
)

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
    monkeypatch.setattr(settings, "provisioning_key", PROVISIONING_KEY)
    for store in _STORES:
        store.reset()
    MemoryChunkStore.clear()
    yield
    for store in _STORES:
        store.reset()
    MemoryChunkStore.clear()


def token_for(email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_a_new_organization_works_end_to_end():
    """من تجهيز الجهة إلى استشهاد الرد بملف رفعه موظف فيها."""
    # ١) التجهيز ينشئ الجهة ومسؤولها واشتراكها معًا.
    provisioned = client.post(
        "/api/organizations",
        json={
            "name": "وزارة التكامل",
            "slug": "integration-ministry",
            "admin_email": "admin@integration-ministry.test",
            "admin_full_name": "خالد المطيري",
            "admin_password": "Provision@2026",
        },
        headers=KEY_HEADER,
    )
    assert provisioned.status_code == 201
    organization_id = provisioned.json()["organization"]["id"]

    admin = token_for("admin@integration-ministry.test", "Provision@2026")

    # ٢) الاشتراك فعّال وله مقعد مستهلَك واحد (المسؤول).
    subscription = client.get(
        f"/api/organizations/{organization_id}/subscription", headers=admin
    ).json()
    assert subscription["is_usable"] is True
    assert subscription["seats_used"] == 1

    # ٣) المسؤول يضيف موظفًا، فيشغل مقعدًا ثانيًا.
    created = client.post(
        "/api/users",
        json={
            "email": "employee@integration-ministry.test",
            "full_name": "ريم العنزي",
            "role": "employee",
            "password": "Employee@2026",
        },
        headers=admin,
    )
    assert created.status_code == 201
    assert created.json()["organization_id"] == organization_id

    subscription = client.get(
        f"/api/organizations/{organization_id}/subscription", headers=admin
    ).json()
    assert subscription["seats_used"] == 2

    # ٤) الموظف يسجّل الدخول ويرفع ملفًا.
    employee = token_for("employee@integration-ministry.test", "Employee@2026")
    uploaded = client.post(
        "/api/files",
        files={"file": ("ميزانية.txt", BUDGET_TEXT.encode(), "text/plain")},
        headers=employee,
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["file"]["status"] == "processed"
    file_id = uploaded.json()["file"]["id"]

    # ٥) يسأل، فتُفتح محادثة تلقائيًا ويُستشهد بملفه.
    answer = client.post(
        "/api/chat",
        json={"message": "كم بلغت مصروفات التشغيل؟"},
        headers=employee,
    )
    assert answer.status_code == 200
    conversation_id = answer.json()["conversation_id"]
    sources = answer.json()["sources"]
    assert [source["file_name"] for source in sources] == ["ميزانية.txt"]

    # ٦) المصدر قابل للاستعلام عنه — صلاحية المصدر توازي صلاحية محتواه.
    assert (
        client.get(f"/api/files/{file_id}", headers=employee).status_code == 200
    )

    # ٧) التبادل محفوظ بالترتيب الصحيح.
    messages = client.get(
        f"/api/conversations/{conversation_id}/messages", headers=employee
    ).json()
    assert [item["role"] for item in messages["messages"]] == ["user", "assistant"]
    assert messages["messages"][0]["content"] == "كم بلغت مصروفات التشغيل؟"

    # ٨) والمسؤول يرى كل ذلك في سجل التدقيق، بجهته وحدها.
    events = client.get("/api/audit-logs", headers=admin).json()
    actions = {event["action"] for event in events["events"]}
    assert {ACTION_LOGIN, ACTION_USER_CREATED, ACTION_FILE_UPLOADED} <= actions
    assert all(
        "digital-services" not in (event["details"] or "")
        for event in events["events"]
    )


def test_the_new_organization_is_isolated_from_the_seeded_ones():
    """جهة جُهّزت للتو لا ترى شيئًا من الجهات المزروعة، ولا العكس."""
    client.post(
        "/api/organizations",
        json={
            "name": "وزارة التكامل",
            "slug": "integration-ministry",
            "admin_email": "admin@integration-ministry.test",
            "admin_full_name": "خالد المطيري",
            "admin_password": "Provision@2026",
        },
        headers=KEY_HEADER,
    )
    newcomer = token_for("admin@integration-ministry.test", "Provision@2026")
    seeded = token_for(
        "admin@digital-services.test", settings.dev_seed_password
    )

    # موظف من الجهة المزروعة يرفع ملفًا ويبدأ محادثة.
    client.post(
        "/api/files",
        files={"file": ("سري.txt", BUDGET_TEXT.encode(), "text/plain")},
        headers=seeded,
    )
    conversation_id = client.post(
        "/api/chat", json={"message": "سؤال داخلي"}, headers=seeded
    ).json()["conversation_id"]

    # الجهة الجديدة لا ترى شيئًا من ذلك.
    assert client.get("/api/users", headers=newcomer).json()["total"] == 1
    assert client.get("/api/files", headers=newcomer).json()["page"]["total"] == 0
    assert (
        client.get("/api/conversations", headers=newcomer).json()["page"]["total"]
        == 0
    )
    assert (
        client.get(
            f"/api/conversations/{conversation_id}", headers=newcomer
        ).status_code
        == 404
    )
    assert client.get("/api/organizations/1", headers=newcomer).status_code == 404

    # ولا يستشهد ردها بملف الجهة الأخرى.
    answer = client.post(
        "/api/chat",
        json={"message": "كم بلغت مصروفات التشغيل؟"},
        headers=newcomer,
    )
    assert answer.json()["sources"] == []
    assert "سري.txt" not in answer.text


def test_an_expiring_subscription_stops_a_working_session():
    """رحلة عاملة تتوقف فور انتهاء الاشتراك، ثم تعود بالتجديد."""
    client.post(
        "/api/organizations",
        json={
            "name": "وزارة التكامل",
            "slug": "integration-ministry",
            "admin_email": "admin@integration-ministry.test",
            "admin_full_name": "خالد المطيري",
            "admin_password": "Provision@2026",
        },
        headers=KEY_HEADER,
    )
    admin = token_for("admin@integration-ministry.test", "Provision@2026")
    organization_id = client.get("/api/auth/me", headers=admin).json()[
        "organization_id"
    ]
    assert client.get("/api/users", headers=admin).status_code == 200

    # الاشتراك يُوقَف من مسار التجهيز.
    client.patch(
        f"/api/organizations/{organization_id}/subscription",
        json={"status": "expired"},
        headers=KEY_HEADER,
    )

    # الرمز نفسه لم يعد يعمل، والرسالة تشرح السبب لا رمز خطأ عام.
    blocked = client.get("/api/users", headers=admin)
    assert blocked.status_code == 403
    assert "اشتراك جهتك" in blocked.json()["detail"]
    assert blocked.json()["code"] == "forbidden"

    # لكن قراءة الحساب والاشتراك تبقى متاحة ليعرف المسؤول السبب.
    assert client.get("/api/auth/me", headers=admin).status_code == 200
    state = client.get(
        f"/api/organizations/{organization_id}/subscription", headers=admin
    ).json()
    assert state["is_usable"] is False
    assert state["blocked_reason"]

    # التجديد يعيد الخدمة.
    client.patch(
        f"/api/organizations/{organization_id}/subscription",
        json={"status": "active"},
        headers=KEY_HEADER,
    )
    assert client.get("/api/users", headers=admin).status_code == 200
