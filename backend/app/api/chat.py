"""نقطة المحادثة."""

from fastapi import APIRouter, HTTPException, status

from ..ai import ModelProviderError
from ..schemas import ChatRequest, ChatResponse
from ..services import send_message

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse, summary="إرسال رسالة إلى الإيجنت")
def chat(payload: ChatRequest) -> ChatResponse:
    """يستقبل رسالة نصية مع سياق المحادثة (اختياري) ويعيد رد المزود المفعّل.

    إن أُرسل organization_id تُبحث ملفات الجهة عن مقاطع تخص السؤال، وتُعاد
    مصادرها في حقل sources. فشل البحث أو غياب الملفات **لا يُفشل الطلب**:
    يجيب الإيجنت من معرفته العامة و sources فارغة.

    أي فشل في المزود (إعداد ناقص، تعذّر اتصال، مهلة، رد غير صالح) يصل هنا
    كـModelProviderError ويُعاد إلى العميل بحالة 503 مع الرسالة العربية كما هي.

    لا يتطلب حاليًا تسجيل دخول ولا قاعدة بيانات. ستُضاف حماية JWT في مهمة BE-03،
    وحفظ الرسائل في مهمة BE-06.
    """
    try:
        return send_message(
            payload.message,
            history=payload.history,
            organization_id=payload.organization_id,
        )
    except ModelProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
