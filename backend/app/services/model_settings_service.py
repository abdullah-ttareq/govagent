"""مزود المودل لكل جهة.

الجهة تختار مزودها، ويُقرأ من القاعدة بدل متغير البيئة **إن وُجد**. غيابه
يعني العودة إلى ``MODEL_PROVIDER`` — فجهةٌ لم تختر شيئًا تعمل بالإعداد العام
كما كانت قبل هذه المهمة، ولا يتعطّل شيء بإضافة الميزة.

**لا مفاتيح ولا أسرار في القاعدة:** الجهة تختار **اسم** المزود فقط، وبيانات
اعتماد OCI تبقى في متغيرات البيئة على السيرفر — كما ينص تعليق جدول
``model_settings`` في المخطط.
"""

from __future__ import annotations

from ..ai import SUPPORTED_PROVIDERS
from ..core.config import settings
from .organization_settings_store import (
    ModelSettings,
    get_organization_settings_store,
)
from .user_store import User


class ModelSettingsError(Exception):
    """خطأ في إعدادات المودل، برسالة عربية صالحة للعرض."""


def resolve_provider_name(organization_id: int | None) -> str | None:
    """يعيد اسم المزود الذي يجب أن يجيب لهذه الجهة.

    ``None`` تعني «استخدم ``MODEL_PROVIDER``» — وهو ما يفعله
    ``get_model_provider(None)`` أصلًا، فلا حاجة إلى قراءة الإعداد العام هنا.

    فشل قراءة القاعدة **لا يُسقط المحادثة**: تعود ``None`` فيجيب المزود
    الافتراضي. مزود مُختار لا يمكن قراءته أهون من محادثة لا تعمل.
    """
    if organization_id is None:
        return None
    try:
        chosen = get_organization_settings_store().get_model_settings(
            organization_id
        )
    except Exception:  # noqa: BLE001 — العودة إلى الافتراضي خير من الفشل
        return None
    return chosen.provider if chosen else None


def read_model_settings(*, actor: User, organization_id: int) -> ModelSettings:
    """يقرأ إعدادات مودل جهة صاحب الطلب.

    الجهة التي لم تختر شيئًا تُعاد بمزودها **الفعلي** (قيمة ``MODEL_PROVIDER``)
    لا بحقل فارغ: الواجهة تعرض ما يجيب فعلًا لا ما سُجّل في صف.
    """
    stored = get_organization_settings_store().get_model_settings(organization_id)
    if stored is not None:
        return stored

    from datetime import UTC, datetime

    return ModelSettings(
        organization_id=organization_id,
        provider=(settings.model_provider or "mock").strip().lower(),
        updated_at=datetime.now(UTC),
    )


def update_model_settings(
    *, actor: User, organization_id: int, provider: str
) -> ModelSettings:
    """يثبّت مزود المودل لجهة صاحب الطلب.

    Raises:
        ModelSettingsError: إذا كان اسم المزود غير مدعوم.
    """
    chosen = provider.strip().lower()
    if chosen not in SUPPORTED_PROVIDERS:
        raise ModelSettingsError(
            f"مزود المودل «{chosen}» غير مدعوم. القيم المدعومة: "
            f"{'، '.join(SUPPORTED_PROVIDERS)}."
        )

    return get_organization_settings_store().set_model_settings(
        organization_id=organization_id, provider=chosen
    )
