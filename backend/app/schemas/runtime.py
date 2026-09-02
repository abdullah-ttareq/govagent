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

#: أقصى طول لرسالة واحدة. يمنع جسمًا ضخمًا ويحدّ كلفة الاستدلال.
MAX_CHAT_CHARS = 8000

#: أقصى عدد رسائل سياق مقبولة من الجهاز.
MAX_CHAT_HISTORY = 40


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
    """نتيجة التفعيل، ومعها **بيان اعتماد الجهاز مرة واحدة**.

    ⚠️ ``device_credential`` قيمة عشوائية يولّدها **السيرفر** لحظةَ نجاح
    الاستبدال. تعود هنا مرة واحدة ولا تُسترجع أبدًا — القاعدة لا تحمل إلا
    SHA-256 لها.

    ⚠️ **هذا الرد لا يصل متصفحًا ولا الإضافة.** يناديه الـRuntime من جهاز
    العميل، فيحفظ القيمة بـWindows DPAPI ولا يعرضها ولا يمرّرها إلى الواجهة
    المحلية. أي مسار جديد يعيد هذا النموذج إلى متصفح تسريبٌ لبيان اعتماد.
    """

    activation_id: int
    status: Literal["trial", "active", "expired", "suspended", "cancelled"]
    expires_at: datetime
    device_credential: str = Field(
        ...,
        description="بيان اعتماد الجهاز — يظهر مرة واحدة، للـRuntime وحده",
    )


class RuntimeEntitlementResponse(BaseModel):
    """حالة الاشتراك كما يقرؤها الـRuntime دوريًا."""

    status: Literal["trial", "active", "expired", "suspended", "cancelled"]
    expires_at: datetime
    is_usable: bool
    blocked_reason: str | None = None
    device_name: str
    #: بريد صاحب الاشتراك، ليعرضه التطبيق المثبَّت. **بلا اسم جهة ولا دور
    #: ولا معرّف داخلي**: المنتج حساب فردي واحد لا مساحة عمل لها مسؤول.
    account_email: str = ""


class RuntimeChatMessage(BaseModel):
    """رسالة واحدة من سياق المحادثة كما يرسلها الـRuntime.

    الأدوار المسموحة اثنان فقط: تعليمات النظام **لا تأتي من الجهاز** بل
    يبنيها السيرفر، فلا يستطيع عميل أن يستبدلها برسالة بدور `system`.
    """

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=MAX_CHAT_CHARS)


class RuntimeChatRequest(BaseModel):
    """طلب محادثة من GovMind على جهاز العميل.

    ⚠️ **لا يحمل معرّف جهة ولا اشتراك ولا مستخدم.** كلها تُشتقّ من بيان
    اعتماد الجهاز في الترويسة، فلا يستطيع جهاز أن يسأل باسم غيره.

    ⚠️ **ولا يحمل تعليمات نظام.** يبنيها السيرفر؛ قبولها من الجهاز يجعل
    كل حدود الإيجنت قابلة للإلغاء من عميل معدَّل.
    """

    message: str = Field(..., min_length=1, max_length=MAX_CHAT_CHARS)
    #: سياق المحادثة بالترتيب الزمني، بلا الرسالة الحالية.
    #:
    #: **محدود العدد عمدًا**: سياق بلا سقف يجعل جهازًا واحدًا قادرًا على
    #: استهلاك حصة الاستدلال كلها بطلب واحد.
    history: list[RuntimeChatMessage] = Field(
        default_factory=list, max_length=MAX_CHAT_HISTORY
    )


class RuntimeChatResponse(BaseModel):
    """ردّ المودل كما يعود إلى الـRuntime.

    ⚠️ **بلا أي معرّف داخلي**: لا معرّف تفعيل ولا اشتراك ولا جهة.
    """

    reply: str
    #: اسم المزوّد الذي أجاب — يعرضه التطبيق ليعرف العميل أين جرت المعالجة.
    provider: str
    #: هل جرت المعالجة خارج الجهاز؟ **يُعرض للعميل** ولا يُخفى.
    cloud: bool = False


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
