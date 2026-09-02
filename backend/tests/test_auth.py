"""اختبارات المصادقة و JWT (مهمة P2-01)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import settings
from app.core.security import (
    MAX_PASSWORD_BYTES,
    ExpiredTokenError,
    InvalidTokenError,
    SecurityError,
    create_access_token,
    decode_access_token,
    get_jwt_secret,
    hash_password,
    verify_password,
)
from app.main import app
from app.services.user_store import MemoryUserStore, get_user_store

client = TestClient(app)

ADMIN_EMAIL = "admin@digital-services.test"
EMPLOYEE_EMAIL = "n.alharbi@digital-services.test"
DISABLED_EMAIL = "s.alzahrani@urban-planning.test"
OTHER_ORG_EMAIL = "admin@urban-planning.test"


@pytest.fixture(autouse=True)
def clean_store():
    """مخزن الذاكرة حالة على مستوى الصنف، فيُفرَّغ بين الاختبارات."""
    MemoryUserStore.reset()
    yield
    MemoryUserStore.reset()


@pytest.fixture
def seed_password() -> str:
    return settings.dev_seed_password


def login(email: str, password: str, **extra):
    payload = {"email": email, "password": password, **extra}
    return client.post("/api/auth/login", json=payload)


def auth_header(email: str, password: str) -> dict[str, str]:
    token = login(email, password).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# تجزئة كلمات المرور
# ---------------------------------------------------------------------------
def test_password_hash_is_not_the_plain_text():
    """شرط الإنجاز: كلمة المرور غير موجودة كنص صريح."""
    password = "GovAgent@2026"
    hashed = hash_password(password)

    assert password not in hashed
    assert hashed.startswith("$2b$")
    assert verify_password(password, hashed)


def test_password_hash_is_salted():
    """تجزئتان لكلمة المرور نفسها تختلفان — لا يمكن استنتاجها بجدول جاهز."""
    assert hash_password("GovAgent@2026") != hash_password("GovAgent@2026")


def test_wrong_password_does_not_verify():
    assert not verify_password("wrong-password", hash_password("GovAgent@2026"))


def test_arabic_password_works():
    password = "كلمة-مرور-قوية"
    assert verify_password(password, hash_password(password))


def test_short_password_is_rejected():
    with pytest.raises(SecurityError, match="قصيرة"):
        hash_password("123")


def test_password_longer_than_bcrypt_limit_is_rejected():
    """الحرف العربي بايتان، فالحد يُفحص بالبايت لا بالحرف."""
    with pytest.raises(SecurityError, match="أطول من الحد"):
        hash_password("ك" * (MAX_PASSWORD_BYTES // 2 + 1))


def test_verify_password_returns_false_on_corrupt_hash():
    """تجزئة تالفة تعني «لا تطابق» لا انهيارًا في مسار الدخول."""
    assert not verify_password("GovAgent@2026", "not-a-bcrypt-hash")


# ---------------------------------------------------------------------------
# إصدار التوكن والتحقق منه
# ---------------------------------------------------------------------------
def test_token_carries_user_organization_and_role():
    token, expires_at = create_access_token(
        user_id=7, organization_id=3, role="admin"
    )
    payload = decode_access_token(token)

    assert payload.user_id == 7
    assert payload.organization_id == 3
    assert payload.role == "admin"
    # حقل exp في JWT ثوانٍ صحيحة، فتضيع الكسور عند الترميز.
    assert abs(payload.expires_at - expires_at) < timedelta(seconds=1)


def test_expired_token_is_rejected():
    token, _ = create_access_token(
        user_id=1, organization_id=1, role="employee", expires_minutes=-1
    )
    with pytest.raises(ExpiredTokenError, match="انتهت صلاحية"):
        decode_access_token(token)


def test_token_signed_with_another_secret_is_rejected():
    forged = jwt.encode(
        {
            "sub": "1",
            "organization_id": 1,
            "role": "admin",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        # طويل بما يكفي لتفادي تحذير طول المفتاح — المقصود اختلاف السر لا قصره.
        "another-secret-long-enough-for-hmac-sha256",
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError, match="غير صالح"):
        decode_access_token(forged)


def test_malformed_token_is_rejected():
    with pytest.raises(InvalidTokenError):
        decode_access_token("this.is.not.a.jwt")


def test_unsigned_token_is_rejected():
    """توكن بـalg=none لا يُقبل — الخوارزمية مثبّتة عند فك التوقيع."""
    unsigned = jwt.encode(
        {
            "sub": "1",
            "organization_id": 1,
            "role": "admin",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        key="",
        algorithm="none",
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(unsigned)


def test_token_without_expiry_is_rejected():
    """توكن أبدي مرفوض حتى لو كان توقيعه صحيحًا."""
    endless = jwt.encode(
        {"sub": "1", "organization_id": 1, "role": "admin"},
        get_jwt_secret(),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(endless)


def test_token_with_missing_claims_is_rejected():
    incomplete = jwt.encode(
        {"sub": "1", "exp": datetime.now(UTC) + timedelta(hours=1)},
        get_jwt_secret(),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError, match="ناقص"):
        decode_access_token(incomplete)


# ---------------------------------------------------------------------------
# سر التوقيع
# ---------------------------------------------------------------------------
def test_configured_secret_is_used_as_is(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "  a-configured-secret  ")
    assert get_jwt_secret() == "a-configured-secret"


def test_empty_secret_in_development_is_generated_once(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "")
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(security, "_ephemeral_secret", None)

    first = get_jwt_secret()
    assert len(first) >= 32
    # ثابت داخل التشغيل الواحد، وإلا سقط كل توكن أُصدر قبل لحظة.
    assert get_jwt_secret() == first


def test_empty_secret_outside_development_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "")
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(security, "_ephemeral_secret", None)

    with pytest.raises(SecurityError, match="JWT_SECRET"):
        get_jwt_secret()


def test_protected_route_reports_503_when_secret_is_missing(monkeypatch):
    """خلل إعداد على السيرفر لا يُعرض كخطأ في طلب المستخدم."""
    headers = auth_header(ADMIN_EMAIL, settings.dev_seed_password)
    monkeypatch.setattr(settings, "jwt_secret", "")
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(security, "_ephemeral_secret", None)

    response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 503
    assert "JWT_SECRET" in response.json()["detail"]


# ---------------------------------------------------------------------------
# تسجيل الدخول
# ---------------------------------------------------------------------------
def test_login_returns_a_valid_token(seed_password):
    """شرط الإنجاز: تسجيل دخول بمستخدم تجريبي يعيد Token صالحًا."""
    response = login(ADMIN_EMAIL, seed_password)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["email"] == ADMIN_EMAIL
    assert body["user"]["role"] == "admin"
    assert body["user"]["organization_name"] == "هيئة الخدمات الرقمية"

    payload = decode_access_token(body["access_token"])
    assert payload.user_id == body["user"]["id"]
    assert payload.organization_id == body["user"]["organization_id"]
    assert payload.role == "admin"


def test_login_response_never_contains_the_password(seed_password):
    body = login(ADMIN_EMAIL, seed_password).text
    assert seed_password not in body
    assert "password" not in body


def test_login_is_case_insensitive_for_email(seed_password):
    response = login(ADMIN_EMAIL.upper(), seed_password)
    assert response.status_code == 200


def test_login_with_wrong_password_returns_401(seed_password):
    response = login(ADMIN_EMAIL, seed_password + "-wrong")
    assert response.status_code == 401
    assert response.json()["detail"] == "البريد الإلكتروني أو كلمة المرور غير صحيحة."


def test_login_with_unknown_email_gives_the_same_message(seed_password):
    """لا يُفرَّق بين بريد غير مسجّل وكلمة مرور خاطئة — منعًا لتعداد الحسابات."""
    unknown = login("nobody@digital-services.test", seed_password)
    wrong = login(ADMIN_EMAIL, "definitely-wrong")

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_disabled_account_cannot_log_in(seed_password):
    response = login(DISABLED_EMAIL, seed_password)
    assert response.status_code == 403
    assert "معطّل" in response.json()["detail"]


def test_login_needs_no_organization_identifier(seed_password):
    """البريد فريد عالميًا، فالبحث به يحسم الحساب والجهة بلا حقل إضافي."""
    response = login(OTHER_ORG_EMAIL, seed_password)

    assert response.status_code == 200
    assert response.json()["user"]["organization_id"] == 2


def test_login_request_has_no_organization_field():
    """أي حقل جهة في طلب الدخول يعني أن الواجهة تختار الجهة — وهذا ما أُلغي."""
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    assert set(schema["LoginRequest"]["properties"]) == {"email", "password"}


def test_an_organization_hint_in_the_body_changes_nothing(seed_password):
    """حقل دخيل لا يوجّه الدخول إلى جهة بعينها."""
    response = login(
        OTHER_ORG_EMAIL, seed_password, organization_slug="digital-services"
    )

    assert response.status_code == 200
    # الحساب حُسم من البريد وحده، لا من التلميح.
    assert response.json()["user"]["organization_id"] == 2


def test_login_rejects_blank_password():
    assert login(ADMIN_EMAIL, "   ").status_code == 422


def test_login_rejects_malformed_email(seed_password):
    assert login("not-an-email", seed_password).status_code == 422


def test_login_rejects_missing_fields():
    assert client.post("/api/auth/login", json={}).status_code == 422


def test_a_duplicated_email_refuses_login_instead_of_guessing(monkeypatch):
    """قاعدة سبقت فهرس التفرّد قد تحمل البريد مرتين: يُرفض الدخول ولا يُخمَّن.

    يحاكي الاختبار مخزنًا يعيد حسابين للبريد نفسه. الحساب الأول له كلمة
    المرور الصحيحة، فلو كان المسار يختار «أول مستخدم» لنجح الدخول صامتًا.
    """
    store = get_user_store()
    first = store.find_login_candidates(email=ADMIN_EMAIL)[0]
    second = store.find_login_candidates(email=OTHER_ORG_EMAIL)[0]
    monkeypatch.setattr(
        MemoryUserStore,
        "find_login_candidates",
        lambda self, **_kwargs: [first, second],
    )

    response = login(ADMIN_EMAIL, settings.dev_seed_password)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "أكثر من حساب" in detail
    assert "راجع مسؤول النظام" in detail
    # الجهتان مذكورتان للمسؤول، ولا رمز دخول في الرد إطلاقًا.
    assert "digital-services" in detail and "urban-planning" in detail
    assert "access_token" not in response.text


def test_a_duplicated_email_is_refused_even_with_a_wrong_password(monkeypatch):
    """الرفض لتعارض البيانات لا لكلمة المرور: لا يُفحص أي منهما ولا يُختار."""
    store = get_user_store()
    duplicates = [
        store.find_login_candidates(email=ADMIN_EMAIL)[0],
        store.find_login_candidates(email=OTHER_ORG_EMAIL)[0],
    ]
    monkeypatch.setattr(
        MemoryUserStore, "find_login_candidates", lambda self, **_kwargs: duplicates
    )

    assert login(ADMIN_EMAIL, "totally-wrong-password").status_code == 409


# ---------------------------------------------------------------------------
# المسارات المحمية
# ---------------------------------------------------------------------------
def test_me_returns_the_current_user(seed_password):
    response = client.get(
        "/api/auth/me", headers=auth_header(EMPLOYEE_EMAIL, seed_password)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == EMPLOYEE_EMAIL
    assert body["full_name"] == "نورة الحربي"
    assert body["role"] == "employee"
    assert body["organization_id"] == 1
    # لا أثر لكلمة المرور في أي رد.
    assert "password_hash" not in body and "password" not in body


def test_protected_route_without_a_token_returns_401():
    """شرط الإنجاز: مسار محمي بلا Token يعيد 401 برسالة واضحة."""
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert "تسجيل الدخول" in response.json()["detail"]
    assert response.headers["www-authenticate"] == "Bearer"


def test_protected_route_with_a_malformed_token_returns_401():
    response = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401
    assert "غير صالح" in response.json()["detail"]


def test_protected_route_with_an_expired_token_returns_401():
    token, _ = create_access_token(
        user_id=1, organization_id=1, role="admin", expires_minutes=-1
    )
    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
    assert "انتهت صلاحية" in response.json()["detail"]


def test_protected_route_rejects_a_token_for_a_deleted_user():
    """التوقيع الصحيح لا يكفي: الحساب يُقرأ من المخزن في كل طلب."""
    token, _ = create_access_token(
        user_id=9999, organization_id=1, role="admin"
    )
    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
    assert "لم يعد" in response.json()["detail"]


def test_token_cannot_reach_a_user_in_another_organization(seed_password):
    """تمهيد لعزل P2-02: معرّف مستخدم صحيح مع جهة خاطئة لا يُقبل."""
    employee = login(EMPLOYEE_EMAIL, seed_password).json()["user"]
    token, _ = create_access_token(
        user_id=employee["id"], organization_id=2, role="employee"
    )

    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


def test_logout_requires_a_token_and_confirms(seed_password):
    assert client.post("/api/auth/logout").status_code == 401

    response = client.post(
        "/api/auth/logout", headers=auth_header(ADMIN_EMAIL, seed_password)
    )
    assert response.status_code == 200
    assert "سارة العتيبي" in response.json()["detail"]


def test_openapi_exposes_the_bearer_scheme():
    """زر Authorize في /docs يعتمد على وجود المخطط في OpenAPI."""
    schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
    assert schemes["JWT"]["type"] == "http"
    assert schemes["JWT"]["scheme"] == "bearer"
