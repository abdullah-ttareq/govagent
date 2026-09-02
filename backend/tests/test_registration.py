"""التسجيل الذاتي: الحساب والمساحة المخفية والاشتراك التجريبي.

**النموذج فردي.** حساب واحد، اشتراك واحد، جهاز فعّال واحد. **العميل لا
يُسأل عن جهة** ولا يرى مفردات المؤسسات ولا لقب «مسؤول». المساحة التي
يحتاجها عزل RLS يولّدها الـBackend من معرّف الحساب.

**ما يثبته هذا الملف.** أن التسجيل يتم بأربعة حقول لا خمسة، وأن المساحة
تُنشأ خلف الستار بمعرّف مشتقّ من `auth.users.id`، وأن البريد المكرر يُرفض
برسالة عربية، و**يحذف حساب المصادقة تعويضًا** إن فشلت الكتابات الأربع،
وأن الاشتراك الناتج تجريبي بمقعد واحد ولثلاثين يومًا.

**لا يثبت ذرّية الكتابات الأربع** — تلك في دالة القاعدة، ويثبتها قسم
الاختبارات داخل `database/supabase/0003_registration.sql` الذي نُفّذ على
PostgreSQL حقيقي. القاعدة المزيّفة هنا **تحاكي عقد الدالة**: إمّا تنجح
الأربع أو لا شيء منها.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.database import supabase
from app.main import app
from app.services import registration_service
from app.services.registration_service import (
    personal_slug,
    personal_workspace_name,
)

from tests.test_entitlements import JWT_SECRET, PEPPER

client = TestClient(app)

NEW_USER_ID = "99999999-9999-4999-8999-999999999999"


def payload(**overrides: Any) -> dict[str, Any]:
    body = {
        "full_name": "سارة العتيبي",
        "email": "sara@example.gov.sa",
        "password": "StrongPass!2026",
        "confirm_password": "StrongPass!2026",
    }
    body.update(overrides)
    return body


class FakeRegistrationBackend:
    """GoTrue وPostgREST مزيّفان بعقد دالة التسجيل الذرّية."""

    def __init__(self) -> None:
        self.auth_users: dict[str, str] = {}          # id -> email
        self.organizations: list[dict[str, Any]] = []
        self.profiles: list[dict[str, Any]] = []
        self.members: list[dict[str, Any]] = []
        self.subscriptions: list[dict[str, Any]] = []
        self.deleted_users: list[str] = []
        self.signup_status = 200
        self.signup_body: dict[str, Any] | None = None
        self.autoconfirm = True
        self._next_id = 500

    # -- GoTrue --------------------------------------------------------
    def _signup(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        email = body["email"].lower()

        if self.signup_body is not None or self.signup_status != 200:
            return httpx.Response(
                self.signup_status, json=self.signup_body or {"msg": "error"}
            )
        if email in self.auth_users.values():
            return httpx.Response(
                422, json={"error_code": "user_already_exists", "msg": "User already registered"}
            )

        self.auth_users[NEW_USER_ID] = email
        payload_out: dict[str, Any] = {"id": NEW_USER_ID, "email": email}
        if self.autoconfirm:
            payload_out |= {
                "access_token": "issued-token",
                "refresh_token": "issued-refresh",
                "expires_in": 3600,
                "user": {"id": NEW_USER_ID, "email": email},
            }
        return httpx.Response(200, json=payload_out)

    # -- الدالة الذرّية -------------------------------------------------
    def _register_organization(self, params: dict[str, Any]) -> httpx.Response:
        slug = params["p_org_slug"]
        email = params["p_email"].lower()

        # ① الجهة — تفرّد المعرّف النصي.
        if any(o["slug"] == slug for o in self.organizations):
            return httpx.Response(
                400, json={"code": "23505", "message": "organization_slug_taken"}
            )

        self._next_id += 1
        org = {"id": self._next_id, "name": params["p_org_name"], "slug": slug}

        # ② الملف — تفرّد البريد. **الفشل هنا يتراجع عن ① كذلك**، وهو ما
        #    يحاكي ذرّية الدالة الحقيقية.
        if any(p["email"] == email for p in self.profiles):
            return httpx.Response(
                400, json={"code": "23505", "message": "email_already_registered"}
            )

        self.organizations.append(org)
        self.profiles.append(
            {
                "id": params["p_user_id"],
                "organization_id": org["id"],
                "email": email,
                "full_name": params["p_full_name"],
                "role": "admin",
            }
        )
        self.members.append(
            {"organization_id": org["id"], "user_id": params["p_user_id"], "role": "admin"}
        )

        self._next_id += 1
        days = int(params.get("p_trial_days") or 30)
        sub = {
            "id": self._next_id,
            "organization_id": org["id"],
            "status": "trial",
            "seats": max(1, int(params.get("p_seats") or 1)),
            "starts_at": datetime.now(UTC).isoformat(),
            "expires_at": (datetime.now(UTC) + timedelta(days=days)).isoformat(),
        }
        self.subscriptions.append(sub)

        return httpx.Response(
            200,
            json=[{"out_organization_id": org["id"], "out_subscription_id": sub["id"]}],
        )

    # -- التوجيه -------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if path.endswith("/auth/v1/signup"):
            return self._signup(request)
        if path.endswith("/auth/v1/token"):
            user_id = next(iter(self.auth_users), NEW_USER_ID)
            return httpx.Response(
                200,
                json={
                    "access_token": "issued-token",
                    "refresh_token": "issued-refresh",
                    "expires_in": 3600,
                    "user": {"id": user_id, "email": self.auth_users.get(user_id, "")},
                },
            )
        if "/auth/v1/admin/users/" in path:
            self.deleted_users.append(path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={})
        if path.endswith("/rpc/register_organization"):
            return self._register_organization(json.loads(request.content))
        if path.endswith("/profiles"):
            rows = [
                {**p, "app_user_id": 1, "is_active": True}
                for p in self.profiles
                if f"eq.{p['id']}" == dict(request.url.params).get("id")
            ]
            return httpx.Response(200, json=rows)

        return httpx.Response(200, json=[])


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key-for-tests")
    monkeypatch.setattr(settings, "supabase_service_role_key", "service-key-for-tests")
    monkeypatch.setattr(settings, "supabase_jwt_secret", JWT_SECRET)
    monkeypatch.setattr(settings, "device_hash_pepper", PEPPER)

    fake = FakeRegistrationBackend()
    supabase.set_client(
        httpx.Client(
            base_url=supabase.rest_base_url(),
            transport=httpx.MockTransport(fake.handler),
        )
    )
    # GoTrue يُنادى بـ`httpx` مباشرة لا بعميل Supabase، فيُوجَّه هنا كذلك.
    real_post, real_delete = httpx.post, httpx.delete
    transport = httpx.MockTransport(fake.handler)

    def routed_post(url, **kwargs):
        with httpx.Client(transport=transport) as routed:
            return routed.post(url, **kwargs)

    def routed_delete(url, **kwargs):
        with httpx.Client(transport=transport) as routed:
            return routed.delete(url, **kwargs)

    monkeypatch.setattr(httpx, "post", routed_post)
    monkeypatch.setattr(httpx, "delete", routed_delete)
    yield fake
    httpx.post, httpx.delete = real_post, real_delete
    supabase.set_client(None)


# ===========================================================================
# المساحة المخفية — يولّدها السيرفر، ولا يراها العميل
# ===========================================================================
def test_workspace_slug_is_derived_from_the_account_id():
    """**المصدر معرّف الحساب لا اسمٌ يكتبه العميل.**

    وهذا وحده ما يجعل التسجيل بأربعة حقول ممكنًا: `uuid` فريد بحكم
    تعريفه، فلا تصادم ولا لاحقة عشوائية ولا رفض «الاسم مستخدم» في وجه
    عميل لم يختر اسمًا أصلًا.
    """
    import re

    slug = personal_slug(NEW_USER_ID)
    assert re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,58}[a-z0-9])?", slug)
    assert slug == personal_slug(NEW_USER_ID), "غير حتمي"
    assert slug != personal_slug("11111111-1111-4111-8111-111111111111")


def test_workspace_slug_respects_the_schema_length_limit():
    assert len(personal_slug("f" * 200)) <= 60


def test_malformed_account_id_still_yields_a_valid_slug():
    """معرّف غير متوقَّع الشكل لا يجوز أن ينتج معرّفًا يخالف قيد العمود."""
    import re

    for odd in ("", "!!!", "zz"):
        assert re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,58}[a-z0-9])?", personal_slug(odd))


def test_workspace_name_is_descriptive_and_bounded():
    """اسم وصفي **لمشغّل النظام في القاعدة**، لا يُعرض للعميل."""
    assert personal_workspace_name("سارة العتيبي") == "مساحة سارة العتيبي"
    assert personal_workspace_name("   ") == "مساحة عميل"
    assert len(personal_workspace_name("ا" * 500)) <= 200


# ===========================================================================
# التسجيل الناجح
# ===========================================================================
def test_registration_needs_no_organization_name(backend):
    """**أربعة حقول لا خمسة.** الحمولة بلا اسم جهة، والتسجيل ينجح."""
    body = payload()
    assert set(body) == {"full_name", "email", "password", "confirm_password"}

    response = client.post("/api/account/register", json=body)
    assert response.status_code == 201, response.text


def test_a_supplied_organization_name_is_ignored(backend):
    """عميل قديم أو فضولي يرسل الحقل: **يُتجاهل ولا يصير اسم المساحة.**"""
    client.post(
        "/api/account/register",
        json=payload(organization_name="هيئة الخدمات الرقمية"),
    )
    assert backend.organizations[0]["name"] == "مساحة سارة العتيبي"
    assert backend.organizations[0]["slug"] == personal_slug(NEW_USER_ID)


def test_hidden_workspace_is_generated_by_the_backend(backend):
    """المساحة تُنشأ خلف الستار: اسمها ومعرّفها من السيرفر لا من العميل."""
    response = client.post("/api/account/register", json=payload())

    assert response.status_code == 201
    assert len(backend.organizations) == 1
    org = backend.organizations[0]
    assert org["slug"] == personal_slug(NEW_USER_ID)
    assert org["name"] == personal_workspace_name("سارة العتيبي")

    # ولا يُذكر شيء من ذلك للعميل.
    text = response.text
    assert org["slug"] not in text
    assert org["name"] not in text


def test_registration_response_uses_no_organization_wording(backend):
    """⚠️ **لا مفردات مؤسسات ولا لقب مسؤول** في أي نص يصل العميل."""
    response = client.post("/api/account/register", json=payload())
    text = response.text

    for word in ("جهة", "مؤسسة", "منظمة", "مسؤول", "organization", "admin"):
        assert word not in text, f"تسرّبت مفردة «{word}» إلى رد التسجيل"


def test_registration_creates_account_workspace_and_trial(backend):
    response = client.post("/api/account/register", json=payload())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["requires_email_confirmation"] is False
    assert body["access_token"] == "issued-token"
    assert body["email"] == "sara@example.gov.sa"

    # الكتابات الأربع كلها.
    assert len(backend.organizations) == 1
    assert len(backend.profiles) == 1
    assert len(backend.members) == 1
    assert len(backend.subscriptions) == 1
    assert backend.deleted_users == [], "لا تعويض بعد نجاح"


def test_owner_role_is_internal_only(backend):
    """الدور `admin` **صلاحية قاعدة لا لقب يُعرض**.

    RLS تقيس عليه ليملك صاحب الحساب صفوف مساحته، ولا يظهر في أي شاشة.
    """
    response = client.post("/api/account/register", json=payload())

    assert backend.profiles[0]["role"] == "admin"
    assert backend.members[0]["role"] == "admin"
    assert "admin" not in response.text
    assert "مسؤول" not in response.text


def test_subscription_is_trial_with_one_seat_for_thirty_days(backend):
    """**شرط صريح**: تجريبي، مقعد واحد، ٣٠ يومًا."""
    client.post("/api/account/register", json=payload())
    sub = backend.subscriptions[0]

    assert sub["status"] == "trial"
    assert sub["seats"] == 1

    expires = datetime.fromisoformat(sub["expires_at"])
    days = (expires - datetime.now(UTC)).days
    assert 29 <= days <= 30


def test_one_seat_matches_the_one_device_policy(backend):
    """مقعد واحد يطابق «جهاز واحد لكل اشتراك» — لا رقم اعتباطي."""
    client.post("/api/account/register", json=payload())
    assert backend.subscriptions[0]["seats"] == registration_service.TRIAL_SEATS == 1


def test_email_confirmation_is_reported_when_signin_is_not_possible(backend):
    """المشروع يشترط تأكيد البريد: التسجيل نجح ولا جلسة."""
    backend.autoconfirm = False

    def refuse_sign_in(email, password):
        from app.services.supabase_auth import InvalidCredentialsError

        raise InvalidCredentialsError("البريد أو كلمة المرور غير صحيحة.")

    registration_service.sign_in = refuse_sign_in
    try:
        response = client.post("/api/account/register", json=payload())
    finally:
        from app.services.supabase_auth import sign_in as real_sign_in

        registration_service.sign_in = real_sign_in

    assert response.status_code == 201
    body = response.json()
    assert body["requires_email_confirmation"] is True
    assert body["access_token"] is None
    # الحساب والجهة أُنشئا رغم ذلك — التسجيل لم يفشل.
    assert len(backend.organizations) == 1
    assert backend.deleted_users == []


# ===========================================================================
# الرفض النظيف
# ===========================================================================
def test_duplicate_email_is_rejected_cleanly(backend):
    client.post("/api/account/register", json=payload())
    response = client.post("/api/account/register", json=payload())

    assert response.status_code == 409
    assert "مسجَّل مسبقًا" in response.json()["detail"]
    # لا جهة ثانية ولا اشتراك ثانٍ.
    assert len(backend.organizations) == 1
    assert len(backend.subscriptions) == 1


def test_workspace_conflict_is_reported_without_organization_wording(backend):
    """تصادم المساحة لا يقع عمليًا (المعرّف من `uuid`)، والقيد يحرسه.

    ما يهمّ هنا أن الرسالة **لا تحدّث العميل عن جهة ولا عن اسم مستخدَم**
    لأنه لم يُدخل شيئًا من ذلك.
    """
    client.post("/api/account/register", json=payload())
    # المستخدم نفسه بمعرّف واحد ⇒ المعرّف النصي نفسه ⇒ تصادم.
    backend.auth_users.clear()
    response = client.post(
        "/api/account/register", json=payload(email="other@example.gov.sa")
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "جهة" not in detail and "مسؤول" not in detail
    assert len(backend.organizations) == 1


def test_password_mismatch_is_refused_before_any_write(backend):
    response = client.post(
        "/api/account/register",
        json=payload(confirm_password="DifferentPass!2026"),
    )

    assert response.status_code == 422
    assert backend.auth_users == {}, "لا يُنشأ حساب وكلمتا المرور مختلفتان"
    assert backend.organizations == []


def test_short_password_is_refused(backend):
    response = client.post(
        "/api/account/register", json=payload(password="short", confirm_password="short")
    )
    assert response.status_code == 422
    assert backend.auth_users == {}


# ===========================================================================
# التعويض عن الفشل الجزئي
# ===========================================================================
def test_failed_organization_creation_deletes_the_auth_user(backend):
    """**جوهر الاتساق.**

    لولا التعويض لبقي بريد محجوزًا بحساب بلا جهة: صاحبه لا يستطيع التسجيل
    من جديد (البريد مأخوذ) ولا استعمال ما سجّله (لا جهة له).
    """
    original = backend._register_organization
    backend._register_organization = lambda params: httpx.Response(
        500, json={"code": "XX000", "message": "boom"}
    )
    try:
        response = client.post("/api/account/register", json=payload())
    finally:
        backend._register_organization = original

    assert response.status_code in (400, 503)
    assert backend.deleted_users == [NEW_USER_ID], "لم يُحذف حساب المصادقة"
    assert backend.organizations == []
    assert backend.subscriptions == []


def test_duplicate_slug_failure_also_compensates(backend):
    client.post("/api/account/register", json=payload())
    backend.deleted_users.clear()
    backend.auth_users.clear()  # يسمح بإنشاء حساب ثانٍ ببريد مختلف

    client.post("/api/account/register", json=payload(email="two@example.gov.sa"))

    assert backend.deleted_users == [NEW_USER_ID]
    assert len(backend.organizations) == 1


def test_existing_auth_email_is_rejected_before_touching_tables(backend):
    backend.auth_users["someone"] = "sara@example.gov.sa"
    response = client.post("/api/account/register", json=payload())

    assert response.status_code == 409
    assert backend.organizations == []


# ===========================================================================
# الأمان
# ===========================================================================
def test_registration_never_returns_a_service_role_key(backend):
    response = client.post("/api/account/register", json=payload())
    assert "service-key-for-tests" not in response.text
    assert "supabase.co" not in response.text
    assert "anon-key-for-tests" not in response.text


def test_registration_request_asks_for_no_url_or_key():
    """⚠️ لا حقل لرابط ولا لمفتاح ولا لاسم جهة في نموذج التسجيل."""
    spec = client.get("/openapi.json").json()
    fields = set(spec["components"]["schemas"]["RegistrationRequest"]["properties"])
    assert fields == {"full_name", "email", "password", "confirm_password"}


def test_internal_failures_do_not_leak_details(backend):
    """رسالة عربية عامة، بلا اسم جدول ولا رمز PostgreSQL."""
    original = backend._register_organization
    backend._register_organization = lambda params: httpx.Response(
        500, json={"code": "42P01", "message": 'relation "public.organizations" does not exist'}
    )
    try:
        response = client.post("/api/account/register", json=payload())
    finally:
        backend._register_organization = original

    detail = response.json()["detail"]
    assert "relation" not in detail
    assert "organizations" not in detail
    assert "جهة" not in detail
    assert "42P01" not in detail
    assert "تعذّر" in detail


def test_login_still_works_after_adding_registration(backend):
    """**التسجيل لا يكسر الدخول**: المساران يتعايشان."""
    response = client.post(
        "/api/account/login",
        json={"email": "sara@example.gov.sa", "password": "StrongPass!2026"},
    )
    assert response.status_code == 200
    assert response.json()["access_token"] == "issued-token"
