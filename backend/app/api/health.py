"""نقطة فحص حالة الخدمة."""

from fastapi import APIRouter

from ..core.config import settings
from ..database import check_status
from ..schemas import HealthResponse, OracleHealth

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="حالة الخدمة")
def health() -> HealthResponse:
    """تعيد حالة الخدمة والبيئة ومزود المودل وحالة قاعدة Oracle.

    فحص Oracle **إعلامي ولا يُفشل النقطة**: إن كانت القاعدة غير مضبوطة أو غير
    متاحة يبقى status = "ok" لأن النظام يعمل بدونها، ويظهر السبب في حقل
    oracle.detail. لا يُفتح اتصال إطلاقًا ما لم تكن المتغيرات مضبوطة.
    """
    oracle = check_status()
    return HealthResponse(
        status="ok",
        app_env=settings.app_env,
        model_provider=settings.model_provider,
        oracle=OracleHealth(
            configured=oracle.configured,
            status=oracle.status,
            detail=oracle.detail,
        ),
    )
