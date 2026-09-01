"""إعدادات التطبيق — تُقرأ من متغيرات البيئة أو من ملف .env."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ModelProviderName = Literal["mock", "oracle", "lmstudio", "local"]


class Settings(BaseSettings):
    """إعدادات GovMind.

    القيم الافتراضية تجعل المشروع يعمل محليًا بدون أي بيانات اعتماد Oracle.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"

    # mock هو الافتراضي في بيئة التطوير.
    model_provider: str = "mock"

    # مخزن بيانات العمل (الجهات والمستخدمون ولاحقًا المحادثات والاشتراكات).
    # memory: مخزن داخل ذاكرة العملية للتطوير — غير دائم ويفرغ عند إعادة التشغيل.
    # oracle: جداول قاعدة Oracle (يحتاج ORACLE_* مضبوطة).
    data_store: str = "memory"

    # --- المصادقة و JWT -----------------------------------------------------
    # لا قيمة افتراضية للسر عمدًا: سر مكتوب في الكود يعني أن أي نسخة من
    # المستودع تستطيع تزوير توكن. الفارغ يُولَّد عشوائيًا في التطوير فقط،
    # ويُرفض الإقلاع عليه خارج التطوير. انظر core/security.py.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    #: مدة صلاحية التوكن بالدقائق — ٨ ساعات تغطي يوم عمل بلا إعادة دخول.
    jwt_expire_minutes: int = 480

    # كلمة مرور المستخدمين التجريبيين في مخزن الذاكرة فقط. حسابات وهمية على
    # نطاق ‎.test‎ ومخزن غير دائم، فليست سرًا. تُهمَل تمامًا مع DATA_STORE=oracle.
    dev_seed_password: str = "GovAgent@2026"

    # مفتاح تجهيز الجهات. إنشاء جهة جديدة عملية تركيب يقوم بها من ينشر النظام
    # على السيرفر، لا عملية داخل التطبيق: لا يوجد مستخدم بعد ليأذن بها. بلا
    # قيمة افتراضية للسبب نفسه في jwt_secret — انظر api/organizations.py.
    provisioning_key: str = ""

    # Oracle Database — فارغة افتراضيًا، والمشروع يعمل بالكامل بدونها.
    oracle_dsn: str = ""
    oracle_user: str = ""
    oracle_password: str = ""

    # ضبط الـConnection Pool — لا تُوضع في .env.example لأن تركها فارغة
    # يفشل الإقلاع. عدّلها فقط إن احتاج حمل الجهة ذلك.
    oracle_pool_min: int = 1
    oracle_pool_max: int = 5
    oracle_pool_idle_timeout: int = 300

    # OCI Generative AI — فارغة افتراضيًا حتى يعمل المشروع بـmock بلا إعداد.
    oci_region: str = ""
    oci_compartment_id: str = ""
    oci_model_id: str = ""

    # هوية OCI على السيرفر: ملف الإعداد (الافتراضي) أو Instance Principal.
    # القيم المقبولة لـoci_auth_type: config | instance_principal.
    oci_auth_type: str = "config"
    oci_config_file: str = ""
    oci_config_profile: str = "DEFAULT"

    # ضبط الاستدعاء — لا تُوضع في .env.example لأن تركها فارغة يفشل الإقلاع.
    oci_timeout_seconds: float = 60.0
    oci_max_tokens: int = 1500
    oci_temperature: float = 0.3

    # LM Studio — مودل محلي على جهاز الجهة بواجهة متوافقة مع OpenAI.
    # القيم الافتراضية تعمل مباشرة مع تثبيت LM Studio قياسي على ويندوز، فلا
    # يحتاج المشغّل إلى ضبط شيء غير MODEL_PROVIDER=lmstudio.
    # داخل Docker يصبح العنوان غالبًا: http://host.docker.internal:1234/v1
    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"
    lm_studio_model: str = "google/gemma-4-e4b"

    # **اختياري عمدًا:** الخادم محلي على 127.0.0.1 ولا يطلب هوية. يُملأ فقط
    # إن وُضع وسيط (Proxy) أمام LM Studio يشترط ترويسة Authorization.
    lm_studio_api_key: str = ""

    # ضبط الاستدعاء — **القيمتان أدناه مقيستان لا مقدَّرتان.**
    #
    # المهلة: التوليد المحلي أبطأ كثيرًا من خدمة سحابية. سؤال إداري متوسط
    # استغرق ٢٦٢ ثانية عبر المسار الكامل على جهاز اختبار، فمهلة ١٢٠ ثانية
    # تقطع إجابة سليمة في منتصفها. ٣٠٠ تترك هامشًا معقولًا.
    lm_studio_timeout_seconds: float = 300.0

    # سقف طول الإجابة. **١٥٠٠ لا ٥١٢:** مودلات الاستدلال (Reasoning) — ومنها
    # google/gemma-4-e4b — تستهلك مئات الرموز في تفكير داخلي **لا يظهر
    # للمستخدم** قبل أن تكتب حرفًا من الإجابة. قياس فعلي: ٥٠٩ رموز استدلال
    # قبل أول حرف، فالسقف ٥١٢ أعاد إجابة **فارغة**، و١٥٠٠ أعاد ردًا كاملًا.
    # خفضها يوفّر وقتًا على مودل غير استدلالي، ويكسر المحادثة على استدلالي.
    lm_studio_max_tokens: int = 1500
    lm_studio_temperature: float = 0.3

    # المتجهات (Embeddings) — mock يعمل محليًا بلا أي خدمة خارجية.
    embedding_provider: str = "mock"
    oci_embedding_model_id: str = ""
    embedding_dimensions: int = 1024

    # الملفات المرفوعة والتقطيع — أرقام، فلا تُوضع في .env.example.
    upload_max_bytes: int = 10 * 1024 * 1024  # 10 ميجابايت
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # مجلد حفظ الملفات المرفوعة على قرص السيرفر. نسبي إلى مجلد تشغيل
    # الخدمة، ومُدرَج في .gitignore. القاعدة تحفظ المسار لا محتوى الملف.
    upload_dir: str = "uploads"

    # الترقيم عند قراءة المحادثات والرسائل والملفات.
    page_size_default: int = 50
    page_size_max: int = 200

    # شروط اشتراك الجهة الجديدة عند تجهيزها. تُعدَّل بعدها عبر مسار
    # تحديث الاشتراك المحروس بمفتاح التجهيز.
    subscription_default_seats: int = 10
    subscription_default_days: int = 365

    # البحث المتجهي (RAG).
    # memory: مخزن محلي داخل الذاكرة يعمل بلا قاعدة بيانات — الافتراضي.
    # oracle: Oracle Vector Search فوق جدول document_chunks.
    retrieval_provider: str = "memory"
    retrieval_top_k: int = 4
    # أقل درجة تشابه يُقبل عندها المقطع. عتبة صغيرة تكفي لإسقاط المقاطع
    # عديمة الصلة (تشابه صفري) حتى لا تُذكر كمصدر لرد لا علاقة لها به.
    retrieval_min_score: float = 0.05
    # سقف طول السياق المُركَّب حتى لا يبتلع نافذة المودل.
    retrieval_context_chars: int = 4000


settings = Settings()
