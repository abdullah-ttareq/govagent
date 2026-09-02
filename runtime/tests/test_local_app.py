"""التطبيق المثبَّت: **بلا دخول ثانٍ، وبلا 405**.

هذا الملف يحرس العطل الحيّ الثاني بنصّه.

**ما رآه العميل.** بعد أن اكتمل التثبيت وفتح GovMind، ظهر له **نموذج دخول
ثانٍ** — وهو قد سجّل دخوله في الإضافة قبل دقائق — وإرسالُه ردّ بـ
``Method Not Allowed``.

**السبب.** بناء سطح المكتب يجعل الواجهة تنادي الأصل نفسه، فتذهب
``POST /api/auth/login`` إلى الـRuntime. ولا مسار بهذا الاسم فيه، فيلتقط
الطلبَ `StaticFiles` المركَّب على ``/`` — وهو لا يعرف إلا ``GET``/``HEAD``
— فيردّ **405** بجسم إنجليزي.

**الإصلاح المُختبَر هنا:**

1. حالة الربط تُقرأ من ``/api/app/session``، فلا نموذج دخول أصلًا.
2. أي مسار تحت ``/api/`` غير معروف ⇒ **404 عربية**.
3. أي فعل غير ``GET``/``HEAD`` على أي مسار ⇒ **404 عربية** كذلك.
4. **لا 405 من أي مسار، بأي فعل، في أي حال.**
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from govmind_runtime.api import SESSION_HEADER, LocalApi
from govmind_runtime.identity import DeviceCredentialStore, DeviceIdentity
from govmind_runtime.service import RuntimeService
from govmind_runtime.state import Phase
from tests.test_service import (
    FAKE_CREDENTIAL,
    FakeControlPlane,
    FakeModelStore,
    FakeSupervisor,
)


@pytest.fixture
def ui(config):
    """يزرع تصدير واجهة ساكنًا كالذي ينشره المثبّت.

    ⚠️ **يزرع `/login/` عمدًا**، وهو ما لا يبنيه تصدير سطح المكتب اليوم.
    الغرض أن تُثبَت الحماية عند أسوأ الحالات: حتى لو عاد الملف يومًا إلى
    الحزمة، لا يجوز أن يردّ إرسالُ نموذج فيه بـ405.
    """
    root = config.install_root / "ui"
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text("<html>GovMind</html>", encoding="utf-8")
    login = root / "login"
    login.mkdir(exist_ok=True)
    (login / "index.html").write_text("<html>legacy</html>", encoding="utf-8")
    return root


@pytest.fixture
def api(config, protector, ui):
    service = RuntimeService(
        config,
        identity=DeviceIdentity(config.data_dir, protector),
        credentials=DeviceCredentialStore(config.data_dir, protector),
        control_plane=FakeControlPlane(),
        model_store=FakeModelStore(),
        supervisor=FakeSupervisor(),
    )
    return LocalApi(service, config)


@pytest.fixture
def client(api):
    return TestClient(api.app)


def auth(api) -> dict[str, str]:
    return {SESSION_HEADER: api.session_token}


def link(api) -> None:
    """يجعل الجهاز مربوطًا: بيان اعتماد محفوظ."""
    api.service._identity.ensure()
    api.service._credentials.store(FAKE_CREDENTIAL)


# ===========================================================================
# ١) العطل الحيّ: 405 على المسارات التي كانت الواجهة تناديها
# ===========================================================================
#: الطلبات التي كان بناء سطح المكتب يصدرها من صفحة `/login/`.
LIVE_REQUESTS = [
    ("POST", "/api/auth/login"),
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
    ("POST", "/login/"),
]


@pytest.mark.parametrize("method,path", LIVE_REQUESTS)
def test_the_exact_live_requests_no_longer_return_405(client, method, path):
    response = client.request(method, path, json={})

    assert response.status_code == 404, (method, path)
    assert "Method Not Allowed" not in response.text
    # الرسالة عربية وتقول ما يُفعل، لا نصّ HTTP خام.
    assert "GovMind" in response.json()["detail"]


@pytest.mark.parametrize(
    "method",
    ["POST", "PUT", "PATCH", "DELETE"],
)
@pytest.mark.parametrize(
    "path",
    ["/", "/login/", "/index.html", "/settings/", "/api/anything", "/nope"],
)
def test_no_write_method_on_any_path_returns_405(client, method, path):
    """⚠️ **مسحٌ شامل.** ما دام التركيب الساكن قائمًا، أي فعل كتابة عليه
    يردّ 405 ما لم تسبقه مصيدة. هذا الاختبار يمرّ على الحالات كلها."""
    response = client.request(method, path, json={})

    assert response.status_code != 405, (method, path)
    assert "Method Not Allowed" not in response.text


@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/api/unknown"])
def test_no_read_path_returns_405_either(client, path):
    response = client.get(path)
    assert response.status_code != 405
    assert "Method Not Allowed" not in response.text


def test_the_static_ui_is_still_served(client):
    """الإصلاح لا يكسر ما كان يعمل: الصفحات تُخدَم كما كانت."""
    assert client.get("/").status_code == 200
    assert "GovMind" in client.get("/").text


# ===========================================================================
# ٢) لا دخول ثانٍ: حالة الربط تحلّ محلّ نموذج الدخول
# ===========================================================================
def test_session_route_replaces_the_login_form(client, api):
    body = client.get("/api/app/session", headers=auth(api)).json()

    assert body["service"] == "govmind-runtime"
    assert body["linked"] is False
    # ⚠️ لا حقل بريد ولا كلمة مرور يُطلبان: الحالة تُقرأ ولا تُدخَل.
    assert "password" not in body


def test_session_route_needs_the_local_session_token(client):
    assert client.get("/api/app/session").status_code == 401
    assert client.post("/api/app/recheck").status_code == 401


def test_a_linked_device_reports_linked_true(client, api):
    link(api)
    body = client.get("/api/app/session", headers=auth(api)).json()

    assert body["linked"] is True


def test_recheck_reports_the_current_state_in_the_same_request(client, api):
    """«إعادة التحقق» تردّ بالنتيجة الآن، لا بوعد بإخبار لاحق."""
    link(api)
    api.service._control.entitlement_value = api.service._control.entitlement_value

    body = client.post("/api/app/recheck", headers=auth(api)).json()
    assert body["linked"] is True
    assert body["account_email"] is not None


def test_the_account_email_reaches_the_app_but_not_health(client, api):
    """بريد العميل معلومةُ عرضٍ له، **لا معلومةً مفتوحة على الاسترجاع المحلي**."""
    link(api)
    api.service.refresh_entitlement()

    assert "account_email" not in client.get("/health").json()
    body = client.get("/api/app/session", headers=auth(api)).json()
    assert body["account_email"] == "owner@example.test"


# ===========================================================================
# ٣) بيان اعتماد الجهاز لا يصل المتصفح
# ===========================================================================
def test_no_route_ever_returns_the_device_credential(client, api):
    """⚠️ **الشرط الأهم في هذا الملف.**

    بيانٌ يصل JavaScript في المتصفح يبطل معنى حفظه بـDPAPI أصلًا: صفحةٌ
    واحدة مصابة تكفي لأخذه.
    """
    link(api)
    api.service.refresh_entitlement()

    responses = [
        client.get("/health"),
        client.get("/api/app/session", headers=auth(api)),
        client.post("/api/app/recheck", headers=auth(api)),
        client.get("/api/status", headers=auth(api)),
        client.post("/api/entitlement/refresh", headers=auth(api)),
        client.post("/activate", json={"token": "installation-token-value-0001"}),
    ]
    for response in responses:
        assert FAKE_CREDENTIAL not in response.text
        assert "credential" not in response.text.lower()


def test_the_credential_file_is_never_served_as_a_static_file(client, api):
    link(api)
    for path in ("/credential.bin", "/api/app/credential", "/device.bin"):
        assert FAKE_CREDENTIAL not in client.get(path).text


# ===========================================================================
# ٤) المحادثة المحلية
# ===========================================================================
def test_chat_needs_the_local_session_token(client):
    assert client.post("/api/app/chat", json={"message": "مرحبا"}).status_code == 401


def test_chat_before_linking_asks_for_the_extension(client, api):
    """⚠️ **لا نموذج دخول ولا 405** — تعليمة واحدة يفهمها العميل."""
    response = client.post(
        "/api/app/chat", json={"message": "مرحبا"}, headers=auth(api)
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "أكمل تثبيت وربط GovMind من إضافة المتصفح."


def test_chat_while_preparing_says_so_instead_of_failing_blankly(client, api):
    link(api)
    api.service.state.set(Phase.DOWNLOADING_MODEL)

    response = client.post(
        "/api/app/chat", json={"message": "مرحبا"}, headers=auth(api)
    )
    assert response.status_code == 409
    assert "المودل" in response.json()["detail"]


def test_chat_on_a_blocked_subscription_reports_the_reason(client, api):
    link(api)
    api.service.state.set(Phase.BLOCKED, "انتهى اشتراكك بتاريخ ٢٠٢٦-٠١-٠١.")

    response = client.post(
        "/api/app/chat", json={"message": "مرحبا"}, headers=auth(api)
    )
    assert response.status_code == 409
    assert "انتهى اشتراكك" in response.json()["detail"]


def test_chat_error_never_names_a_port_or_a_path(client, api):
    link(api)
    api.service.state.set(Phase.MODEL_MISSING)

    response = client.post(
        "/api/app/chat", json={"message": "مرحبا"}, headers=auth(api)
    )
    assert "127.0.0.1" not in response.text
    assert str(api.config.data_dir) not in response.text


# ===========================================================================
# ٥) لا لفظ من المنتج القديم في أي رد
# ===========================================================================
FORBIDDEN_WORDS = ("مسؤول النظام", "مسؤول الجهة", "جهتك", "بريد العمل")


def test_no_response_mentions_an_organization_or_an_administrator(client, api):
    link(api)
    api.service.refresh_entitlement()

    responses = [
        client.get("/health"),
        client.get("/api/app/session", headers=auth(api)),
        client.post("/api/app/chat", json={"message": "س"}, headers=auth(api)),
        client.post("/api/auth/login", json={}),
        client.get("/api/unknown"),
    ]
    for response in responses:
        for word in FORBIDDEN_WORDS:
            assert word not in response.text


def test_the_runtime_source_carries_no_organization_wording():
    """⚠️ يشمل السجلّات ورسائل الاستثناءات، لا الردود وحدها."""
    import inspect

    from govmind_runtime import (
        api,
        control_plane,
        identity,
        llama_supervisor,
        model_store,
        opener,
        service,
        state,
    )

    for module in (
        api,
        control_plane,
        identity,
        llama_supervisor,
        model_store,
        opener,
        service,
        state,
    ):
        source = inspect.getsource(module)
        for word in FORBIDDEN_WORDS:
            assert word not in source, f"{module.__name__} يذكر «{word}»"
