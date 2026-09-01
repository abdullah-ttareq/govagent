"""اختبارات مزود LM Studio.

**لا يحتاج أي اختبار هنا أن يكون LM Studio مفتوحًا،** ولا يخرج أي طلب من
العملية: كل الاستدعاءات تمر عبر ``httpx.MockTransport`` الذي يردّ محليًا.
ما يُختبر: شكل الطلب المرسل (تعليمات النظام والسجل والسؤال)، واستخراج نص
الإجابة، وتحويل كل فشل (انقطاع، مهلة، مودل غير محمّل، رد ناقص) إلى
``ModelProviderError`` برسالة عربية بلا تفاصيل داخلية.
"""

import json

import httpx
import pytest

from app.ai import ChatMessage, ModelProviderError, get_model_provider
from app.ai.lmstudio_provider import LMStudioModelProvider
from app.core.config import Settings, settings

BASE_URL = "http://127.0.0.1:1234/v1"
CHAT_URL = f"{BASE_URL}/chat/completions"
MODEL = "google/gemma-4-e4b"

SYSTEM_PROMPT = "أنت GovMind، مساعد موظفي الجهة."


def user(text: str) -> ChatMessage:
    return ChatMessage(role="user", content=text)


def assistant(text: str) -> ChatMessage:
    return ChatMessage(role="assistant", content=text)


CONVERSATION = [
    user("لخّص لي التقرير"),
    assistant("هذا ملخص التقرير."),
    user("اجعله أقصر"),
]


@pytest.fixture(autouse=True)
def lm_settings(monkeypatch):
    """يثبّت إعدادات LM Studio لكل اختبار مهما كان ملف .env على الجهاز."""
    monkeypatch.setattr(settings, "lm_studio_base_url", BASE_URL)
    monkeypatch.setattr(settings, "lm_studio_model", MODEL)
    monkeypatch.setattr(settings, "lm_studio_api_key", "")
    monkeypatch.setattr(settings, "lm_studio_timeout_seconds", 120.0)
    monkeypatch.setattr(settings, "lm_studio_max_tokens", 512)


def provider_returning(payload, *, status: int = 200, captured: list | None = None):
    """مزودًا موصولًا بناقل وهمي يعيد ``payload`` ويسجّل الطلب في ``captured``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        if isinstance(payload, (dict, list)):
            return httpx.Response(status, json=payload)
        return httpx.Response(status, text=payload)

    return LMStudioModelProvider(transport=httpx.MockTransport(handler))


def provider_raising(error: Exception):
    """مزودًا ناقله يرفع استثناء شبكة بدل أن يرد."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return LMStudioModelProvider(transport=httpx.MockTransport(handler))


def reply_payload(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


# ---------------------------------------------------------------------------
# 1) اختيار المزود من الإعداد
# ---------------------------------------------------------------------------
def test_lmstudio_is_selected_by_name():
    assert isinstance(get_model_provider("lmstudio"), LMStudioModelProvider)


def test_lmstudio_is_selected_from_model_provider_setting(monkeypatch):
    """MODEL_PROVIDER=lmstudio وحدها تكفي لاختيار المزود."""
    monkeypatch.setattr(settings, "model_provider", "lmstudio")
    assert isinstance(get_model_provider(), LMStudioModelProvider)


def test_oracle_and_mock_remain_selectable(monkeypatch):
    """إضافة lmstudio لا تُزيح المزودات القائمة."""
    from app.ai.mock_provider import MockModelProvider
    from app.ai.oracle_provider import OracleModelProvider

    assert isinstance(get_model_provider("mock"), MockModelProvider)
    assert isinstance(get_model_provider("oracle"), OracleModelProvider)


# ---------------------------------------------------------------------------
# 2) شكل الطلب المرسل
# ---------------------------------------------------------------------------
def test_request_goes_to_the_chat_completions_path():
    captured: list[httpx.Request] = []
    provider_returning(reply_payload("تم"), captured=captured).generate(
        messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
    )

    assert str(captured[0].url) == CHAT_URL
    assert captured[0].method == "POST"


def test_request_carries_system_prompt_history_and_question():
    """تعليمات النظام أولًا، ثم السجل بترتيبه، وآخر رسالة سؤال المستخدم."""
    captured: list[httpx.Request] = []
    provider_returning(reply_payload("تم"), captured=captured).generate(
        messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
    )

    body = json.loads(captured[0].content)
    assert body["model"] == MODEL
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "لخّص لي التقرير"},
        {"role": "assistant", "content": "هذا ملخص التقرير."},
        {"role": "user", "content": "اجعله أقصر"},
    ]


def test_request_caps_the_answer_at_the_configured_max_tokens(monkeypatch):
    """سقف الإجابة يُقرأ من الإعداد ويُرسل في كل طلب."""
    monkeypatch.setattr(settings, "lm_studio_max_tokens", 512)
    captured: list[httpx.Request] = []
    provider_returning(reply_payload("تم"), captured=captured).generate(
        messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
    )

    assert json.loads(captured[0].content)["max_tokens"] == 512


def test_max_tokens_default_fits_a_reasoning_model():
    """١٥٠٠ لا ٥١٢: قياس فعلي أثبت أن ٥١٢ يبتلعها الاستدلال فتعود إجابة فارغة."""
    assert Settings.model_fields["lm_studio_max_tokens"].default == 1500


def test_timeout_default_fits_a_medium_local_answer():
    """٣٠٠ ثانية: سؤال إداري متوسط قيس عند ٢٦٢ ثانية عبر المسار الكامل."""
    assert Settings.model_fields["lm_studio_timeout_seconds"].default == 300.0


def test_raising_max_tokens_is_honoured(monkeypatch):
    """الإعداد قابل للرفع لمن كان جهازه سريعًا."""
    monkeypatch.setattr(settings, "lm_studio_max_tokens", 2048)
    captured: list[httpx.Request] = []
    provider_returning(reply_payload("تم"), captured=captured).generate(
        messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
    )

    assert json.loads(captured[0].content)["max_tokens"] == 2048


def test_max_tokens_change_does_not_touch_oracle_settings(monkeypatch):
    """سقف LM Studio مستقل عن سقف Oracle، ولا يغيّره."""
    monkeypatch.setattr(settings, "lm_studio_max_tokens", 64)
    assert settings.oci_max_tokens == 1500


def test_request_uses_the_configured_model_id(monkeypatch):
    monkeypatch.setattr(settings, "lm_studio_model", "another/model")
    captured: list[httpx.Request] = []
    provider_returning(reply_payload("تم"), captured=captured).generate(
        messages=[user("مرحبا")], system_prompt=SYSTEM_PROMPT
    )

    assert json.loads(captured[0].content)["model"] == "another/model"


def test_request_has_no_authorization_header_by_default():
    """الخادم محلي: لا مفتاح ولا ترويسة هوية ما لم يُضبط المتغير."""
    captured: list[httpx.Request] = []
    provider_returning(reply_payload("تم"), captured=captured).generate(
        messages=[user("مرحبا")], system_prompt=SYSTEM_PROMPT
    )

    assert "authorization" not in captured[0].headers


def test_optional_api_key_is_sent_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "lm_studio_api_key", "proxy-key")
    captured: list[httpx.Request] = []
    provider_returning(reply_payload("تم"), captured=captured).generate(
        messages=[user("مرحبا")], system_prompt=SYSTEM_PROMPT
    )

    assert captured[0].headers["authorization"] == "Bearer proxy-key"


def test_base_url_with_trailing_slash_does_not_duplicate_it(monkeypatch):
    monkeypatch.setattr(settings, "lm_studio_base_url", BASE_URL + "/")
    captured: list[httpx.Request] = []
    provider_returning(reply_payload("تم"), captured=captured).generate(
        messages=[user("مرحبا")], system_prompt=SYSTEM_PROMPT
    )

    assert str(captured[0].url) == CHAT_URL


def test_docker_host_base_url_is_honoured(monkeypatch):
    """الـBackend داخل Docker يصل إلى LM Studio عبر host.docker.internal."""
    monkeypatch.setattr(
        settings, "lm_studio_base_url", "http://host.docker.internal:1234/v1"
    )
    captured: list[httpx.Request] = []
    provider_returning(reply_payload("تم"), captured=captured).generate(
        messages=[user("مرحبا")], system_prompt=SYSTEM_PROMPT
    )

    assert (
        str(captured[0].url)
        == "http://host.docker.internal:1234/v1/chat/completions"
    )


def test_empty_conversation_is_rejected_before_any_request():
    captured: list[httpx.Request] = []
    with pytest.raises(ModelProviderError) as exc:
        provider_returning(reply_payload("تم"), captured=captured).generate(
            messages=[], system_prompt=SYSTEM_PROMPT
        )

    assert "فارغ" in str(exc.value)
    assert captured == []


# ---------------------------------------------------------------------------
# 3) استخراج نص الإجابة
# ---------------------------------------------------------------------------
def test_reply_text_is_extracted_from_the_first_choice():
    result = provider_returning(reply_payload("  هذا نص الإجابة.  ")).generate(
        messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
    )

    assert result.reply == "هذا نص الإجابة."
    assert result.provider == "lmstudio"


# ---------------------------------------------------------------------------
# 4) تعطل الاتصال — LM Studio مغلق أو غير قابل للوصول
# ---------------------------------------------------------------------------
def test_connection_refused_explains_that_the_local_server_is_off():
    with pytest.raises(ModelProviderError) as exc:
        provider_raising(httpx.ConnectError("connection refused")).generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    message = str(exc.value)
    assert "LM Studio" in message
    assert BASE_URL in message
    assert "connection refused" not in message


def test_unreachable_host_is_reported_as_a_connection_failure():
    with pytest.raises(ModelProviderError) as exc:
        provider_raising(httpx.ConnectError("name resolution failed")).generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    assert "تعذّر الاتصال" in str(exc.value)


# ---------------------------------------------------------------------------
# 5) انتهاء المهلة
# ---------------------------------------------------------------------------
def test_read_timeout_mentions_the_timeout_setting():
    with pytest.raises(ModelProviderError) as exc:
        provider_raising(httpx.ReadTimeout("timed out")).generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    message = str(exc.value)
    assert "مهلة" in message
    assert "LM_STUDIO_TIMEOUT_SECONDS" in message


def test_connect_timeout_is_classified_as_a_timeout():
    with pytest.raises(ModelProviderError) as exc:
        provider_raising(httpx.ConnectTimeout("timed out")).generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    assert "مهلة" in str(exc.value)


# ---------------------------------------------------------------------------
# 6) المودل غير محمّل
# ---------------------------------------------------------------------------
def test_model_not_found_names_the_configured_model():
    payload = {"error": {"message": "Model 'google/gemma-4-e4b' not found"}}
    with pytest.raises(ModelProviderError) as exc:
        provider_returning(payload, status=404).generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    message = str(exc.value)
    assert MODEL in message
    assert "LM_STUDIO_MODEL" in message


def test_model_not_loaded_reported_with_a_non_404_status():
    payload = {"error": "model_not_found: no model is loaded"}
    with pytest.raises(ModelProviderError) as exc:
        provider_returning(payload, status=400).generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    assert MODEL in str(exc.value)


def test_server_error_does_not_leak_the_upstream_body():
    with pytest.raises(ModelProviderError) as exc:
        provider_returning(
            "Traceback (most recent call last): RuntimeError", status=500
        ).generate(messages=CONVERSATION, system_prompt=SYSTEM_PROMPT)

    message = str(exc.value)
    assert "500" in message
    assert "Traceback" not in message


def test_unauthorized_points_to_the_optional_api_key():
    with pytest.raises(ModelProviderError) as exc:
        provider_returning({"error": "unauthorized"}, status=401).generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    assert "LM_STUDIO_API_KEY" in str(exc.value)


# ---------------------------------------------------------------------------
# 7) استجابة ناقصة أو غير صالحة
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": "   "}}]},
        {"choices": [{"message": {"content": 42}}]},
        {"choices": "not-a-list"},
    ],
)
def test_incomplete_response_is_rejected_with_one_clear_message(payload):
    with pytest.raises(ModelProviderError) as exc:
        provider_returning(payload).generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    assert "رد غير صالح" in str(exc.value)


def test_empty_answer_cut_by_the_token_cap_names_max_tokens():
    """مودلات الاستدلال تبتلع السقف في تفكير داخلي فتعود بإجابة فارغة.

    الرسالة هنا **ليست** «رد غير صالح»: المودل يعمل، والسقف هو المشكلة،
    وذكر المتغير يجعل الخطأ قابلًا للإصلاح بلا مراجعة السجلات.
    """
    payload = {
        "choices": [
            {"message": {"role": "assistant", "content": ""}, "finish_reason": "length"}
        ],
        "usage": {"completion_tokens_details": {"reasoning_tokens": 509}},
    }
    with pytest.raises(ModelProviderError) as exc:
        provider_returning(payload).generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    message = str(exc.value)
    assert "LM_STUDIO_MAX_TOKENS" in message
    assert "رد غير صالح" not in message


def test_partial_answer_cut_by_the_token_cap_is_still_returned():
    """إجابة مبتورة لكنها موجودة تُعاد كما هي: نصٌ ناقص خير من خطأ."""
    payload = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "بداية الخطاب"},
                "finish_reason": "length",
            }
        ]
    }
    result = provider_returning(payload).generate(
        messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
    )

    assert result.reply == "بداية الخطاب"


def test_empty_answer_without_length_reason_stays_a_generic_invalid_response():
    payload = {
        "choices": [
            {"message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}
        ]
    }
    with pytest.raises(ModelProviderError) as exc:
        provider_returning(payload).generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    assert "رد غير صالح" in str(exc.value)


def test_non_json_body_is_rejected():
    with pytest.raises(ModelProviderError) as exc:
        provider_returning("<html>not json</html>").generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    assert "رد غير صالح" in str(exc.value)


# ---------------------------------------------------------------------------
# 8) إعداد ناقص
# ---------------------------------------------------------------------------
def test_missing_base_url_names_the_variable(monkeypatch):
    monkeypatch.setattr(settings, "lm_studio_base_url", "")
    with pytest.raises(ModelProviderError) as exc:
        LMStudioModelProvider().generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    message = str(exc.value)
    assert "LM_STUDIO_BASE_URL" in message
    assert "mock" in message


def test_missing_model_names_the_variable(monkeypatch):
    monkeypatch.setattr(settings, "lm_studio_model", "")
    with pytest.raises(ModelProviderError) as exc:
        LMStudioModelProvider().generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    assert "LM_STUDIO_MODEL" in str(exc.value)


def test_non_positive_timeout_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "lm_studio_timeout_seconds", 0.0)
    with pytest.raises(ModelProviderError) as exc:
        LMStudioModelProvider().generate(
            messages=CONVERSATION, system_prompt=SYSTEM_PROMPT
        )

    assert "LM_STUDIO_TIMEOUT_SECONDS" in str(exc.value)


# ---------------------------------------------------------------------------
# 9) المسار الكامل عبر chat_service — الجهة والمصادر تبقى كما هي
# ---------------------------------------------------------------------------
def test_chat_service_uses_lmstudio_when_configured(monkeypatch):
    """المزود يُستدعى من نفس مسار المحادثة، بلا مسار موازٍ."""
    from app.services import chat_service

    captured: list[httpx.Request] = []
    monkeypatch.setattr(settings, "model_provider", "lmstudio")
    monkeypatch.setattr(
        chat_service,
        "get_model_provider",
        lambda name=None: provider_returning(
            reply_payload("رد المودل المحلي"), captured=captured
        ),
    )

    response = chat_service.send_message("ما نظام الإجازات؟")

    assert response.reply == "رد المودل المحلي"
    assert response.provider == "lmstudio"
    body = json.loads(captured[0].content)
    # تعليمات GovMind تصل كما هي، والسؤال آخر رسالة.
    assert body["messages"][0]["role"] == "system"
    assert "GovMind" in body["messages"][0]["content"]
    assert body["messages"][-1] == {
        "role": "user",
        "content": "ما نظام الإجازات؟",
    }
