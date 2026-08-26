"""عزل البيانات بين الجهات (مهمة P2-02، الشرط الخامس).

يثبت هذا الملف أن مستخدم جهة (أ) لا يستطيع **قراءة ولا تعديل ولا تعطيل** أي
سجل يخص جهة (ب)، وأن المحاولة تعيد 404 بلا تسريب أي بيان.

**لماذا 404 لا 403؟** «ممنوع» تؤكد أن السجل موجود، وهذه في ذاتها معلومة عن
جهة أخرى: تكشف أن الموظف فلانًا مسجّل هناك. «غير موجود» لا تكشف شيئًا. شرط
الإنجاز يقبل أيًّا منهما، والاختيار هنا هو الأشد.

**نطاقان مختلفان داخل الجهة الواحدة:**

* **المحادثات خاصة بمالكها** — زميل في الجهة نفسها لا يراها.
* **الملفات معرفةٌ مشتركة داخل الجهة** — يقرأ بياناتها كل موظفيها، لأن
  محتواها متاح لهم أصلًا عبر البحث المتجهي. حذفها للرافع أو لمسؤول الجهة.

الجهتان من `mock-data/organizations.json`:
* (أ) `digital-services` — معرّفها ١
* (ب) `urban-planning` — معرّفها ٢
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token
from app.main import app
from app.services.conversation_store import MemoryConversationStore
from app.services.file_store import MemoryFileStore
from app.services.retrieval import MemoryChunkStore
from app.services.user_store import MemoryUserStore, get_user_store

client = TestClient(app)

ORG_A, ORG_B = 1, 2
ADMIN_A = "admin@digital-services.test"
EMPLOYEE_A = "n.alharbi@digital-services.test"
ADMIN_B = "admin@urban-planning.test"
EMPLOYEE_B = "l.aldosari@urban-planning.test"


@pytest.fixture(autouse=True)
def clean_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    for store in (MemoryUserStore, MemoryConversationStore, MemoryFileStore):
        store.reset()
    MemoryChunkStore.clear()
    yield
    for store in (MemoryUserStore, MemoryConversationStore, MemoryFileStore):
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
def admin_a() -> dict[str, str]:
    return auth_header(ADMIN_A)


@pytest.fixture
def admin_b() -> dict[str, str]:
    return auth_header(ADMIN_B)


@pytest.fixture
def employee_a() -> dict[str, str]:
    return auth_header(EMPLOYEE_A)


@pytest.fixture
def user_ids() -> dict[str, int]:
    """معرّفات المستخدمين من المخزن مباشرة، لا عبر مسار محمي."""
    store = get_user_store()
    return {
        user.email: user.id
        for organization_id in (ORG_A, ORG_B)
        for user in store.list_users(organization_id=organization_id)
    }


# ---------------------------------------------------------------------------
# ١) سجلات المستخدمين
# ---------------------------------------------------------------------------
def test_admin_a_cannot_read_a_user_of_organization_b(admin_a, user_ids):
    """شرط الإنجاز: محاولة الوصول إلى سجل جهة أخرى تعيد 404، لا بيانات."""
    response = client.get(f"/api/users/{user_ids[EMPLOYEE_B]}", headers=admin_a)

    assert response.status_code == 404
    body = response.text
    assert EMPLOYEE_B not in body
    assert "لمياء" not in body


def test_admin_a_cannot_edit_a_user_of_organization_b(admin_a, user_ids):
    target = user_ids[EMPLOYEE_B]

    response = client.patch(
        f"/api/users/{target}", json={"full_name": "اسم مفروض"}, headers=admin_a
    )

    assert response.status_code == 404
    # والسجل لم يتغيّر فعلًا في جهته.
    assert get_user_store().get_user(
        user_id=target, organization_id=ORG_B
    ).full_name == "لمياء الدوسري"


def test_admin_a_cannot_promote_a_user_of_organization_b(admin_a, user_ids):
    target = user_ids[EMPLOYEE_B]

    response = client.patch(
        f"/api/users/{target}", json={"role": "admin"}, headers=admin_a
    )

    assert response.status_code == 404
    assert get_user_store().get_user(
        user_id=target, organization_id=ORG_B
    ).role == "employee"


def test_admin_a_cannot_deactivate_a_user_of_organization_b(admin_a, user_ids):
    target = user_ids[EMPLOYEE_B]

    response = client.delete(f"/api/users/{target}", headers=admin_a)

    assert response.status_code == 404
    # والحساب ما زال يعمل: تسجيل دخوله ينجح.
    assert get_user_store().get_user(
        user_id=target, organization_id=ORG_B
    ).is_active is True


def test_employee_a_cannot_reach_a_user_of_organization_b(employee_a, user_ids):
    """الموظف كذلك، لا المسؤول وحده."""
    assert (
        client.get(f"/api/users/{user_ids[EMPLOYEE_B]}", headers=employee_a).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/users/{user_ids[EMPLOYEE_B]}",
            json={"full_name": "س"},
            headers=employee_a,
        ).status_code
        == 404
    )


def test_the_users_list_never_crosses_organizations(admin_a, admin_b):
    """شرط الإنجاز: كل استعلام قراءة مقيّد بجهة صاحب الرمز."""
    listing_a = client.get("/api/users", headers=admin_a).json()
    listing_b = client.get("/api/users", headers=admin_b).json()

    emails_a = {user["email"] for user in listing_a["users"]}
    emails_b = {user["email"] for user in listing_b["users"]}

    assert emails_a.isdisjoint(emails_b)
    assert {user["organization_id"] for user in listing_a["users"]} == {ORG_A}
    assert {user["organization_id"] for user in listing_b["users"]} == {ORG_B}
    assert EMPLOYEE_B not in emails_a


# ---------------------------------------------------------------------------
# ٢) سجلات الجهات
# ---------------------------------------------------------------------------
def test_admin_a_cannot_read_organization_b(admin_a):
    response = client.get(f"/api/organizations/{ORG_B}", headers=admin_a)

    assert response.status_code == 404
    assert "التخطيط العمراني" not in response.text
    assert "urban-planning" not in response.text


def test_admin_a_cannot_edit_organization_b(admin_a):
    response = client.patch(
        f"/api/organizations/{ORG_B}", json={"name": "اسم مفروض"}, headers=admin_a
    )

    assert response.status_code == 404
    assert get_user_store().get_organization(ORG_B).name == "مركز التخطيط العمراني"


def test_a_nonexistent_organization_looks_the_same_as_another_ones(admin_a):
    """الجهة غير الموجودة والجهة الأخرى تعطيان الرد نفسه — لا تعداد للجهات."""
    other = client.get(f"/api/organizations/{ORG_B}", headers=admin_a)
    missing = client.get("/api/organizations/999999", headers=admin_a)

    assert other.status_code == missing.status_code == 404
    assert other.json()["detail"] == missing.json()["detail"]


# ---------------------------------------------------------------------------
# ٣) الجهة تأتي من الرمز لا من جسم الطلب
# ---------------------------------------------------------------------------
def test_no_request_schema_accepts_an_organization_id():
    """شرط الإنجاز: organization_id لا يُقرأ من جسم الطلب في أي مسار.

    يُفحص من مواصفة OpenAPI نفسها لا من مسار بعينه، فيغطي كل الطلبات الحالية
    وأي طلب يُضاف لاحقًا.
    """
    spec = client.get("/openapi.json").json()

    offenders = [
        f"{name}.{field}"
        for name, schema in spec["components"]["schemas"].items()
        if name.endswith("Request")
        for field in schema.get("properties", {})
        if field == "organization_id"
    ]

    assert offenders == []


def test_an_injected_organization_id_in_the_body_is_ignored(admin_a):
    """حقل دخيل في الطلب لا يغيّر الجهة: الـschema تتجاهله والرمز يحسم."""
    response = client.post(
        "/api/users",
        json={
            "email": "injected@digital-services.test",
            "full_name": "محاولة حقن",
            "role": "employee",
            "password": "Injected@2026",
            "organization_id": ORG_B,
        },
        headers=admin_a,
    )

    assert response.status_code == 201
    assert response.json()["organization_id"] == ORG_A
    # ولم يُنشأ شيء في جهة (ب).
    assert get_user_store().find_user_by_email(
        organization_id=ORG_B, email="injected@digital-services.test"
    ) is None


def test_a_forged_organization_in_the_token_reaches_nothing(user_ids):
    """رمز موقّع بجهة غير جهة صاحبه لا يفتح شيئًا.

    الحالة الأخطر: من يسرّب سر التوقيع يستطيع صياغة الحمولة. الحماية أن هوية
    المستخدم تُقرأ من المخزن بشرط (المعرّف **و** الجهة) معًا، فالمزج بينهما
    لا يطابق أي صف.
    """
    token, _ = create_access_token(
        user_id=user_ids[ADMIN_A], organization_id=ORG_B, role="admin"
    )
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.get("/api/users", headers=headers).status_code == 401
    assert client.get(f"/api/organizations/{ORG_B}", headers=headers).status_code == 401


def test_organization_b_stays_untouched_after_every_attempt(admin_a, user_ids):
    """حصيلة نهائية: بعد كل المحاولات أعلاه، جهة (ب) كما كانت."""
    target = user_ids[EMPLOYEE_B]
    for attempt in (
        lambda: client.get(f"/api/users/{target}", headers=admin_a),
        lambda: client.patch(
            f"/api/users/{target}", json={"full_name": "x", "role": "admin"}, headers=admin_a
        ),
        lambda: client.delete(f"/api/users/{target}", headers=admin_a),
        lambda: client.patch(
            f"/api/organizations/{ORG_B}", json={"slug": "hijacked"}, headers=admin_a
        ),
    ):
        assert attempt().status_code == 404

    store = get_user_store()
    user = store.get_user(user_id=target, organization_id=ORG_B)
    organization = store.get_organization(ORG_B)

    assert user.full_name == "لمياء الدوسري"
    assert user.role == "employee"
    assert user.is_active is True
    assert organization.slug == "urban-planning"
    assert len(store.list_users(organization_id=ORG_B)) == 3

# ---------------------------------------------------------------------------
# ٤) المحادثات والملفات — العزل هنا **بالمالك** لا بالجهة وحدها
# ---------------------------------------------------------------------------
COLLEAGUE_A = "f.alqahtani@digital-services.test"


@pytest.fixture
def colleague_a() -> dict[str, str]:
    return auth_header(COLLEAGUE_A)


def start_conversation(headers: dict[str, str], message: str) -> int:
    """يبدأ محادثة عبر /api/chat ويعيد معرّفها."""
    response = client.post("/api/chat", json={"message": message}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["conversation_id"]


def upload_file(headers: dict[str, str], name: str) -> int:
    response = client.post(
        "/api/files",
        files={"file": (name, "محتوى تجريبي للبحث".encode(), "text/plain")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["file"]["id"]


def test_a_colleague_in_the_same_organization_cannot_reach_a_conversation(
    employee_a, colleague_a
):
    """المحادثة خاصة بصاحبها، لا بجهته — أضيق من بقية قواعد المشروع."""
    conversation_id = start_conversation(employee_a, "سؤال خاص عن راتبي")

    for method, path, body in (
        ("GET", f"/api/conversations/{conversation_id}", None),
        ("GET", f"/api/conversations/{conversation_id}/messages", None),
        ("PATCH", f"/api/conversations/{conversation_id}", {"title": "مفروض"}),
        ("DELETE", f"/api/conversations/{conversation_id}", None),
    ):
        response = client.request(method, path, json=body, headers=colleague_a)
        assert response.status_code == 404, (method, path)
        assert "راتبي" not in response.text

    # والمحادثة سليمة عند صاحبها بعد كل المحاولات.
    intact = client.get(
        f"/api/conversations/{conversation_id}", headers=employee_a
    )
    assert intact.status_code == 200
    assert intact.json()["message_count"] == 2


def test_an_admin_cannot_read_an_employee_conversation(admin_a, employee_a):
    """حتى مسؤول الجهة: الإدارة تشمل الحسابات لا محتوى المحادثات."""
    conversation_id = start_conversation(employee_a, "سؤال خاص")

    response = client.get(
        f"/api/conversations/{conversation_id}", headers=admin_a
    )
    assert response.status_code == 404


def test_a_user_of_organization_b_cannot_reach_a_conversation_of_a(
    employee_a, admin_b
):
    conversation_id = start_conversation(employee_a, "سؤال داخلي")

    assert (
        client.get(
            f"/api/conversations/{conversation_id}", headers=admin_b
        ).status_code
        == 404
    )


def test_conversation_lists_never_cross_owners(employee_a, colleague_a):
    start_conversation(employee_a, "محادثة الموظف الأول")
    start_conversation(colleague_a, "محادثة الموظف الثاني")

    mine = client.get("/api/conversations", headers=employee_a).json()
    theirs = client.get("/api/conversations", headers=colleague_a).json()

    assert mine["page"]["total"] == 1
    assert theirs["page"]["total"] == 1
    assert mine["conversations"][0]["title"] == "محادثة الموظف الأول"
    assert theirs["conversations"][0]["title"] == "محادثة الموظف الثاني"


def test_a_colleague_reads_a_file_but_cannot_delete_it(employee_a, colleague_a):
    """الملفات معرفةٌ مشتركة داخل الجهة: القراءة للجميع والحذف للرافع."""
    file_id = upload_file(employee_a, "مشترك.txt")

    read = client.get(f"/api/files/{file_id}", headers=colleague_a)
    assert read.status_code == 200
    assert read.json()["original_name"] == "مشترك.txt"
    assert read.json()["can_modify"] is False

    removed = client.delete(f"/api/files/{file_id}", headers=colleague_a)
    assert removed.status_code == 403


def test_file_lists_cover_the_organization_not_the_owner(
    employee_a, colleague_a
):
    upload_file(employee_a, "ملف-الأول.txt")
    upload_file(colleague_a, "ملف-الثاني.txt")

    for headers in (employee_a, colleague_a):
        listing = client.get("/api/files", headers=headers).json()
        assert {f["original_name"] for f in listing["files"]} == {
            "ملف-الأول.txt",
            "ملف-الثاني.txt",
        }


def test_an_admin_may_delete_a_file_it_did_not_upload(employee_a, admin_a):
    """إدارة الجهة تشمل معرفتها المشتركة، بخلاف المحادثات الخاصة."""
    file_id = upload_file(employee_a, "ملف-الموظف.txt")

    assert client.delete(f"/api/files/{file_id}", headers=admin_a).status_code == 200


def test_a_user_of_organization_b_cannot_read_a_file_of_a(employee_a, admin_b):
    file_id = upload_file(employee_a, "داخلي.txt")

    assert client.get(f"/api/files/{file_id}", headers=admin_b).status_code == 404
    # ولا يحذفه: 404 لا 403 — لا يُكشف وجوده أصلًا.
    assert client.delete(f"/api/files/{file_id}", headers=admin_b).status_code == 404


def test_every_cited_source_is_readable_by_the_asker(employee_a, colleague_a):
    """شرط التطابق: كل ملف يظهر في sources يستطيع قارئ الرد الاستعلام عنه.

    البحث المتجهي مقيّد بالجهة لا بالمالك، فلو بقيت بيانات الملف خاصة
    بالرافع لظهر في المصادر ملفٌ يعيد 404 عند الاستعلام عنه — مصدرٌ مجهول
    لقارئه. هذا الاختبار يمنع رجوع ذلك التعارض.
    """
    client.post(
        "/api/files",
        files={
            "file": (
                "ميزانية.txt",
                "بلغت مصروفات التشغيل مليون ريال هذا العام.".encode(),
                "text/plain",
            )
        },
        headers=employee_a,
    )

    # يسأل **زميل آخر** في الجهة نفسها، لا رافع الملف.
    answer = client.post(
        "/api/chat",
        json={"message": "كم بلغت مصروفات التشغيل؟"},
        headers=colleague_a,
    )
    assert answer.status_code == 200
    sources = answer.json()["sources"]
    assert sources

    for source in sources:
        details = client.get(f"/api/files/{source['file_id']}", headers=colleague_a)
        assert details.status_code == 200, source["file_id"]
        assert details.json()["original_name"] == source["file_name"]


def test_sources_never_cite_another_organizations_file(employee_a, admin_b):
    """جهة (ب) لا ترى ملف جهة (أ) لا في المصادر ولا بالاستعلام المباشر."""
    response = client.post(
        "/api/files",
        files={
            "file": (
                "سري-أ.txt",
                "بلغت مصروفات التشغيل مليون ريال هذا العام.".encode(),
                "text/plain",
            )
        },
        headers=employee_a,
    )
    file_id = response.json()["file"]["id"]

    answer = client.post(
        "/api/chat",
        json={"message": "كم بلغت مصروفات التشغيل؟"},
        headers=admin_b,
    )
    assert answer.json()["sources"] == []
    assert "سري-أ.txt" not in answer.text

    assert client.get(f"/api/files/{file_id}", headers=admin_b).status_code == 404
    assert client.delete(f"/api/files/{file_id}", headers=admin_b).status_code == 404
