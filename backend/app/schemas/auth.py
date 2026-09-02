"""Schemas الخاصة بالمصادقة.

**لا يوجد هنا حقل لكلمة المرور المُجزّأة ولا حقل ``organization_id`` في أي
طلب.** الجهة تُقرأ من التوكن دائمًا؛ لو قُبلت من جسم الطلب لأمكن لأي موظف أن
يدّعي جهة غيره.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.security import MAX_PASSWORD_BYTES


def validate_email_shape(value: str) -> str:
    """فحص شكلي خفيف للبريد.

    عمدًا **ليس** ``EmailStr``: مُحقِّقها يرفض النطاقات المحجوزة في RFC 2606
    (‎.test‎ و ‎.example‎ و ‎.invalid‎)، وهي بالضبط ما تستخدمه البيانات
    التجريبية لتفادي أي نطاق حقيقي. البريد هنا مفتاح بحث تحرسه كلمة المرور،
    والتحقق الصارم مكانه إنشاء المستخدم في P2-02.
    """
    cleaned = value.strip()
    local, separator, domain = cleaned.partition("@")
    if not separator or not local or "." not in domain or domain.startswith("."):
        raise ValueError("صيغة البريد الإلكتروني غير صحيحة")
    return cleaned


class LoginRequest(BaseModel):
    """طلب تسجيل الدخول."""

    email: str = Field(
        ..., max_length=200, description="البريد الإلكتروني للموظف"
    )
    password: str = Field(
        ...,
        # الحد بالحرف أوسع من حد bcrypt بالبايت، والفحص الدقيق في core/security.
        max_length=MAX_PASSWORD_BYTES,
        description="كلمة المرور",
    )
    # لا حقل للجهة هنا عمدًا: البريد هوية دخول فريدة على مستوى النظام
    # (فهرس uq_users_email_lower)، فلا حاجة إلى ما يميّز بين حسابين.

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "admin@digital-services.test",
                "password": "GovAgent@2026",
            }
        }
    )

    @field_validator("email")
    @classmethod
    def email_must_look_like_an_address(cls, value: str) -> str:
        return validate_email_shape(value)

    @field_validator("password")
    @classmethod
    def password_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("كلمة المرور لا يمكن أن تكون فارغة")
        # بلا strip على القيمة نفسها: الفراغ قد يكون جزءًا من كلمة المرور.
        return value


class UserOut(BaseModel):
    """بيانات المستخدم كما تُعاد للعميل.

    بلا ``password_hash`` ولا أي أثر لكلمة المرور.
    """

    id: int = Field(..., description="معرّف المستخدم")
    email: str = Field(..., description="البريد الإلكتروني")
    full_name: str = Field(..., description="الاسم الكامل")
    role: Literal["admin", "employee"] = Field(
        ..., description="admin: مسؤول الجهة | employee: موظف"
    )
    organization_id: int = Field(..., description="معرّف جهة المستخدم")
    organization_name: str | None = Field(
        None, description="اسم الجهة للعرض في الواجهة"
    )
    is_active: bool = Field(..., description="هل الحساب مفعّل؟")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 1,
                "email": "admin@digital-services.test",
                "full_name": "سارة العتيبي",
                "role": "admin",
                "organization_id": 1,
                "organization_name": "هيئة الخدمات الرقمية",
                "is_active": True,
            }
        }
    )


class TokenResponse(BaseModel):
    """رد تسجيل الدخول الناجح."""

    access_token: str = Field(
        ..., description="رمز الدخول. يُرسل في ترويسة: Authorization: Bearer <token>"
    )
    token_type: Literal["bearer"] = Field(
        "bearer", description="نوع الرمز، دائمًا bearer"
    )
    expires_in: int = Field(
        ..., description="المدة المتبقية لصلاحية الرمز بالثواني"
    )
    user: UserOut = Field(..., description="بيانات صاحب الرمز")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9…",
                "token_type": "bearer",
                "expires_in": 28800,
                "user": {
                    "id": 1,
                    "email": "admin@digital-services.test",
                    "full_name": "سارة العتيبي",
                    "role": "admin",
                    "organization_id": 1,
                    "organization_name": "هيئة الخدمات الرقمية",
                    "is_active": True,
                },
            }
        }
    )


class LogoutResponse(BaseModel):
    """رد تسجيل الخروج."""

    detail: str = Field(..., description="رسالة تأكيد للعرض في الواجهة")
