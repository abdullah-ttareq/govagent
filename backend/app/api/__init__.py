"""مسارات الـHTTP. كل ملف هنا يصدّر router واحدًا، وتُجمَّع كلها في api_router.

الـRouters رفيعة: تتحقق من الشكل وتترجم أخطاء الخدمات إلى رموز HTTP، والمنطق
في `app/services/`. وصف كل وسم (tag) بالعربية في `app/main.py`.
"""

from fastapi import APIRouter

from ..schemas import ErrorResponse
from . import (
    audit,
    auth,
    chat,
    conversations,
    entitlements,
    files,
    health,
    organizations,
    runtime,
    users,
)

#: الحالات التي قد تخرج من أي مسار في الـAPI، بنموذج الخطأ الموحّد.
#: تُمرَّر عند تضمين الـRouter فتظهر في /docs بلا تكرارها في كل مسار.
#: المسارات التي تعرّف الحالة نفسها بوصف أدق تُبقي وصفها.
_API_ERRORS: dict = {
    422: {"model": ErrorResponse, "description": "بيانات الطلب مرفوضة"},
    500: {"model": ErrorResponse, "description": "خطأ غير متوقع في الخدمة"},
}

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, responses=_API_ERRORS)
api_router.include_router(organizations.router, responses=_API_ERRORS)
api_router.include_router(users.router, responses=_API_ERRORS)
api_router.include_router(conversations.router, responses=_API_ERRORS)
api_router.include_router(files.router, responses=_API_ERRORS)
api_router.include_router(audit.router, responses=_API_ERRORS)
api_router.include_router(chat.router, responses=_API_ERRORS)
api_router.include_router(entitlements.router, responses=_API_ERRORS)
api_router.include_router(runtime.router, responses=_API_ERRORS)

__all__ = ["api_router"]
