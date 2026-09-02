"""Schemas الحساب والاشتراك وتفعيل الجهاز وتحميل المثبّت.

**لا يوجد هنا حقل `organization_id` في أي طلب**، ولا حقل لرابط سيرفر ولا
لمفتاح: الجهة تُشتق من رمز الدخول، وعنوان الـBackend مثبَّت في الإضافة وقت
البناء، وعنوان Azure لا يعرفه العميل أصلًا.

⚠️ **`device_id_hash` لا يظهر في أي نموذج رد هنا.** التجزئة تُقارن على
السيرفر وحده؛ من يعرفها يستطيع انتحال الجهاز أمام أي فحص يقارنها.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    """صاحب الحساب كما يُعرض في الإضافة.

    ⚠️ **بلا دور وبلا معرّف مساحة.** المنتج اشتراك فردي: لا لقب «مسؤول»
    يُعرض ولا مفردات مؤسسات. الدور والمساحة بنيتان تحتاجهما RLS في
    القاعدة، **ولا يحتاجهما عميلٌ أبدًا**، فلا تخرجان من السيرفر أصلًا —
    وهذا أضمن من التعهّد بألا تُعرضا.
    """

    email: str
    full_name: str


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


class RegistrationRequest(BaseModel):
    """طلب إنشاء حساب جديد.

    **أربعة حقول لا خمسة.** المنتج اشتراك فردي: حساب واحد واشتراك واحد
    وجهاز فعّال واحد، **ولا يُسأل العميل عن جهة**. المساحة التي يحتاجها
    عزل RLS يولّدها السيرفر من معرّف الحساب ولا يراها العميل.

    ⚠️ ولا حقل لرابط ولا لمفتاح — كبقية طلبات الإضافة.
    """

    full_name: str = Field(..., min_length=2, max_length=200, description="الاسم الكامل")
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=8, max_length=200)
    confirm_password: str = Field(..., min_length=8, max_length=200)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "full_name": "سارة العتيبي",
                "email": "sara@example.gov.sa",
                "password": "••••••••",
                "confirm_password": "••••••••",
            }
        }
    )

    @field_validator("full_name")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("القيمة قصيرة جدًا")
        return cleaned

    @model_validator(mode="after")
    def passwords_must_match(self) -> "RegistrationRequest":
        """يُفحص التطابق على السيرفر كذلك لا في المتصفح وحده.

        فحص المتصفح تحسينٌ لتجربة الاستخدام، ويمكن تجاوزه بطلب مباشر —
        فالسيرفر لا يبني على أن العميل فحص.
        """
        if self.password != self.confirm_password:
            raise ValueError("كلمتا المرور غير متطابقتين")
        return self


class RegistrationResponse(BaseModel):
    """نتيجة التسجيل.

    عند نجاح الدخول التلقائي تُعاد الجلسة كاملة، فتتابع الإضافة إلى حالة
    الاشتراك وتفعيل الجهاز بلا خطوة إضافية. وإن كان المشروع يشترط تأكيد
    البريد تكون الجلسة فارغة و`requires_email_confirmation` صحيحة.
    """

    requires_email_confirmation: bool
    email: str
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
    account: AccountOut | None = None


class DeviceReplaceRequest(BaseModel):
    """استبدال الجهاز السابق بهذا الجهاز — يفعله صاحب الحساب بنفسه.

    ⚠️ **كلمة المرور مطلوبة مرة أخرى.** رمز الدخول وحده لا يكفي لعملية
    تُوقف GovMind على حاسب آخر: من ترك جلسته مفتوحة على جهاز عام يجب ألا
    يفقد بها جهازه. والتحقق يتم عبر Supabase Auth لا بمقارنة محلية.
    """

    device_id: str = Field(..., min_length=MIN_DEVICE_ID, max_length=MAX_DEVICE_ID)
    device_name: str = Field("جهاز غير مسمّى", max_length=120)
    password: str = Field(..., min_length=1, max_length=200)


class DeviceReplaceResponse(BaseModel):
    """نتيجة الاستبدال، ومعها حالة الاشتراك بعده."""

    #: هل أُبطل جهاز سابق فعلًا؟ خطأ إن كان هذا الجهاز هو المفعّل أصلًا.
    replaced: bool
    subscription: SubscriptionStatusResponse
