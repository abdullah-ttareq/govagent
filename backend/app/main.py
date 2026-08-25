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
    # إضافة المتصفح (extension/) تعمل من أصل chrome-extension://<id>، ومعرّف
    # الإضافة يتغيّر عند كل Load unpacked، لذلك يُسمح به بنمط بدل قيمة ثابتة.
    allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
