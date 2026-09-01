"""نقطة فحص حالة الخدمة."""

from fastapi import APIRouter

from ..core.config import settings
from ..database import check_status
from ..database import supabase as supabase_db
from ..schemas import DependencyHealth, HealthResponse, OracleHealth
from ..services import installer_service

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="حالة الخدمة")
def health() -> HealthResponse:
    """تعيد حالة الخدمة والبيئة ومزود المودل وحالة مخازن البيانات.

    فحوص القواعد **إعلامية ولا تُفشل النقطة**: إن كانت غير مضبوطة أو غير
    متاحة يبقى status = "ok" لأن النظام يعمل بدونها، ويظهر السبب في حقل
    `detail` الخاص بها. لا يُفتح أي اتصال ما لم تكن متغيراتها مضبوطة.

    **تخزين Azure يُفحص بقراءة الإعداد وحده ولا يُنادى**: نداؤه يكلّف طلبًا
    شبكيًا في كل فحص صحة، ولا يضيف شيئًا — الرابط يُولَّد محليًا بالتوقيع.
    """
    oracle = check_status()
    supabase_status = supabase_db.check_status()
    return HealthResponse(
        status="ok",
        app_env=settings.app_env,
        model_provider=settings.model_provider,
        oracle=OracleHealth(
            configured=oracle.configured,
            status=oracle.status,
            detail=oracle.detail,
        ),
        supabase=DependencyHealth(
            configured=supabase_status.configured,
            status=supabase_status.status,
            detail=supabase_status.detail,
        ),
        installer_storage_configured=installer_service.is_configured(),
    )
