"""نقطة تشغيل GovAgent Backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .core.config import settings
from .database import close_pool


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """دورة حياة التطبيق.

    لا يُفتح أي اتصال بقاعدة البيانات عند الإقلاع — الاتصال كسول ويُنشأ عند
    أول استخدام فعلي. المطلوب هنا هو الإغلاق النظيف فقط، وهو آمن حتى لو لم
    يُنشأ Pool إطلاقًا.
    """
    yield
    close_pool()


app = FastAPI(
    title="GovAgent API",
    description="مساعد ذكاء اصطناعي عام لموظفي الجهات الحكومية — نسخة MVP.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    # إضافة المتصفح (extension/) تعمل من أصل chrome-extension://<id>، ومعرّف
    # الإضافة يتغيّر عند كل Load unpacked، لذلك يُسمح به بنمط بدل قيمة ثابتة.
    allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
