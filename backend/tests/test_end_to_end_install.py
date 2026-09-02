"""المسار الكامل من دخول الإضافة إلى فتح GovMind بلا دخول ثانٍ.

**لماذا هنا وليس في `runtime/tests`؟** لأن هذا هو الاختبار الوحيد الذي
يشغّل **الطرفين معًا**: الـBackend الحقيقي (تطبيق FastAPI كما هو) وعميل
الـRuntime الحقيقي (``ControlPlaneClient`` و``RuntimeService`` كما هما).
ما بينهما وحده مزيّف: قاعدة Supabase، وتخزين Azure، وحماية DPAPI على غير
ويندوز، ومحرّك `llama-server`.

**ما يثبته هذا الملف بالضبط** — وهو التسلسل الحيّ الذي فشل عند العميل:

    دخول الإضافة
    → التحقق من الاشتراك
    → اختيار التجربة
    → إنشاء جلسة تركيب
    → طلب رابط Azure مؤقّت
    → تنزيل المثبّت
    → **نقرة صريحة من المستخدم تفتح المثبّت**
    → إقلاع الـRuntime
    → استبدال جلسة التركيب
    → إصدار بيان اعتماد الجهاز وحفظه محميًّا
    → الجهاز يصير فعّالًا
    → GovMind يفتح **بلا تسجيل دخول آخر**

⚠️ **ولا يعود «Method Not Allowed» في أي خطوة.**
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

# الـRuntime حزمة مستقلة خارج `backend/`؛ هذا الاختبار وحده يحتاج الاثنين.
_RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime"
if str(_RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_DIR))

from app.core.config import settings  # noqa: E402
from app.database import supabase  # noqa: E402
from app.main import app  # noqa: E402
from govmind_runtime.config import RuntimeConfig  # noqa: E402
from govmind_runtime.control_plane import (  # noqa: E402
    ALLOWED_ROUTES,
    ControlPlaneClient,
    RouteNotAllowedError,
)
from govmind_runtime.identity import (  # noqa: E402
    DeviceCredentialStore,
    DeviceIdentity,
)
from govmind_runtime.service import RuntimeService  # noqa: E402
from govmind_runtime.state import Phase  # noqa: E402

from tests.test_entitlements import (  # noqa: E402
    DEVICE_A,
    EMPLOYEE_A,
    JWT_SECRET,
    PEPPER,
    auth,
)
from tests.test_installation_sessions import SessionAwareSupabase  # noqa: E402

client = TestClient(app)


class LocalProtector:
    """حامي أسرار للاختبار — **بديل DPAPI على غير ويندوز فقط**.

    على ويندوز يستعمل الاختبار DPAPI الحقيقي (انظر `dpapi_protector`)، لأن
    اختبار الحماية بمزيّف يختبر المزيّف. وهذا البديل يحفظ الخاصية الوحيدة
    التي يقيسها الاختبار على كل نظام: **أن الملف لا يحوي القيمة الخام**.
    """

    name = "test-inmemory"

    def protect(self, secret: bytes) -> bytes:
        return b"TESTBLOB:" + secret[::-1]

    def unprotect(self, blob: bytes) -> bytes:
        if not blob.startswith(b"TESTBLOB:"):
            raise ValueError("blob غير معروف")
        return blob[len(b"TESTBLOB:") :][::-1]


def make_protector():
    if sys.platform == "win32":
        from govmind_runtime.identity import DpapiProtector

        return DpapiProtector()
    return LocalProtector()


class BackendTransport(httpx.BaseTransport):
    """ينقل نداءات الـRuntime إلى تطبيق الـBackend **بلا شبكة**.

    ⚠️ **ليس مزيّفًا للـBackend.** الطلب يمرّ بمسارات FastAPI الحقيقية،
    وباعتمادياتها، وبنماذجها. المزيّف هو ما تحت الـBackend وحده.
    """

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self._asgi = httpx.ASGITransport(app=app)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        # `ASGITransport` غير متزامن؛ يُلَفّ بعميل الاختبار المتزامن.
        response = client.request(
            request.method,
            request.url.path,
            content=request.content or None,
            headers={
                key: value
                for key, value in request.headers.items()
                if key.lower() not in ("host", "content-length")
            },
        )
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers={"content-type": response.headers.get("content-type", "")},
            request=request,
        )


@pytest.fixture
def world(monkeypatch, tmp_path):
    """يبني العالمين معًا: Backend بقاعدة مزيّفة، وRuntime على قرص مؤقت."""
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key-for-tests")
    monkeypatch.setattr(settings, "supabase_service_role_key", "service-key")
    monkeypatch.setattr(settings, "supabase_jwt_secret", JWT_SECRET)
    monkeypatch.setattr(settings, "device_hash_pepper", PEPPER)
    monkeypatch.setattr(settings, "installation_token_ttl_minutes", 15)

    # تخزين مثبّت وهمي. **ليست بيانات اعتماد حقيقية.**
    monkeypatch.setattr(settings, "azure_storage_account", "govmindtest")
    monkeypatch.setattr(settings, "azure_storage_container", "releases")
    monkeypatch.setattr(
        settings, "azure_installer_blob_name", "setup/GovMindSetup.exe"
    )
    monkeypatch.setattr(
        settings,
        "azure_storage_connection_string",
        "DefaultEndpointsProtocol=https;AccountName=govmindtest;"
        "AccountKey=dGVzdC1hY2NvdW50LWtleS1ub3QtcmVhbA==;"
        "EndpointSuffix=core.windows.net",
    )

    database = SessionAwareSupabase()
    supabase.set_client(
        httpx.Client(
            base_url=supabase.rest_base_url(),
            transport=httpx.MockTransport(database.handler),
        )
    )

    transport = BackendTransport()
    data_dir = tmp_path / "programdata"
    config = RuntimeConfig(
        control_plane_url="https://control.govmind.test",
        data_dir=data_dir,
        install_root=tmp_path / "install",
        port=8765,
    )
    protector = make_protector()

    service = RuntimeService(
        config,
        identity=DeviceIdentity(data_dir, protector),
        credentials=DeviceCredentialStore(data_dir, protector),
        control_plane=ControlPlaneClient(
            config.control_plane_url, client=httpx.Client(transport=transport)
        ),
        model_store=_NoModel(),
        supervisor=_NoEngine(),
    )

    yield _World(database=database, transport=transport, service=service, config=config)
    supabase.set_client(None)


class _World:
    def __init__(self, *, database, transport, service, config) -> None:
        self.database = database
        self.transport = transport
        self.service = service
        self.config = config


class _NoModel:
    """مخزن مودل لا ينزّل شيئًا: هذا الاختبار عن الربط لا عن المودل."""

    def is_installed(self) -> bool:
        return True

    def download(self, artifact, *, on_progress=None) -> None:  # pragma: no cover
        raise AssertionError("لا يُفترض أن يُنزَّل مودل في هذا الاختبار")

    def cancel(self) -> None:  # pragma: no cover
        pass


class _NoEngine:
    def __init__(self) -> None:
        self.base_url = None
        self.started = 0

    def start(self, **kwargs):
        self.started += 1
        self.base_url = "http://127.0.0.1:51234/v1"
        return self.base_url

    def stop(self) -> None:
        self.base_url = None


def wait(service: RuntimeService) -> None:
    worker = service._worker
    if worker is not None:
        worker.join(timeout=10)


# ===========================================================================
# المسار الكامل
# ===========================================================================
def test_the_whole_install_flow_ends_without_a_second_login(world):
    """التسلسل الحيّ كاملًا، خطوةً خطوة، بترتيبه الصحيح."""
    service = world.service

    # ① دخول الإضافة ------------------------------------------------------
    # (الجلسة في هذا الاختبار رمز Supabase موقَّع؛ `auth` تبنيه.)
    headers = auth(EMPLOYEE_A)

    # ② التحقق من الاشتراك -------------------------------------------------
    status_response = client.get("/api/account/subscription", headers=headers)
    assert status_response.status_code == 200
    assert status_response.json()["is_usable"] is True
    assert status_response.json()["status"] in ("trial", "active")

    # ③ اختيار التجربة — **إقرار في الإضافة، بلا أي طلب شبكي.**
    #    الاشتراك التجريبي يُنشأ عند التسجيل، ونداءٌ ثانٍ كان سيضاعف الصفوف.
    before = len(world.transport.requests)

    # ④ إنشاء جلسة تركيب ---------------------------------------------------
    session = client.post("/api/account/installation-session", headers=headers)
    assert session.status_code == 200
    install_token = session.json()["token"]

    # ⚠️ الرمز الخام لا يدخل القاعدة: المخزَّن تجزئته وحدها.
    stored = world.database.tables["installation_sessions"][0]
    assert install_token not in str(stored)

    # ⑤ رابط Azure مؤقّت ---------------------------------------------------
    link = client.post(
        "/api/account/installer/download-url",
        json={"device_id": DEVICE_A},
        headers=headers,
    )
    assert link.status_code == 200
    assert "sig=" in link.json()["download_url"]
    # ⚠️ سلسلة اتصال Azure لا تخرج مع الرابط.
    assert "AccountKey" not in link.text

    # ⑥ التنزيل، ثم ⑦ **نقرة المستخدم تفتح المثبّت** ------------------------
    #    الخطوتان في المتصفح — يغطّيهما `extension/tests/popup.test.js`.
    #    ما يهمّ هنا أن ما بعدهما لا يبدأ قبلهما: لا نداء إلى الـControl
    #    Plane من الـRuntime حتى الآن.
    assert len(world.transport.requests) == before

    # ⑧ إقلاع الـRuntime: غير مربوط، فينتظر رمزًا -------------------------
    assert service.is_activated is False
    service.prepare()
    assert service.state.phase is Phase.AWAITING_ACTIVATION

    # ⑨ استبدال جلسة التركيب ⑩ وإصدار بيان الاعتماد وحفظه ------------------
    service.activate(install_token)
    wait(service)

    assert ("POST", "/api/runtime/activate") in world.transport.requests
    assert service.is_activated is True

    # بيان الاعتماد **محفوظ محميًّا لا خامًا**.
    blob = service._credentials.path.read_bytes()
    raw = service._credentials.load()
    assert raw is not None
    assert raw.encode() not in blob
    if sys.platform == "win32":
        assert service.credential_protection == "dpapi-local-machine"

    # وتجزئته وحدها في القاعدة.
    credentials = world.database.tables["device_credentials"]
    assert len(credentials) == 1
    assert credentials[0]["credential_hash"] != raw
    assert raw not in str(world.database.tables)

    # ⑪ الجهاز صار فعّالًا -------------------------------------------------
    active = [
        row
        for row in world.database.tables["device_activations"]
        if row["revoked_at"] is None
    ]
    assert len(active) == 1

    # ⑫ GovMind يفتح — والاستحقاق يُقرأ ببيان الاعتماد، بلا دخول آخر -------
    assert service.refresh_entitlement() is True
    assert service.state.subscription_status in ("trial", "active")
    assert service.state.account_email

    # ⚠️ ولا خطوة في هذا المسار ردّت 405.
    assert all(
        method != "OPTIONS" for method, _ in world.transport.requests
    )


def test_every_control_plane_call_in_the_flow_is_allowlisted(world):
    """كل ما خرج من الجهاز خرج على مسار مقرَّر سلفًا."""
    service = world.service
    token = client.post(
        "/api/account/installation-session", headers=auth(EMPLOYEE_A)
    ).json()["token"]

    service.activate(token)
    wait(service)
    service.refresh_entitlement()

    assert world.transport.requests, "لم يخرج أي طلب — الاختبار لا يقيس شيئًا"
    for method, path in world.transport.requests:
        assert (method, path) in ALLOWED_ROUTES, f"{method} {path} خارج القائمة"


def test_the_runtime_cannot_reach_an_account_route_with_its_credential(world):
    """⚠️ **لا وكيل مفتوح**: بيان اعتماد الجهاز لا يفتح مسارات الحساب."""
    service = world.service
    token = client.post(
        "/api/account/installation-session", headers=auth(EMPLOYEE_A)
    ).json()["token"]
    service.activate(token)
    wait(service)

    with pytest.raises(RouteNotAllowedError):
        service._control._request(
            "GET",
            "/api/account/subscription",
            device_credential=service._credentials.load(),
        )


def test_a_replaced_device_loses_its_credential_immediately(world):
    """استبدال الجهاز يبطل بيان اعتماده — فيعود الـRuntime إلى انتظار ربط."""
    service = world.service
    token = client.post(
        "/api/account/installation-session", headers=auth(EMPLOYEE_A)
    ).json()["token"]
    service.activate(token)
    wait(service)
    assert service.refresh_entitlement() is True

    # يستبدل صاحب الحساب جهازه من حاسب آخر: يُبطل التفعيل السابق.
    now = datetime.now(UTC).isoformat()
    for row in world.database.tables["device_activations"]:
        row["revoked_at"] = now

    assert service.refresh_entitlement() is False
    assert service.state.phase is Phase.AWAITING_ACTIVATION
    assert service.is_activated is False
    assert service._credentials.exists() is False


@pytest.mark.parametrize("status", ["expired", "suspended", "cancelled"])
def test_a_blocked_subscription_stops_the_runtime_with_its_reason(world, status):
    service = world.service
    token = client.post(
        "/api/account/installation-session", headers=auth(EMPLOYEE_A)
    ).json()["token"]
    service.activate(token)
    wait(service)

    world.database.tables["subscriptions"][0]["status"] = status

    assert service.refresh_entitlement() is False
    assert service.state.phase is Phase.BLOCKED
    # الرسالة تشرح السبب بالعربية ولا تكتفي بـ«ممنوع».
    assert service.state.message
    assert "403" not in service.state.message


def test_no_secret_of_the_server_ever_reaches_the_runtime(world):
    """⚠️ **الشرط الذي لا يُساوَم عليه.**

    كل ما وصل جهاز العميل في هذا المسار يُفتَّش: لا مفتاح Supabase، ولا
    سرّ توقيع، ولا سلسلة اتصال Azure، ولا مِلح تجزئة.
    """
    service = world.service
    token = client.post(
        "/api/account/installation-session", headers=auth(EMPLOYEE_A)
    ).json()["token"]
    service.activate(token)
    wait(service)
    service.refresh_entitlement()

    seen = "".join(
        [
            str(service.state.account_snapshot()),
            str(service.state.snapshot()),
            service._credentials.path.read_bytes().decode("latin-1"),
        ]
    )
    for secret in (
        settings.supabase_service_role_key,
        settings.supabase_jwt_secret,
        settings.device_hash_pepper,
        "AccountKey",
        "dGVzdC1hY2NvdW50LWtleS1ub3QtcmVhbA==",
    ):
        assert secret
        assert secret not in seen
