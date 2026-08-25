"""نقطة فحص حالة الخدمة."""

from fastapi import APIRouter

from ..core.config import settings
from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="حالة الخدمة")
def health() -> HealthResponse:
    """تعيد حالة الخدمة والبيئة ومزود المودل المفعّل."""
    return HealthResponse(
        status="ok",
        app_env=settings.app_env,
        model_provider=settings.model_provider,
    )
