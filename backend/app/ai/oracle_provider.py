"""مزود OCI Generative AI — غير منفذ بعد.

التنفيذ الفعلي مهمة AI-02 في docs/tasks/ai-oracle.md.
لا يوجد اتصال حقيقي ولا بيانات اعتماد في هذا الملف.
"""

from ..core.config import settings
from .base import ChatResult, ModelProvider, ModelProviderError


class OracleModelProvider(ModelProvider):
    """يستدعي مودلًا مستضافًا على OCI Generative AI.

    الإعدادات المطلوبة لاحقًا: OCI_REGION و OCI_COMPARTMENT_ID و OCI_MODEL_ID،
    إضافة إلى ملف بيانات اعتماد OCI على السيرفر (خارج المستودع).
    """

    name = "oracle"

    def generate(self, message: str, system_prompt: str) -> ChatResult:
        missing = [
            key
            for key, value in (
                ("OCI_REGION", settings.oci_region),
                ("OCI_COMPARTMENT_ID", settings.oci_compartment_id),
                ("OCI_MODEL_ID", settings.oci_model_id),
            )
            if not value
        ]
        raise ModelProviderError(
            "مزود Oracle غير منفذ بعد (مهمة AI-02). "
            + (f"الإعدادات الناقصة: {', '.join(missing)}. " if missing else "")
            + "استخدم MODEL_PROVIDER=mock للتشغيل المحلي."
        )
