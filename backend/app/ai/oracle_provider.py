"""مزود OCI Generative AI.

يبني طلب محادثة (Chat) على نموذج مستضاف في OCI Generative AI ويعيد نصّ الرد.

**استيراد حزمة `oci` كسول عمدًا** داخل الدوال، لا في أعلى الملف: المشروع
يجب أن يقلع ويعمل بالكامل بـMODEL_PROVIDER=mock دون تثبيت الحزمة إطلاقًا.
لا توجد أي بيانات اعتماد في هذا الملف؛ الهوية تُقرأ من ملف إعداد OCI على
السيرفر أو من Instance Principal.
"""

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

#: نقطة خدمة الاستدلال تختلف باختلاف المنطقة.
_ENDPOINT_TEMPLATE = "https://inference.generativeai.{region}.oci.oraclecloud.com"

_SUPPORTED_AUTH_TYPES = ("config", "instance_principal")


@dataclass(frozen=True)
class _OciSdk:
    """ما نحتاجه فعليًا من حزمة oci بعد الاستيراد الكسول."""

    root: Any
    client_class: Any
    models: Any


@dataclass(frozen=True)
class _OciConfig:
    """إعدادات المزود بعد التحقق من اكتمالها."""

    region: str
    compartment_id: str
    model_id: str


class OracleModelProvider(ModelProvider):
    """يستدعي مودلًا مستضافًا على OCI Generative AI.

    الإعدادات المطلوبة: OCI_REGION و OCI_COMPARTMENT_ID و OCI_MODEL_ID،
    إضافة إلى هوية OCI على السيرفر (ملف ~/.oci/config أو Instance Principal)،
    وكلاهما خارج المستودع.
    """

    name = "oracle"

    def generate(
        self, messages: list[ChatMessage], system_prompt: str
    ) -> ChatResult:
        conversation = ensure_conversation(messages)
        config = self._read_settings()
        sdk = self._import_sdk()
        client = self._build_client(sdk, config.region)
        details = self._build_chat_details(sdk, config, conversation, system_prompt)
        response = self._call_model(sdk, client, details)
        return ChatResult(reply=self._extract_reply(response), provider=self.name)

    # ------------------------------------------------------------------
    # الإعدادات
    # ------------------------------------------------------------------
    @staticmethod
    def _read_settings() -> _OciConfig:
        """يقرأ إعدادات OCI ويرفض الإعداد الناقص برسالة تذكر المتغير الناقص."""
        values = {
            "OCI_REGION": (settings.oci_region or "").strip(),
            "OCI_COMPARTMENT_ID": (settings.oci_compartment_id or "").strip(),
            "OCI_MODEL_ID": (settings.oci_model_id or "").strip(),
        }
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise ModelProviderError(
                "إعداد مزود Oracle غير مكتمل، ولا يمكن الاتصال بـOCI Generative AI. "
                f"المتغيرات الناقصة: {'، '.join(missing)}. "
                "اضبطها في ملف .env على السيرفر، أو استخدم MODEL_PROVIDER=mock "
                "للتشغيل بدون مودل حقيقي."
            )
        return _OciConfig(
            region=values["OCI_REGION"],
            compartment_id=values["OCI_COMPARTMENT_ID"],
            model_id=values["OCI_MODEL_ID"],
        )

    # ------------------------------------------------------------------
    # الاستيراد الكسول وبناء العميل
    # ------------------------------------------------------------------
    @staticmethod
    def _import_sdk() -> _OciSdk:
        """يستورد حزمة oci عند الحاجة فقط.

        الاستيراد هنا وليس في أعلى الملف حتى يبقى المشروع صالحًا للتشغيل
        بـmock على جهاز لا تُثبَّت فيه الحزمة.
        """
        try:
            import oci
            from oci.generative_ai_inference import GenerativeAiInferenceClient
            from oci.generative_ai_inference import models as genai_models
        except ImportError as exc:
            raise ModelProviderError(
                "حزمة oci غير مثبّتة على هذا السيرفر، ولا يمكن الاتصال "
                "بـOCI Generative AI. ثبّتها عبر: pip install oci، أو استخدم "
                "MODEL_PROVIDER=mock للتشغيل بدون مودل حقيقي."
            ) from exc
        return _OciSdk(
            root=oci,
            client_class=GenerativeAiInferenceClient,
            models=genai_models,
        )

    @staticmethod
    def _build_signer_or_config(sdk: _OciSdk) -> tuple[Any, Any]:
        """يجهّز هوية OCI: ملف الإعداد (افتراضيًا) أو Instance Principal."""
        auth_type = (settings.oci_auth_type or "config").strip().lower()
        if auth_type not in _SUPPORTED_AUTH_TYPES:
            supported = "، ".join(_SUPPORTED_AUTH_TYPES)
            raise ModelProviderError(
                f"OCI_AUTH_TYPE='{auth_type}' غير مدعوم. القيم المدعومة: {supported}."
            )

        if auth_type == "instance_principal":
            try:
                signer = sdk.root.auth.signers.InstancePrincipalsSecurityTokenSigner()
            except Exception as exc:
                raise ModelProviderError(
                    "تعذّر إنشاء هوية Instance Principal لهذا السيرفر. "
                    "تأكد أن السيرفر داخل OCI وأن سياسات Dynamic Group تسمح له "
                    "باستخدام خدمة Generative AI."
                ) from exc
            return {"region": (settings.oci_region or "").strip()}, signer

        config_file = (settings.oci_config_file or "").strip()
        profile = (settings.oci_config_profile or "DEFAULT").strip()
        try:
            if config_file:
                config = sdk.root.config.from_file(
                    file_location=config_file, profile_name=profile
                )
            else:
                config = sdk.root.config.from_file(profile_name=profile)
        except Exception as exc:
            shown_file = config_file or "~/.oci/config"
            raise ModelProviderError(
                "تعذّرت قراءة ملف هوية OCI على السيرفر "
                f"(الملف: {shown_file}، البروفايل: {profile}). "
                "تأكد من وجود الملف وصحة مفتاح الـAPI، أو اضبط "
                "OCI_AUTH_TYPE=instance_principal إذا كان السيرفر داخل OCI."
            ) from exc
        return config, None

    @classmethod
    def _build_client(cls, sdk: _OciSdk, region: str) -> Any:
        """ينشئ عميل الاستدلال بمهلة صريحة ومن دون إعادة محاولة طويلة."""
        config, signer = cls._build_signer_or_config(sdk)
        timeout = float(settings.oci_timeout_seconds)
        kwargs: dict[str, Any] = {
            "config": config,
            "service_endpoint": _ENDPOINT_TEMPLATE.format(region=region),
            # (مهلة الاتصال، مهلة القراءة) — تمنع تعليق الطلب إلى ما لا نهاية.
            "timeout": (min(timeout, 10.0), timeout),
            "retry_strategy": sdk.root.retry.NoneRetryStrategy(),
        }
        if signer is not None:
            kwargs["signer"] = signer
        try:
            return sdk.client_class(**kwargs)
        except Exception as exc:
            raise ModelProviderError(
                "تعذّر تهيئة الاتصال بخدمة OCI Generative AI. تأكد من صحة "
                f"OCI_REGION='{region}' ومن إعداد هوية OCI على السيرفر."
            ) from exc

    # ------------------------------------------------------------------
    # بناء الطلب
    # ------------------------------------------------------------------
    @staticmethod
    def _build_chat_details(
        sdk: _OciSdk,
        config: _OciConfig,
        conversation: list[ChatMessage],
        system_prompt: str,
    ) -> Any:
        """يحوّل سياق المحادثة إلى طلب Chat بصيغة OCI Generic."""
        models = sdk.models

        try:
            sdk_messages: list[Any] = []
            if system_prompt and system_prompt.strip():
                sdk_messages.append(
                    models.SystemMessage(
                        content=[models.TextContent(text=system_prompt)]
                    )
                )
            for message in conversation:
                message_class = (
                    models.UserMessage
                    if message.role == "user"
                    else models.AssistantMessage
                )
                sdk_messages.append(
                    message_class(content=[models.TextContent(text=message.content)])
                )

            chat_request = models.GenericChatRequest(
                api_format=models.BaseChatRequest.API_FORMAT_GENERIC,
                messages=sdk_messages,
                max_tokens=int(settings.oci_max_tokens),
                temperature=float(settings.oci_temperature),
                is_stream=False,
            )
            return models.ChatDetails(
                compartment_id=config.compartment_id,
                serving_mode=models.OnDemandServingMode(model_id=config.model_id),
                chat_request=chat_request,
            )
        except Exception as exc:
            raise ModelProviderError(
                "تعذّر بناء طلب المحادثة لخدمة OCI Generative AI. "
                "تأكد من صحة OCI_MODEL_ID ومن تحديث حزمة oci على السيرفر."
            ) from exc

    # ------------------------------------------------------------------
    # الاستدعاء وقراءة الرد
    # ------------------------------------------------------------------
    @staticmethod
    def _call_model(sdk: _OciSdk, client: Any, details: Any) -> Any:
        """ينفّذ الطلب ويحوّل كل فشل إلى ModelProviderError برسالة عربية."""
        try:
            return client.chat(details)
        except sdk.root.exceptions.ServiceError as exc:
            status = getattr(exc, "status", "غير معروف")
            message = getattr(exc, "message", "") or "بدون تفاصيل"
            if status in (401, 403):
                raise ModelProviderError(
                    "رفضت خدمة OCI Generative AI الطلب لعدم وجود صلاحية "
                    f"(رمز {status}). راجع صلاحيات المستخدم أو Dynamic Group "
                    "على الـCompartment المحدد في OCI_COMPARTMENT_ID."
                ) from exc
            if status == 404:
                raise ModelProviderError(
                    "لم تجد خدمة OCI Generative AI المودل المطلوب "
                    f"(رمز {status}). راجع قيمة OCI_MODEL_ID وتأكد أنه متاح في "
                    "المنطقة المحددة في OCI_REGION."
                ) from exc
            if status == 429:
                raise ModelProviderError(
                    "تم تجاوز الحد المسموح من الطلبات لخدمة OCI Generative AI "
                    "حاليًا. انتظر قليلًا ثم أعد المحاولة."
                ) from exc
            raise ModelProviderError(
                f"رفضت خدمة OCI Generative AI الطلب (رمز {status}): {message}"
            ) from exc
        except Exception as exc:
            if "timeout" in type(exc).__name__.lower():
                raise ModelProviderError(
                    "انتهت مهلة الاتصال بخدمة OCI Generative AI قبل وصول الرد. "
                    "أعد المحاولة، وإذا تكرر الأمر فراجع اتصال السيرفر بالشبكة."
                ) from exc
            raise ModelProviderError(
                "تعذّر الاتصال بخدمة OCI Generative AI. تأكد من اتصال السيرفر "
                "بالشبكة ومن صحة OCI_REGION."
            ) from exc

    @staticmethod
    def _extract_reply(response: Any) -> str:
        """يستخرج نص الرد، ويرفض أي بنية غير متوقعة برسالة واضحة."""

        def invalid() -> ModelProviderError:
            return ModelProviderError(
                "وصل رد غير صالح من خدمة OCI Generative AI (بنية غير متوقعة). "
                "أعد المحاولة، وإذا تكرر الأمر فراجع قيمة OCI_MODEL_ID."
            )

        chat_response = getattr(getattr(response, "data", None), "chat_response", None)
        choices = getattr(chat_response, "choices", None) or []
        if not choices:
            raise invalid()

        parts = getattr(getattr(choices[0], "message", None), "content", None) or []
        texts = [
            part.text.strip()
            for part in parts
            if isinstance(getattr(part, "text", None), str) and part.text.strip()
        ]
        if not texts:
            raise invalid()
        return "\n".join(texts)
