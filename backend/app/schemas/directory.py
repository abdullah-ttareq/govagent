"""Schemas الجهات والمستخدمين.

**لا يوجد حقل ``organization_id`` في أي طلب هنا، ولا في أي مكان آخر.** الجهة
تُشتق من التوكن وحده؛ لو قُبلت من جسم الطلب لأمكن لأي موظف أن يقرأ أو يكتب في
جهة غيره بتغيير رقم واحد. هذا الغياب مقصود، لا سهو.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.security import MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH
from .auth import UserOut, validate_email_shape

#: المعرّف النصي يظهر في الروابط وفي تسجيل الدخول: حروف لاتينية صغيرة وأرقام
#: وشرطات فقط، ولا يبدأ أو ينتهي بشرطة.
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_SLUG_DESCRIPTION = (
    "معرّف نصي قصير يظهر في الروابط، مثل: ministry-x. "
    "حروف إنجليزية صغيرة وأرقام وشرطات فقط"
)


def _validate_slug(value: str) -> str:
    cleaned = value.strip().lower()
    if not SLUG_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "المعرّف النصي يقبل الحروف الإنجليزية الصغيرة والأرقام والشرطات "
            "فقط، ولا يبدأ أو ينتهي بشرطة"
        )
    return cleaned


def _validate_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("الاسم لا يمكن أن يكون فارغًا")
    return cleaned


class OrganizationOut(BaseModel):
    """بيانات الجهة كما تُعاد للعميل."""

    id: int = Field(..., description="معرّف الجهة")
    name: str = Field(..., description="اسم الجهة")
    slug: str = Field(..., description="المعرّف النصي للجهة")
    is_active: bool = Field(..., description="هل الجهة مفعّلة في النظام؟")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 1,
                "name": "هيئة الخدمات الرقمية",
                "slug": "digital-services",
                "is_active": True,
            }
        }
    )


class OrganizationCreateRequest(BaseModel):
    """طلب تجهيز جهة جديدة مع مسؤولها الأول.

    المسؤول جزء من الطلب لا خطوة تالية: جهة بلا مسؤول لا يمكن الدخول إليها.
    """

    name: str = Field(..., max_length=200, description="اسم الجهة")
    slug: str = Field(..., max_length=60, description=_SLUG_DESCRIPTION)
    admin_email: str = Field(
        ..., max_length=200, description="بريد مسؤول الجهة الأول"
    )
    admin_full_name: str = Field(
        ..., max_length=200, description="الاسم الكامل للمسؤول"
    )
    admin_password: str = Field(
        ...,
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_BYTES,
        description=f"كلمة مرور المسؤول، {MIN_PASSWORD_LENGTH} أحرف فأكثر",
    )

    @field_validator("name", "admin_full_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return _validate_name(value)

    @field_validator("slug")
    @classmethod
    def clean_slug(cls, value: str) -> str:
        return _validate_slug(value)

    @field_validator("admin_email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return validate_email_shape(value)


class OrganizationUpdateRequest(BaseModel):
    """طلب تعديل بيانات الجهة. الحقول المتروكة فارغة لا تتغيّر.

    ``is_active`` غير قابلة للتعديل هنا: تعطيل الجهة من داخلها يقفل الباب على
    كل موظفيها بلا طريق للعودة.
    """

    name: str | None = Field(None, max_length=200, description="اسم الجهة الجديد")
    slug: str | None = Field(None, max_length=60, description=_SLUG_DESCRIPTION)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return None if value is None else _validate_name(value)

    @field_validator("slug")
    @classmethod
    def clean_slug(cls, value: str | None) -> str | None:
        return None if value is None else _validate_slug(value)


class UserCreateRequest(BaseModel):
    """طلب إضافة موظف. يُنشأ في جهة صاحب الطلب دائمًا."""

    email: str = Field(..., max_length=200, description="البريد الإلكتروني للموظف")
    full_name: str = Field(..., max_length=200, description="الاسم الكامل")
    role: Literal["admin", "employee"] = Field(
        "employee", description="admin: مسؤول الجهة | employee: موظف"
    )
    password: str = Field(
        ...,
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_BYTES,
        description=f"كلمة المرور الأولى، {MIN_PASSWORD_LENGTH} أحرف فأكثر",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "n.alharbi@digital-services.test",
                "full_name": "نورة الحربي",
                "role": "employee",
                "password": "Employee@2026",
            }
        }
    )

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return validate_email_shape(value)

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return _validate_name(value)


class UserUpdateRequest(BaseModel):
    """طلب تعديل موظف. الحقول المتروكة فارغة لا تتغيّر.

    البريد غير قابل للتعديل: هو هوية الدخول ومرجع سجل التدقيق. تغييره يتم
    بتعطيل الحساب وإنشاء غيره.

    ``role`` و ``is_active`` لمسؤول الجهة فقط، ولا يغيّرهما المسؤول على نفسه.
    """

    full_name: str | None = Field(None, max_length=200, description="الاسم الكامل")
    role: Literal["admin", "employee"] | None = Field(
        None, description="لمسؤول الجهة فقط"
    )
    is_active: bool | None = Field(None, description="لمسؤول الجهة فقط")
    password: str | None = Field(
        None,
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_BYTES,
        description="كلمة مرور جديدة",
    )

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return None if value is None else _validate_name(value)


class OrganizationCreatedResponse(BaseModel):
    """رد تجهيز جهة جديدة."""

    organization: OrganizationOut = Field(..., description="الجهة المُنشأة")
    admin: UserOut = Field(..., description="مسؤول الجهة الأول")


class UserListResponse(BaseModel):
    """قائمة موظفي الجهة."""

    users: list[UserOut] = Field(..., description="الموظفون مرتبين بالمعرّف")
    total: int = Field(..., description="عدد الموظفين في الجهة")
