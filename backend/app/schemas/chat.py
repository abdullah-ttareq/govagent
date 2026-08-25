"""Schemas الخاصة بالمحادثة."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

#: أقصى عدد رسائل سابقة تُقبل كسياق في الطلب الواحد. الحد يمنع تضخّم
#: الطلب وتجاوز حدود المودل، والواجهة مسؤولة عن إرسال الأحدث فقط.
MAX_HISTORY_MESSAGES = 20


class ChatMessageIn(BaseModel):
    """رسالة سابقة في المحادثة تُرسل كسياق مع الرسالة الحالية."""

    role: Literal["user", "assistant"] = Field(
        ..., description="صاحب الرسالة: user للموظف، assistant للإيجنت"
    )
    content: str = Field(..., max_length=8000, description="نص الرسالة")

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("محتوى الرسالة في السياق لا يمكن أن يكون فارغًا")
        return cleaned


class ChatRequest(BaseModel):
    """طلب إرسال رسالة إلى الإيجنت."""

    message: str = Field(..., max_length=8000, description="نص رسالة الموظف")
    history: list[ChatMessageIn] = Field(
        default_factory=list,
        max_length=MAX_HISTORY_MESSAGES,
        description="رسائل المحادثة السابقة بالترتيب الزمني (اختيارية)",
    )
    # ⚠️ مؤقت حتى مهمة BE-03: لا يوجد تسجيل دخول بعد، فتصل الجهة من العميل.
    # بعد تفعيل JWT **يجب** أن تُقرأ من التوكن ويُحذف هذا الحقل من الطلب، وإلا
    # أمكن لأي عميل أن يطلب مقاطع جهة أخرى. بلا قيمة هنا لا يجري أي بحث.
    organization_id: int | None = Field(
        None,
        gt=0,
        description="جهة الموظف. بدونها يجيب الإيجنت من معرفته العامة بلا ملفات",
    )

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("الرسالة لا يمكن أن تكون فارغة")
        return cleaned


class ChatSource(BaseModel):
    """مصدر واحد من ملفات الجهة استُند إليه في الرد."""

    file_id: int = Field(..., description="معرّف الملف")
    file_name: str = Field(..., description="اسم الملف كما رفعه الموظف")
    chunk_index: int = Field(..., description="رقم المقطع داخل الملف")
    score: float = Field(..., description="درجة قرب المقطع من السؤال")


class ChatResponse(BaseModel):
    """رد الإيجنت."""

    reply: str = Field(..., description="نص الرد")
    provider: str = Field(..., description="اسم مزود المودل الذي أنتج الرد")
    sources: list[ChatSource] = Field(
        default_factory=list,
        description="مقاطع ملفات الجهة المستخدمة في الرد، فارغة إن لم تُستخدم",
    )


class OracleHealth(BaseModel):
    """حالة قاعدة Oracle كما تظهر في /health.

    حقل إعلامي فقط: كون القاعدة غير مضبوطة أو غير متاحة لا يجعل الخدمة
    نفسها غير سليمة، لأن النظام يعمل بالكامل بدونها في وضع التطوير.
    """

    configured: bool = Field(..., description="هل ضُبطت متغيرات Oracle كلها؟")
    status: Literal["not_configured", "ok", "error"] = Field(
        ..., description="not_configured: غير مضبوطة | ok: متصلة | error: تعذّر الاتصال"
    )
    detail: str | None = Field(
        None, description="شرح عربي للحالة عند عدم الضبط أو عند الفشل"
    )


class HealthResponse(BaseModel):
    """حالة الخدمة."""

    status: str
    app_env: str
    model_provider: str
    oracle: OracleHealth
