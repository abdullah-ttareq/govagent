"""اختبارات الاشتراك وتفعيل الجهاز الواحد وتحميل المثبّت.

**بلا شبكة وبلا مشروع Supabase وبلا حساب Azure.** كل نداء PostgREST يمرّ
على ``httpx.MockTransport`` مركّب في :func:`fake_supabase`، فيُختبر الكود
كاملًا — بناء المسارات والمرشّحات وتحويل الصفوف — لا بديلٌ عنه.

الجدول المزيّف يحاكي **قيود القاعدة الحقيقية**، وأهمها الفهرس الفريد الجزئي
على ``device_activations``: محاولة إدراج جهاز ثانٍ والأول فعّال تعيد ٤٠٩ مع
رمز ``23505``، تمامًا كما تفعل PostgreSQL. بدون محاكاة القيد يصير الاختبار
اختبارًا لفحصٍ في بايثون لا لقاعدة الأمان نفسها.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.database import supabase
from app.main import app
from app.services import entitlement_service as entitlements

client = TestClient(app)

#: ٣٢ بايتًا فأكثر — أقصر منه يُطلق تحذير PyJWT في كل استدعاء.
JWT_SECRET = "test-supabase-jwt-secret-32-bytes-long"
PEPPER = "test-device-pepper"

# جهتان ومستخدمون ثلاثة — العزل لا يُثبت بجهة واحدة.
ORG_A, ORG_B = 1, 2
SUB_A, SUB_B = 10, 20
ADMIN_A = "11111111-1111-4111-8111-111111111111"
EMPLOYEE_A = "22222222-2222-4222-8222-222222222222"
ADMIN_B = "33333333-3333-4333-8333-333333333333"
ORPHAN = "44444444-4444-4444-8444-444444444444"  # بلا ملف عمل

DEVICE_A = "device-fingerprint-employee-a"
DEVICE_OTHER = "device-fingerprint-some-other-machine"

#: سلسلة اتصال وهمية بمفتاح Base64 صالح الشكل. **ليست بيانات اعتماد حقيقية.**
FAKE_CONNECTION_STRING = (
    "DefaultEndpointsProtocol=https;AccountName=govmindtest;"
    "AccountKey=dGVzdC1hY2NvdW50LWtleS1ub3QtcmVhbA==;"
    "EndpointSuffix=core.windows.net"
)


def token_for(user_id: str, *, expired: bool = False) -> str:
    """يصدر رمز Supabase صالح البنية موقّعًا بالسرّ التجريبي."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user_id,
            "email": f"{user_id[:8]}@govmind.test",
            "aud": "authenticated",
            "role": "authenticated",
            "iat": int(now.timestamp()),
            "exp": int(
                (now - timedelta(hours=1) if expired else now + timedelta(hours=1))
                .timestamp()
            ),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def auth(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user_id)}"}


def iso(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


class FakeSupabase:
    """قاعدة في الذاكرة تردّ على PostgREST بما يكفي لهذه الاختبارات.

    تدعم مرشّحات ``eq.`` و ``is.null`` و ``is.true`` فقط — وهي كل ما
    يستعمله كود الإنتاج. أي مرشّح آخر يرفع خطأً بدل أن يُتجاهل بصمت
    فيمرّ اختبار على استعلام لا يفعل ما يظنّه.
    """

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "organizations": [
                {"id": ORG_A, "name": "جهة أ", "slug": "org-a", "is_active": True},
                {"id": ORG_B, "name": "جهة ب", "slug": "org-b", "is_active": True},
            ],
            "profiles": [
                {
                    "id": ADMIN_A,
                    "app_user_id": 1,
                    "organization_id": ORG_A,
                    "email": "admin-a@govmind.test",
                    "full_name": "مسؤول أ",
                    "role": "admin",
                    "is_active": True,
                },
                {
                    "id": EMPLOYEE_A,
                    "app_user_id": 2,
                    "organization_id": ORG_A,
                    "email": "employee-a@govmind.test",
                    "full_name": "موظف أ",
                    "role": "employee",
                    "is_active": True,
                },
                {
                    "id": ADMIN_B,
                    "app_user_id": 3,
                    "organization_id": ORG_B,
                    "email": "admin-b@govmind.test",
                    "full_name": "مسؤول ب",
                    "role": "admin",
                    "is_active": True,
                },
            ],
            "subscriptions": [
                {
                    "id": SUB_A,
                    "organization_id": ORG_A,
                    "status": "active",
                    "seats": 10,
                    "starts_at": iso(-10),
                    "expires_at": iso(300),
                },
                {
                    "id": SUB_B,
                    "organization_id": ORG_B,
                    "status": "active",
                    "seats": 5,
                    "starts_at": iso(-10),
                    "expires_at": iso(300),
                },
            ],
            "device_activations": [],
        }
        self._next_id = 100

    # -- أدوات المرشّحات -------------------------------------------------
    @staticmethod
    def _matches(row: dict[str, Any], key: str, expression: str) -> bool:
        operator, _, value = expression.partition(".")
        if operator == "eq":
            current = row.get(key)
            return str(current) == value
        if operator == "is":
            if value == "null":
                return row.get(key) is None
            if value == "true":
                return row.get(key) is True
            if value == "false":
                return row.get(key) is False
        raise AssertionError(f"مرشّح غير مدعوم في المحاكاة: {key}={expression}")

    def _select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        rows = list(self.tables.setdefault(table, []))
        for key, expression in params.items():
            if key in ("select", "order", "limit", "offset"):
                continue
            rows = [row for row in rows if self._matches(row, key, expression)]
        return rows

    # -- القيد الحقيقي: جهاز فعّال واحد لكل اشتراك ----------------------
    def _violates_one_active_device(self, row: dict[str, Any]) -> bool:
        return any(
            existing["subscription_id"] == row["subscription_id"]
            and existing.get("revoked_at") is None
            for existing in self.tables["device_activations"]
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        table = request.url.path.rsplit("/", 1)[-1]
        params = dict(request.url.params)

        if request.method == "GET":
            rows = self._select(table, params)
            if params.get("order", "").endswith(".desc"):
                rows = list(reversed(rows))
            limit = params.get("limit")
            if limit:
                rows = rows[: int(limit)]
            headers = {}
            if request.headers.get("Prefer") == "count=exact":
                headers["content-range"] = f"0-0/{len(self._select(table, params))}"
            return httpx.Response(200, json=rows, headers=headers)

        if request.method == "POST":
            row = json.loads(request.content)
            if table == "device_activations":
                if self._violates_one_active_device(row):
                    # ما تعيده PostgreSQL عند مخالفة الفهرس الفريد الجزئي.
                    return httpx.Response(
                        409,
                        json={
                            "code": "23505",
                            "message": "duplicate key value violates unique constraint",
                        },
                    )
                row.setdefault("activated_at", datetime.now(UTC).isoformat())
                row.setdefault("last_seen_at", datetime.now(UTC).isoformat())
                row.setdefault("revoked_at", None)
            self._next_id += 1
            row["id"] = self._next_id
            self.tables.setdefault(table, []).append(row)
            return httpx.Response(201, json=[row])

        if request.method == "PATCH":
            values = json.loads(request.content)
            rows = self._select(table, params)
            for row in rows:
                row.update(values)
            return httpx.Response(200, json=rows)

        if request.method == "DELETE":
            rows = self._select(table, params)
            self.tables[table] = [
                row for row in self.tables[table] if row not in rows
            ]
            return httpx.Response(200, json=rows)

        raise AssertionError(f"طريقة غير متوقعة: {request.method}")


@pytest.fixture
def fake_supabase(monkeypatch):
    """يركّب قاعدة مزيّفة وإعدادًا كاملًا، ويفكّهما بعد كل اختبار."""
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key-for-tests")
    monkeypatch.setattr(
        settings, "supabase_service_role_key", "service-key-for-tests"
    )
    monkeypatch.setattr(settings, "supabase_jwt_secret", JWT_SECRET)
    monkeypatch.setattr(settings, "device_hash_pepper", PEPPER)

    fake = FakeSupabase()
    supabase.set_client(
        httpx.Client(
            base_url=supabase.rest_base_url(),
            transport=httpx.MockTransport(fake.handler),
        )
    )
    yield fake
    supabase.set_client(None)


@pytest.fixture
def azure_configured(monkeypatch):
    """يضبط تخزين Azure بقيم وهمية. **لا بيانات اعتماد حقيقية هنا.**"""
    monkeypatch.setattr(settings, "azure_storage_account", "govmindtest")
    monkeypatch.setattr(settings, "azure_storage_container", "releases")
    monkeypatch.setattr(
        settings, "azure_storage_blob_name", "govmind/GovMindSetup.exe"
    )
    monkeypatch.setattr(
        settings, "azure_storage_connection_string", FAKE_CONNECTION_STRING
    )
    monkeypatch.setattr(settings, "download_link_ttl_minutes", 15)


def activate(user_id: str, device_id: str, name: str = "حاسب المكتب"):
    return client.post(
        "/api/account/devices/activate",
        json={"device_id": device_id, "device_name": name},
        headers=auth(user_id),
    )


# ===========================================================================
# المصادقة
# ===========================================================================
def test_endpoints_require_a_token(fake_supabase):
    """كل مسار محمي يرفض الطلب بلا رمز، برسالة عربية لا بنص إطار العمل."""
    for method, path in (
        ("get", "/api/account/subscription"),
        ("get", "/api/account/me"),
        ("get", "/api/account/devices"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 401, path
        assert "تسجيل الدخول" in response.json()["detail"]


def test_expired_token_is_rejected(fake_supabase):
    response = client.get(
        "/api/account/subscription",
        headers={"Authorization": f"Bearer {token_for(EMPLOYEE_A, expired=True)}"},
    )
    assert response.status_code == 401
    assert "انتهت صلاحية جلستك" in response.json()["detail"]


def test_token_signed_with_another_secret_is_rejected(fake_supabase):
    """رمز صحيح البنية موقّع بسرّ آخر لا يُقبل — وإلا صار التوقيع زينة."""
    forged = jwt.encode(
        {
            "sub": EMPLOYEE_A,
            "aud": "authenticated",
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        },
        "a-completely-different-secret-32-bytes",
        algorithm="HS256",
    )
    response = client.get(
        "/api/account/subscription", headers={"Authorization": f"Bearer {forged}"}
    )
    assert response.status_code == 401


def test_account_without_a_profile_is_refused(fake_supabase):
    """حساب في auth بلا ملف عمل: رفض برسالة تشرح، لا انهيار ولا وصول."""
    response = client.get("/api/account/subscription", headers=auth(ORPHAN))
    assert response.status_code == 403
    assert "غير مرتبط بأي جهة" in response.json()["detail"]


# ===========================================================================
# حالة الاشتراك
# ===========================================================================
def test_subscription_status_is_reported(fake_supabase):
    response = client.get("/api/account/subscription", headers=auth(EMPLOYEE_A))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["is_usable"] is True
    assert body["blocked_reason"] is None
    assert body["device"] is None
    assert body["requires_activation"] is True


@pytest.mark.parametrize(
    "status,fragment",
    [
        ("expired", "انتهى اشتراكك"),
        ("suspended", "موقوف"),
        ("cancelled", "ملغى"),
    ],
)
def test_blocked_statuses_report_their_reason(fake_supabase, status, fragment):
    """كل حالة مانعة لها رسالتها: «موقوف» و«ملغى» ليسا «منتهيًا»."""
    fake_supabase.tables["subscriptions"][0]["status"] = status
    response = client.get("/api/account/subscription", headers=auth(EMPLOYEE_A))
    assert response.status_code == 200
    body = response.json()
    assert body["is_usable"] is False
    assert fragment in body["blocked_reason"]


def test_trial_is_serviceable(fake_supabase):
    """`trial` يسمح بالخدمة كـ`active` — وإلا لم تعمل الفترة التجريبية."""
    fake_supabase.tables["subscriptions"][0]["status"] = "trial"
    response = client.get("/api/account/subscription", headers=auth(EMPLOYEE_A))
    assert response.json()["is_usable"] is True


def test_active_status_with_a_past_date_is_expired(fake_supabase):
    """الحالة والتاريخ يُفحصان معًا: لا Trigger يحدّث الحالة في القاعدة."""
    fake_supabase.tables["subscriptions"][0]["expires_at"] = iso(-1)
    response = client.get("/api/account/subscription", headers=auth(EMPLOYEE_A))
    body = response.json()
    assert body["status"] == "active"
    assert body["is_usable"] is False
    assert "انتهى اشتراكك" in body["blocked_reason"]


def test_organization_without_a_subscription_is_blocked(fake_supabase):
    """فشل مغلق: غياب صف الاشتراك يمنع، لا يسمح."""
    fake_supabase.tables["subscriptions"] = [
        row
        for row in fake_supabase.tables["subscriptions"]
        if row["organization_id"] != ORG_A
    ]
    response = client.get("/api/account/subscription", headers=auth(EMPLOYEE_A))
    assert response.status_code == 403
    assert "لا يوجد اشتراك مسجّل" in response.json()["detail"]


# ===========================================================================
# جهاز واحد لكل اشتراك
# ===========================================================================
def test_first_device_activates(fake_supabase):
    response = activate(EMPLOYEE_A, DEVICE_A)
    assert response.status_code == 200
    body = response.json()
    assert body["device"]["device_name"] == "حاسب المكتب"
    assert body["device"]["is_current_device"] is True
    assert body["requires_activation"] is False


def test_raw_fingerprint_is_never_stored(fake_supabase):
    """البصمة الخام لا تصل القاعدة، والمخزَّن تجزئة ٦٤ خانة ست عشرية."""
    activate(EMPLOYEE_A, DEVICE_A)
    row = fake_supabase.tables["device_activations"][0]
    stored = row["device_id_hash"]

    assert stored != DEVICE_A
    assert DEVICE_A not in json.dumps(fake_supabase.tables, ensure_ascii=False)
    assert len(stored) == 64
    assert all(character in "0123456789abcdef" for character in stored)


def test_device_hash_is_not_exposed_in_any_response(fake_supabase):
    """التجزئة لا تخرج في أي رد: من يعرفها ينتحل الجهاز."""
    stored = activate(EMPLOYEE_A, DEVICE_A)
    fake_hash = fake_supabase.tables["device_activations"][0]["device_id_hash"]

    for response in (
        stored,
        client.get("/api/account/subscription", headers=auth(EMPLOYEE_A)),
        client.get("/api/account/devices", headers=auth(ADMIN_A)),
    ):
        assert fake_hash not in response.text


def test_second_device_is_refused_while_the_first_is_active(fake_supabase):
    """**جوهر الشرط:** حساب واحد لا يفعّل جهازًا ثانيًا."""
    assert activate(EMPLOYEE_A, DEVICE_A).status_code == 200

    response = activate(EMPLOYEE_A, DEVICE_OTHER, name="حاسب المنزل")
    assert response.status_code == 409
    assert "مفعّل بالفعل على جهاز آخر" in response.json()["detail"]

    active = [
        row
        for row in fake_supabase.tables["device_activations"]
        if row["revoked_at"] is None
    ]
    assert len(active) == 1


def test_a_colleague_cannot_activate_a_second_device_either(fake_supabase):
    """الحدّ على **الاشتراك** لا على المستخدم: زميل في الجهة يصطدم به كذلك."""
    assert activate(EMPLOYEE_A, DEVICE_A).status_code == 200
    response = activate(ADMIN_A, DEVICE_OTHER)
    assert response.status_code == 409


def test_reactivating_the_same_device_succeeds(fake_supabase):
    """إعادة الطلب من الجهاز نفسه لا تفشل: قد تعيدها الإضافة بعد انقطاع."""
    first = activate(EMPLOYEE_A, DEVICE_A)
    second = activate(EMPLOYEE_A, DEVICE_A)

    assert second.status_code == 200
    assert second.json()["device"]["id"] == first.json()["device"]["id"]
    assert len(fake_supabase.tables["device_activations"]) == 1


def test_database_constraint_is_the_real_guard(fake_supabase, monkeypatch):
    """لو سبق جهازٌ آخر بين الفحص والإدراج، القاعدة ترفض والرسالة تبقى مفهومة.

    يُحاكى السباق بإفراغ نتيجة الفحص المسبق مع إبقاء الصف في الجدول، فيصل
    الطلب إلى الإدراج ويصطدم بالفهرس الفريد.
    """
    activate(EMPLOYEE_A, DEVICE_A)
    monkeypatch.setattr(entitlements, "active_device", lambda subscription_id: None)

    response = activate(EMPLOYEE_A, DEVICE_OTHER)
    assert response.status_code == 409
    assert "جهاز آخر" in response.json()["detail"]


def test_activation_is_refused_on_an_expired_subscription(fake_supabase):
    fake_supabase.tables["subscriptions"][0]["status"] = "expired"
    response = activate(EMPLOYEE_A, DEVICE_A)
    assert response.status_code == 403
    assert fake_supabase.tables["device_activations"] == []


def test_missing_pepper_stops_activation(fake_supabase, monkeypatch):
    """بلا مِلح لا تُخزَّن تجزئة ضعيفة بصمت — يتوقف المسار برسالة إعداد."""
    monkeypatch.setattr(settings, "device_hash_pepper", "")
    response = activate(EMPLOYEE_A, DEVICE_A)
    assert response.status_code == 400
    assert "DEVICE_HASH_PEPPER" in response.json()["detail"]


# ===========================================================================
# التحقق من الجهاز
# ===========================================================================
def test_verify_accepts_the_activated_device(fake_supabase):
    activate(EMPLOYEE_A, DEVICE_A)
    response = client.post(
        "/api/account/devices/verify",
        json={"device_id": DEVICE_A},
        headers=auth(EMPLOYEE_A),
    )
    assert response.status_code == 200
    assert response.json()["device"]["is_current_device"] is True


def test_verify_refuses_another_device(fake_supabase):
    activate(EMPLOYEE_A, DEVICE_A)
    response = client.post(
        "/api/account/devices/verify",
        json={"device_id": DEVICE_OTHER},
        headers=auth(EMPLOYEE_A),
    )
    assert response.status_code == 409
    assert "مفعّل على جهاز آخر" in response.json()["detail"]


def test_verify_before_activation_says_so(fake_supabase):
    response = client.post(
        "/api/account/devices/verify",
        json={"device_id": DEVICE_A},
        headers=auth(EMPLOYEE_A),
    )
    assert response.status_code == 409
    assert "لم يُفعَّل أي جهاز" in response.json()["detail"]


# ===========================================================================
# الإبطال — والعزل بين الجهات
# ===========================================================================
def test_admin_revokes_then_a_new_device_activates(fake_supabase):
    """المسار الكامل لتغيير الجهاز: إبطال من المسؤول ثم تفعيل الجديد."""
    activate(EMPLOYEE_A, DEVICE_A)
    activation_id = fake_supabase.tables["device_activations"][0]["id"]

    revoked = client.post(
        f"/api/account/devices/{activation_id}/revoke", headers=auth(ADMIN_A)
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None

    assert activate(EMPLOYEE_A, DEVICE_OTHER, name="حاسب المنزل").status_code == 200
    # الصف القديم يبقى في السجل ولا يُحذف.
    assert len(fake_supabase.tables["device_activations"]) == 2


def test_employee_cannot_revoke(fake_supabase):
    activate(EMPLOYEE_A, DEVICE_A)
    activation_id = fake_supabase.tables["device_activations"][0]["id"]

    response = client.post(
        f"/api/account/devices/{activation_id}/revoke", headers=auth(EMPLOYEE_A)
    )
    assert response.status_code == 403
    assert fake_supabase.tables["device_activations"][0]["revoked_at"] is None


def test_admin_of_another_organization_cannot_revoke(fake_supabase):
    """**عزل الجهات:** مسؤول جهة ب لا يمسّ تفعيلًا في جهة أ، ويُعاد ٤٠٤."""
    activate(EMPLOYEE_A, DEVICE_A)
    activation_id = fake_supabase.tables["device_activations"][0]["id"]

    response = client.post(
        f"/api/account/devices/{activation_id}/revoke", headers=auth(ADMIN_B)
    )
    assert response.status_code == 404
    assert fake_supabase.tables["device_activations"][0]["revoked_at"] is None


def test_admin_sees_only_their_own_organization_devices(fake_supabase):
    activate(EMPLOYEE_A, DEVICE_A)

    own = client.get("/api/account/devices", headers=auth(ADMIN_A)).json()
    other = client.get("/api/account/devices", headers=auth(ADMIN_B)).json()

    assert len(own["devices"]) == 1
    assert other["devices"] == []


def test_employee_cannot_list_devices(fake_supabase):
    response = client.get("/api/account/devices", headers=auth(EMPLOYEE_A))
    assert response.status_code == 403


# ===========================================================================
# رابط تحميل المثبّت
# ===========================================================================
def download(user_id: str, device_id: str):
    return client.post(
        "/api/account/installer/download-url",
        json={"device_id": device_id},
        headers=auth(user_id),
    )


def test_download_url_is_issued_to_the_activated_device(
    fake_supabase, azure_configured
):
    activate(EMPLOYEE_A, DEVICE_A)
    response = download(EMPLOYEE_A, DEVICE_A)

    assert response.status_code == 200
    body = response.json()
    assert body["file_name"] == "GovMindSetup.exe"
    assert body["expires_in_minutes"] == 15
    assert body["download_url"].startswith(
        "https://govmindtest.blob.core.windows.net/releases/"
    )
    # رابط موقّع قصير العمر بصلاحية قراءة فقط.
    assert "sig=" in body["download_url"]
    assert "sp=r" in body["download_url"]
    assert "se=" in body["download_url"]


def test_download_url_never_leaks_the_connection_string(
    fake_supabase, azure_configured
):
    """مفتاح الحساب لا يظهر في الرد بأي شكل — لا كاملًا ولا مجزّأً."""
    activate(EMPLOYEE_A, DEVICE_A)
    response = download(EMPLOYEE_A, DEVICE_A)

    assert "AccountKey" not in response.text
    assert "dGVzdC1hY2NvdW50LWtleS1ub3QtcmVhbA==" not in response.text
    assert FAKE_CONNECTION_STRING not in response.text


def test_download_is_refused_without_an_activated_device(
    fake_supabase, azure_configured
):
    response = download(EMPLOYEE_A, DEVICE_A)
    assert response.status_code == 409
    assert "لم يُفعَّل أي جهاز" in response.json()["detail"]


def test_download_is_refused_from_a_different_device(fake_supabase, azure_configured):
    """**الشرط الرابع:** الطالب يجب أن يكون الجهاز المفعّل نفسه."""
    activate(EMPLOYEE_A, DEVICE_A)
    response = download(EMPLOYEE_A, DEVICE_OTHER)
    assert response.status_code == 409
    assert "download_url" not in response.text


@pytest.mark.parametrize("status", ["expired", "suspended", "cancelled"])
def test_download_is_refused_on_a_non_serviceable_subscription(
    fake_supabase, azure_configured, status
):
    """**اشتراك منتهٍ لا يحصل على رابط تحميل** — ولو كان جهازه مفعّلًا."""
    activate(EMPLOYEE_A, DEVICE_A)
    fake_supabase.tables["subscriptions"][0]["status"] = status

    response = download(EMPLOYEE_A, DEVICE_A)
    assert response.status_code == 403
    assert "download_url" not in response.text


def test_download_is_refused_when_the_date_has_passed(
    fake_supabase, azure_configured
):
    activate(EMPLOYEE_A, DEVICE_A)
    fake_supabase.tables["subscriptions"][0]["expires_at"] = iso(-1)

    response = download(EMPLOYEE_A, DEVICE_A)
    assert response.status_code == 403
    assert "انتهى اشتراكك" in response.json()["detail"]


def test_download_without_azure_configuration_says_so(fake_supabase, monkeypatch):
    """إعداد ناقص = ٥٠٣ برسالة تسمّي المتغيرات، لا ٥٠٠ ولا رابط تالف."""
    monkeypatch.setattr(settings, "azure_storage_account", "")
    monkeypatch.setattr(settings, "azure_storage_container", "")
    monkeypatch.setattr(settings, "azure_storage_blob_name", "")
    monkeypatch.setattr(settings, "azure_storage_connection_string", "")

    activate(EMPLOYEE_A, DEVICE_A)
    response = download(EMPLOYEE_A, DEVICE_A)

    assert response.status_code == 503
    assert "AZURE_STORAGE_ACCOUNT" in response.json()["detail"]
