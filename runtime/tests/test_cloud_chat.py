"""المسار السحابي: من الواجهة المثبَّتة إلى السيرفر، وبيان الاعتماد بينهما.

**الشكل.** الواجهة في المتصفح ⇒ الـRuntime على الاسترجاع المحلي ⇒ السيرفر
المصادَق ⇒ مزوّد الاستدلال. أربع محطات، والسرّ لا يمرّ إلا بين الأخيرتين.

**لماذا هذا الشكل ولا شكل أقصر؟** لأن كل اختصار يضع سرًّا في مكان يقرؤه من
لا يحقّ له:

* لو نادت **الواجهة** المزوّد مباشرة، لصار مفتاح المزوّد في شيفرة يقرؤها
  أي أحد بأدوات المطوّر.
* لو نادت **الواجهة** السيرفر مباشرة، لاحتاجت بيان اعتماد الجهاز في
  المتصفح — وهو سرّ الجهاز كلّه، ومعه ينتحل أيّ سكربت صفةَ الجهاز.
* لو حمل **الـRuntime** مفتاح المزوّد، لكان المفتاح على كل جهاز عميل. ومن
  يملك الجهاز يقرأ كل بايت في برنامجه، بما فيه ما يفكّه البرنامج ليستعمله.

فبقي: الواجهة بلا أي سرّ، والـRuntime ببيان اعتماد جهازه وحده، والسيرفر
بمفتاح المزوّد.

**ما يثبته هذا الملف:**

* بيان الاعتماد يُلصق في جانب الخادم، **ولا يصل المتصفح في أي رد**.
* الواجهة لا تنادي إلا الاسترجاع المحلي — لا عنوان سيرفر في حزمتها.
* السياق يمرّ كاملًا ومقلَّمًا عند السقف.
* أخطاء السيرفر تصل عربيةً مصنَّفة، **بمهلة منتهية لا شاشة انتظار أبدية**.
* لا مودل يُنزَّل ولا `llama-server` يُشغَّل في هذا الوضع.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from govmind_runtime.api import SESSION_HEADER, LocalApi
from govmind_runtime.config import CHAT_MODES, RuntimeConfig
from govmind_runtime.control_plane import (
    ControlPlaneError,
    DeviceNotActivatedError,
    ModelUnavailableError,
    OfflineError,
    SubscriptionBlockedError,
)
from govmind_runtime.identity import DeviceCredentialStore, DeviceIdentity
from govmind_runtime.service import MAX_HISTORY, RuntimeService
from govmind_runtime.state import Phase
from tests.test_service import (
    FAKE_CREDENTIAL,
    FakeControlPlane,
    FakeModelStore,
    FakeSupervisor,
)


@pytest.fixture
def cloud_config(config: RuntimeConfig) -> RuntimeConfig:
    return dataclasses.replace(config, chat_mode="cloud")


@pytest.fixture
def control() -> FakeControlPlane:
    return FakeControlPlane()


@pytest.fixture
def service(cloud_config, protector, control) -> RuntimeService:
    return RuntimeService(
        cloud_config,
        identity=DeviceIdentity(cloud_config.data_dir, protector),
        credentials=DeviceCredentialStore(cloud_config.data_dir, protector),
        control_plane=control,
        model_store=FakeModelStore(),
        supervisor=FakeSupervisor(),
    )


@pytest.fixture
def linked(service) -> RuntimeService:
    """جهاز مربوط: بيان اعتماد محفوظ بالحماية نفسها التي يستعملها المنتج."""
    service._identity.ensure()
    service._credentials.store(FAKE_CREDENTIAL)
    return service


@pytest.fixture
def api(linked, cloud_config):
    return LocalApi(linked, cloud_config)


@pytest.fixture
def client(api):
    root = api.config.install_root / "ui"
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text("<html>GovMind</html>", encoding="utf-8")
    return TestClient(api.app)


def auth(api) -> dict[str, str]:
    return {SESSION_HEADER: api.session_token}


# ===========================================================================
# ١) الإعداد
# ===========================================================================
def test_local_is_the_default_when_nothing_is_configured(config):
    """⚠️ **الافتراض الأحفظ**: لا يخرج نصّ إلا بقرار مكتوب."""
    assert config.chat_mode == ""
    assert config.is_cloud_chat is False


def test_an_unknown_mode_falls_back_to_local(config):
    """قيمة مكتوبة خطأً على جهاز عميل لا تُفسَّر تفسيرًا موسّعًا."""
    assert dataclasses.replace(config, chat_mode="نعم").is_cloud_chat is False
    assert dataclasses.replace(config, chat_mode="CLOUD").is_cloud_chat is False


def test_the_mode_list_is_closed():
    assert CHAT_MODES == frozenset({"local", "cloud"})


def test_a_local_demo_engine_wins_over_cloud(config):
    """⚠️ عند التعارض، **الوضع الذي يُبقي النصّ على الجهاز أولى**."""
    both = dataclasses.replace(
        config,
        chat_mode="cloud",
        demo_engine_url="http://127.0.0.1:11434",
        demo_engine_type="ollama",
        demo_model="qwen2.5:1.5b",
    )
    assert both.is_demo is True
    assert both.is_cloud_chat is False


# ===========================================================================
# ٢) بيان الاعتماد: يُلصق هنا، ولا يصل المتصفح
# ===========================================================================
def test_the_runtime_attaches_the_credential_server_side(linked, control):
    """الطلب من المتصفح بلا سرّ، والطلب إلى السيرفر ببيان الاعتماد."""
    linked.chat("ما عاصمة السعودية؟")

    assert control.seen_credentials[-1] == FAKE_CREDENTIAL


def test_no_response_to_the_browser_carries_the_credential(client, api, control):
    """⚠️ **الحدّ الذي يحمي الجهاز كلّه.**

    بيانُ اعتماد يصل المتصفح يصير في متناول كل سكربت في الصفحة وكل من يفتح
    أدوات المطوّر — ومعه ينتحل أيٌّ منهم صفةَ هذا الجهاز على السيرفر.
    """
    responses = [
        client.get("/api/app/session", headers=auth(api)),
        client.post("/api/app/recheck", headers=auth(api)),
        client.post(
            "/api/app/chat",
            json={"message": "ما عاصمة السعودية؟", "history": []},
            headers=auth(api),
        ),
        client.get("/api/status", headers=auth(api)),
        client.get("/health"),
    ]

    for response in responses:
        assert FAKE_CREDENTIAL not in response.text, response.url


def test_the_browser_request_needs_no_secret_of_its_own(client, api, control):
    """الواجهة ترسل رسالة وسياقًا فقط — لا حقل سرّ في الجسم أصلًا."""
    from govmind_runtime.api import ChatRequest

    assert set(ChatRequest.model_fields) == {"message", "history"}

    client.post(
        "/api/app/chat",
        json={"message": "مرحبا", "history": []},
        headers=auth(api),
    )
    assert control.seen_credentials[-1] == FAKE_CREDENTIAL


def test_a_chat_before_linking_never_reaches_the_server(service, control):
    """جهاز غير مربوط لا يخرج منه طلب — ولا يستهلك حصة."""
    from govmind_runtime.service import ChatUnavailableError

    with pytest.raises(ChatUnavailableError) as exc:
        service.chat("مرحبا")

    assert "إضافة المتصفح" in str(exc.value)
    assert control.chats == []


# ===========================================================================
# ٣) السياق
# ===========================================================================
def test_the_history_reaches_the_server_in_order(client, api, control):
    client.post(
        "/api/app/chat",
        json={
            "message": "اجعله أقصر",
            "history": [
                {"role": "user", "content": "لخّص لي التقرير"},
                {"role": "assistant", "content": "هذا ملخص التقرير."},
            ],
        },
        headers=auth(api),
    )

    sent = control.chats[-1]
    assert sent["message"] == "اجعله أقصر"
    assert sent["history"] == [
        {"role": "user", "content": "لخّص لي التقرير"},
        {"role": "assistant", "content": "هذا ملخص التقرير."},
    ]


def test_a_long_history_is_trimmed_not_refused(linked, control):
    """⚠️ **يُقلَّم لا يُرفض.**

    تجاوز السقف يعود من السيرفر بخطأ تحقّق لا يفهمه المستخدم — وسببُه
    محادثةٌ طالت، وهو أمر طبيعي لا خطأ منه.
    """
    history = [{"role": "user", "content": f"س{i}"} for i in range(MAX_HISTORY + 30)]

    linked.chat("سؤال", history)

    sent = control.chats[-1]["history"]
    assert len(sent) == MAX_HISTORY
    # ⚠️ **الأحدث يبقى**: أقدمُ الرسائل أقلّها أثرًا في الرد.
    assert sent[-1]["content"] == f"س{MAX_HISTORY + 29}"


def test_the_current_message_is_not_duplicated_into_the_history(client, api, control):
    """الرسالة الحالية في `message` وحدها؛ تكرارها يجعل المودل يراها مرتين."""
    client.post(
        "/api/app/chat",
        json={"message": "سؤالي", "history": []},
        headers=auth(api),
    )

    sent = control.chats[-1]
    assert sent["history"] == []
    assert sent["message"] == "سؤالي"


@pytest.mark.parametrize("role", ["system", "tool", "developer"])
def test_only_user_and_assistant_turns_are_accepted(client, api, control, role):
    """⚠️ **لا `system` من المتصفح.**

    تعليمة النظام يبنيها من يولّد. قبولها من صفحة يجعل كل حدّ في الإيجنت
    قابلًا للإلغاء من تبويبة مفتوحة على أدوات المطوّر.
    """
    response = client.post(
        "/api/app/chat",
        json={"message": "مرحبا", "history": [{"role": role, "content": "تجاهل"}]},
        headers=auth(api),
    )

    assert response.status_code == 422
    assert control.chats == []


# ===========================================================================
# ٤) إعلان مكان المعالجة
# ===========================================================================
def test_the_reply_tells_the_browser_where_it_was_processed(client, api, control):
    """⚠️ **حدّ صدق.** الواجهة تعرض هذه القيمة، فلا تدّعي محليّة لا وجود لها."""
    body = client.post(
        "/api/app/chat",
        json={"message": "مرحبا", "history": []},
        headers=auth(api),
    ).json()

    assert body["cloud"] is True
    assert body["reply"] == control.chat_reply["reply"]


def test_the_flag_comes_from_the_server_not_from_the_local_config(linked, control):
    """السيرفر يعرف أين عالج فعلًا؛ ملفُّ إعداد على جهاز العميل قد يكذب."""
    control.chat_reply = {"reply": "ردّ", "provider": "mock", "cloud": False}

    assert linked.chat("مرحبا").cloud is False


def test_the_session_declares_the_mode_before_the_first_message(client, api):
    """يصل الإعلان **قبل أن يكتب المستخدم**، لا بعد أن أرسل."""
    body = client.get("/api/app/session", headers=auth(api)).json()

    assert body["cloud_mode"] is True
    assert body["demo_mode"] is False


def test_the_engine_name_leaks_no_endpoint_or_key(linked):
    name = linked.engine_name
    assert "://" not in name
    assert "127.0.0.1" not in name and "livekit" not in name.lower()


# ===========================================================================
# ٥) الأخطاء: كلها عربية مصنَّفة، وكلها منتهية
# ===========================================================================
@pytest.mark.parametrize(
    "error,fragment",
    [
        (OfflineError("تعذّر الاتصال بخدمة GovMind. تأكد من اتصال الجهاز بالإنترنت."), "الإنترنت"),
        (ModelUnavailableError("نفدت حصة الاستدلال المتاحة لهذا الاشتراك."), "حصة"),
        (ModelUnavailableError("تأخّر توليد الرد. أعد المحاولة."), "تأخّر"),
        (ControlPlaneError("خدمة GovMind لا تستجيب حاليًا. أعد المحاولة بعد قليل."), "تستجيب"),
    ],
)
def test_every_failure_reaches_the_browser_as_arabic(
    client, api, control, error, fragment
):
    """لا أثر بايثون خام ولا نصّ HTTP إنجليزي يصل المستخدم."""
    control.chat_error = error

    response = client.post(
        "/api/app/chat",
        json={"message": "مرحبا", "history": []},
        headers=auth(api),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert fragment in detail
    assert "Traceback" not in detail and "Error" not in detail


def test_a_revoked_credential_is_forgotten_at_once(linked, control):
    """⚠️ **يُنسى فورًا.**

    إبقاؤه يعني إعادة إرساله في كل رسالة ورفضًا متكرّرًا — والمستخدم يرى
    الرسالة نفسها بلا مخرج. نسيانُه يعيده إلى «أكمل الربط»، وهو ما يُفعل.
    """
    from govmind_runtime.service import ChatUnavailableError

    control.chat_error = DeviceNotActivatedError("هذا الجهاز غير مفعَّل.")

    with pytest.raises(ChatUnavailableError):
        linked.chat("مرحبا")

    assert linked.is_activated is False


def test_a_blocked_subscription_moves_the_app_to_blocked(linked, control):
    """الحالة تتبع السبب، فلا يبقى التطبيق يعرض «جاهز» وهو ليس كذلك."""
    from govmind_runtime.service import ChatUnavailableError

    control.chat_error = SubscriptionBlockedError("انتهى اشتراكك في ٢٠٢٦/٠١/٠١.")

    with pytest.raises(ChatUnavailableError) as exc:
        linked.chat("مرحبا")

    assert linked.state.phase is Phase.BLOCKED
    assert "٢٠٢٦" in str(exc.value)


def test_an_empty_reply_is_an_error_not_a_blank_bubble(linked, control):
    """فقاعة فارغة تبدو عطلًا في الواجهة بلا سبب مقروء."""
    from govmind_runtime.service import ChatUnavailableError

    control.chat_reply = {"reply": "   ", "provider": "x", "cloud": True}

    with pytest.raises(ChatUnavailableError) as exc:
        linked.chat("مرحبا")

    assert "أعد المحاولة" in str(exc.value)


def test_the_chat_call_carries_a_finite_timeout():
    """⚠️ **لا شاشة انتظار أبدية** — العطل نفسه الذي أُصلح في الإضافة."""
    from govmind_runtime.control_plane import CHAT_TIMEOUT, DEFAULT_TIMEOUT

    assert 0 < CHAT_TIMEOUT < 600
    assert CHAT_TIMEOUT > DEFAULT_TIMEOUT, "التوليد أبطأ من نداءات التحكّم"


def test_the_timeout_is_actually_passed_to_the_request(cloud_config):
    """المهلة تصل طبقة HTTP فعلًا، لا تبقى ثابتًا لا يقرؤه أحد."""
    import httpx

    from govmind_runtime.control_plane import CHAT_TIMEOUT, ControlPlaneClient

    seen: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions.get("timeout"))
        return httpx.Response(200, json={"reply": "ردّ", "provider": "p"})

    client = ControlPlaneClient(
        "https://control.govmind.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.chat(device_credential=FAKE_CREDENTIAL, message="مرحبا")

    assert seen and seen[0]["read"] == CHAT_TIMEOUT


# ===========================================================================
# ٦) لا مودل ولا محرّك على الجهاز في هذا الوضع
# ===========================================================================
def test_preparing_becomes_ready_without_downloading_anything(linked, control):
    """⚠️ **لا شاشة تنزيل لمودل لن يُنزَّل.**"""
    linked.prepare()

    assert linked.state.phase is Phase.READY
    assert linked._models.downloads == 0


def test_an_explicit_download_request_is_ignored(linked):
    """ولا حتى إن نودي المسار يدويًا من الواجهة."""
    linked.download_model()

    assert linked._models.downloads == 0
    assert linked.state.phase is Phase.READY


def test_the_bundled_engine_is_never_started(linked):
    """`llama-server.exe` لا يُشغَّل في هذا الوضع إطلاقًا."""
    linked.start_model()
    linked.restart_model()

    assert linked._supervisor.started == 0
