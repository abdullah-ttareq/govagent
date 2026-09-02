"""مزود llama.cpp — المودل يعمل داخل GovMind Runtime بلا LM Studio.

`llama-server` (رخصة MIT) يعرض الواجهة المتوافقة مع OpenAI نفسها التي
يعرضها LM Studio، فالفرق بين المزوّدين **ليس في البروتوكول** وإنما في:

* من يشغّل الخادم: هنا يشغّله GovMind Runtime ويشرف عليه، وهناك يشغّله
  المستخدم يدويًا من تطبيق LM Studio.
* من أين يأتي العنوان: هنا من `LLAMACPP_BASE_URL` الذي يكتبه الـRuntime
  بعد أن يحجز منفذًا حرًّا، وهناك من إعداد ثابت يكتبه المشغّل.

لذلك يرث هذا المزوّد منطق النداء كاملًا من :class:`LMStudioModelProvider`
ولا يعيد كتابته: نسخُ مئتي سطر لتغيير مصدر عنوان يجعل إصلاح خطأ في تحليل
الرد يحتاج إصلاحين.

⚠️ **مزود LM Studio باقٍ كما هو ولم يُمسّ.** يبقى الخيار الأنسب للتطوير
على جهاز فيه LM Studio أصلًا.
"""

from __future__ import annotations

from ..core.config import settings
from .lmstudio_provider import LMStudioModelProvider, _LmStudioConfig
from .base import ModelProviderError


class LlamaCppModelProvider(LMStudioModelProvider):
    """يستدعي `llama-server` الذي يشرف عليه GovMind Runtime.

    الإعدادات: ``LLAMACPP_BASE_URL`` و ``LLAMACPP_MODEL``، وتُملأ الأولى
    من الـRuntime عند تشغيل المحرّك — **لا يكتبها المستخدم في أي شاشة**.
    """

    name = "llamacpp"

    # ⚠️ **العميل يجب ألا يقرأ «LM Studio» في أي رسالة.** المزوّد الأصل
    # يمرّ كل رسائله بـ`_localize`، وهذه القيم هي ما تُستبدل به.
    PRODUCT_LABEL = "محرّك GovMind المحلي"
    SETTINGS_PREFIX = "LLAMACPP"

    @staticmethod
    def _read_settings() -> _LmStudioConfig:
        base_url = (settings.llamacpp_base_url or "").strip().rstrip("/")
        if not base_url:
            raise ModelProviderError(
                "محرّك المودل المحلي لم يبدأ بعد. انتظر حتى يكتمل تجهيز "
                "GovMind، أو أعد تشغيله من نافذة البرنامج."
            )

        # اسم المودل اختياري في llama-server: يخدم مودلًا واحدًا محمَّلًا،
        # ويقبل أي اسم. القيمة هنا للعرض في السجلّات لا للاختيار.
        model = (settings.llamacpp_model or "govmind-local").strip()

        return _LmStudioConfig(
            base_url=base_url,
            model=model,
            # ⚠️ لا مفتاح: الخادم على الاسترجاع المحلي، والـRuntime يحرسه.
            api_key="",
            timeout=float(settings.llamacpp_timeout_seconds),
            max_tokens=int(settings.llamacpp_max_tokens),
            temperature=float(settings.llamacpp_temperature),
        )
