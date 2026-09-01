"""الواجهة المحلية: المصادقة، والاسترجاع المحلي، وعدم كشف أي سرّ.

**ما تحرسه هذه الاختبارات:**

* لا مسار تحكّم بلا رمز جلسة محلي — فلا يستهلك موقعُ ويب مفتوح في المتصفح
  نفسه مودلَ العميل.
* `/health` وحده مفتوح، ولا يكشف منفذًا ولا مسارًا ولا سرًّا.
* الخادم يُربط بـ`127.0.0.1` وحده.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from govmind_runtime.api import SESSION_HEADER, LocalApi
from govmind_runtime.control_plane import ActivationRejectedError
from govmind_runtime.identity import DeviceIdentity
from govmind_runtime.service import RuntimeService
from govmind_runtime.state import Phase
from tests.test_service import FakeControlPlane, FakeModelStore, FakeSupervisor


@pytest.fixture
def api(config, protector):
    service = RuntimeService(
        config,
        identity=DeviceIdentity(config.data_dir, protector),
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


# ===========================================================================
# الصحة — المسار المفتوح الوحيد
# ===========================================================================
def test_health_needs_no_session_token(client):
    """تستطلعه الإضافة قبل أن تملك أي رمز."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "govmind-runtime"


def test_health_reports_the_phase_in_arabic(client):
    body = client.get("/health").json()
    assert body["phase"] == Phase.AWAITING_ACTIVATION.value
    assert body["needs_activation"] is True
    assert "بانتظار تفعيل" in body["message"]


def test_health_leaks_no_internal_detail(client, api):
    """⚠️ لا منفذ محرّك، ولا مسار على القرص، ولا رمز جلسة."""
    text = client.get("/health").text
    assert api.session_token not in text
    assert str(api.config.data_dir) not in text
    assert "llama" not in text.lower()


# ===========================================================================
# المصادقة المحلية
# ===========================================================================
CONTROL_PATHS = [
    ("get", "/api/status"),
    ("post", "/api/model/download"),
    ("post", "/api/model/cancel"),
    ("post", "/api/model/start"),
    ("post", "/api/model/stop"),
    ("post", "/api/model/restart"),
    ("post", "/api/entitlement/refresh"),
]


@pytest.mark.parametrize("method,path", CONTROL_PATHS)
def test_control_paths_require_the_session_token(client, method, path):
    """بلا رمز محلي لا تحكّم — وإلا استهلك أي موقع مفتوح مودلَ العميل."""
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize("method,path", CONTROL_PATHS)
def test_control_paths_accept_the_session_token(client, api, method, path):
    assert getattr(client, method)(path, headers=auth(api)).status_code == 200


def test_wrong_session_token_is_refused(client):
    assert (
        client.get("/api/status", headers={SESSION_HEADER: "wrong"}).status_code == 401
    )


def test_session_token_is_written_for_the_local_ui(api):
    assert api.config.session_file.read_text(encoding="utf-8") == api.session_token


def test_session_endpoint_refuses_a_foreign_origin(client):
    """صفحة على نطاق خارجي لا تحصل على الرمز."""
    response = client.get(
        "/api/local/session", headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


def test_session_endpoint_serves_the_local_ui(client, api):
    response = client.get("/api/local/session")
    assert response.status_code == 200
    assert response.json()["token"] == api.session_token


# ===========================================================================
# التفعيل
# ===========================================================================
def test_activate_needs_no_session_token(client):
    """الإضافة لا تملك الرمز المحلي؛ رمز التركيب نفسه هو الإثبات."""
    response = client.post(
        "/activate", json={"token": "installation-token-value-32-chars"}
    )
    assert response.status_code == 200
    assert response.json()["phase"] != Phase.AWAITING_ACTIVATION.value


def test_activate_rejects_a_short_token(client):
    assert client.post("/activate", json={"token": "short"}).status_code == 422


def test_activate_surfaces_a_rejection_as_conflict(client, api):
    api.service._control.activate_error = ActivationRejectedError(
        "هذا الاشتراك مفعّل على جهاز آخر."
    )
    response = client.post(
        "/activate", json={"token": "installation-token-value-32-chars"}
    )
    assert response.status_code == 409
    assert "جهاز آخر" in response.json()["detail"]


def test_activation_token_never_appears_in_a_response(client, api):
    token = "installation-token-value-32-chars"
    response = client.post("/activate", json={"token": token})
    assert token not in response.text

    api.service._control.activate_error = ActivationRejectedError("مرفوض")
    assert token not in client.post("/activate", json={"token": token}).text


# ===========================================================================
# لا واجهة عامة ولا توثيق على جهاز عميل
# ===========================================================================
def test_no_openapi_or_docs_are_exposed(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_no_general_openai_compatible_endpoint(client):
    """⚠️ لا مسار محادثة عام: المحرّك خلف الـRuntime لا أمامه."""
    for path in ("/v1/chat/completions", "/v1/models", "/completion"):
        assert client.post(path, json={}).status_code in (404, 405)


# ===========================================================================
# الاسترجاع المحلي وحده
# ===========================================================================
def _string_literals(module) -> list[str]:
    """نصوص الشيفرة الفعلية، بلا تعليقات ولا سلاسل توثيق.

    الفحص على الشجرة لا على النصّ الخام: التعليق الذي يقول «لا يجوز
    `0.0.0.0`» ليس ربطًا بـ`0.0.0.0`، ومطابقة النصّ الخام تعدّه كذلك.
    """
    import ast

    tree = ast.parse(inspect.getsource(module))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))

    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_runtime_binds_loopback_only():
    """الخادم المحلي يُربط بالاسترجاع وحده — لا بكل الواجهات."""
    from govmind_runtime import main as main_module

    literals = _string_literals(main_module)
    assert "127.0.0.1" in literals
    assert not any("0.0.0.0" in value for value in literals)


def test_llama_server_binds_loopback_only():
    """محرّك المودل كذلك: ربطه بكل الواجهات يعرضه لشبكة الجهة بلا مصادقة."""
    from govmind_runtime import llama_supervisor

    literals = _string_literals(llama_supervisor)
    assert "127.0.0.1" in literals
    assert not any("0.0.0.0" in value for value in literals)


def test_no_cloud_secret_name_appears_in_runtime_sources():
    """⚠️ أسرار الخادم لا تُذكر في أي ملف يُثبَّت على جهاز عميل."""
    package = Path(__file__).resolve().parents[1] / "govmind_runtime"
    forbidden = (
        "SUPABASE_SERVICE_ROLE_KEY",
        "AZURE_STORAGE_CONNECTION_STRING",
        "DEVICE_HASH_PEPPER",
        "SUPABASE_JWT_SECRET",
    )

    for path in package.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            # `config.py` يذكرها في قائمة **المحظورات** ليمنعها — وهو
            # الموضع الوحيد المسموح.
            if name in text and path.name != "config.py":
                raise AssertionError(f"{name} مذكور في {path.name}")
