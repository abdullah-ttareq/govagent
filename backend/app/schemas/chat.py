"""Schemas الخاصة بالمحادثة."""

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """طلب إرسال رسالة إلى الإيجنت."""

    message: str = Field(..., max_length=8000, description="نص رسالة الموظف")

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("الرسالة لا يمكن أن تكون فارغة")
        return cleaned


class ChatResponse(BaseModel):
    """رد الإيجنت."""

    reply: str = Field(..., description="نص الرد")
    provider: str = Field(..., description="اسم مزود المودل الذي أنتج الرد")


class HealthResponse(BaseModel):
    """حالة الخدمة."""

    status: str
    app_env: str
    model_provider: str
