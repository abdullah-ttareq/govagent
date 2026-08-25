"""نقطة تشغيل GovAgent Backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .core.config import settings

app = FastAPI(
    title="GovAgent API",
    description="مساعد ذكاء اصطناعي عام لموظفي الجهات الحكومية — نسخة MVP.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
