"""مسارات الـHTTP. كل ملف هنا يصدّر router واحدًا."""

from fastapi import APIRouter

from . import chat, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router)

__all__ = ["api_router"]
