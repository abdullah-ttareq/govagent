"""Schemas الاشتراك وإعدادات المودل وسجل التدقيق.

**لا يوجد هنا حقل ``organization_id`` في أي طلب.** الجهة تُشتق من رمز الدخول،
أو من المسار في عمليات التجهيز المحروسة بالمفتاح.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..ai import SUPPORTED_PROVIDERS
from .workspace import PageMeta

#: حدّ عمود audit_logs.action في المخطط. مكرّر هنا بدل استيراده من
#: `services.audit_store` عمدًا: اتجاه الاعتماد في المشروع
#: schemas ← services، وعكسه يصنع استيرادًا دائريًا.
MAX_ACTION_FILTER_LENGTH = 60


class SubscriptionOut(BaseModel):
    """اشتراك الجهة كما يُعاد للمسؤول."""

    organization_id: int = Field(..., description="معرّف الجهة")
    status: Literal["active", "expired", "suspended"] = Field(
        ..., description="active: فعّال | expired: منتهٍ | suspended: موقوف"
    )
    seats: int = Field(..., description="عدد التراخيص (المقاعد)")
    seats_used: int = Field(
        ..., description="المقاعد المستهلَكة = عدد المستخدمين النشطين"
    )
    seats_available: int = Field(
        ..., description="المقاعد الشاغرة، وصفر إن اكتملت"
    )
    starts_at: datetime = Field(..., description="بداية الاشتراك")
    expires_at: datetime = Field(..., description="نهاية الاشتراك")
    is_usable: bool = Field(
        ..., description="هل يسمح الاشتراك باستخدام الخدمة الآن؟"
    )
    blocked_reason: str | None = Field(
        None,
        description=(
            "سبب المنع بالعربية مع تاريخ الانتهاء، أو فارغ إن كان الاشتراك "
            "صالحًا"
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "organization_id": 1,
                "status": "active",
                "seats": 10,
                "seats_used": 3,
                "seats_available": 7,
                "starts_at": "2025-01-01T00:00:00Z",
                "expires_at": "2030-01-01T00:00:00Z",
                "is_usable": True,
                "blocked_reason": None,
            }
        }
    )


class SubscriptionUpdateRequest(BaseModel):
    """طلب تعديل اشتراك جهة. الحقول المتروكة فارغة لا تتغيّر.

    **يحرسه مفتاح التجهيز لا رمز الدخول:** تجديد الاشتراك وزيادة المقاعد قرار
    من يقدّم الخدمة لا من يستهلكها؛ لو مَلَكَه مسؤول الجهة لمنح نفسه مقاعد
    بلا حد ولمدّد اشتراكه بنفسه.
    """

    status: Literal["active", "expired", "suspended"] | None = Field(
        None, description="حالة الاشتراك الجديدة"
    )
    seats: int | None = Field(
        None, ge=1, description="عدد التراخيص الجديد، واحد على الأقل"
    )
    starts_at: datetime | None = Field(None, description="بداية جديدة")
    expires_at: datetime | None = Field(None, description="نهاية جديدة")


class ModelSettingsOut(BaseModel):
    """مزود المودل المفعّل للجهة."""

    organization_id: int = Field(..., description="معرّف الجهة")
    provider: str = Field(
        ...,
        description=(
            "المزود الذي يجيب لهذه الجهة فعلًا. الجهة التي لم تختر شيئًا "
            "تُعاد بقيمة MODEL_PROVIDER العامة"
        ),
    )
    updated_at: datetime = Field(..., description="لحظة آخر تغيير")


class ModelSettingsUpdateRequest(BaseModel):
    """طلب تغيير مزود مودل الجهة. لمسؤول الجهة.

    **اسم المزود فقط، بلا مفاتيح ولا أسرار** — بيانات اعتماد OCI تبقى في
    متغيرات البيئة على السيرفر، خارج القاعدة وخارج المستودع.
    """

    provider: str = Field(
        ...,
        max_length=20,
        description=f"القيم المدعومة: {'، '.join(SUPPORTED_PROVIDERS)}",
    )

    @field_validator("provider")
    @classmethod
    def clean_provider(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("اسم المزود لا يمكن أن يكون فارغًا")
        return cleaned


class AuditEventOut(BaseModel):
    """حدث واحد في سجل التدقيق."""

    id: int = Field(..., description="معرّف الحدث")
    action: str = Field(
        ...,
        description=(
            "نوع الحدث: login أو user_created أو user_disabled أو "
            "conversation_deleted أو file_uploaded أو file_deleted أو "
            "model_provider_changed أو subscription_changed أو "
            "organization_provisioned"
        ),
    )
    user_id: int | None = Field(
        None, description="صاحب الحدث، أو فارغ لحدث سبق وجود مستخدم"
    )
    details: str | None = Field(None, description="وصف قصير للعرض")
    created_at: datetime = Field(..., description="لحظة وقوع الحدث")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 87,
                "action": "file_uploaded",
                "user_id": 2,
                "details": "رفع الملف «لائحة-الإجازات.pdf»",
                "created_at": "2026-08-26T09:10:00Z",
            }
        }
    )


class AuditListResponse(BaseModel):
    """صفحة من سجل تدقيق الجهة، من الأحدث."""

    events: list[AuditEventOut] = Field(..., description="الأحداث")
    page: PageMeta = Field(..., description="بيانات الترقيم")
