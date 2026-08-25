"""نقطة المحادثة."""

from fastapi import APIRouter, HTTPException, status

from ..ai import ModelProviderError
from ..schemas import ChatRequest, ChatResponse
from ..services import send_message

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse, summary="إرسال رسالة إلى الإيجنت")
def chat(payload: ChatRequest) -> ChatResponse:
    """يستقبل رسالة نصية ويعيد رد المزود المفعّل.

    لا يتطلب حاليًا تسجيل دخول ولا قاعدة بيانات. ستُضاف حماية JWT في مهمة BE-03،
    وحفظ الرسائل في مهمة BE-06.
    """
    try:
        return send_message(payload.message)
    except ModelProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
