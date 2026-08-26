"""Schemas المحادثات والرسائل والملفات.

**لا يوجد هنا حقل ``organization_id`` ولا ``user_id`` في أي طلب.** الجهة
والمالك يُشتقان من رمز الدخول؛ لو قُبلا من جسم الطلب لأمكن لأي موظف أن يكتب
في محادثة غيره أو يقرأها.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: أقصى طول لعنوان المحادثة، مطابق لعمود conversations.title في المخطط.
MAX_TITLE_LENGTH = 300


def _clean_title(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("عنوان المحادثة لا يمكن أن يكون فارغًا")
    return cleaned


class ConversationOut(BaseModel):
    """محادثة كما تُعاد للعميل."""

    id: int = Field(..., description="معرّف المحادثة")
    title: str = Field(..., description="عنوان المحادثة")
    message_count: int = Field(..., description="عدد رسائلها")
    created_at: datetime = Field(..., description="لحظة الإنشاء")
    updated_at: datetime = Field(..., description="لحظة آخر رسالة أو تعديل")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 12,
                "title": "ما نظام الإجازات في الجهة؟",
                "message_count": 4,
                "created_at": "2026-08-26T09:15:00Z",
                "updated_at": "2026-08-26T09:21:00Z",
            }
        }
    )


class ConversationCreateRequest(BaseModel):
    """طلب إنشاء محادثة. العنوان اختياري ويمكن تغييره لاحقًا."""

    title: str | None = Field(
        None, max_length=MAX_TITLE_LENGTH, description="عنوان المحادثة"
    )

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        return None if value is None else _clean_title(value)


class ConversationRenameRequest(BaseModel):
    """طلب إعادة تسمية محادثة."""

    title: str = Field(
        ..., max_length=MAX_TITLE_LENGTH, description="العنوان الجديد"
    )

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _clean_title(value)


class MessageOut(BaseModel):
    """رسالة واحدة داخل محادثة."""

    id: int = Field(..., description="معرّف الرسالة")
    conversation_id: int = Field(..., description="معرّف محادثتها")
    role: Literal["user", "assistant"] = Field(
        ..., description="user: رسالة الموظف | assistant: رد الإيجنت"
    )
    content: str = Field(..., description="نص الرسالة")
    created_at: datetime = Field(..., description="لحظة الحفظ")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 41,
                "conversation_id": 12,
                "role": "user",
                "content": "ما نظام الإجازات في الجهة؟",
                "created_at": "2026-08-26T09:15:00Z",
            }
        }
    )


class PageMeta(BaseModel):
    """بيانات الترقيم المرافقة لكل قائمة."""

    total: int = Field(..., description="العدد الكلي قبل الترقيم")
    limit: int = Field(..., description="عدد العناصر المطلوبة في الصفحة")
    offset: int = Field(..., description="عدد العناصر المتجاوَزة")


class ConversationListResponse(BaseModel):
    """قائمة محادثات الموظف، من الأحدث تعديلًا."""

    conversations: list[ConversationOut] = Field(..., description="المحادثات")
    page: PageMeta = Field(..., description="بيانات الترقيم")


class MessageListResponse(BaseModel):
    """رسائل محادثة بالترتيب الزمني الصاعد."""

    messages: list[MessageOut] = Field(..., description="الرسائل من الأقدم")
    page: PageMeta = Field(..., description="بيانات الترقيم")


class FileOut(BaseModel):
    """بيانات ملف مرفوع، كما يراها أي موظف في الجهة.

    **بلا ``storage_path``:** مسار الملف على قرص السيرفر تفصيل داخلي، وكشفه
    يعطي معلومة عن بنية السيرفر بلا فائدة للعميل.
    """

    id: int = Field(..., description="معرّف الملف")
    original_name: str = Field(..., description="اسم الملف كما رفعه الموظف")
    mime_type: str = Field(..., description="نوع المحتوى المشتق من الامتداد")
    size_bytes: int = Field(..., description="حجم الملف بالبايت")
    status: Literal["pending", "processed", "failed"] = Field(
        ...,
        description=(
            "processed: مفهرس وقابل للبحث | failed: محفوظ لكن تعذّرت فهرسته | "
            "pending: قيد المعالجة"
        ),
    )
    uploaded_by: int = Field(
        ..., description="معرّف الموظف الذي رفع الملف داخل الجهة"
    )
    can_modify: bool = Field(
        ...,
        description=(
            "هل يملك صاحب الرمز حذف هذا الملف؟ صحيح لرافعه ولمسؤول الجهة. "
            "تعرضه الواجهة لتعرف أيّ ملف يظهر له زر حذف"
        ),
    )
    conversation_id: int | None = Field(
        None,
        description=(
            "المحادثة المرتبط بها. **يظهر لرافع الملف وحده**: الارتباط جزء "
            "من خصوصية المحادثة لا من بيانات الملف"
        ),
    )
    created_at: datetime = Field(..., description="لحظة الرفع")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 4,
                "original_name": "لائحة-الإجازات.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 248392,
                "status": "processed",
                "uploaded_by": 2,
                "can_modify": True,
                "conversation_id": 12,
                "created_at": "2026-08-26T09:10:00Z",
            }
        }
    )


class FileUploadResponse(BaseModel):
    """رد رفع ملف."""

    file: FileOut = Field(..., description="بيانات الملف المحفوظ")
    chunk_count: int = Field(
        ..., description="عدد المقاطع المفهرسة للبحث، و0 إن تعذّرت الفهرسة"
    )
    indexing_error: str | None = Field(
        None,
        description=(
            "سبب تعذّر الفهرسة. الملف محفوظ في كل الأحوال، لكنه لن يظهر في "
            "نتائج البحث إن وُجد هذا الحقل"
        ),
    )


class FileListResponse(BaseModel):
    """قائمة ملفات الموظف، من الأحدث."""

    files: list[FileOut] = Field(..., description="الملفات")
    page: PageMeta = Field(..., description="بيانات الترقيم")
