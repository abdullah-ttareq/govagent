"""توليد المتجهات (Embeddings) لمقاطع المستندات.

نفس مبدأ مزود المحادثة: واجهة واحدة، ومزود تجريبي يعمل محليًا بلا أي خدمة
خارجية، ومزود Oracle يستدعي OCI Generative AI باستيراد كسول لحزمة `oci`.

المزود التجريبي **ليس عشوائيًا**: يبني المتجه من كلمات النص عبر تجزئة ثابتة،
فالنص نفسه يعطي المتجه نفسه دائمًا، والنصوص المتشابهة تعطي متجهات متقاربة.
هذا يكفي لتطوير البحث المتجهي واختباره في P1-04 قبل توفّر Oracle.
"""

import hashlib
import math
import re
from abc import ABC, abstractmethod

from ..core.config import settings
from .base import ModelProviderError

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

#: أقصى عدد نصوص في طلب واحد إلى OCI. الخدمة ترفض الدفعات الكبيرة.
_OCI_BATCH_SIZE = 96


class EmbeddingProvider(ABC):
    """واجهة مشتركة لكل مزود متجهات."""

    name: str = "base"

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """عدد أبعاد المتجه الناتج."""
        raise NotImplementedError

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """يحوّل قائمة نصوص إلى قائمة متجهات بالترتيب نفسه.

        Raises:
            ModelProviderError: إذا فشل التوليد.
        """
        raise NotImplementedError


def _normalize_vector(vector: list[float]) -> list[float]:
    """يجعل طول المتجه واحدًا حتى تصبح المسافة الجيبية قابلة للمقارنة."""
    length = math.sqrt(sum(value * value for value in vector))
    if length == 0:
        return vector
    return [value / length for value in vector]


class MockEmbeddingProvider(EmbeddingProvider):
    """متجهات محلية ثابتة، بلا أي خدمة خارجية.

    الطريقة: كل كلمة تُجزَّأ بـSHA-256 وتُسقَط على خانة من خانات المتجه. النص
    نفسه يعطي المتجه نفسه، والنصوص التي تشترك في كلمات تعطي متجهات متقاربة.
    ليست بديلًا عن مودل حقيقي، لكنها تكفي لتشغيل المشروع واختباره بلا Oracle.
    """

    name = "mock"

    def __init__(self, dimensions: int | None = None) -> None:
        self._dimensions = dimensions or settings.embedding_dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        words = _WORD.findall(text.lower())
        if not words:
            # نص بلا كلمات (أرقام أو رموز فقط): متجه ثابت غير صفري.
            words = [text.strip() or "فارغ"]

        for word in words:
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimensions
            # البايت الخامس يحدد الإشارة، فلا تتراكم كل الكلمات في اتجاه واحد.
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        return _normalize_vector(vector)


class OracleEmbeddingProvider(EmbeddingProvider):
    """يستدعي مودل Embedding مستضافًا على OCI Generative AI.

    الإعدادات المطلوبة: OCI_REGION و OCI_COMPARTMENT_ID و
    OCI_EMBEDDING_MODEL_ID، إضافة إلى هوية OCI على السيرفر.
    """

    name = "oracle"

    @property
    def dimensions(self) -> int:
        return settings.embedding_dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        region, compartment_id, model_id = self._read_settings()
        # يُعاد استخدام منطق الاستيراد الكسول وبناء العميل من مزود المحادثة.
        from .oracle_provider import OracleModelProvider

        sdk = OracleModelProvider._import_sdk()
        client = OracleModelProvider._build_client(sdk, region)
        models = sdk.models

        vectors: list[list[float]] = []
        for start in range(0, len(texts), _OCI_BATCH_SIZE):
            batch = texts[start : start + _OCI_BATCH_SIZE]
            details = models.EmbedTextDetails(
                compartment_id=compartment_id,
                serving_mode=models.OnDemandServingMode(model_id=model_id),
                inputs=batch,
                truncate="END",
            )
            vectors.extend(self._call(sdk, client, details, expected=len(batch)))
        return vectors

    @staticmethod
    def _read_settings() -> tuple[str, str, str]:
        values = {
            "OCI_REGION": (settings.oci_region or "").strip(),
            "OCI_COMPARTMENT_ID": (settings.oci_compartment_id or "").strip(),
            "OCI_EMBEDDING_MODEL_ID": (settings.oci_embedding_model_id or "").strip(),
        }
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise ModelProviderError(
                "إعداد مزود المتجهات غير مكتمل، ولا يمكن توليد Embeddings. "
                f"المتغيرات الناقصة: {'، '.join(missing)}. "
                "اضبطها في ملف .env، أو استخدم EMBEDDING_PROVIDER=mock."
            )
        return (
            values["OCI_REGION"],
            values["OCI_COMPARTMENT_ID"],
            values["OCI_EMBEDDING_MODEL_ID"],
        )

    @staticmethod
    def _call(sdk, client, details, expected: int) -> list[list[float]]:
        try:
            response = client.embed_text(details)
        except sdk.root.exceptions.ServiceError as exc:
            status = getattr(exc, "status", "غير معروف")
            raise ModelProviderError(
                f"رفضت خدمة OCI Generative AI طلب المتجهات (رمز {status}). "
                "راجع OCI_EMBEDDING_MODEL_ID وصلاحيات الـCompartment."
            ) from exc
        except Exception as exc:
            if "timeout" in type(exc).__name__.lower():
                raise ModelProviderError(
                    "انتهت مهلة توليد المتجهات من OCI Generative AI. أعد المحاولة."
                ) from exc
            raise ModelProviderError(
                "تعذّر الاتصال بخدمة OCI Generative AI لتوليد المتجهات. "
                "تأكد من اتصال السيرفر بالشبكة ومن صحة OCI_REGION."
            ) from exc

        embeddings = getattr(getattr(response, "data", None), "embeddings", None)
        if not embeddings or len(embeddings) != expected:
            raise ModelProviderError(
                "وصل رد غير صالح من خدمة المتجهات (عدد المتجهات لا يطابق عدد "
                "المقاطع المرسلة). أعد المحاولة."
            )
        return [list(vector) for vector in embeddings]


_EMBEDDING_PROVIDERS: dict[str, type[EmbeddingProvider]] = {
    "mock": MockEmbeddingProvider,
    "oracle": OracleEmbeddingProvider,
}

#: القيم المقبولة لـEMBEDDING_PROVIDER.
SUPPORTED_EMBEDDING_PROVIDERS: tuple[str, ...] = tuple(sorted(_EMBEDDING_PROVIDERS))


def get_embedding_provider(name: str | None = None) -> EmbeddingProvider:
    """يعيد مزود المتجهات المطلوب.

    Raises:
        ModelProviderError: إذا كان الاسم غير مدعوم.
    """
    provider_name = (name or settings.embedding_provider or "mock").strip().lower()
    provider_class = _EMBEDDING_PROVIDERS.get(provider_name)
    if provider_class is None:
        supported = "، ".join(SUPPORTED_EMBEDDING_PROVIDERS)
        raise ModelProviderError(
            f"EMBEDDING_PROVIDER='{provider_name}' غير مدعوم. "
            f"القيم المدعومة: {supported}."
        )
    return provider_class()
