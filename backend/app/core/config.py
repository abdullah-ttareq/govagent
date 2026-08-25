"""إعدادات التطبيق — تُقرأ من متغيرات البيئة أو من ملف .env."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ModelProviderName = Literal["mock", "oracle", "local"]


class Settings(BaseSettings):
    """إعدادات GovAgent.

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

    # المتجهات (Embeddings) — mock يعمل محليًا بلا أي خدمة خارجية.
    embedding_provider: str = "mock"
    oci_embedding_model_id: str = ""
    embedding_dimensions: int = 1024

    # الملفات المرفوعة والتقطيع — أرقام، فلا تُوضع في .env.example.
    upload_max_bytes: int = 10 * 1024 * 1024  # 10 ميجابايت
    chunk_size: int = 1000
    chunk_overlap: int = 150

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
