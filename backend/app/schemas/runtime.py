"""Schemas مسارات GovMind Runtime وجلسات التركيب.

⚠️ **لا يظهر في أي نموذج هنا:** سرّ جهاز مخزَّن، ولا تجزئة، ولا مفتاح
Supabase، ولا سلسلة اتصال Azure. ما يخرج إلى الـRuntime هو رابط موقّع
قصير العمر وبيانات تحقّق منه، وما يخرج إلى الإضافة هو رمز تركيب لمرة
واحدة لا يفتح شيئًا بذاته.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: طول الرمز والسرّ المقبول من العميل. الحدّان يمنعان جسمًا ضخمًا ويرفضان
#: قيمة أقصر من أن تكون عشوائية.
MIN_TOKEN = 16
MAX_TOKEN = 512


class InstallationSessionResponse(BaseModel):
    """رمز تركيب صادر للإضافة.

    ⚠️ **يظهر مرة واحدة فقط.** لا يُخزَّن خامًا على السيرفر، فلا سبيل إلى
    استرجاعه؛ الإضافة تحفظه مؤقتًا حتى ينتهي التركيب ثم تمحوه.
    """

    token: str = Field(..., description="رمز التركيب، لمرة واحدة")
    expires_at: datetime = Field(..., description="لحظة انتهاء صلاحيته")
    expires_in_minutes: int


class RuntimeActivateRequest(BaseModel):
    """طلب التفعيل من الـRuntime.

    `device_secret` سرّ ولّده الـRuntime على الجهاز. **يُجزَّأ على السيرفر
    فور وصوله ولا يُخزَّن خامًا ولا يُسجَّل.**
    """

    token: str = Field(..., min_length=MIN_TOKEN, max_length=MAX_TOKEN)
    device_secret: str = Field(..., min_length=MIN_TOKEN, max_length=MAX_TOKEN)
    device_name: str = Field("جهاز غير مسمّى", max_length=120)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "token": "<رمز التركيب من الإضافة>",
                "device_secret": "<سرّ يولّده الـRuntime>",
                "device_name": "حاسب المكتب",
            }
        }
    )


class RuntimeActivationResponse(BaseModel):
    """نتيجة التفعيل. بلا أي معرّف حسّاس."""

    activation_id: int
    status: Literal["trial", "active", "expired", "suspended", "cancelled"]
    expires_at: datetime


class RuntimeEntitlementResponse(BaseModel):
    """حالة الاشتراك كما يقرؤها الـRuntime دوريًا."""

    status: Literal["trial", "active", "expired", "suspended", "cancelled"]
    expires_at: datetime
    is_usable: bool
    blocked_reason: str | None = None
    device_name: str


class ModelArtifactResponse(BaseModel):
    """رابط المودل وبيانات التحقق منه.

    `sha256` و `size_bytes` يأتيان من السيرفر لا من الـRuntime: تغيير ملف
    المودل يجب ألا يستلزم إصدارًا جديدًا من البرنامج على أجهزة العملاء.
    """

    download_url: str
    file_name: str
    expires_at: datetime
    sha256: str = Field(..., description="التجزئة المتوقّعة، ست عشرية")
    size_bytes: int = Field(..., description="الحجم المتوقّع بالبايت")
