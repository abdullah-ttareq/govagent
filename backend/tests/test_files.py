"""اختبارات رفع الملفات وبياناتها وحدودها وصلاحياتها (مهمة P2-03).

**سياسة الصلاحيات المُختبَرة هنا:**

* القراءة داخل الجهة لكل موظفيها — لتوازي صلاحية المصدر صلاحية محتواه.
* الحذف لرافع الملف أو لمسؤول الجهة فقط.
* أي موظف من جهة أخرى: 404 بلا تسريب (في `tests/test_isolation.py`).
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.conversation_store import MemoryConversationStore
from app.services.file_store import MemoryFileStore
from app.services.retrieval import MemoryChunkStore
from app.services.text_extraction import SUPPORTED_EXTENSIONS
from app.services.user_store import MemoryUserStore

client = TestClient(app)

EMPLOYEE_A = "n.alharbi@digital-services.test"
COLLEAGUE_A = "f.alqahtani@digital-services.test"
ADMIN_A = "admin@digital-services.test"

BUDGET_TEXT = (
    "تقرير الميزانية السنوية للجهة.\n\n"
    "بلغت مصروفات التشغيل مبلغ مليون ريال خلال السنة المالية.\n\n"
    "وتشمل الميزانية بند الصيانة وبند التدريب."
)


@pytest.fixture(autouse=True)
def clean_stores(tmp_path, monkeypatch):
    """مخازن نظيفة ومجلد رفع مؤقت — لا يُكتب شيء داخل المستودع."""
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
def employee() -> dict[str, str]:
    return auth_header(EMPLOYEE_A)


@pytest.fixture
def colleague() -> dict[str, str]:
    return auth_header(COLLEAGUE_A)


@pytest.fixture
def admin() -> dict[str, str]:
    return auth_header(ADMIN_A)


def upload(
    headers,
    *,
    name: str = "ميزانية.txt",
    content: bytes | None = None,
    data: dict | None = None,
):
    payload = BUDGET_TEXT.encode("utf-8") if content is None else content
    return client.post(
        "/api/files",
        files={"file": (name, payload, "text/plain")},
        data=data or {},
        headers=headers,
    )


def my_id(headers: dict[str, str]) -> int:
    return client.get("/api/auth/me", headers=headers).json()["id"]


# ---------------------------------------------------------------------------
# الرفع الناجح
# ---------------------------------------------------------------------------
def test_upload_stores_metadata_and_indexes_the_file(employee):
    response = upload(employee)

    assert response.status_code == 201
    body = response.json()
    assert body["file"]["original_name"] == "ميزانية.txt"
    assert body["file"]["mime_type"].startswith("text/plain")
    assert body["file"]["size_bytes"] == len(BUDGET_TEXT.encode("utf-8"))
    assert body["file"]["status"] == "processed"
    assert body["file"]["uploaded_by"] == my_id(employee)
    assert body["file"]["can_modify"] is True
    assert body["chunk_count"] >= 1
    assert body["indexing_error"] is None


def test_the_storage_path_is_never_exposed(employee):
    body = upload(employee).text
    assert "storage_path" not in body
    assert settings.upload_dir not in body


def test_the_file_lands_on_disk_under_its_organization(employee):
    upload(employee)

    root = Path(settings.upload_dir)
    stored = list(root.rglob("*.txt"))
    assert len(stored) == 1
    # مقسّم بالجهة، والاسم عشوائي لا اسم الموظف الأصلي.
    assert stored[0].parent.name == "1"
    assert "ميزانية" not in stored[0].name
    assert stored[0].read_bytes() == BUDGET_TEXT.encode("utf-8")


def test_a_malicious_filename_never_escapes_the_upload_folder(employee):
    """اسم مثل ‎../../.env‎ كان سيكتب خارج مجلد الرفع."""
    response = upload(employee, name="../../../evil.txt")

    assert response.status_code == 201
    root = Path(settings.upload_dir).resolve()
    written = list(root.rglob("*.txt"))
    assert len(written) == 1
    assert written[0].resolve().is_relative_to(root)
    # الاسم الأصلي محفوظ كبيان وصفي فقط.
    assert response.json()["file"]["original_name"] == "../../../evil.txt"


def test_an_uploaded_file_becomes_searchable_in_chat(employee):
    upload(employee)

    response = client.post(
        "/api/chat", json={"message": "كم بلغت مصروفات التشغيل؟"}, headers=employee
    )

    assert response.status_code == 200
    names = {source["file_name"] for source in response.json()["sources"]}
    assert "ميزانية.txt" in names


# ---------------------------------------------------------------------------
# سياسة الصلاحيات: القراءة داخل الجهة
# ---------------------------------------------------------------------------
def test_a_colleague_can_read_the_file_metadata(employee, colleague):
    """القراءة داخل الجهة: زميل يقرأ بيانات ملف رفعه غيره."""
    file_id = upload(employee).json()["file"]["id"]

    response = client.get(f"/api/files/{file_id}", headers=colleague)

    assert response.status_code == 200
    body = response.json()
    assert body["original_name"] == "ميزانية.txt"
    assert body["uploaded_by"] == my_id(employee)
    # لكنه لا يملك حذفه.
    assert body["can_modify"] is False


def test_the_list_shows_the_whole_organization(employee, colleague):
    upload(employee, name="ملف-الأول.txt")
    upload(colleague, name="ملف-الثاني.txt")

    for headers in (employee, colleague):
        listing = client.get("/api/files", headers=headers).json()
        assert listing["page"]["total"] == 2
        assert {item["original_name"] for item in listing["files"]} == {
            "ملف-الأول.txt",
            "ملف-الثاني.txt",
        }


def test_uploaded_by_filters_the_list_to_my_files(employee, colleague):
    upload(employee, name="ملفي.txt")
    upload(colleague, name="ملف-الزميل.txt")

    mine = client.get(
        "/api/files", params={"uploaded_by": my_id(employee)}, headers=employee
    ).json()

    assert [item["original_name"] for item in mine["files"]] == ["ملفي.txt"]


def test_the_conversation_link_is_visible_to_the_uploader_only(employee, colleague):
    """ارتباط الملف بمحادثة جزء من خصوصية المحادثة لا من بيانات الملف."""
    conversation_id = client.post(
        "/api/conversations", json={"title": "مراجعة خاصة"}, headers=employee
    ).json()["id"]
    file_id = upload(
        employee, data={"conversation_id": str(conversation_id)}
    ).json()["file"]["id"]

    mine = client.get(f"/api/files/{file_id}", headers=employee).json()
    theirs = client.get(f"/api/files/{file_id}", headers=colleague).json()

    assert mine["conversation_id"] == conversation_id
    assert theirs["conversation_id"] is None


# ---------------------------------------------------------------------------
# سياسة الصلاحيات: الحذف للرافع أو لمسؤول الجهة
# ---------------------------------------------------------------------------
def test_the_uploader_can_delete_its_own_file(employee):
    file_id = upload(employee).json()["file"]["id"]

    removed = client.delete(f"/api/files/{file_id}", headers=employee)

    assert removed.status_code == 200
    assert client.get(f"/api/files/{file_id}", headers=employee).status_code == 404


def test_the_organization_admin_can_delete_any_file(employee, admin):
    file_id = upload(employee).json()["file"]["id"]

    assert client.get(f"/api/files/{file_id}", headers=admin).json()["can_modify"]
    assert client.delete(f"/api/files/{file_id}", headers=admin).status_code == 200


def test_a_colleague_cannot_delete_someone_elses_file(employee, colleague):
    """القراءة مشتركة، أما إزالة معرفة من الجهة فقرار لصاحبها أو لمن يديرها."""
    file_id = upload(employee).json()["file"]["id"]

    response = client.delete(f"/api/files/{file_id}", headers=colleague)

    assert response.status_code == 403
    assert "رافعه أو لمسؤول الجهة" in response.json()["detail"]
    # والملف باقٍ فعلًا.
    assert client.get(f"/api/files/{file_id}", headers=employee).status_code == 200


def test_deleting_a_file_removes_it_from_search(employee):
    """مقاطع باقية بعد الحذف تعني مصدرًا يُستشهد به من ملف لم يعد موجودًا."""
    file_id = upload(employee).json()["file"]["id"]
    question = {"message": "كم بلغت مصروفات التشغيل؟"}

    before = client.post("/api/chat", json=question, headers=employee).json()
    assert before["sources"]

    client.delete(f"/api/files/{file_id}", headers=employee)

    after = client.post("/api/chat", json=question, headers=employee).json()
    assert after["sources"] == []


def test_deleting_a_file_removes_it_from_disk(employee):
    upload(employee)
    file_id = client.get("/api/files", headers=employee).json()["files"][0]["id"]
    assert list(Path(settings.upload_dir).rglob("*.txt"))

    client.delete(f"/api/files/{file_id}", headers=employee)

    assert list(Path(settings.upload_dir).rglob("*.txt")) == []


# ---------------------------------------------------------------------------
# الحدود
# ---------------------------------------------------------------------------
def test_an_unsupported_extension_is_refused_with_415(employee):
    response = upload(employee, name="صورة.png", content=b"\x89PNG\r\n")

    assert response.status_code == 415
    detail = response.json()["detail"]
    assert "غير مدعومة" in detail
    for extension in SUPPORTED_EXTENSIONS:
        assert extension in detail


def test_a_file_without_an_extension_is_refused(employee):
    assert upload(employee, name="تقرير").status_code == 415


def test_a_file_over_the_limit_is_refused_with_413(employee, monkeypatch):
    monkeypatch.setattr(settings, "upload_max_bytes", 100)

    response = upload(employee, content=b"x" * 101)

    assert response.status_code == 413
    detail = response.json()["detail"]
    assert "يتجاوز الحد" in detail
    # الرسالة تذكر الحجمين لا رقمًا مجردًا.
    assert "بايت" in detail or "كيلوبايت" in detail


def test_an_oversized_file_is_never_written_to_disk(employee, monkeypatch):
    monkeypatch.setattr(settings, "upload_max_bytes", 100)
    upload(employee, content=b"x" * 101)

    assert list(Path(settings.upload_dir).rglob("*")) == []


def test_an_empty_file_is_refused(employee):
    response = upload(employee, content=b"")
    assert response.status_code == 422
    assert "فارغ" in response.json()["detail"]


# ---------------------------------------------------------------------------
# فشل الفهرسة لا يُفشل الرفع
# ---------------------------------------------------------------------------
def test_a_file_with_no_text_is_saved_but_marked_failed(employee):
    response = upload(employee, content="   \n  \n".encode())

    assert response.status_code == 201
    body = response.json()
    assert body["file"]["status"] == "failed"
    assert body["chunk_count"] == 0
    assert body["indexing_error"]
    # ومع ذلك الملف محفوظ على القرص وقابل للقراءة.
    assert (
        client.get(f"/api/files/{body['file']['id']}", headers=employee).status_code
        == 200
    )


def test_an_embedding_failure_does_not_lose_the_file(employee, monkeypatch):
    def boom(**_kwargs):
        raise RuntimeError("تعذّر الوصول إلى مزود المتجهات.")

    monkeypatch.setattr("app.services.document_service.ingest_document", boom)

    response = upload(employee)

    assert response.status_code == 201
    assert response.json()["file"]["status"] == "failed"
    assert "المتجهات" in response.json()["indexing_error"]
    assert len(list(Path(settings.upload_dir).rglob("*.txt"))) == 1


# ---------------------------------------------------------------------------
# القراءة والربط بالمحادثة
# ---------------------------------------------------------------------------
def test_files_are_listed_newest_first(employee):
    for index in range(3):
        upload(employee, name=f"ملف-{index}.txt")

    listing = client.get("/api/files", headers=employee).json()

    assert listing["page"]["total"] == 3
    assert [item["original_name"] for item in listing["files"]] == [
        "ملف-2.txt",
        "ملف-1.txt",
        "ملف-0.txt",
    ]


def test_a_file_can_be_attached_to_a_conversation(employee):
    conversation_id = client.post(
        "/api/conversations", json={"title": "مراجعة"}, headers=employee
    ).json()["id"]

    response = upload(employee, data={"conversation_id": str(conversation_id)})

    assert response.status_code == 201
    assert response.json()["file"]["conversation_id"] == conversation_id

    scoped = client.get(
        "/api/files", params={"conversation_id": conversation_id}, headers=employee
    ).json()
    assert scoped["page"]["total"] == 1


def test_attaching_to_someone_elses_conversation_is_refused(employee, colleague):
    """المحادثات تبقى خاصة بمالكها حتى بعد فتح قراءة الملفات للجهة."""
    conversation_id = client.post(
        "/api/conversations", json={"title": "خاصة"}, headers=colleague
    ).json()["id"]

    response = upload(employee, data={"conversation_id": str(conversation_id)})

    assert response.status_code == 404
    # ولم يُكتب شيء على القرص لطلب مرفوض.
    assert list(Path(settings.upload_dir).rglob("*.txt")) == []


def test_listing_by_someone_elses_conversation_is_refused(employee, colleague):
    conversation_id = client.post(
        "/api/conversations", json={"title": "خاصة"}, headers=colleague
    ).json()["id"]

    response = client.get(
        "/api/files", params={"conversation_id": conversation_id}, headers=employee
    )
    assert response.status_code == 404


def test_file_routes_require_a_token():
    assert client.get("/api/files").status_code == 401
    assert client.get("/api/files/1").status_code == 401
    assert client.delete("/api/files/1").status_code == 401
    assert (
        client.post(
            "/api/files", files={"file": ("a.txt", b"data", "text/plain")}
        ).status_code
        == 401
    )
