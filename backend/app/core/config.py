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

    # Oracle Database — فارغة في الـMVP، تُملأ في مهمة AI-04.
    oracle_dsn: str = ""
    oracle_user: str = ""
    oracle_password: str = ""

    # OCI Generative AI — فارغة في الـMVP، تُملأ في مهمة AI-02.
    oci_region: str = ""
    oci_compartment_id: str = ""
    oci_model_id: str = ""


settings = Settings()
