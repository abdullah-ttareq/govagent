"""شكل رد الخطأ الموحّد لكل مسارات الـAPI.

**شكل واحد لكل حالة**: 400 و 401 و 403 و 404 و 405 و 409 و 413 و 415 و 422
و 500 و 503 كلها تعيد هذا الغلاف نفسه، فيكتب العميل معالجة أخطاء واحدة بدل
معالجة لكل مسار.

``detail`` نصٌّ عربي **دائمًا**، ولو كان الخطأ خطأ تحقق من الحقول: كان
FastAPI يعيد قائمة كائنات في هذا الحقل، فيتعذّر على الواجهة عرضه مباشرة.

**لا Stack Trace ولا تفاصيل داخلية في الرد إطلاقًا** — ولا حتى القيمة التي
أرسلها المستخدم: كان ``input`` في رد التحقق يعيد الحقل كما وصل، فكلمة مرور
قصيرة تعود نصًّا صريحًا في جسم الرد وفي أي سجل يلتقطه.
"""

from pydantic import BaseModel, ConfigDict, Field


class FieldError(BaseModel):
    """خطأ في حقل واحد من الطلب. يظهر في أخطاء التحقق (422) وحدها."""

    field: str = Field(
        ...,
        description="موضع الحقل، مثل: body.email أو query.limit",
        examples=["body.email"],
    )
    message: str = Field(
        ...,
        description="سبب الرفض بالعربية",
        examples=["صيغة البريد الإلكتروني غير صحيحة"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "field": "body.email",
                "message": "صيغة البريد الإلكتروني غير صحيحة",
            }
        }
    )


class ErrorResponse(BaseModel):
    """رد الخطأ الموحّد."""

    detail: str = Field(
        ..., description="رسالة عربية صالحة للعرض على المستخدم مباشرة"
    )
    status: int = Field(..., description="رمز حالة HTTP نفسه، لتسهيل المعالجة")
    code: str = Field(
        ...,
        description=(
            "معرّف نصي ثابت لنوع الخطأ: unauthorized أو forbidden أو "
            "not_found أو validation_error أو internal_error … يُبنى عليه "
            "المنطق بدل مطابقة نص الرسالة"
        ),
        examples=["not_found"],
    )
    errors: list[FieldError] = Field(
        default_factory=list,
        description=(
            "تفصيل أخطاء الحقول. **فارغة في كل الحالات عدا 422 و 400** — "
            "الحقل موجود دائمًا ليبقى شكل الرد واحدًا"
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "المستخدم المطلوب غير موجود.",
                "status": 404,
                "code": "not_found",
                "errors": [],
            }
        }
    )
