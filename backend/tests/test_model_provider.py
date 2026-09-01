"""اختبارات اختيار مزود المودل وسياق المحادثة."""

import pytest

from app.ai import (
    SUPPORTED_PROVIDERS,
    ChatMessage,
    ModelProviderError,
    get_model_provider,
)
from app.ai.mock_provider import MockModelProvider


def user(text: str) -> ChatMessage:
    return ChatMessage(role="user", content=text)


def assistant(text: str) -> ChatMessage:
    return ChatMessage(role="assistant", content=text)


# ---------------------------------------------------------------------------
# اختيار المزود
# ---------------------------------------------------------------------------
def test_mock_provider_is_selected_by_name():
    provider = get_model_provider("mock")
    assert isinstance(provider, MockModelProvider)


def test_unknown_provider_error_lists_supported_values():
    """رسالة المزود غير المدعوم يجب أن تذكر القيم المقبولة كلها."""
    with pytest.raises(ModelProviderError) as exc:
        get_model_provider("gemini")

    message = str(exc.value)
    assert "gemini" in message
    for name in SUPPORTED_PROVIDERS:
        assert name in message


def test_supported_providers_are_the_expected_four():
    assert set(SUPPORTED_PROVIDERS) == {"mock", "oracle", "lmstudio", "local"}


# ---------------------------------------------------------------------------
# مزود mock — المسار الافتراضي للمشروع
# ---------------------------------------------------------------------------
def test_mock_provider_answers_a_single_message():
    result = get_model_provider("mock").generate(
        messages=[user("اكتب لي خطابًا رسميًا")],
        system_prompt="تعليمات",
    )
    assert result.provider == "mock"
    assert "اكتب لي خطابًا رسميًا" in result.reply


def test_mock_provider_receives_the_conversation_context():
    """السياق يصل إلى المزود، ويُبنى الرد على آخر رسالة مستخدم."""
    result = get_model_provider("mock").generate(
        messages=[
            user("لخّص لي التقرير"),
            assistant("هذا ملخص التقرير."),
            user("اجعله أقصر"),
        ],
        system_prompt="تعليمات",
    )
    assert "اجعله أقصر" in result.reply
    assert "2 رسالة سابقة" in result.reply


def test_provider_rejects_empty_conversation():
    with pytest.raises(ModelProviderError) as exc:
        get_model_provider("mock").generate(messages=[], system_prompt="تعليمات")
    assert "فارغ" in str(exc.value)


def test_provider_rejects_conversation_not_ending_with_user():
    with pytest.raises(ModelProviderError) as exc:
        get_model_provider("mock").generate(
            messages=[user("سؤال"), assistant("جواب")],
            system_prompt="تعليمات",
        )
    assert "المستخدم" in str(exc.value)


# ---------------------------------------------------------------------------
# المزود المحلي — ما زال خارج نطاق الـMVP
# ---------------------------------------------------------------------------
def test_local_provider_is_not_implemented_yet():
    provider = get_model_provider("local")
    with pytest.raises(ModelProviderError) as exc:
        provider.generate(messages=[user("مرحبا")], system_prompt="تعليمات")
    assert "mock" in str(exc.value)
