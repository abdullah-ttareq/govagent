"""مزود LM Studio — مودل محلي على جهاز الجهة بواجهة متوافقة مع OpenAI.

LM Studio يشغّل خادمًا محليًا (Local Server) يعرض المسار
``POST {LM_STUDIO_BASE_URL}/chat/completions`` بصيغة OpenAI Chat Completions.
هذا المزود يستدعيه عبر HTTP فقط، ولا يحمّل أي مودل بنفسه ولا يفتح أي اتصال
خارج الجهاز.

**لا مفتاح API افتراضيًا:** الخادم محلي على 127.0.0.1 ولا يطلب هوية. يبقى
``LM_STUDIO_API_KEY`` اختياريًا لمن وضع وسيطًا (Proxy) أمام LM Studio يطلب
ترويسة ``Authorization``.

**استيراد httpx كسول** داخل الدالة على نهج ``oracle_provider``: المشروع يجب
أن يقلع ويعمل بـMODEL_PROVIDER=mock حتى على تثبيت لا يحوي الحزمة.

لا توجد أسرار في هذا الملف؛ كل الإعدادات تُقرأ من متغيرات البيئة.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..core.config import settings
from .base import (
    ChatMessage,
    ChatResult,
    ModelProvider,
    ModelProviderError,
    ensure_conversation,
)

logger = logging.getLogger(__name__)

#: مسار المحادثة داخل الواجهة المتوافقة مع OpenAI.
_CHAT_PATH = "chat/completions"

#: مهلة فتح الاتصال. أقصر بكثير من مهلة التوليد: خادم مغلق يُعرف في ثوانٍ،
#: أما التوليد على مودل محلي فقد يطول. min مع المهلة العامة حتى لا تتجاوزها
#: إذا ضبط المشغّل مهلة أقصر من عشر ثوانٍ.
_CONNECT_TIMEOUT_CAP = 10.0


@dataclass(frozen=True)
class _LmStudioConfig:
    """إعدادات المزود بعد التنظيف والتحقق."""

    base_url: str
    model: str
    api_key: str
    timeout: float
    max_tokens: int
    temperature: float

    @property
    def chat_url(self) -> str:
        return f"{self.base_url}/{_CHAT_PATH}"


class LMStudioModelProvider(ModelProvider):
    """يستدعي مودلًا محمّلًا في LM Studio على جهاز الجهة.

    الإعدادات: ``LM_STUDIO_BASE_URL`` و ``LM_STUDIO_MODEL`` و
    ``LM_STUDIO_TIMEOUT_SECONDS``، ولها جميعًا قيم افتراضية تعمل مباشرة على
    تثبيت LM Studio قياسي على ويندوز.

    كل فشل يتحوّل إلى ``ModelProviderError`` برسالة عربية صالحة للعرض على
    الموظف، وتفاصيل الفشل التقنية تُكتب في سجل التطبيق وحده.
    """

    name = "lmstudio"

    #: اسم المنتج كما يظهر **للمستخدم** في رسائل الخطأ.
    #: يبدّله المزوّد الوارث فلا يرى عميل GovMind اسم LM Studio إطلاقًا.
    PRODUCT_LABEL = "LM Studio"

    #: بادئة متغيّرات البيئة كما تُذكر للمشغّل في رسائل الإعداد.
    SETTINGS_PREFIX = "LM_STUDIO"

    def __init__(self, transport: Any = None) -> None:
        """Args:
        transport: ناقل httpx بديل — **للاختبارات وحدها**. يسمح باختبار
            المزود بـ``httpx.MockTransport`` بلا تشغيل LM Studio ولا أي
            اتصال شبكي. يبنيه المصنع دائمًا بلا وسيط، فالمسار الفعلي
            في التشغيل هو الناقل الافتراضي.
        """
        self._transport = transport

    @classmethod
    def _localize(cls, message: str) -> str:
        """يستبدل اسم المنتج وبادئة الإعدادات في رسالة موجّهة للمستخدم.

        **لماذا هنا لا في كل رسالة؟** الرسائل عشرون موضعًا، ونسيان واحد
        منها يعني أن عميل GovMind يقرأ «LM Studio» — وهو ما يجب ألا يراه
        بحال. المرور بنقطة واحدة يجعل النسيان مستحيلًا.

        في المزوّد الأصل هذا استبدالٌ محايد: القيمتان هما نفسهما.
        """
        if cls.PRODUCT_LABEL == "LM Studio" and cls.SETTINGS_PREFIX == "LM_STUDIO":
            return message
        return message.replace("LM Studio", cls.PRODUCT_LABEL).replace(
            "LM_STUDIO", cls.SETTINGS_PREFIX
        )

    def generate(
        self, messages: list[ChatMessage], system_prompt: str
    ) -> ChatResult:
        conversation = ensure_conversation(messages)
        try:
            config = self._read_settings()
            payload = self._build_payload(config, conversation, system_prompt)
            data = self._call_model(config, payload)
            reply = self._extract_reply(data)
        except ModelProviderError as exc:
            # كل رسالة تخرج من هنا تمرّ بنقطة الترجمة الواحدة.
            raise ModelProviderError(self._localize(str(exc))) from exc
        return ChatResult(reply=reply, provider=self.name)

    # ------------------------------------------------------------------
    # الإعدادات
    # ------------------------------------------------------------------
    @staticmethod
    def _read_settings() -> _LmStudioConfig:
        """يقرأ إعدادات LM Studio ويرفض الناقص برسالة تذكر المتغير الناقص.

        المفتاح ليس ضمن المطلوب: الخادم محلي، واشتراطه يمنع التشغيل الصحيح.
        """
        base_url = (settings.lm_studio_base_url or "").strip().rstrip("/")
        model = (settings.lm_studio_model or "").strip()

        missing = []
        if not base_url:
            missing.append("LM_STUDIO_BASE_URL")
        if not model:
            missing.append("LM_STUDIO_MODEL")
        if missing:
            raise ModelProviderError(
                "إعداد مزود LM Studio غير مكتمل، ولا يمكن الاتصال بالمودل "
                f"المحلي. المتغيرات الناقصة: {'، '.join(missing)}. "
                "اضبطها في ملف .env، أو استخدم MODEL_PROVIDER=mock للتشغيل "
                "بدون مودل حقيقي."
            )

        timeout = float(settings.lm_studio_timeout_seconds)
        if timeout <= 0:
            raise ModelProviderError(
                "قيمة LM_STUDIO_TIMEOUT_SECONDS يجب أن تكون أكبر من صفر. "
                "اضبطها في ملف .env (القيمة المقترحة: 120)."
            )

        return _LmStudioConfig(
            base_url=base_url,
            model=model,
            api_key=(settings.lm_studio_api_key or "").strip(),
            timeout=timeout,
            max_tokens=int(settings.lm_studio_max_tokens),
            temperature=float(settings.lm_studio_temperature),
        )

    # ------------------------------------------------------------------
    # بناء الطلب
    # ------------------------------------------------------------------
    @staticmethod
    def _build_payload(
        config: _LmStudioConfig,
        conversation: list[ChatMessage],
        system_prompt: str,
    ) -> dict[str, Any]:
        """يحوّل تعليمات النظام وسياق المحادثة إلى جسم طلب OpenAI Chat.

        تعليمات النظام أول رسالة بدور ``system``، ثم رسائل المحادثة
        بترتيبها الزمني وآخرها رسالة المستخدم الحالية. لا يُحذف شيء من
        السياق هنا: تقليمه — إن لزم — قرار طبقة أعلى.
        """
        api_messages: list[dict[str, str]] = []
        if system_prompt and system_prompt.strip():
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(
            {"role": message.role, "content": message.content}
            for message in conversation
        )
        return {
            "model": config.model,
            "messages": api_messages,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            # البث معطّل: الواجهة الحالية تعيد الرد كاملًا في استجابة واحدة.
            "stream": False,
        }

    # ------------------------------------------------------------------
    # الاستدعاء
    # ------------------------------------------------------------------
    @staticmethod
    def _import_httpx() -> Any:
        """يستورد httpx عند الحاجة فقط، لا عند إقلاع التطبيق."""
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - الحزمة مثبّتة دائمًا
            raise ModelProviderError(
                "حزمة httpx غير مثبّتة على هذا السيرفر، ولا يمكن الاتصال "
                "بـLM Studio. ثبّتها عبر: pip install httpx، أو استخدم "
                "MODEL_PROVIDER=mock للتشغيل بدون مودل حقيقي."
            ) from exc
        return httpx

    def _call_model(
        self, config: _LmStudioConfig, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """ينفّذ الطلب ويحوّل كل فشل إلى ``ModelProviderError`` بالعربية.

        التفاصيل التقنية (نوع الاستثناء، العنوان، رمز الحالة) تُكتب في سجل
        التطبيق ولا تصل إلى المستخدم: رد المزود يظهر كما هو في خطأ 503.
        """
        httpx = self._import_httpx()

        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        timeout = httpx.Timeout(
            config.timeout,
            connect=min(config.timeout, _CONNECT_TIMEOUT_CAP),
        )

        try:
            with httpx.Client(
                timeout=timeout, transport=self._transport
            ) as client:
                response = client.post(
                    config.chat_url, json=payload, headers=headers
                )
        except httpx.TimeoutException as exc:
            logger.warning(
                "انتهت مهلة الاتصال بـLM Studio: url=%s timeout=%s error=%s",
                config.chat_url,
                config.timeout,
                type(exc).__name__,
            )
            raise ModelProviderError(
                "انتهت مهلة انتظار الرد من المودل المحلي (LM Studio) قبل "
                "اكتمال الإجابة. جرّب سؤالًا أقصر، أو ارفع قيمة "
                "LM_STUDIO_TIMEOUT_SECONDS في ملف .env."
            ) from exc
        except httpx.HTTPError as exc:
            # يشمل ConnectError: الخادم مغلق أو العنوان غير صحيح.
            logger.warning(
                "تعذّر الاتصال بـLM Studio: url=%s error=%s",
                config.chat_url,
                type(exc).__name__,
            )
            raise ModelProviderError(
                "تعذّر الاتصال بالمودل المحلي (LM Studio). تأكد أن التطبيق "
                "يعمل وأن الخادم المحلي (Local Server) مشغَّل على العنوان "
                f"{config.base_url}، ثم أعد المحاولة."
            ) from exc

        return self._read_response(config, response)

    def _read_response(self, config: _LmStudioConfig, response: Any) -> dict[str, Any]:
        """يفحص رمز الحالة ثم يحوّل الجسم إلى JSON."""
        status = response.status_code
        if status >= 400:
            detail = self._error_detail(response)
            logger.warning(
                "رفض LM Studio الطلب: url=%s status=%s model=%s detail=%s",
                config.chat_url,
                status,
                config.model,
                detail,
            )
            if status in (401, 403):
                raise ModelProviderError(
                    "رفض المودل المحلي (LM Studio) الطلب لعدم وجود صلاحية. "
                    "إذا كان أمامه وسيط يطلب مفتاحًا فاضبط LM_STUDIO_API_KEY "
                    "في ملف .env."
                )
            if status == 404:
                raise ModelProviderError(
                    f"المودل «{config.model}» غير محمّل في LM Studio. افتح "
                    "التطبيق وحمّل المودل من تبويب Developer / Local Server، "
                    "أو صحّح قيمة LM_STUDIO_MODEL في ملف .env."
                )
            if status == 429:
                raise ModelProviderError(
                    "المودل المحلي (LM Studio) مشغول بطلبات أخرى حاليًا. "
                    "انتظر قليلًا ثم أعد المحاولة."
                )
            if self._looks_like_missing_model(detail):
                raise ModelProviderError(
                    f"المودل «{config.model}» غير محمّل في LM Studio. افتح "
                    "التطبيق وحمّل المودل من تبويب Developer / Local Server، "
                    "أو صحّح قيمة LM_STUDIO_MODEL في ملف .env."
                )
            raise ModelProviderError(
                "رفض المودل المحلي (LM Studio) الطلب ولم تكتمل الإجابة "
                f"(رمز {status}). راجع نافذة LM Studio، ثم أعد المحاولة."
            )

        try:
            data = response.json()
        except Exception as exc:  # noqa: BLE001 — أي فشل تحليل يعني ردًا تالفًا
            logger.warning(
                "رد غير قابل للتحليل من LM Studio: url=%s error=%s",
                config.chat_url,
                type(exc).__name__,
            )
            raise self._invalid_response() from exc

        if not isinstance(data, dict):
            logger.warning(
                "رد بصيغة غير متوقعة من LM Studio: url=%s type=%s",
                config.chat_url,
                type(data).__name__,
            )
            raise self._invalid_response()
        return data

    @staticmethod
    def _error_detail(response: Any) -> str:
        """يستخرج وصف الخطأ من جسم الرد **للسجل وحده**، لا للعرض."""
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 — الجسم قد لا يكون JSON أصلًا
            body = None
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error)
            if error:
                return str(error)
        text = getattr(response, "text", "") or ""
        return text[:300]

    @staticmethod
    def _looks_like_missing_model(detail: str) -> bool:
        """LM Studio يصف المودل غير المحمّل بصيغ مختلفة حسب الإصدار."""
        lowered = detail.lower()
        return "model_not_found" in lowered or (
            "model" in lowered and ("not found" in lowered or "not loaded" in lowered)
        )

    # ------------------------------------------------------------------
    # قراءة الرد
    # ------------------------------------------------------------------
    @staticmethod
    def _invalid_response() -> ModelProviderError:
        return ModelProviderError(
            "وصل رد غير صالح من المودل المحلي (LM Studio). تأكد أن المودل "
            "محمّل بالكامل في التطبيق، ثم أعد المحاولة."
        )

    @staticmethod
    def _truncated_before_answer() -> ModelProviderError:
        """سقف الرموز نفد قبل أن يكتب المودل حرفًا من الإجابة.

        يحدث مع مودلات الاستدلال (Reasoning): تستهلك جزءًا من السقف في تفكير
        داخلي لا يظهر للمستخدم، فسقفٌ منخفض يُنهي التوليد قبل بدء الإجابة.
        رسالة «رد غير صالح» العامة تضلّل هنا: المودل يعمل، والسقف هو المشكلة.
        """
        return ModelProviderError(
            "لم يكتمل الرد من المودل المحلي (LM Studio): انتهى الحد الأقصى "
            "لطول الإجابة قبل أن تبدأ. ارفع قيمة LM_STUDIO_MAX_TOKENS في ملف "
            ".env (وارفع معها LM_STUDIO_TIMEOUT_SECONDS)، ثم أعد المحاولة."
        )

    @classmethod
    def _extract_reply(cls, data: dict[str, Any]) -> str:
        """يستخرج نص الإجابة، ويرفض أي بنية ناقصة برسالة واضحة."""
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            logger.warning("رد LM Studio بلا choices: keys=%s", sorted(data))
            raise cls._invalid_response()

        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            finish_reason = (
                first.get("finish_reason") if isinstance(first, dict) else None
            )
            if finish_reason == "length":
                # التفاصيل في السجل: كم رمزًا ابتلعه الاستدلال قبل أن ينفد السقف.
                logger.warning(
                    "نفد سقف LM_STUDIO_MAX_TOKENS قبل بدء الإجابة: usage=%s",
                    data.get("usage"),
                )
                raise cls._truncated_before_answer()
            logger.warning("رد LM Studio بلا نص إجابة في أول choice.")
            raise cls._invalid_response()
        return content.strip()
