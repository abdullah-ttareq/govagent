"""اختيار مزود المودل حسب الإعداد MODEL_PROVIDER."""

from ..core.config import settings
from .base import ModelProvider, ModelProviderError
from .livekit_provider import LiveKitModelProvider
from .llamacpp_provider import LlamaCppModelProvider
from .lmstudio_provider import LMStudioModelProvider
from .local_provider import LocalModelProvider
from .mock_provider import MockModelProvider
from .oracle_provider import OracleModelProvider

_PROVIDERS: dict[str, type[ModelProvider]] = {
    "mock": MockModelProvider,
    "oracle": OracleModelProvider,
    "lmstudio": LMStudioModelProvider,
    # المودل داخل GovMind Runtime — لا يحتاج LM Studio مثبَّتة.
    "llamacpp": LlamaCppModelProvider,
    "local": LocalModelProvider,
    # ⚠️ **الوحيد السحابي.** يرسل نصّ المحادثة إلى خدمة خارجية، بخلاف كل
    # ما سبقه. اختياره قرارٌ يخصّ خصوصية البيانات لا الأداء وحده.
    "livekit": LiveKitModelProvider,
}

#: القيم المقبولة لـMODEL_PROVIDER، تُذكر في رسالة الخطأ وفي التوثيق.
SUPPORTED_PROVIDERS: tuple[str, ...] = tuple(sorted(_PROVIDERS))


def get_model_provider(name: str | None = None) -> ModelProvider:
    """يعيد نسخة من المزود المطلوب.

    Args:
        name: اسم المزود، أو None لاستخدام قيمة MODEL_PROVIDER.

    Raises:
        ModelProviderError: إذا كان اسم المزود غير مدعوم.
    """
    provider_name = (name or settings.model_provider or "").strip().lower()
    provider_class = _PROVIDERS.get(provider_name)
    if provider_class is None:
        supported = "، ".join(SUPPORTED_PROVIDERS)
        raise ModelProviderError(
            f"MODEL_PROVIDER='{provider_name}' غير مدعوم. "
            f"القيم المدعومة: {supported}."
        )
    return provider_class()
