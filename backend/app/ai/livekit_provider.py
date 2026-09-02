"""مزوّد LiveKit Inference — **استدلال سحابي، لا محلي**.

⚠️⚠️ **هذا المزوّد يرسل نصّ المحادثة إلى خدمة خارجية.** هو الوحيد بين
مزوّدي هذا المشروع الذي يفعل ذلك: `lmstudio` و`llamacpp` يبقيان النصّ على
الجهاز، و`mock` لا يرسل شيئًا. أي واجهة تعرض هذا المزوّد **يجب أن تقول
ذلك للمستخدم صراحة**، ولا يجوز أن يبقى فيها ادّعاء أن المعالجة محلية.

--------------------------------------------------------------------------
لماذا لا يُستعمل `livekit-agents`؟
--------------------------------------------------------------------------
بوابة LiveKit Inference **متوافقة مع OpenAI**: نداء
``POST {gateway}/chat/completions`` برمز في ترويسة ``Authorization``. وهو
البروتوكول نفسه الذي يتكلّمه :class:`LMStudioModelProvider` منذ البداية.

لذلك يرث هذا المزوّد بناءَ الطلب واستخراجَ الرد منه، ولا يضيف حزمة
``livekit-agents`` (إطار وكلاء صوتيين كامل) ولا ``livekit-api`` (يجرّ
``aiohttp`` و``protobuf``) — إحدى عشرة حزمة لتوليد رمز JWT يولّده
``PyJWT`` الموجود أصلًا في هذا المشروع.

**ما يُعاد كتابته هنا وحده:** قراءة الإعدادات، وتوليد الرمز، وتصنيف
الأخطاء. والأخير ضروري: رسائل المزوّد الأصل ترشد إلى «افتح تطبيق LM Studio
وشغّل الخادم المحلي»، وهي إرشاد خاطئ تمامًا لخدمة سحابية.

--------------------------------------------------------------------------
الأسرار
--------------------------------------------------------------------------
⚠️ ``LIVEKIT_API_KEY`` و``LIVEKIT_API_SECRET`` **لا يغادران السيرفر**:
لا إلى متصفح، ولا إلى الإضافة، ولا إلى الـRuntime على جهاز العميل، ولا
إلى أي حزمة واجهة. ما يخرج من هنا رمزٌ **قصير العمر** (عشر دقائق
افتراضًا) يُولَّد لكل طلب ولا يُخزَّن.

⚠️ **لا يُسجَّل شيء من هذه:** نصّ المستخدم، ولا ردّ المودل، ولا الرمز،
ولا المفتاح، ولا السرّ. السجلّ يحمل رمز الحالة والمودل والزمن.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import jwt

from ..core.config import settings
from .base import ChatMessage, ChatResult, ModelProviderError, ensure_conversation
from .lmstudio_provider import LMStudioModelProvider, _LmStudioConfig

logger = logging.getLogger(__name__)

#: بوابة الاستدلال. تُشتقّ من `LIVEKIT_URL` حين لا تُضبط صراحةً.
PRODUCTION_GATEWAY = "https://agent-gateway.livekit.cloud/v1"
STAGING_GATEWAY = "https://agent-gateway.staging.livekit.cloud/v1"

#: العلامة التي تميّز مشروع staging في عنوان LiveKit.
_STAGING_MARKER = ".staging.livekit.cloud"

#: هوية حامل الرمز. البوابة تتوقّع فاعلًا لا مستخدمًا نهائيًا.
_TOKEN_IDENTITY = "agent"


def resolve_gateway(livekit_url: str, override: str = "") -> str:
    """يحدّد عنوان بوابة الاستدلال.

    الأولوية للقيمة الصريحة، ثم يُشتقّ من عنوان المشروع: مشروع staging
    يُخدَم من بوابة staging، وما عداه من بوابة الإنتاج.
    """
    explicit = (override or "").strip().rstrip("/")
    if explicit:
        return explicit
    return (
        STAGING_GATEWAY
        if _STAGING_MARKER in (livekit_url or "")
        else PRODUCTION_GATEWAY
    )


def mint_access_token(api_key: str, api_secret: str, ttl_seconds: int) -> str:
    """يولّد رمز وصول قصير العمر لبوابة الاستدلال.

    البنية هي بنية ``AccessToken`` في LiveKit: ``iss`` هو المفتاح،
    و``sub`` هوية الفاعل، ومنحة ``inference`` تعطي حقّ التنفيذ. التوقيع
    ``HS256`` بالسرّ.

    ⚠️ **يُولَّد لكل طلب ولا يُخزَّن ولا يُسجَّل.** عمره القصير يجعل تسريبه
    — إن وقع — نافذةً بدقائق لا مفتاحًا دائمًا.
    """
    now = int(time.time())
    return jwt.encode(
        {
            "iss": api_key,
            "sub": _TOKEN_IDENTITY,
            "name": _TOKEN_IDENTITY,
            "nbf": now,
            "exp": now + max(60, int(ttl_seconds)),
            "inference": {"perform": True},
        },
        api_secret,
        algorithm="HS256",
    )


class LiveKitModelProvider(LMStudioModelProvider):
    """يستدعي مودلًا عبر LiveKit Inference.

    ⚠️ **سحابي.** النصّ يغادر الجهاز والسيرفر إلى بوابة LiveKit.
    """

    name = "livekit"

    #: ⚠️ **يُعرض للمستخدم.** يقول صراحة إن الاستدلال سحابي.
    PRODUCT_LABEL = "LiveKit Inference (استدلال سحابي)"
    SETTINGS_PREFIX = "LIVEKIT"

    #: نصّ يُعرض في الواجهة بجانب الرد. **لا يجوز حذفه** — هو التصريح
    #: الذي يمنع ادّعاء أن المحادثة محلية.
    CLOUD_NOTICE = (
        "تتم المعالجة على خدمة LiveKit السحابية، لا على هذا الجهاز."
    )

    # ------------------------------------------------------------------
    @staticmethod
    def _read_settings() -> _LmStudioConfig:
        """يقرأ إعداد LiveKit ويولّد رمز الطلب.

        Raises:
            ModelProviderError: إعداد ناقص، برسالة تسمّي المتغيّر الناقص
                **ولا تكشف أي قيمة**.
        """
        api_key = (settings.livekit_api_key or "").strip()
        api_secret = (settings.livekit_api_secret or "").strip()
        model = (settings.livekit_model or "").strip()

        missing = []
        if not api_key:
            missing.append("LIVEKIT_API_KEY")
        if not api_secret:
            missing.append("LIVEKIT_API_SECRET")
        if not model:
            missing.append("LIVEKIT_MODEL")
        if missing:
            raise ModelProviderError(
                "إعداد مزوّد LiveKit غير مكتمل، ولا يمكن الاتصال بالمودل. "
                f"المتغيرات الناقصة: {'، '.join(missing)}. اضبطها في ملف "
                ".env على السيرفر، أو استخدم MODEL_PROVIDER=mock للتشغيل "
                "بدون مودل حقيقي."
            )

        timeout = float(settings.livekit_timeout_seconds)
        if timeout <= 0:
            raise ModelProviderError(
                "قيمة LIVEKIT_TIMEOUT_SECONDS يجب أن تكون أكبر من صفر. "
                "اضبطها في ملف .env (القيمة المقترحة: 120)."
            )

        gateway = resolve_gateway(
            settings.livekit_url, settings.livekit_inference_url
        )

        return _LmStudioConfig(
            base_url=gateway,
            model=model,
            # ⚠️ رمز قصير العمر لا المفتاح نفسه.
            api_key=mint_access_token(
                api_key, api_secret, settings.livekit_token_ttl_seconds
            ),
            timeout=timeout,
            max_tokens=int(settings.livekit_max_tokens),
            temperature=float(settings.livekit_temperature),
        )

    # ------------------------------------------------------------------
    def _call_model(
        self, config: _LmStudioConfig, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """ينفّذ النداء على البوابة، بأخطاء سحابية مصنَّفة.

        **لماذا لا يُورَث النداء كما هو؟** رسائل المزوّد الأصل ترشد إلى
        تشغيل تطبيق محلي وفتح «Local Server» — إرشادٌ لا معنى له لخدمة
        سحابية، ويضيّع على المستخدم الإجراء الصحيح.
        """
        httpx = self._import_httpx()

        headers = {
            "Content-Type": "application/json",
            # ⚠️ الرمز هنا وحده. لا يُسجَّل ولا يظهر في أي رسالة خطأ.
            "Authorization": f"Bearer {config.api_key}",
        }
        timeout = httpx.Timeout(config.timeout, connect=min(config.timeout, 10.0))

        started = time.monotonic()
        try:
            with httpx.Client(
                timeout=timeout, transport=self._transport
            ) as client:
                response = client.post(
                    config.chat_url, json=payload, headers=headers
                )
        except httpx.TimeoutException as exc:
            # ⚠️ يُسجَّل النوع والمهلة — لا الرمز ولا النصّ.
            logger.warning(
                "انتهت مهلة LiveKit Inference: model=%s timeout=%s error=%s",
                config.model,
                config.timeout,
                type(exc).__name__,
            )
            raise ModelProviderError(
                "انتهت مهلة انتظار الرد من خدمة LiveKit قبل اكتمال الإجابة. "
                "جرّب سؤالًا أقصر، أو ارفع قيمة LIVEKIT_TIMEOUT_SECONDS في "
                "ملف .env على السيرفر."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "تعذّر الاتصال بـLiveKit Inference: model=%s error=%s",
                config.model,
                type(exc).__name__,
            )
            raise ModelProviderError(
                "تعذّر الاتصال بخدمة LiveKit. تأكد من اتصال السيرفر "
                "بالإنترنت، ثم أعد المحاولة."
            ) from exc

        logger.info(
            "ردّت LiveKit Inference: model=%s status=%s seconds=%.1f",
            config.model,
            response.status_code,
            time.monotonic() - started,
        )
        return self._read_response(config, response)

    # ------------------------------------------------------------------
    def _read_response(
        self, config: _LmStudioConfig, response: Any
    ) -> dict[str, Any]:
        """يصنّف رمز الحالة إلى رسالة عربية تقول ما يُفعل.

        كل فرع هنا يقابل إجراءً مختلفًا من المشغّل: بيانات اعتماد خاطئة
        تُصحَّح، ومودل غير متاح يُبدَّل، وحصة منتهية تُنتظر أو تُرفع.
        """
        status = response.status_code
        if status < 400:
            return super()._read_response(config, response)

        # ⚠️ تفصيل الخطأ يُقرأ للسجلّ فقط، ولا يُمرَّر إلى المستخدم: قد
        # يحمل معرّفات مشروع أو أثرًا داخليًا من المزوّد.
        detail = self._error_detail(response)
        logger.warning(
            "رفضت LiveKit Inference الطلب: model=%s status=%s detail=%s",
            config.model,
            status,
            detail[:200],
        )

        if status in (401, 403):
            raise ModelProviderError(
                "رفضت خدمة LiveKit بيانات الاعتماد. تأكد من صحة "
                "LIVEKIT_API_KEY و LIVEKIT_API_SECRET في ملف .env على "
                "السيرفر، ومن أن المشروع يسمح بالاستدلال."
            )
        if status == 404:
            raise ModelProviderError(
                f"المودل «{config.model}» غير متاح على خدمة LiveKit. صحّح "
                "قيمة LIVEKIT_MODEL في ملف .env على السيرفر."
            )
        if status == 429:
            raise ModelProviderError(
                "بلغت حصة الاستدلال في LiveKit حدّها، أو كثُرت الطلبات "
                "المتزامنة. انتظر قليلًا ثم أعد المحاولة، أو راجع رصيد "
                "الحساب."
            )
        if status == 402:
            raise ModelProviderError(
                "نفد رصيد الاستدلال في حساب LiveKit. جدّد الرصيد لمتابعة "
                "الاستخدام."
            )
        if status >= 500:
            raise ModelProviderError(
                "خدمة LiveKit لا تستجيب حاليًا. أعد المحاولة بعد قليل."
            )
        raise ModelProviderError(
            f"رفضت خدمة LiveKit الطلب ولم تكتمل الإجابة (رمز {status}). "
            "أعد المحاولة، وإن تكرر فراجع إعداد المزوّد."
        )

    # ------------------------------------------------------------------
    def generate(
        self, messages: list[ChatMessage], system_prompt: str
    ) -> ChatResult:
        """كما في المزوّد الأصل، مع تسجيل صريح أن الاستدلال سحابي.

        ⚠️ **يُحتفظ بتعليمات النظام وسياق المحادثة كاملين** — يبنيهما
        `_build_payload` الموروث بلا تقليم.
        """
        conversation = ensure_conversation(messages)
        logger.info(
            "استدلال سحابي عبر LiveKit: model=%s رسائل=%d",
            (settings.livekit_model or "").strip(),
            len(conversation),
        )
        return super().generate(conversation, system_prompt)
