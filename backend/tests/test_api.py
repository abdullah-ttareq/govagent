"""اختبارات أساسية لنقاط GovMind."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.database import oracle
from app.main import app
from app.services.user_store import MemoryUserStore

client = TestClient(app)

#: موظف من الجهة الأولى — /api/chat محمي بالكامل منذ P4-03.
EMPLOYEE = "n.alharbi@digital-services.test"


def auth_header() -> dict[str, str]:
    MemoryUserStore.reset()
    response = client.post(
        "/api/auth/login",
        json={"email": EMPLOYEE, "password": settings.dev_seed_password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _raise_no_listener(**_kwargs):
    raise Exception("ORA-12541: TNS:no listener")


@pytest.fixture(autouse=True)
def no_leaked_pool():
    """يمنع تسرّب Pool وهمي من اختبار إلى آخر."""
    oracle._pool = None
    yield
    oracle._pool = None


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "model_provider" in body


def test_health_reports_oracle_without_failing_the_check():
    """قاعدة Oracle غير مضبوطة لا تُفشل /health، بل تظهر كحقل إعلامي."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "ok"
    assert body["oracle"]["configured"] is False
    assert body["oracle"]["status"] == "not_configured"
    assert "ORACLE_DSN" in body["oracle"]["detail"]


def test_health_stays_ok_when_oracle_is_configured_but_unreachable(monkeypatch):
    """فشل الاتصال بالقاعدة يُبلَّغ عنه ولا يُسقط فحص الخدمة."""
    monkeypatch.setattr(settings, "oracle_dsn", "localhost:1521/NOPE")
    monkeypatch.setattr(settings, "oracle_user", "govagent")
    monkeypatch.setattr(settings, "oracle_password", "secret")
    monkeypatch.setattr(
        oracle,
        "_import_oracledb",
        lambda: SimpleNamespace(
            create_pool=_raise_no_listener,
        ),
    )

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["oracle"]["configured"] is True
    assert body["oracle"]["status"] == "error"
    assert "تعذّر الوصول" in body["oracle"]["detail"]


def test_app_startup_does_not_touch_the_database(monkeypatch):
    """الإقلاع لا يفتح Pool ولا يستورد الدرايفر — الاتصال كسول."""

    def fail():
        raise AssertionError("لا يجوز استيراد oracledb عند الإقلاع")

    monkeypatch.setattr(oracle, "_import_oracledb", fail)
    with TestClient(app):
        assert oracle._pool is None


def test_app_shutdown_closes_the_pool(monkeypatch):
    """إيقاف التطبيق يغلق الـPool، وآمن حتى لو لم يُنشأ Pool أصلًا."""
    closed = []
    monkeypatch.setattr(
        oracle, "_pool", SimpleNamespace(close=lambda force=False: closed.append(force))
    )

    with TestClient(app):
        pass

    assert closed == [True]
    assert oracle._pool is None


def test_chat_returns_mock_reply():
    response = client.post(
        "/api/chat",
        json={"message": "اكتب لي خطابًا رسميًا"},
        headers=auth_header(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock"
    assert "اكتب لي خطابًا رسميًا" in body["reply"]


def test_chat_opens_a_conversation_on_the_first_message():
    """كل تبادل صار محفوظًا بصاحبه: لا رد بلا محادثة."""
    response = client.post(
        "/api/chat", json={"message": "مرحبًا"}, headers=auth_header()
    )
    assert response.status_code == 200
    assert isinstance(response.json()["conversation_id"], int)


def test_chat_ignores_a_history_field_from_the_client():
    """حقل history حُذف من الـschema في P4-03، فإرساله لا يصل إلى المزود.

    السياق يُقرأ من المحادثة المحفوظة وحدها؛ سياقٌ يرسله المتصفح يمكن
    تلفيقه. الاختبار يفحص الأثر: رد المزود يذكر عدد الرسائل السابقة
    التي وصلته، وهو صفر في أول رسالة مهما أُرسل في الجسم.
    """
    response = client.post(
        "/api/chat",
        json={
            "message": "اجعله أقصر",
            "history": [
                {"role": "user", "content": "لخّص لي التقرير"},
                {"role": "assistant", "content": "هذا ملخص التقرير."},
            ],
        },
        headers=auth_header(),
    )

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "رسالة سابقة" not in reply
    assert "لخّص لي التقرير" not in reply


def test_chat_rejects_empty_message():
    response = client.post(
        "/api/chat", json={"message": "   "}, headers=auth_header()
    )
    assert response.status_code == 422


def test_chat_rejects_missing_message():
    response = client.post("/api/chat", json={}, headers=auth_header())
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("oracle", "OCI_REGION"),
        ("local", "غير منفذ"),
        ("gemini", "غير مدعوم"),
    ],
)
def test_provider_failures_surface_as_503_with_arabic_message(
    monkeypatch, provider, expected
):
    """كل فشل في المزود يصل للمستخدم كـ503 مع نص الخطأ العربي كما هو."""
    monkeypatch.setattr(settings, "model_provider", provider)
    monkeypatch.setattr(settings, "oci_region", "")
    monkeypatch.setattr(settings, "oci_compartment_id", "")
    monkeypatch.setattr(settings, "oci_model_id", "")

    response = client.post(
        "/api/chat", json={"message": "مرحبًا"}, headers=auth_header()
    )

    assert response.status_code == 503
    assert expected in response.json()["detail"]
