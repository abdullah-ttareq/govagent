"""اختبارات اختيار مزود المودل."""

import pytest

from app.ai import ModelProviderError, get_model_provider
from app.ai.mock_provider import MockModelProvider


def test_mock_provider_is_selected_by_name():
    provider = get_model_provider("mock")
    assert isinstance(provider, MockModelProvider)


def test_unknown_provider_raises_clear_error():
    with pytest.raises(ModelProviderError) as exc:
        get_model_provider("gemini")
    assert "gemini" in str(exc.value)
    assert "mock" in str(exc.value)


def test_oracle_provider_is_not_implemented_yet():
    provider = get_model_provider("oracle")
    with pytest.raises(ModelProviderError):
        provider.generate("مرحبا", "system")


def test_local_provider_is_not_implemented_yet():
    provider = get_model_provider("local")
    with pytest.raises(ModelProviderError):
        provider.generate("مرحبا", "system")
