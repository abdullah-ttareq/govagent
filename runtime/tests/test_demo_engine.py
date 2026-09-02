"""وضع العرض الأكاديمي: محرّك Ollama محلي بدل تنزيل مودل من Azure.

**ما تحرسه هذه الاختبارات:**

* المسار الإنتاجي **لا يتغيّر** حين لا يُضبط وضع العرض.
* في وضع العرض: **لا تنزيل من Azure، ولا تشغيل لـ`llama-server.exe`**،
  ولا حاجة إلى أي `AZURE_MODEL_*`.
* كل حركة المحادثة على الاسترجاع المحلي، وعنوانٌ غير محلي يُرفض.
* **لا ردّ مصطنع بحال**: تعذّر المحرّك يخرج خطأً لا نصًّا ملفَّقًا.
* لكل فشل رسالته العربية المميّزة، لأن إجراء المستخدم يختلف بينها.
* لا نصّ مستخدم ولا ردّ في السجلّ.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from govmind_runtime.config import (
    DEMO_ENGINE_TYPES,
    LOOPBACK_HOSTS,
    RuntimeConfig,
    normalize_demo_url,
)
from govmind_runtime.demo_engine import (
    DemoEngineRejectedError,
    DemoEngineTimeoutError,
    DemoEngineUnavailableError,
    DemoModelLoadingError,
    DemoModelMissingError,
    OllamaEngine,
)
from govmind_runtime.service import RuntimeService
from govmind_runtime.state import Phase
from tests.test_service import (
    FAKE_CREDENTIAL,
    FakeControlPlane,
    FakeModelStore,
    FakeSupervisor,
)

MODEL = "qwen2.5:1.5b"


# ===========================================================================
# خادم Ollama حقيقي بروتوكولًا — **بديل للخادم لا للرد**
# ===========================================================================
class FakeOllama(BaseHTTPRequestHandler):
    """ينطق بروتوكول Ollama فعليًا على منفذ حقيقي.

    ⚠️ هذا **بديل للطرف الآخر** لا «رد مصطنع في المنتج»: المنتج لا يملك
    مسارًا يخترع نصًّا؛ ما يعيده يأتي دائمًا من محرّك على الشبكة المحلية.
    الاختبار يملك ذلك المحرّك ليقرّر ماذا يردّ ومتى يفشل.
    """

    installed: list[str] = [MODEL]
    loaded: list[str] = [MODEL]
    reply: str = "الرياض هي عاصمة المملكة العربية السعودية."
    status: int = 200
    body_error: str | None = None
    requests: list[dict] = []

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/api/tags":
            self._json({"models": [{"name": name} for name in self.installed]})
        elif self.path == "/api/ps":
            self._json({"models": [{"name": name} for name in self.loaded]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        FakeOllama.requests.append(payload)

        if self.status != 200:
            self._json({"error": "engine failure"}, self.status)
            return
        if self.body_error:
            self._json({"error": self.body_error})
            return
        self._json(
            {
                "model": payload.get("model"),
                "message": {"role": "assistant", "content": self.reply},
                "done": True,
            }
        )

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def ollama():
    """يشغّل خادمًا يتكلّم بروتوكول Ollama على منفذ محلي حقيقي."""
    FakeOllama.installed = [MODEL]
    FakeOllama.loaded = [MODEL]
    FakeOllama.reply = "الرياض هي عاصمة المملكة العربية السعودية."
    FakeOllama.status = 200
    FakeOllama.body_error = None
    FakeOllama.requests = []

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", FakeOllama
    server.shutdown()


@pytest.fixture
def demo_config(tmp_path, ollama):
    url, _ = ollama
    return RuntimeConfig(
        control_plane_url="https://control.govmind.test",
        data_dir=tmp_path / "data",
        install_root=tmp_path / "install",
        port=8765,
        demo_engine_url=url,
        demo_engine_type="ollama",
        demo_model=MODEL,
    )


def make_service(config, protector, **kwargs):
    from govmind_runtime.identity import DeviceCredentialStore, DeviceIdentity

    service = RuntimeService(
        config,
        identity=DeviceIdentity(config.data_dir, protector),
        credentials=DeviceCredentialStore(config.data_dir, protector),
        control_plane=FakeControlPlane(),
        model_store=FakeModelStore(),
        supervisor=FakeSupervisor(),
        **kwargs,
    )
    service._identity.ensure()
    service._credentials.store(FAKE_CREDENTIAL)
    return service


# ===========================================================================
# ١) الإعداد
# ===========================================================================
def test_production_config_is_not_demo(config):
    """غياب الإعداد يبقي المسار الإنتاجي كما هو — بلا شرط إضافي."""
    assert config.is_demo is False


def test_all_three_settings_are_required(tmp_path):
    base = dict(
        control_plane_url="https://c.test",
        data_dir=tmp_path,
        install_root=tmp_path,
        port=8765,
    )
    assert RuntimeConfig(**base, demo_engine_url="http://127.0.0.1:11434",
                         demo_engine_type="ollama", demo_model=MODEL).is_demo
    # نقصُ أيٍّ منها ⇒ لا وضع عرض.
    assert not RuntimeConfig(**base, demo_engine_type="ollama",
                             demo_model=MODEL).is_demo
    assert not RuntimeConfig(**base, demo_engine_url="http://127.0.0.1:11434",
                             demo_model=MODEL).is_demo
    assert not RuntimeConfig(**base, demo_engine_url="http://127.0.0.1:11434",
                             demo_engine_type="ollama").is_demo


def test_an_unknown_engine_type_is_ignored(tmp_path):
    """نوع لا نعرفه لا يُحاوَل التحدّث إليه."""
    assert not RuntimeConfig(
        control_plane_url="https://c.test", data_dir=tmp_path,
        install_root=tmp_path, port=8765,
        demo_engine_url="http://127.0.0.1:11434",
        demo_engine_type="something-else", demo_model=MODEL,
    ).is_demo
    assert DEMO_ENGINE_TYPES == frozenset({"ollama"})


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:11434", "http://localhost:11434", "http://127.0.0.1:11434/"],
)
def test_loopback_urls_are_accepted(url):
    assert normalize_demo_url(url).startswith("http")


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5:11434",
        "https://api.example.com",
        "http://ollama.internal:11434",
        "ftp://127.0.0.1:11434",
        "not-a-url",
        "",
    ],
)
def test_non_loopback_urls_are_refused(url):
    """⚠️ **نصّ العميل لا يغادر الجهاز.** عنوانٌ غير محلي يُبطل الوضع كله."""
    assert normalize_demo_url(url) == ""


def test_loopback_list_is_explicit():
    assert "127.0.0.1" in LOOPBACK_HOSTS
    assert "0.0.0.0" not in LOOPBACK_HOSTS


# ===========================================================================
# ٢) التجهيز — بلا Azure وبلا llama-server
# ===========================================================================
def test_demo_becomes_ready_without_downloading_anything(demo_config, protector):
    service = make_service(demo_config, protector)
    service.prepare()

    assert service.state.phase is Phase.READY
    assert service.is_demo is True
    # ⚠️ الشرطان اللذان يميّزان الوضع.
    assert service._models.downloads == 0, "نُزّل مودل في وضع العرض"
    assert service._supervisor.started == 0, "شُغّل llama-server في وضع العرض"


def test_demo_never_asks_the_control_plane_for_a_model(demo_config, protector):
    """`/api/runtime/model` لا يُنادى، فلا حاجة إلى `AZURE_MODEL_*`."""
    service = make_service(demo_config, protector)
    service._control.artifact_error = AssertionError("لا يجوز طلب مودل Azure")
    service.prepare()

    assert service.state.phase is Phase.READY


def test_explicit_download_request_is_ignored_in_demo(demo_config, protector):
    service = make_service(demo_config, protector)
    service.download_model()

    assert service._models.downloads == 0
    assert service.state.phase is Phase.READY


def test_explicit_start_model_never_launches_the_bundled_engine(demo_config, protector):
    """⚠️ حتى النداء اليدوي من الواجهة لا يشغّل الملف المرفق."""
    service = make_service(demo_config, protector)
    service.start_model()

    assert service._supervisor.started == 0
    assert service.state.phase is Phase.READY


def test_missing_model_stops_at_a_clear_arabic_error(demo_config, protector, ollama):
    _, engine = ollama
    engine.installed = ["llama3:8b"]

    service = make_service(demo_config, protector)
    service.prepare()

    assert service.state.phase is Phase.ERROR
    assert MODEL in service.state.message
    assert "غير مثبَّت" in service.state.message
    assert service._supervisor.started == 0


def test_engine_name_is_reported(demo_config, protector, config):
    service = make_service(demo_config, protector)
    assert service.engine_name == f"ollama:{MODEL}"

    from govmind_runtime.identity import DeviceCredentialStore, DeviceIdentity

    production = RuntimeService(
        config,
        identity=DeviceIdentity(config.data_dir, protector),
        credentials=DeviceCredentialStore(config.data_dir, protector),
        control_plane=FakeControlPlane(),
        model_store=FakeModelStore(),
        supervisor=FakeSupervisor(),
    )
    assert production.is_demo is False
    assert production.engine_name == "llama.cpp"


# ===========================================================================
# ٣) المحادثة
# ===========================================================================
def test_a_real_reply_comes_back_from_the_engine(demo_config, protector, ollama):
    _, engine = ollama
    service = make_service(demo_config, protector)
    service.prepare()

    result = service.chat("ما عاصمة السعودية؟")

    assert result.reply == engine.reply
    assert result.cloud is False, "وضع العرض محلي: لا يجوز أن يُعلَن سحابيًّا"
    payload = engine.requests[-1]
    assert payload["model"] == MODEL
    assert payload["stream"] is False, "البثّ يجب أن يكون معطّلًا"
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]
    assert payload["messages"][1]["content"] == "ما عاصمة السعودية؟"


def test_the_system_prompt_mentions_no_organisation(demo_config, protector, ollama):
    _, engine = ollama
    service = make_service(demo_config, protector)
    service.prepare()
    service.chat("سؤال")

    system = engine.requests[-1]["messages"][0]["content"]
    for word in ("مسؤول", "جهتك", "بريد العمل", "مسؤول النظام"):
        assert word not in system


def test_chat_requires_a_linked_device(demo_config, protector):
    from govmind_runtime.identity import DeviceCredentialStore, DeviceIdentity
    from govmind_runtime.service import ChatUnavailableError

    service = RuntimeService(
        demo_config,
        identity=DeviceIdentity(demo_config.data_dir, protector),
        credentials=DeviceCredentialStore(demo_config.data_dir, protector),
        control_plane=FakeControlPlane(),
        model_store=FakeModelStore(),
        supervisor=FakeSupervisor(),
    )
    with pytest.raises(ChatUnavailableError) as caught:
        service.chat("مرحبا")
    assert "إضافة المتصفح" in str(caught.value)


def test_a_blocked_subscription_still_blocks_in_demo(demo_config, protector):
    """⚠️ العرض يخصّ المحرّك، **لا من يملك حقّ الاستعمال**."""
    from govmind_runtime.service import ChatUnavailableError

    service = make_service(demo_config, protector)
    service.state.set(Phase.BLOCKED, "انتهى اشتراكك بتاريخ ٢٠٢٦-٠١-٠١.")

    with pytest.raises(ChatUnavailableError) as caught:
        service.chat("مرحبا")
    assert "انتهى اشتراكك" in str(caught.value)


def test_an_empty_reply_is_an_error_not_an_invented_answer(demo_config, protector, ollama):
    """⚠️ **لا ردّ مصطنع.** الفراغ فشلٌ يُقال لا فرصةٌ للتلفيق."""
    from govmind_runtime.service import ChatUnavailableError

    _, engine = ollama
    engine.reply = "   "
    service = make_service(demo_config, protector)
    service.prepare()

    with pytest.raises(ChatUnavailableError):
        service.chat("سؤال")


# ===========================================================================
# ٤) الأخطاء — لكل حالة رسالتها وإجراؤها
# ===========================================================================
def test_engine_not_running(tmp_path, protector):
    """منفذ مغلق: «شغّله ثم أعد التحقق»."""
    from govmind_runtime.service import ChatUnavailableError

    config = RuntimeConfig(
        control_plane_url="https://c.test", data_dir=tmp_path / "d",
        install_root=tmp_path / "i", port=8765,
        demo_engine_url="http://127.0.0.1:1",  # لا شيء يستمع هنا
        demo_engine_type="ollama", demo_model=MODEL,
    )
    service = make_service(config, protector)
    service.prepare()

    assert service.state.phase is Phase.ERROR
    assert "لا يعمل" in service.state.message
    with pytest.raises(ChatUnavailableError) as caught:
        service.chat("مرحبا")
    assert "لا يعمل" in str(caught.value)


def test_model_not_installed(ollama):
    url, engine = ollama
    engine.installed = []
    client = OllamaEngine(url, MODEL)

    with pytest.raises(DemoModelMissingError) as caught:
        client.probe()
    assert MODEL in str(caught.value)
    client.close()


def test_model_still_loading_is_distinct_from_a_timeout(ollama):
    """⚠️ التفريق يقرّر ما يفعله المستخدم: ينتظر، أو يعيد بسؤال أقصر."""
    url, engine = ollama

    def slow(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            # المودل **ليس** محمَّلًا بعد.
            return httpx.Response(200, json={"models": []})
        raise httpx.ReadTimeout("too slow", request=request)

    client = OllamaEngine(url, MODEL,
                          client=httpx.Client(transport=httpx.MockTransport(slow)))
    with pytest.raises(DemoModelLoadingError) as caught:
        client.chat("s", "u")
    assert "يُحمَّل" in str(caught.value)
    client.close()

    def slow_but_loaded(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": MODEL}]})
        raise httpx.ReadTimeout("too slow", request=request)

    client = OllamaEngine(
        url, MODEL, client=httpx.Client(transport=httpx.MockTransport(slow_but_loaded))
    )
    with pytest.raises(DemoEngineTimeoutError) as caught:
        client.chat("s", "u")
    assert "أطول من المتوقّع" in str(caught.value)
    client.close()


def test_engine_returns_an_error_status(ollama):
    url, engine = ollama
    engine.status = 500
    client = OllamaEngine(url, MODEL)

    with pytest.raises(DemoEngineRejectedError):
        client.chat("s", "u")
    client.close()


def test_a_503_is_read_as_loading(ollama):
    url, engine = ollama
    engine.status = 503
    client = OllamaEngine(url, MODEL)

    with pytest.raises(DemoModelLoadingError):
        client.chat("s", "u")
    client.close()


def test_an_error_in_the_body_is_a_failure_not_a_reply(ollama):
    url, engine = ollama
    engine.body_error = "model requires more system memory"
    client = OllamaEngine(url, MODEL)

    with pytest.raises(DemoEngineRejectedError) as caught:
        client.chat("s", "u")
    # ⚠️ النصّ الإنجليزي الخام لا يصل المستخدم.
    assert "memory" not in str(caught.value)
    client.close()


def test_every_error_message_is_arabic_and_actionable(ollama):
    url, _ = ollama
    client = OllamaEngine(url, MODEL)
    messages = [
        client._unavailable_message(),
        client._rejected_message(),
        str(client._timeout_error()),
    ]
    for text in messages:
        assert any("؀" <= ch <= "ۿ" for ch in text), text
        assert "Traceback" not in text
        assert "http://" not in text
    client.close()


# ===========================================================================
# ٥) الخصوصية والسجلّ
# ===========================================================================
def test_nothing_of_the_conversation_reaches_the_log(demo_config, protector,
                                                     ollama, caplog):
    """⚠️ **لا نصّ مستخدم ولا ردّ في السجلّ.** أحداثٌ وأرقام فقط."""
    _, engine = ollama
    engine.reply = "سرٌّ لا يجوز أن يظهر في سجلّ"
    secret_question = "سؤالٌ خاصّ جدًّا لا يجوز تسجيله"

    service = make_service(demo_config, protector)
    service.prepare()
    with caplog.at_level(logging.DEBUG):
        service.chat(secret_question)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_question not in logged
    assert engine.reply not in logged


def test_all_engine_traffic_stays_on_loopback(demo_config, protector, ollama):
    """كل نداء يخرج من الـRuntime إلى المحرّك يذهب إلى 127.0.0.1 وحده."""
    seen: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": MODEL}]})
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "ردّ"}}
        )

    engine = OllamaEngine(
        demo_config.demo_engine_url, MODEL,
        client=httpx.Client(transport=httpx.MockTransport(record)),
    )
    service = make_service(demo_config, protector, demo_engine=engine)
    service.prepare()
    service.chat("سؤال")

    assert seen, "لم يخرج أي نداء"
    for url in seen:
        assert url.startswith("http://127.0.0.1:"), url
    engine.close()


def test_shutdown_closes_the_engine_client(demo_config, protector):
    service = make_service(demo_config, protector)
    session = service._demo._session()
    service.shutdown()
    assert session.is_closed is True
