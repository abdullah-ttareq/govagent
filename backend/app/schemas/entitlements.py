"""Schemas الحساب والاشتراك وتفعيل الجهاز وتحميل المثبّت.

**لا يوجد هنا حقل `organization_id` في أي طلب**، ولا حقل لرابط سيرفر ولا
لمفتاح: الجهة تُشتق من رمز الدخول، وعنوان الـBackend مثبَّت في الإضافة وقت
البناء، وعنوان Azure لا يعرفه العميل أصلًا.

⚠️ **`device_id_hash` لا يظهر في أي نموذج رد هنا.** التجزئة تُقارن على
السيرفر وحده؛ من يعرفها يستطيع انتحال الجهاز أمام أي فحص يقارنها.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: طول البصمة الخام المقبول من العميل. الحد الأعلى يمنع جسمًا ضخمًا.
MIN_DEVICE_ID = 8
MAX_DEVICE_ID = 512


class AccountLoginRequest(BaseModel):
    """تسجيل الدخول عبر Supabase Auth. **لا حقل لرابط سيرفر ولا لمفتاح.**"""

    email: str = Field(..., min_length=3, max_length=200, description="البريد")
    password: str = Field(..., min_length=1, max_length=200)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"email": "user@example.gov.sa", "password": "••••••••"}
        }
    )


class AccountOut(BaseModel):
    """صاحب الحساب كما يُعرض في الإضافة."""

    email: str
    full_name: str
    role: Literal["admin", "employee"]
    organization_id: int


class AccountSessionResponse(BaseModel):
    """جلسة Supabase بعد دخول ناجح.

    `access_token` يُحفظ في `chrome.storage.local` ويُرسل في كل طلب لاحق.
    لا يُحفظ في `localStorage` ولا يمرّ على أي صفحة ويب.
    """

    access_token: str
    refresh_token: str
    #: العمر بالثواني كما أعادته Supabase.
    expires_in: int
    account: AccountOut | None = Field(
        None,
        description=(
            "ملف العمل، أو فارغ إن لم يُربط الحساب بجهة بعد — عندها تعرض "
            "الإضافة رسالة «راجع مسؤول النظام» بدل متابعة التهيئة"
        ),
    )


class ActiveDeviceOut(BaseModel):
    """الجهاز المفعّل كما يُعرض. **بلا تجزئة ولا بصمة.**"""

    id: int
    device_name: str
    activated_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None = None
    is_current_device: bool = Field(
        ...,
        description="هل الجهاز المفعّل هو الجهاز الذي أرسل هذا الطلب؟",
    )


class SubscriptionStatusResponse(BaseModel):
    """حالة الاشتراك والجهاز — المصدر الوحيد الذي تبني عليه الإضافة شاشتها."""

    status: Literal["trial", "active", "expired", "suspended", "cancelled"]
    seats: int
    starts_at: datetime
    expires_at: datetime
    is_usable: bool = Field(
        ..., description="هل يسمح الاشتراك باستخدام الخدمة الآن؟"
    )
    blocked_reason: str | None = Field(
        None, description="سبب المنع بالعربية، أو فارغ إن كان صالحًا"
    )
    device: ActiveDeviceOut | None = Field(
        None, description="الجهاز المفعّل، أو فارغ إن لم يُفعَّل جهاز بعد"
    )
    requires_activation: bool = Field(
        ...,
        description=(
            "هل على المستخدم تفعيل هذا الجهاز؟ صحيح إن لم يُفعَّل جهاز، أو "
            "إن كان المفعّل جهازًا آخر"
        ),
    )


class DeviceActivateRequest(BaseModel):
    """تفعيل الجهاز الحالي.

    `device_id` بصمة يولّدها العميل. **تُجزَّأ على السيرفر فور وصولها ولا
    تُخزَّن ولا تُسجَّل خامًا في أي مكان.**
    """

    device_id: str = Field(..., min_length=MIN_DEVICE_ID, max_length=MAX_DEVICE_ID)
    device_name: str = Field(
        "جهاز غير مسمّى",
        max_length=120,
        description="اسم وصفي يميّز الجهاز في قائمة المسؤول",
    )


class DeviceVerifyRequest(BaseModel):
    """التحقق من أن هذا الجهاز هو المفعّل."""

    device_id: str = Field(..., min_length=MIN_DEVICE_ID, max_length=MAX_DEVICE_ID)


class DeviceListResponse(BaseModel):
    """سجل أجهزة الاشتراك — الفعّال والمبطل — لمسؤول الجهة."""

    devices: list[ActiveDeviceOut]


class InstallerDownloadRequest(BaseModel):
    """طلب رابط تحميل المثبّت من الجهاز المفعّل."""

    device_id: str = Field(..., min_length=MIN_DEVICE_ID, max_length=MAX_DEVICE_ID)


class InstallerDownloadResponse(BaseModel):
    """رابط تحميل مؤقّت.

    ⚠️ **لا يُعرض `download_url` للمستخدم في الإضافة**: يُمرَّر إلى
    `chrome.downloads` مباشرة. عنوان Azure تفصيل داخلي، وإظهاره يدعو إلى
    مشاركة رابط يعمل بلا هوية حتى ينتهي.
    """

    download_url: str
    file_name: str
    expires_at: datetime
    expires_in_minutes: int
