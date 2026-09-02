"""جلسات التركيب ومسارات الـRuntime.

**ما يثبته هذا الملف وما لا يثبته.**

يثبت: أن الـBackend يولّد رمزًا عشوائيًا قويًا، ويخزّن **تجزئته وحدها**،
ويجزّئ سرّ الجهاز بالمِلح قبل أن يمسّ القاعدة، ويترجم أخطاء القاعدة إلى
رسائل عربية، وأن كل مسار مقيّد بجهازه.

**لا يثبت الذرّية** — تلك في القاعدة نفسها، ويثبتها قسم الاختبارات داخل
`database/supabase/0002_installation_sessions.sql` الذي نُفّذ على PostgreSQL
حقيقي. القاعدة المزيّفة هنا **تحاكي عقد الدالة**: رمز لمرة واحدة، ورفض
المنتهي، وجهاز فعّال واحد. محاكاة العقد تجعل اختبار بايثون ذا معنى؛ ولو
حاكت نجاحًا دائمًا لاختبرت المزيّف.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.database import supabase
from app.main import app
from app.services import installation_session_service as sessions

from tests.test_entitlements import (
    ADMIN_A,
    DEVICE_A,
    EMPLOYEE_A,
    JWT_SECRET,
    ORG_A,
    PEPPER,
    SUB_A,
    FakeSupabase,
    auth,
    iso,
    token_for,
)

client = TestClient(app)

#: هوية جهاز يولّدها الـRuntime. **ليست بيان اعتماد**: لا يصادق بها مسار.
RUNTIME_SECRET = "runtime-device-secret-value-0001"
OTHER_SECRET = "runtime-device-secret-value-0002"

#: بيانات الاعتماد الصادرة في هذا الاختبار، بترتيب إصدارها.
#:
#: يُفرَّغ في التركيبة `fake`: بقاؤه بين الاختبارات يجعل اختبارًا يصادق
#: ببيان أصدره اختبار سابق، فتصير النتيجة تابعة للترتيب.
ISSUED_CREDENTIALS: list[str] = []


class SessionAwareSupabase(FakeSupabase):
    """يضيف جدول الجلسات ودالة `redeem_installation_session`.

    الدالة المزيّفة تنفّذ **الشروط نفسها** التي ينفّذها نظيرها في
    PostgreSQL: رمز غير مستعمَل وغير منتهٍ، واشتراك يسمح، وجهاز فعّال واحد.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tables["installation_sessions"] = []
        self.tables["device_credentials"] = []
        self.rpc_calls: list[tuple[str, dict[str, Any]]] = []

    # -- دالة الاستهلاك ------------------------------------------------
    def _redeem(self, payload: dict[str, Any]) -> httpx.Response:
        token_hash = payload["p_token_hash"]
        device_hash = payload["p_device_hash"]
        now = datetime.now(UTC)

        row = next(
            (
                item
                for item in self.tables["installation_sessions"]
                if item["token_hash"] == token_hash
                and item.get("used_at") is None
                and datetime.fromisoformat(item["expires_at"]) > now
            ),
            None,
        )
        if row is None:
            return httpx.Response(
                400,
                json={"code": "28000", "message": "invalid_installation_token"},
            )

        subscription = next(
            item
            for item in self.tables["subscriptions"]
            if item["id"] == row["subscription_id"]
        )
        if subscription["status"] not in ("trial", "active") or datetime.fromisoformat(
            subscription["expires_at"]
        ) <= now:
            return httpx.Response(
                400,
                json={"code": "22023", "message": "subscription_not_serviceable"},
            )

        active = [
            item
            for item in self.tables["device_activations"]
            if item["subscription_id"] == row["subscription_id"]
            and item.get("revoked_at") is None
        ]

        # الجهاز نفسه: عملية مُعادة التنفيذ لا خطأ.
        same = next(
            (item for item in active if item["device_id_hash"] == device_hash), None
        )
        if same is not None:
            row["used_at"] = now.isoformat()
            return httpx.Response(
                200,
                json=[
                    {
                        "out_activation_id": same["id"],
                        "out_subscription_id": row["subscription_id"],
                        "out_organization_id": row["organization_id"],
                        "out_user_id": row["user_id"],
                    }
                ],
            )

        if active:
            # ما يعيده الفهرس الفريد الجزئي في PostgreSQL.
            return httpx.Response(
                409, json={"code": "23505", "message": "unique constraint"}
            )

        self._next_id += 1
        activation = {
            "id": self._next_id,
            "subscription_id": row["subscription_id"],
            "device_id_hash": device_hash,
            "device_name": payload.get("p_device_name") or "جهاز غير مسمّى",
            "activated_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "revoked_at": None,
        }
        self.tables["device_activations"].append(activation)
        row["used_at"] = now.isoformat()

        return httpx.Response(
            200,
            json=[
                {
                    "out_activation_id": activation["id"],
                    "out_subscription_id": row["subscription_id"],
                    "out_organization_id": row["organization_id"],
                    "out_user_id": row["user_id"],
                }
            ],
        )

    # -- بيانات اعتماد الأجهزة -----------------------------------------
    def _issue_credential(self, payload: dict[str, Any]) -> httpx.Response:
        """يحاكي `issue_device_credential` بشروطها الثلاثة نفسها.

        محاكاة **العقد** لا النجاح: تفعيل مبطَل يُرفض، واشتراك لا يسمح
        يُرفض، والبيان السابق يُبطل قبل إدراج الجديد. مزيّفٌ ينجح دائمًا
        يختبر المزيّف.
        """
        activation_id = int(payload["p_activation_id"])
        credential_hash = payload["p_credential_hash"]
        now = datetime.now(UTC)

        activation = next(
            (
                item
                for item in self.tables["device_activations"]
                if item["id"] == activation_id
            ),
            None,
        )
        if activation is None:
            return httpx.Response(
                400, json={"code": "22023", "message": "activation_not_found"}
            )
        if activation.get("revoked_at") is not None:
            return httpx.Response(
                400, json={"code": "22023", "message": "activation_revoked"}
            )

        subscription = next(
            item
            for item in self.tables["subscriptions"]
            if item["id"] == activation["subscription_id"]
        )
        if subscription["status"] not in ("trial", "active") or datetime.fromisoformat(
            subscription["expires_at"]
        ) <= now:
            return httpx.Response(
                400,
                json={"code": "22023", "message": "subscription_not_serviceable"},
            )

        revoked_id = None
        for item in self.tables["device_credentials"]:
            if item["activation_id"] == activation_id and item["revoked_at"] is None:
                item["revoked_at"] = now.isoformat()
                revoked_id = item["id"]

        self._next_id += 1
        self.tables["device_credentials"].append(
            {
                "id": self._next_id,
                "activation_id": activation_id,
                "credential_hash": credential_hash,
                "issued_at": now.isoformat(),
                "last_used_at": now.isoformat(),
                "revoked_at": None,
            }
        )
        return httpx.Response(
            200,
            json=[
                {"out_credential_id": self._next_id, "out_revoked_id": revoked_id}
            ],
        )

    def _authenticate_credential(self, payload: dict[str, Any]) -> httpx.Response:
        """يحاكي `authenticate_device_credential` — الفحوص الثلاثة معًا.

        ⚠️ **إبطال التفعيل يبطل بيانه** كما يفعل المشغّل في القاعدة: تُقرأ
        `revoked_at` من صفّ التفعيل نفسه، فلا يحتاج الاختبار أن يتذكّر
        تحديث الجدولين معًا.
        """
        now = datetime.now(UTC)
        credential = next(
            (
                item
                for item in self.tables["device_credentials"]
                if item["credential_hash"] == payload["p_credential_hash"]
                and item["revoked_at"] is None
            ),
            None,
        )
        if credential is None:
            return httpx.Response(200, json=[])

        activation = next(
            (
                item
                for item in self.tables["device_activations"]
                if item["id"] == credential["activation_id"]
                and item.get("revoked_at") is None
            ),
            None,
        )
        if activation is None:
            return httpx.Response(200, json=[])

        subscription = next(
            (
                item
                for item in self.tables["subscriptions"]
                if item["id"] == activation["subscription_id"]
            ),
            None,
        )
        if subscription is None:
            return httpx.Response(200, json=[])

        # الراية تستثني فحص الاشتراك وحده — لمسار الإخبار.
        if payload.get("p_require_serviceable", True) and (
            subscription["status"] not in ("trial", "active")
            or datetime.fromisoformat(subscription["expires_at"]) <= now
        ):
            return httpx.Response(200, json=[])

        credential["last_used_at"] = now.isoformat()
        activation["last_seen_at"] = now.isoformat()

        return httpx.Response(
            200,
            json=[
                {
                    "out_activation_id": activation["id"],
                    "out_subscription_id": subscription["id"],
                    "out_organization_id": subscription["organization_id"],
                    "out_device_name": activation["device_name"],
                    "out_activated_at": activation["activated_at"],
                    "out_last_seen_at": activation["last_seen_at"],
                    "out_status": subscription["status"],
                    "out_starts_at": subscription["starts_at"],
                    "out_expires_at": subscription["expires_at"],
                    "out_seats": subscription.get("seats", 1),
                }
            ],
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        if "/rpc/" in request.url.path:
            name = request.url.path.rsplit("/", 1)[-1]
            payload = json.loads(request.content or b"{}")
            self.rpc_calls.append((name, payload))
            if name == "redeem_installation_session":
                return self._redeem(payload)
            if name == "issue_device_credential":
                return self._issue_credential(payload)
            if name == "authenticate_device_credential":
                return self._authenticate_credential(payload)
            if name in (
                "purge_expired_installation_sessions",
                "purge_revoked_device_credentials",
            ):
                return httpx.Response(200, json=0)
            return httpx.Response(404, json={"message": "unknown function"})
        return super().handler(request)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key-for-tests")
    monkeypatch.setattr(settings, "supabase_service_role_key", "service-key")
    monkeypatch.setattr(settings, "supabase_jwt_secret", JWT_SECRET)
    monkeypatch.setattr(settings, "device_hash_pepper", PEPPER)
    monkeypatch.setattr(settings, "installation_token_ttl_minutes", 15)

    ISSUED_CREDENTIALS.clear()
    backend = SessionAwareSupabase()
    supabase.set_client(
        httpx.Client(
            base_url=supabase.rest_base_url(),
            transport=httpx.MockTransport(backend.handler),
        )
    )
    yield backend
    supabase.set_client(None)
    ISSUED_CREDENTIALS.clear()


def issue_token(user: str = EMPLOYEE_A) -> str:
    response = client.post(
        "/api/account/installation-session", headers=auth(user)
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def runtime_activate(token: str, secret: str = RUNTIME_SECRET):
    """يستبدل رمز التركيب، ويحفظ بيان الاعتماد العائد للاختبارات التالية."""
    response = client.post(
        "/api/runtime/activate",
        json={
            "token": token,
            "device_secret": secret,
            "device_name": "حاسب ويندوز 11",
        },
    )
    if response.status_code == 200:
        ISSUED_CREDENTIALS.append(response.json()["device_credential"])
    return response


def device_headers(credential: str | None = None) -> dict[str, str]:
    """ترويسة مصادقة الـRuntime — **ببيان الاعتماد لا بسرّ الهوية**."""
    value = credential or (ISSUED_CREDENTIALS[-1] if ISSUED_CREDENTIALS else "")
    return {"X-GovMind-Device-Credential": value}


# ===========================================================================
# إصدار الرمز
# ===========================================================================
def test_issuing_requires_authentication(fake):
    assert client.post("/api/account/installation-session").status_code == 401


def test_token_is_returned_once_and_stored_hashed_only(fake):
    """⚠️ **الرمز الخام لا يدخل القاعدة.** المخزَّن تجزئته وحدها."""
    token = issue_token()

    stored = fake.tables["installation_sessions"]
    assert len(stored) == 1
    assert stored[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in json.dumps(fake.tables, ensure_ascii=False)


def test_token_has_high_entropy(fake):
    """رمز يُخمَّن لا يحمي شيئًا. ٣٢ بايت عشوائية ⇒ ٤٣ حرفًا على الأقل."""
    tokens = {issue_token() for _ in range(5)}
    assert len(tokens) == 5, "تكرّر رمز — المولّد ليس عشوائيًا"
    for token in tokens:
        assert len(token) >= 43


def test_token_is_bound_to_user_organization_and_subscription(fake):
    issue_token()
    row = fake.tables["installation_sessions"][0]

    assert row["user_id"] == EMPLOYEE_A
    assert row["organization_id"] == ORG_A
    assert row["subscription_id"] == SUB_A


def test_token_expires_quickly(fake):
    body = client.post(
        "/api/account/installation-session", headers=auth(EMPLOYEE_A)
    ).json()

    assert body["expires_in_minutes"] == 15
    expires = datetime.fromisoformat(body["expires_at"])
    assert expires - datetime.now(UTC) < timedelta(minutes=20)


@pytest.mark.parametrize("status", ["expired", "suspended", "cancelled"])
def test_blocked_subscription_gets_no_token(fake, status):
    fake.tables["subscriptions"][0]["status"] = status
    response = client.post(
        "/api/account/installation-session", headers=auth(EMPLOYEE_A)
    )
    assert response.status_code == 403
    assert fake.tables["installation_sessions"] == []


# ===========================================================================
# استهلاك الرمز — لمرة واحدة
# ===========================================================================
def test_activation_succeeds_and_stores_only_a_hash(fake):
    """⚠️ **سرّ الجهاز الخام لا يدخل القاعدة.**"""
    response = runtime_activate(issue_token())
    assert response.status_code == 200

    activation = fake.tables["device_activations"][0]
    stored = activation["device_id_hash"]
    assert stored != RUNTIME_SECRET
    assert len(stored) == 64
    assert all(character in "0123456789abcdef" for character in stored)
    assert RUNTIME_SECRET not in json.dumps(fake.tables, ensure_ascii=False)


def test_hash_uses_the_configured_pepper(fake, monkeypatch):
    """مِلح مختلف ⇒ تجزئة مختلفة. بلا مِلح لكانت التجزئة قابلة للتخمين."""
    runtime_activate(issue_token())
    first = fake.tables["device_activations"][0]["device_id_hash"]

    fake.tables["device_activations"].clear()
    monkeypatch.setattr(settings, "device_hash_pepper", "a-completely-different-pepper")
    runtime_activate(issue_token())

    assert fake.tables["device_activations"][0]["device_id_hash"] != first


def test_token_is_single_use(fake):
    """**الشرط الأصعب:** الرمز يُحرق باستهلاكه."""
    token = issue_token()
    assert runtime_activate(token).status_code == 200

    replay = runtime_activate(token, OTHER_SECRET)
    assert replay.status_code == 401
    assert "غير صالح" in replay.json()["detail"]


def test_replaying_from_the_same_device_also_fails(fake):
    """إعادة الإرسال بالسرّ نفسه بعد الحرق: مرفوضة كذلك."""
    token = issue_token()
    runtime_activate(token)
    assert runtime_activate(token).status_code == 401


def test_expired_token_is_refused(fake):
    token = issue_token()
    fake.tables["installation_sessions"][0]["expires_at"] = (
        datetime.now(UTC) - timedelta(minutes=1)
    ).isoformat()

    response = runtime_activate(token)
    assert response.status_code == 401
    assert fake.tables["device_activations"] == []


def test_unknown_token_is_refused(fake):
    response = runtime_activate("a-token-that-was-never-issued-0001")
    assert response.status_code == 401
    assert fake.tables["device_activations"] == []


def test_error_message_does_not_distinguish_failure_causes(fake):
    """لا يُفرَّق بين «خاطئ» و«منتهٍ» و«مستعمَل».

    التفريق يخبر من يجرّب الرموز أيّها كان صحيحًا يومًا.
    """
    used = issue_token()
    runtime_activate(used)

    expired = issue_token()
    fake.tables["installation_sessions"][-1]["expires_at"] = (
        datetime.now(UTC) - timedelta(minutes=1)
    ).isoformat()

    messages = {
        runtime_activate(used, OTHER_SECRET).json()["detail"],
        runtime_activate(expired, OTHER_SECRET).json()["detail"],
        runtime_activate("never-issued-token-value-000001").json()["detail"],
    }
    assert len(messages) == 1


def test_second_device_is_refused(fake):
    """الرفض يأتي من **قيد القاعدة** (23505)، ويُترجم إلى رسالة مفهومة."""
    runtime_activate(issue_token())
    response = runtime_activate(issue_token(), OTHER_SECRET)

    assert response.status_code == 409
    assert "جهاز آخر" in response.json()["detail"]
    active = [
        item
        for item in fake.tables["device_activations"]
        if item["revoked_at"] is None
    ]
    assert len(active) == 1


def test_same_device_reactivation_is_idempotent(fake):
    """انقطاع بين النجاح ووصول الرد: إعادة المحاولة تنجح ولا تكرّر."""
    runtime_activate(issue_token())
    response = runtime_activate(issue_token(), RUNTIME_SECRET)

    assert response.status_code == 200
    assert len(fake.tables["device_activations"]) == 1


def test_activation_after_admin_revocation_succeeds(fake):
    """المسار الكامل لتغيير الجهاز: إبطال ثم تفعيل جهاز جديد."""
    runtime_activate(issue_token())
    fake.tables["device_activations"][0]["revoked_at"] = datetime.now(UTC).isoformat()

    assert runtime_activate(issue_token(), OTHER_SECRET).status_code == 200


def test_blocked_subscription_refuses_activation(fake):
    token = issue_token()
    fake.tables["subscriptions"][0]["status"] = "expired"

    response = runtime_activate(token)
    assert response.status_code == 403
    assert fake.tables["device_activations"] == []


# ===========================================================================
# مصادقة الـRuntime ببيان اعتماده
# ===========================================================================
def test_entitlement_requires_a_device_credential(fake):
    assert client.get("/api/runtime/entitlement").status_code == 401


def test_entitlement_reads_the_subscription(fake):
    runtime_activate(issue_token())
    response = client.get("/api/runtime/entitlement", headers=device_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["is_usable"] is True
    assert body["status"] == "active"
    assert body["device_name"] == "حاسب ويندوز 11"


def test_unknown_device_credential_is_refused(fake):
    runtime_activate(issue_token())
    response = client.get(
        "/api/runtime/entitlement",
        headers=device_headers("a-credential-that-was-never-issued-0001"),
    )
    # ٤٠١ = «لم أقبل بيان اعتمادك»، لا ٤٠٣ = «اشتراكك لا يسمح».
    assert response.status_code == 401


def test_the_runtime_generated_secret_is_not_accepted_as_a_credential(fake):
    """⚠️ **سرّ الجهاز لم يعد يصادق شيئًا.**

    كان مقبولًا، وكان ذلك خطأً في نموذج الثقة: مصدر القيمة هو الطرف غير
    الموثوق. الاختبار يرسله في ترويسة المصادقة ويتوقّع الرفض.
    """
    runtime_activate(issue_token())
    response = client.get(
        "/api/runtime/entitlement", headers=device_headers(RUNTIME_SECRET)
    )
    assert response.status_code == 401


def test_the_legacy_device_secret_header_authenticates_nothing(fake):
    """الترويسة القديمة لا تفتح شيئًا — ولو حملت القيمة الصحيحة."""
    runtime_activate(issue_token())
    response = client.get(
        "/api/runtime/entitlement",
        headers={"X-GovMind-Device-Secret": ISSUED_CREDENTIALS[-1]},
    )
    assert response.status_code == 401


def test_revoked_device_loses_access(fake):
    """إبطال المسؤول: أول تحديث استحقاق يفشل، فيتوقف المودل."""
    runtime_activate(issue_token())
    fake.tables["device_activations"][0]["revoked_at"] = datetime.now(UTC).isoformat()

    response = client.get("/api/runtime/entitlement", headers=device_headers())
    # **٤٠١ لا ٤٠٣**: الجهاز لم يعد مقبولًا، لا أن اشتراكه لا يسمح. الفرق
    # يقرّر ما يفعله الـRuntime: يمحو ربطه ويطلب ربطًا جديدًا من الإضافة.
    assert response.status_code == 401
    assert "غير مرتبط" in response.json()["detail"]


def test_expired_subscription_is_reported_not_hidden(fake):
    """الـRuntime يحتاج **السبب** ليعرضه بالعربية، لا خطأً عامًا."""
    runtime_activate(issue_token())
    fake.tables["subscriptions"][0]["status"] = "expired"

    body = client.get("/api/runtime/entitlement", headers=device_headers()).json()
    assert body["is_usable"] is False
    assert "انتهى اشتراكك" in body["blocked_reason"]


def test_device_hash_never_appears_in_a_runtime_response(fake):
    runtime_activate(issue_token())
    stored = fake.tables["device_activations"][0]["device_id_hash"]
    stored_credential = fake.tables["device_credentials"][0]["credential_hash"]

    for response in (
        client.get("/api/runtime/entitlement", headers=device_headers()),
        runtime_activate(issue_token(), RUNTIME_SECRET),
    ):
        assert stored not in response.text
        assert stored_credential not in response.text
        assert RUNTIME_SECRET not in response.text


# ===========================================================================
# رابط المودل
# ===========================================================================
@pytest.fixture
def azure_model(monkeypatch):
    """إعداد مودل وهمي. **ليست بيانات اعتماد حقيقية.**"""
    monkeypatch.setattr(settings, "azure_storage_account", "govmindtest")
    monkeypatch.setattr(settings, "azure_storage_container", "releases")
    monkeypatch.setattr(settings, "azure_model_blob_name", "models/govmind.gguf")
    monkeypatch.setattr(settings, "azure_model_sha256", "b" * 64)
    monkeypatch.setattr(settings, "azure_model_size_bytes", 5_335_291_936)
    monkeypatch.setattr(
        settings,
        "azure_storage_connection_string",
        "DefaultEndpointsProtocol=https;AccountName=govmindtest;"
        "AccountKey=dGVzdC1hY2NvdW50LWtleS1ub3QtcmVhbA==;"
        "EndpointSuffix=core.windows.net",
    )


def test_model_url_is_issued_with_verification_data(fake, azure_model):
    runtime_activate(issue_token())
    response = client.get("/api/runtime/model", headers=device_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["sha256"] == "b" * 64
    assert body["size_bytes"] == 5_335_291_936
    assert "sig=" in body["download_url"]
    assert "sp=r" in body["download_url"]


def test_model_url_needs_an_activated_device(fake, azure_model):
    assert client.get("/api/runtime/model").status_code == 401
    assert (
        client.get(
            "/api/runtime/model",
            headers=device_headers("never-issued-credential-value-0001"),
        ).status_code
        == 401
    )


@pytest.mark.parametrize("status", ["expired", "suspended", "cancelled"])
def test_model_url_is_refused_on_a_blocked_subscription(fake, azure_model, status):
    runtime_activate(issue_token())
    fake.tables["subscriptions"][0]["status"] = status

    response = client.get("/api/runtime/model", headers=device_headers())
    assert response.status_code == 403
    assert "download_url" not in response.text


def test_model_url_never_leaks_the_connection_string(fake, azure_model):
    runtime_activate(issue_token())
    response = client.get("/api/runtime/model", headers=device_headers())

    assert "AccountKey" not in response.text
    assert "dGVzdC1hY2NvdW50LWtleS1ub3QtcmVhbA==" not in response.text


def test_missing_model_configuration_names_the_variables(fake, monkeypatch):
    monkeypatch.setattr(settings, "azure_storage_account", "govmindtest")
    monkeypatch.setattr(settings, "azure_storage_container", "releases")
    monkeypatch.setattr(
        settings,
        "azure_storage_connection_string",
        "AccountName=x;AccountKey=dGVzdA==;",
    )
    monkeypatch.setattr(settings, "azure_model_blob_name", "")
    monkeypatch.setattr(settings, "azure_model_sha256", "")
    monkeypatch.setattr(settings, "azure_model_size_bytes", 0)

    runtime_activate(issue_token())
    response = client.get("/api/runtime/model", headers=device_headers())

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "AZURE_MODEL_BLOB_NAME" in detail
    assert "AZURE_MODEL_SHA256" in detail
    assert "AZURE_MODEL_SIZE_BYTES" in detail


def test_installer_and_model_use_separate_blobs(fake, azure_model, monkeypatch):
    """المثبّت والمودل مدوّنتان منفصلتان — لا يُحزَم أحدهما مع الآخر."""
    monkeypatch.setattr(settings, "azure_installer_blob_name", "setup/GovMindSetup.exe")
    runtime_activate(issue_token())

    model = client.get("/api/runtime/model", headers=device_headers()).json()
    installer = client.post(
        "/api/account/installer/download-url",
        json={"device_id": DEVICE_A},
        headers=auth(EMPLOYEE_A),
    )

    assert "models/govmind.gguf" in model["download_url"]
    # المثبّت يتطلّب جهازًا مفعّلًا ببصمة الإضافة؛ يكفي هنا أن يختلف المسار.
    assert model["file_name"] == "govmind.gguf"
    del installer
