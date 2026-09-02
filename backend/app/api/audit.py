"""مسار قراءة سجل التدقيق.

**لمسؤول الجهة ولجهته وحدها.** السجل يكشف من فعل ماذا ومتى، فهو أحسّ من
قائمة الموظفين. لا توجد مسارات كتابة ولا حذف: السجل يُضاف إليه من الخدمات
نفسها، وسجلٌ يمكن تنقيحه لا يصلح دليلًا.
"""

from fastapi import APIRouter, HTTPException, Query, status

from ..schemas import AuditEventOut, AuditListResponse, PageMeta
from ..schemas.governance import MAX_ACTION_FILTER_LENGTH
from ..services.audit_service import AuditPermissionError, list_events
from ..services.audit_store import AuditEvent
from ..services.conversation_store import Page
from .dependencies import AdminUser

router = APIRouter(prefix="/api/audit-logs", tags=["audit"])


def _to_event_out(event: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        id=event.id,
        action=event.action,
        user_id=event.user_id,
        details=event.details,
        created_at=event.created_at,
    )


@router.get(
    "",
    response_model=AuditListResponse,
    summary="قراءة سجل تدقيق الجهة",
    responses={
        401: {"description": "رمز الدخول مفقود أو غير صالح"},
        403: {"description": "السجل متاح لمسؤول الجهة فقط"},
    },
)
def read_audit_logs(
    admin: AdminUser,
    action: str | None = Query(
        None,
        max_length=MAX_ACTION_FILTER_LENGTH,
        description="تصفية على نوع الحدث، مثل: login أو file_uploaded",
    ),
    user_id: int | None = Query(
        None, ge=1, description="تصفية على موظف بعينه داخل الجهة"
    ),
    limit: int | None = Query(None, ge=1, description="عدد الأحداث في الصفحة"),
    offset: int | None = Query(None, ge=0, description="عدد الأحداث المتجاوَزة"),
) -> AuditListResponse:
    """يعيد أحداث جهة المسؤول من الأحدث، مع الترقيم والتصفية.

    الأحداث المسجَّلة: تسجيل الدخول، إنشاء موظف، تعطيل موظف، حذف محادثة، رفع
    ملف، حذف ملف، تغيير مزود المودل، تغيير الاشتراك، تجهيز الجهة.

    أحداث الجهات الأخرى لا تظهر هنا إطلاقًا: الاستعلام مقيّد بجهة الرمز.
    """
    try:
        page: Page = list_events(
            actor=admin,
            action=action,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )
    except AuditPermissionError as exc:  # pragma: no cover — AdminUser تسبقها
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    return AuditListResponse(
        events=[_to_event_out(event) for event in page.items],
        page=PageMeta(total=page.total, limit=page.limit, offset=page.offset),
    )
