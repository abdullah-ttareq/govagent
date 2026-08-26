"""اختبارات معالجة الأخطاء الموحّدة وتوثيق Swagger (مهمة P2-05).

**شرطا الإنجاز المُختبَران هنا:**

* خطأ داخلي يعطي رسالة عربية عامة بلا تسريب تفاصيل.
* `/docs` تعرض كل المسارات موصوفة بالعربية مع زر Authorize.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.errors import ARABIC_MESSAGES, ERROR_CODES
from app.core.config import settings
from app.main import app
from app.services.audit_store import MemoryAuditStore
from app.services.conversation_store import MemoryConversationStore
from app.services.file_store import MemoryFileStore
from app.services.organization_settings_store import (
    MemoryOrganizationSettingsStore,
)
from app.services.retrieval import MemoryChunkStore
from app.services.user_store import MemoryUserStore

client = TestClient(app)

#: عميل لا يعيد رفع استثناءات السيرفر، فيمر الخطأ بمعالج 500 كما في التشغيل.
failing_client = TestClient(app, raise_server_exceptions=False)

ADMIN_A = "admin@digital-services.test"
EXPIRED_ADMIN = "admin@national-archive.test"

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


def auth_header(email: str = ADMIN_A) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": settings.dev_seed_password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def assert_envelope(response, *, status: int) -> dict:
    """يتحقق من الغلاف الموحّد ويعيد جسم الرد."""
    assert response.status_code == status
    body = response.json()

    assert set(body) == {"detail", "status", "code", "errors"}
    assert isinstance(body["detail"], str) and body["detail"].strip()
    assert body["status"] == status
    assert body["code"] == ERROR_CODES[status]
    assert isinstance(body["errors"], list)
    return body


def is_arabic(text: str) -> bool:
    return any("؀" <= character <= "ۿ" for character in text)


# ---------------------------------------------------------------------------
# ١) شكل واحد لكل الحالات
# ---------------------------------------------------------------------------
def test_every_status_uses_the_same_envelope():
    """شرط الإنجاز: شكل رد خطأ واحد لكل المسارات."""
    admin = auth_header()
    cases = [
        # 400: جسم الطلب ليس JSON صالحًا.
        (400, lambda: client.post(
            "/api/auth/login",
            content="{not json",
            headers={"Content-Type": "application/json"},
        )),
        # 401: بلا رمز دخول.
        (401, lambda: client.get("/api/users")),
        # 403: موظف يطلب مسارًا للمسؤول.
        (403, lambda: client.get(
            "/api/audit-logs",
            headers=auth_header("n.alharbi@digital-services.test"),
        )),
        # 404: مسار غير موجود أصلًا.
        (404, lambda: client.get("/api/does-not-exist")),
        # 405: طريقة غير مسموحة.
        (405, lambda: client.delete("/health")),
        # 409: بريد مكرر.
        (409, lambda: client.post(
            "/api/users",
            json={
                "email": ADMIN_A,
                "full_name": "تكرار",
                "role": "employee",
                "password": "Employee@2026",
            },
            headers=admin,
        )),
        # 422: حقل مرفوض.
        (422, lambda: client.post(
            "/api/auth/login", json={"email": "not-an-email", "password": "x"}
        )),
    ]

    for status, call in cases:
        body = assert_envelope(call(), status=status)
        assert is_arabic(body["detail"]), (status, body["detail"])


def test_a_service_failure_uses_the_envelope_too():
    """503 من مزود المودل يمر بالغلاف نفسه."""
    response = client.post(
        "/api/chat",
        json={"message": "سؤال"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert_envelope(response, status=401)


def test_unknown_routes_and_methods_answer_in_arabic():
    """رسائل Starlette الافتراضية إنجليزية، فتُستبدل."""
    missing = assert_envelope(client.get("/api/does-not-exist"), status=404)
    wrong_method = assert_envelope(client.delete("/health"), status=405)

    assert missing["detail"] == ARABIC_MESSAGES[404]
    assert wrong_method["detail"] == ARABIC_MESSAGES[405]
    assert "Not Found" not in missing["detail"]
    assert "Method Not Allowed" not in wrong_method["detail"]


def test_the_unauthorized_header_survives_the_handler():
    """ترويسة WWW-Authenticate جزء من عقد 401 القياسي."""
    response = client.get("/api/users")

    assert_envelope(response, status=401)
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_route_message_is_not_replaced_by_the_default():
    """رسائل المسارات تمر كما هي؛ الاستبدال للرسائل الإنجليزية وحدها."""
    body = assert_envelope(client.get("/api/users"), status=401)
    assert "Authorization" in body["detail"]
    assert body["detail"] != ARABIC_MESSAGES[404]


# ---------------------------------------------------------------------------
# ٢) شرط الإنجاز: خطأ داخلي بلا تسريب
# ---------------------------------------------------------------------------
def test_an_internal_error_leaks_nothing(monkeypatch):
    """شرط الإنجاز: رسالة عربية عامة بلا Stack Trace ولا تفاصيل داخلية."""

    def boom():
        raise RuntimeError(
            "ORA-01017 user=govagent password=super-secret dsn=prod:1521/DB"
        )

    monkeypatch.setattr("app.api.health.check_status", boom)

    response = failing_client.get("/health")
    body = assert_envelope(response, status=500)
    raw = response.text

    assert body["detail"] == ARABIC_MESSAGES[500]
    assert is_arabic(body["detail"])
    for leak in (
        "RuntimeError",
        "Traceback",
        "super-secret",
        "ORA-01017",
        "prod:1521",
        "govagent",
        "app/api/health.py",
        "boom",
    ):
        assert leak not in raw, leak


def test_the_internal_error_is_logged_on_the_server(monkeypatch, caplog):
    """ما يُحجب عن المستخدم يجب ألا يضيع عن مسؤول السيرفر."""
    import logging

    def boom():
        raise RuntimeError("سبب داخلي مفصّل")

    monkeypatch.setattr("app.api.health.check_status", boom)

    with caplog.at_level(logging.ERROR, logger="app.api.errors"):
        failing_client.get("/health")

    assert any("خطأ غير متوقع" in item.getMessage() for item in caplog.records)
    assert any(item.exc_info for item in caplog.records)


# ---------------------------------------------------------------------------
# ٣) أخطاء التحقق: عربية، وبلا صدى للمُدخَلات
# ---------------------------------------------------------------------------
def test_validation_errors_never_echo_the_submitted_value():
    """رد FastAPI كان يعيد ``input`` — فكلمة المرور تعود نصًّا صريحًا."""
    response = client.post(
        "/api/auth/login",
        json={"email": "not-an-email", "password": "MySecretPassword"},
    )
    body = assert_envelope(response, status=422)
    raw = response.text

    assert "MySecretPassword" not in raw
    assert "not-an-email" not in raw
    # ولا تفاصيل المحلّل الداخلية.
    assert "ctx" not in raw
    assert "input" not in raw
    assert "url" not in raw

    assert body["errors"] == [
        {"field": "body.email", "message": "صيغة البريد الإلكتروني غير صحيحة"}
    ]


def test_validation_detail_is_a_readable_arabic_string():
    """كان ``detail`` قائمة كائنات، فيتعذّر عرضه في الواجهة مباشرة."""
    body = assert_envelope(
        client.post("/api/auth/login", json={}), status=422
    )

    assert isinstance(body["detail"], str)
    assert is_arabic(body["detail"])
    fields = {item["field"] for item in body["errors"]}
    assert fields == {"body.email", "body.password"}
    assert all(item["message"] == "هذا الحقل مطلوب." for item in body["errors"])


def test_pydantic_messages_are_translated():
    """رسائل pydantic المدمجة إنجليزية، فتُترجم."""
    body = assert_envelope(
        client.post(
            "/api/auth/login",
            json={"email": "admin@digital-services.test", "password": 12345},
        ),
        status=422,
    )

    assert all(is_arabic(item["message"]) for item in body["errors"])


def test_a_query_parameter_error_names_its_location():
    body = assert_envelope(
        client.get(
            "/api/conversations", params={"limit": 0}, headers=auth_header()
        ),
        status=422,
    )

    assert body["errors"][0]["field"] == "query.limit"


def test_malformed_json_is_a_bad_request_not_a_validation_error():
    """العيب في صيغة الطلب نفسه لا في معاني حقوله، ولا حقول تُذكر أصلًا."""
    body = assert_envelope(
        client.post(
            "/api/auth/login",
            content="{not json",
            headers={"Content-Type": "application/json"},
        ),
        status=400,
    )

    assert body["errors"] == []
    assert "JSON" in body["detail"]
    assert "json_invalid" not in json.dumps(body, ensure_ascii=False)


# ---------------------------------------------------------------------------
# ٤) شرط الإنجاز: /docs بالعربية مع Authorize
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def spec() -> dict:
    return TestClient(app).get("/openapi.json").json()


def test_the_docs_page_is_served():
    assert client.get("/docs").status_code == 200


def test_every_route_has_an_arabic_summary_and_description(spec):
    """شرط الإنجاز: كل المسارات موصوفة بالعربية."""
    incomplete = []
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            summary = operation.get("summary", "")
            description = operation.get("description", "")
            if not (is_arabic(summary) and is_arabic(description)):
                incomplete.append(f"{method.upper()} {path}")

    assert incomplete == []
    assert len(spec["paths"]) >= 12


def test_every_tag_is_described_in_arabic(spec):
    assert spec["tags"]
    for tag in spec["tags"]:
        assert is_arabic(tag["description"]), tag["name"]


def test_the_authorize_button_is_wired(spec):
    """شرط الإنجاز: زر Authorize لـJWT مفعّل."""
    scheme = spec["components"]["securitySchemes"]["JWT"]

    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"
    # والمسارات المحمية تعلن أنها تستخدمه، فيظهر القفل بجانبها.
    assert "JWT" in json.dumps(spec["paths"]["/api/users"]["get"]["security"])


def test_the_error_model_is_published(spec):
    """شكل الخطأ الموحّد موثّق في المواصفة لا في التعليقات وحدها."""
    error = spec["components"]["schemas"]["ErrorResponse"]

    assert set(error["properties"]) == {"detail", "status", "code", "errors"}
    assert is_arabic(error["properties"]["detail"]["description"])


def test_requests_and_responses_carry_examples(spec):
    """أمثلة للطلب والرد كما تطلب المهمة."""
    schemas = spec["components"]["schemas"]
    for name in (
        "LoginRequest",
        "TokenResponse",
        "ChatRequest",
        "ChatResponse",
        "UserCreateRequest",
        "UserOut",
        "ConversationOut",
        "MessageOut",
        "FileOut",
        "SubscriptionOut",
        "AuditEventOut",
        "ErrorResponse",
    ):
        assert "example" in schemas[name], name


def test_the_api_description_documents_the_error_shape(spec):
    description = spec["info"]["description"]

    assert is_arabic(description)
    for token in ("Authorize", "not_found", "validation_error", "errors"):
        assert token in description
