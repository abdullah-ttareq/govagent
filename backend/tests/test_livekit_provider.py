"""مزوّد LiveKit Inference — **استدلال سحابي**.

**ما تحرسه هذه الاختبارات:**

* المزوّد مسجَّل ويعمل بـ``MODEL_PROVIDER=livekit``، **وبقية المزوّدين
  كما هم** — لا يُحذف ولا يتغيّر مسار محلي واحد.
* تعليمات النظام **وسياق المحادثة كاملًا** يصلان المزوّد بلا تقليم.
* المفتاح والسرّ **لا يخرجان في أي طلب ولا رسالة خطأ ولا سجلّ**؛ الذي
  يخرج رمزٌ قصير العمر.
* لكل فشل رسالته العربية: بيانات اعتماد، ومودل غير متاح، وحصة، وشبكة،
  ومهلة.
* **لا يُسجَّل نصّ المستخدم ولا ردّ المودل.**

⚠️ لا اختبار هنا ينادي الشبكة: كلها بـ``httpx.MockTransport``.
"""

from __future__ import annotations

import logging
import time

import httpx
import jwt
import pytest

from app.ai import ChatMessage
from app.ai.base import ModelProviderError
from app.ai.factory import SUPPORTED_PROVIDERS, get_model_provider
from app.ai.livekit_provider import (
    PRODUCTION_GATEWAY,
    STAGING_GATEWAY,
    LiveKitModelProvider,
    mint_access_token,
    resolve_gateway,
)
from app.core.config import settings

API_KEY = "APItestkeynotreal"
API_SECRET = "test-secret-value-that-is-not-real-0123456789"
MODEL = "google/gemini-2.5-flash-lite"

SYSTEM_PROMPT = "أنت GovMind، مساعد إداري."
ARABIC_REPLY = "الرياض هي عاصمة المملكة العربية السعودية."


@pytest.fixture
def livekit(monkeypatch):
    monkeypatch.setattr(settings, "livekit_url", "wss://demo.livekit.cloud")
    monkeypatch.setattr(settings, "livekit_api_key", API_KEY)
    monkeypatch.setattr(settings, "livekit_api_secret", API_SECRET)
    monkeypatch.setattr(settings, "livekit_model", MODEL)
    monkeypatch.setattr(settings, "livekit_inference_url", "")
    monkeypatch.setattr(settings, "livekit_timeout_seconds", 30.0)
    monkeypatch.setattr(settings, "livekit_max_tokens", 512)
    monkeypatch.setattr(settings, "livekit_temperature", 0.3)
    monkeypatch.setattr(settings, "livekit_token_ttl_seconds", 600)


class Recorder:
    """ينقل الطلبات ويسجّلها. **لا شبكة.**"""

    def __init__(self, response=None, raises=None) -> None:
        self.requests: list[httpx.Request] = []
        self._response = response
        self._raises = raises

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._raises is not None:
            raise self._raises
        return self._response or httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant",
                                           "content": ARABIC_REPLY}}]},
        )


def provider(recorder: Recorder) -> LiveKitModelProvider:
    return LiveKitModelProvider(transport=httpx.MockTransport(recorder))


def conversation() -> list[ChatMessage]:
    return [
        ChatMessage(role="user", content="مرحبًا"),
        ChatMessage(role="assistant", content="أهلًا بك، كيف أساعدك؟"),
        ChatMessage(role="user", content="ما عاصمة السعودية؟"),
    ]


# ===========================================================================
# ١) التسجيل — بلا مساس بالمزوّدين القائمين
# ===========================================================================
def test_livekit_is_registered_and_nothing_was_removed():
    """⚠️ المسارات المحلية تبقى كلها."""
    for name in ("mock", "oracle", "lmstudio", "llamacpp", "local", "livekit"):
        assert name in SUPPORTED_PROVIDERS, name


def test_provider_resolves_by_setting(livekit):
    assert get_model_provider("livekit").name == "livekit"


def test_the_label_says_it_is_cloud_inference():
    """⚠️ **الشرط الذي يمنع ادّعاء المحلية.**"""
    assert "سحاب" in LiveKitModelProvider.PRODUCT_LABEL
    assert "سحاب" in LiveKitModelProvider.CLOUD_NOTICE
    assert "هذا الجهاز" in LiveKitModelProvider.CLOUD_NOTICE


def test_local_providers_still_claim_locality_correctly():
    """المزوّدون المحليون لم تتغيّر تسمياتهم — التمييز يبقى صادقًا."""
    from app.ai.llamacpp_provider import LlamaCppModelProvider
    from app.ai.lmstudio_provider import LMStudioModelProvider

    assert "سحاب" not in LlamaCppModelProvider.PRODUCT_LABEL
    assert "سحاب" not in LMStudioModelProvider.PRODUCT_LABEL


# ===========================================================================
# ٢) البوابة والرمز
# ===========================================================================
def test_gateway_defaults_to_production():
    assert resolve_gateway("wss://demo.livekit.cloud") == PRODUCTION_GATEWAY


def test_staging_project_uses_the_staging_gateway():
    assert resolve_gateway("wss://x.staging.livekit.cloud") == STAGING_GATEWAY


def test_explicit_gateway_wins():
    assert resolve_gateway("wss://x.livekit.cloud", "https://gw.test/v1") == (
        "https://gw.test/v1"
    )


def test_token_carries_the_inference_grant_and_expires():
    token = mint_access_token(API_KEY, API_SECRET, 600)
    claims = jwt.decode(token, API_SECRET, algorithms=["HS256"])

    assert claims["iss"] == API_KEY
    assert claims["inference"] == {"perform": True}
    assert claims["exp"] > time.time()
    assert claims["exp"] - claims["nbf"] == 600


def test_the_secret_is_never_inside_the_token():
    """⚠️ السرّ يوقّع الرمز، ولا يُحمَل فيه."""
    token = mint_access_token(API_KEY, API_SECRET, 600)
    assert API_SECRET not in token


def test_a_wrong_secret_cannot_verify_the_token():
    token = mint_access_token(API_KEY, API_SECRET, 600)
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, "another-secret", algorithms=["HS256"])


def test_a_very_short_ttl_is_floored():
    """رمزٌ ينتهي قبل أن يصل لا يفيد أحدًا."""
    claims = jwt.decode(
        mint_access_token(API_KEY, API_SECRET, 1), API_SECRET,
        algorithms=["HS256"],
    )
    assert claims["exp"] - claims["nbf"] >= 60


# ===========================================================================
# ٣) الطلب — النظام والسياق كاملين
# ===========================================================================
def test_system_prompt_and_full_history_are_sent(livekit):
    recorder = Recorder()
    reply = provider(recorder).generate(conversation(), SYSTEM_PROMPT)

    assert reply.reply == ARABIC_REPLY
    assert reply.provider == "livekit"

    import json

    body = json.loads(recorder.requests[0].content)
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant", "user"], "قُلّم السياق"
    assert body["messages"][0]["content"] == SYSTEM_PROMPT
    assert body["messages"][-1]["content"] == "ما عاصمة السعودية؟"
    assert body["model"] == MODEL
    assert body["stream"] is False


def test_the_request_goes_to_the_gateway(livekit):
    recorder = Recorder()
    provider(recorder).generate(conversation(), SYSTEM_PROMPT)

    url = str(recorder.requests[0].url)
    assert url.startswith(PRODUCTION_GATEWAY)
    assert url.endswith("/chat/completions")


def test_the_authorization_header_carries_a_short_lived_token_not_the_secret(livekit):
    """⚠️ **الشرط الأهم.** ما يخرج رمزٌ، لا المفتاح ولا السرّ."""
    recorder = Recorder()
    provider(recorder).generate(conversation(), SYSTEM_PROMPT)

    request = recorder.requests[0]
    header = request.headers["Authorization"]
    assert header.startswith("Bearer ")

    token = header.split(" ", 1)[1]
    assert token != API_SECRET
    assert API_SECRET not in header

    claims = jwt.decode(token, API_SECRET, algorithms=["HS256"])
    assert claims["inference"] == {"perform": True}

    # ولا في الجسم.
    assert API_SECRET.encode() not in request.content


# ===========================================================================
# ٤) الأخطاء — لكل حالة رسالتها
# ===========================================================================
@pytest.mark.parametrize("status", [401, 403])
def test_invalid_credentials(livekit, status):
    recorder = Recorder(httpx.Response(status, json={"error": "unauthorized"}))
    with pytest.raises(ModelProviderError) as caught:
        provider(recorder).generate(conversation(), SYSTEM_PROMPT)
    message = str(caught.value)
    assert "بيانات الاعتماد" in message
    assert "LIVEKIT_API_KEY" in message


def test_model_unavailable(livekit):
    recorder = Recorder(httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(ModelProviderError) as caught:
        provider(recorder).generate(conversation(), SYSTEM_PROMPT)
    assert MODEL in str(caught.value)
    assert "LIVEKIT_MODEL" in str(caught.value)


def test_quota_or_rate_limit(livekit):
    recorder = Recorder(httpx.Response(429, json={"error": "rate limited"}))
    with pytest.raises(ModelProviderError) as caught:
        provider(recorder).generate(conversation(), SYSTEM_PROMPT)
    assert "حصة" in str(caught.value)


def test_out_of_credit(livekit):
    recorder = Recorder(httpx.Response(402, json={"error": "payment required"}))
    with pytest.raises(ModelProviderError) as caught:
        provider(recorder).generate(conversation(), SYSTEM_PROMPT)
    assert "رصيد" in str(caught.value)


def test_provider_timeout(livekit):
    recorder = Recorder(raises=httpx.ReadTimeout("slow"))
    with pytest.raises(ModelProviderError) as caught:
        provider(recorder).generate(conversation(), SYSTEM_PROMPT)
    assert "مهلة" in str(caught.value)


def test_network_failure(livekit):
    recorder = Recorder(raises=httpx.ConnectError("offline"))
    with pytest.raises(ModelProviderError) as caught:
        provider(recorder).generate(conversation(), SYSTEM_PROMPT)
    assert "تعذّر الاتصال" in str(caught.value)
    assert "الإنترنت" in str(caught.value)


def test_server_error(livekit):
    recorder = Recorder(httpx.Response(503, json={"error": "unavailable"}))
    with pytest.raises(ModelProviderError) as caught:
        provider(recorder).generate(conversation(), SYSTEM_PROMPT)
    assert "لا تستجيب" in str(caught.value)


def test_missing_settings_name_the_variables(monkeypatch):
    monkeypatch.setattr(settings, "livekit_api_key", "")
    monkeypatch.setattr(settings, "livekit_api_secret", "")
    monkeypatch.setattr(settings, "livekit_model", "")

    with pytest.raises(ModelProviderError) as caught:
        LiveKitModelProvider().generate(conversation(), SYSTEM_PROMPT)
    message = str(caught.value)
    for name in ("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "LIVEKIT_MODEL"):
        assert name in message


def test_no_error_message_ever_leaks_a_secret(livekit):
    """⚠️ ولا رسالة خطأ واحدة تحمل مفتاحًا أو سرًّا أو رمزًا."""
    cases = [
        Recorder(httpx.Response(401, json={"error": "bad key"})),
        Recorder(httpx.Response(429, json={"error": "quota"})),
        Recorder(raises=httpx.ConnectError("offline")),
        Recorder(raises=httpx.ReadTimeout("slow")),
    ]
    for recorder in cases:
        with pytest.raises(ModelProviderError) as caught:
            provider(recorder).generate(conversation(), SYSTEM_PROMPT)
        message = str(caught.value)
        assert API_SECRET not in message
        assert API_KEY not in message
        assert "Bearer" not in message


# ===========================================================================
# ٥) السجلّ
# ===========================================================================
def test_nothing_sensitive_reaches_the_log(livekit, caplog):
    """⚠️ لا نصّ مستخدم، ولا ردّ، ولا مفتاح، ولا سرّ، ولا رمز."""
    question = "سؤال سرّي جدًّا لا يجوز تسجيله"
    recorder = Recorder()

    with caplog.at_level(logging.DEBUG):
        provider(recorder).generate(
            [ChatMessage(role="user", content=question)], SYSTEM_PROMPT
        )

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert question not in logged
    assert ARABIC_REPLY not in logged
    assert API_SECRET not in logged
    assert API_KEY not in logged
    token = recorder.requests[0].headers["Authorization"].split(" ", 1)[1]
    assert token not in logged


def test_failures_do_not_log_the_conversation(livekit, caplog):
    question = "سؤال آخر لا يجوز تسجيله"
    recorder = Recorder(httpx.Response(500, json={"error": "boom"}))

    with caplog.at_level(logging.DEBUG), pytest.raises(ModelProviderError):
        provider(recorder).generate(
            [ChatMessage(role="user", content=question)], SYSTEM_PROMPT
        )

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert question not in logged
    assert API_SECRET not in logged
