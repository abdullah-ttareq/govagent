"""إعداد مشترك لكل اختبارات الـBackend.

**مزود المودل مثبّت على ``mock`` طوال الجلسة، مهما كانت قيمة ``MODEL_PROVIDER``
في ملف ‎.env‎ على جهاز المطوّر.**

بلا هذا التثبيت يقرأ ``Settings`` ملف ‎.env‎ المحلي، فمطوّرٌ يشغّل الاختبارات
وهو ضابط ``MODEL_PROVIDER=lmstudio`` يجعل **كل** اختبار يمر بمسار المحادثة
يستدعي مودلًا حقيقيًا: دقائق لكل اختبار، ونتيجة تتغيّر بتغيّر جهاز المشغّل
وحالة الخادم المحلي. اختبارات المشروع يجب أن تكون محسومة ومعزولة عن أي خدمة
خارجية، وأن تمر على جهاز لا يوجد فيه LM Studio ولا Oracle أصلًا.

الاختبار الذي يريد مزودًا بعينه يستبدله بـ``monkeypatch`` داخله — وهو أضيق
نطاقًا (دالة واحدة) فيغلب هذا التثبيت ويُستعاد بعده تلقائيًا.
"""

import pytest

from app.core.config import settings


#: إعدادات تُصفَّر طوال جلسة الاختبار.
#
# **الخطر الذي تمنعه:** ملف ‎.env‎ على جهاز المطوّر قد يحمل بيانات مشروع
# Supabase حقيقي ومفاتيح Azure حقيقية. اختبارٌ يقرأها قد يكتب في قاعدة
# إنتاج أو يوقّع رابطًا حقيقيًا — وهو أسوأ من اختبار يفشل.
#
# الاختبار الذي يحتاج قيمة يضبطها بـ`monkeypatch` داخله، وهو أضيق نطاقًا
# فيغلب هذا التصفير ويُستعاد بعده تلقائيًا.
_NEUTRALIZED_SETTINGS: tuple[str, ...] = (
    "supabase_url",
    "supabase_anon_key",
    "supabase_service_role_key",
    "supabase_jwt_secret",
    "device_hash_pepper",
    "azure_storage_account",
    "azure_storage_container",
    "azure_storage_connection_string",
    "azure_installer_blob_name",
    "azure_model_blob_name",
    "azure_model_sha256",
    "azure_storage_blob_name",
)


@pytest.fixture(autouse=True, scope="session")
def isolate_from_developer_environment() -> None:
    """يعزل الاختبارات عن كل خدمة خارجية طوال الجلسة.

    **مزود المودل** مثبّت على ``mock``: مطوّرٌ يضبط ``MODEL_PROVIDER=lmstudio``
    كان كل اختبار محادثة عنده يستدعي مودلًا حقيقيًا — دقائق لكل اختبار،
    ونتيجة تتغيّر بتغيّر جهاز المشغّل.

    **مخزن البيانات** مثبّت على ``memory``: الاختبارات مبنية على الجهات
    التجريبية المزروعة فيه. مطوّرٌ يضبط ``DATA_STORE=supabase`` كانت تفشل
    عنده عشرات الاختبارات لسبب لا علاقة له بشيفرته — وأخطر من ذلك أن
    اختبارًا قد يكتب في مشروعه الحقيقي.

    **بيانات الاعتماد** تُفرَّغ للسبب نفسه.
    """
    settings.model_provider = "mock"
    settings.data_store = "memory"
    settings.azure_model_size_bytes = 0

    for name in _NEUTRALIZED_SETTINGS:
        setattr(settings, name, "")
