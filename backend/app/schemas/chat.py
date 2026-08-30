"""Schemas الخاصة بالمحادثة."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

class ChatMessageIn(BaseModel):
    """رسالة سابقة في المحادثة تُمرَّر كسياق إلى المزود.

    **ليست حقلًا في أي طلب**: السياق يُبنى في `api/chat.py` من الرسائل
    المحفوظة على السيرفر. الحد الأقصى لعددها هو `CONTEXT_MESSAGE_LIMIT`
    في `services/conversation_service.py`.
    """

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
    # حقل history كان هنا حتى P4-03، وحُذف عمدًا مع إنهاء الوضع الانتقالي:
    # كان يسمح للعميل بإرسال «ما قيل سابقًا»، وسياقٌ يرسله المتصفح يمكن
    # تلفيقه. السياق يُقرأ الآن من المحادثة المحفوظة على السيرفر. **لا تُعده.**
    #
    # وحقل organization_id حُذف قبله في P2-02: كان يصل من العميل على مسار بلا
    # مصادقة، فيستطيع أي أحد طلب مقاطع ملفات أي جهة برقم واحد. الجهة تُشتق من
    # رمز الدخول في api/chat.py. **لا تُعده.**
    conversation_id: int | None = Field(
        None,
        gt=0,
        description=(
            "المحادثة التي تُكمَّل. يتطلب رمز دخول، وبلا قيمة تُفتح محادثة "
            "جديدة تلقائيًا ويُعاد معرّفها في الرد"
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "ما نظام الإجازات في الجهة؟",
                "conversation_id": 12,
            }
        }
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
    conversation_id: int | None = Field(
        None,
        description=(
            "المحادثة التي حُفظ فيها التبادل. فارغ في الطلبات بلا رمز دخول، "
            "فلا حفظ حينها"
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reply": "نظام الإجازات في الجهة ينص على…",
                "provider": "mock",
                "sources": [
                    {
                        "file_id": 4,
                        "file_name": "لائحة-الإجازات.pdf",
                        "chunk_index": 2,
                        "score": 0.8134,
                    }
                ],
                "conversation_id": 12,
            }
        }
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
