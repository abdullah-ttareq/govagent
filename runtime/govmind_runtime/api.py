"""واجهة GovMind Runtime المحلية — **على `127.0.0.1` وحدها**.

⚠️ **لا يُربط الخادم بـ`0.0.0.0` بحال.** ربطُه بكل الواجهات يعرض مودلًا
ومسارَ تفعيل لكل جهاز على شبكة الجهة.

⚠️ **لا مسار OpenAI عام بلا مصادقة.** كل مسار هنا — عدا `/health` —
يتطلّب **رمز الجلسة المحلي**: قيمة عشوائية تُولَّد عند كل إقلاع وتُكتب في
ملف داخل مجلد بيانات التركيب. الواجهة تقرؤها من `/api/local/session`
المحمي بفحص أصل الطلب، وموقعُ ويب مفتوح في المتصفح نفسه لا يستطيع قراءتها
ولا استهلاك المودل.

`/health` وحده بلا رمز: تحتاجه الإضافة قبل أن تملك شيئًا، وهو لا يكشف إلا
مرحلة الـRuntime ورسالتها العربية.
"""

from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import RuntimeConfig
from .control_plane import ActivationRejectedError, ControlPlaneError
from .service import RuntimeService

logger = logging.getLogger(__name__)

SESSION_HEADER = "X-GovMind-Session"

#: أصول مسموح لها بمناداة الـRuntime. الإضافة أصلها `chrome-extension://`،
#: والواجهة تُخدَم من الـRuntime نفسه.
_EXTENSION_ORIGIN = r"^chrome-extension://[a-p]{32}$"


class ActivateRequest(BaseModel):
    """رمز التركيب الذي تسلّمه الإضافة.

    ⚠️ **لا يُسجَّل الرمز**، ولا يُعاد في أي رد.
    """

    token: str = Field(..., min_length=16, max_length=512)


class LocalApi:
    """يبني تطبيق FastAPI المحلي فوق :class:`RuntimeService`."""

    def __init__(self, service: RuntimeService, config: RuntimeConfig) -> None:
        self.service = service
        self.config = config
        # رمز جلسة جديد عند كل إقلاع: رمزٌ ثابت مخزَّن يبقى صالحًا بعد
        # إغلاق الـRuntime، ورمزُ إقلاعٍ ينتهي بانتهاء العملية.
        self.session_token = secrets.token_urlsafe(32)
        self._write_session_file()
        self.app = self._build()

    def _write_session_file(self) -> None:
        """يكتب رمز الجلسة ليقرأه الواجهة المحلية.

        فشل الكتابة **لا يُسقط الـRuntime**: المسارات تبقى تعمل بالرمز
        المرسَل في الترويسة، والواجهة وحدها هي التي تتعطّل.
        """
        try:
            path = self.config.session_file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.session_token, encoding="utf-8")
        except OSError:
            logger.warning("تعذّرت كتابة ملف جلسة الواجهة المحلية.")

    # ------------------------------------------------------------------
    def _require_session(
        self, token: Annotated[str | None, Header(alias=SESSION_HEADER)] = None
    ) -> None:
        """يتحقق من رمز الجلسة المحلي بمقارنة ثابتة الزمن."""
        if not token or not secrets.compare_digest(token, self.session_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="طلب غير مصرّح به إلى خدمة GovMind المحلية.",
            )

    def _build(self) -> FastAPI:
        app = FastAPI(
            title="GovMind Runtime",
            description=(
                "واجهة محلية على 127.0.0.1 لإدارة تفعيل الجهاز وتنزيل المودل "
                "وتشغيله. **ليست واجهة عامة ولا تُعرَّض للشبكة.**"
            ),
            version="1.0.0",
            docs_url=None,  # لا صفحة توثيق على جهاز عميل.
            redoc_url=None,
            openapi_url=None,
        )

        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=_EXTENSION_ORIGIN,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

        guard = Depends(self._require_session)

        # -- الصحة: بلا رمز، وهو المسار الوحيد كذلك --------------------
        @app.get("/health")
        def health() -> dict[str, object]:
            """تستطلعه الإضافة لتعرف أن الـRuntime يعمل وأي مرحلة بلغ.

            **لا يكشف شيئًا حسّاسًا**: لا منفذ المحرّك ولا مسارات ولا رمز.
            """
            snapshot = self.service.state.snapshot()
            return {"service": "govmind-runtime", **snapshot}

        # -- التفعيل: بلا رمز جلسة، فالإضافة لا تملكه ------------------
        @app.post("/activate")
        def activate(payload: ActivateRequest) -> JSONResponse:
            """يستبدل رمز التركيب بتفعيل هذا الجهاز.

            **لا يحتاج رمز الجلسة المحلي**: الإضافة لا تملكه، ورمز التركيب
            نفسه هو إثبات الصلاحية — صادر من الـBackend، لمرة واحدة،
            وقصير العمر.
            """
            try:
                snapshot = self.service.activate(payload.token)
            except ActivationRejectedError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail=str(exc)
                ) from exc
            except ControlPlaneError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
                ) from exc
            return JSONResponse(snapshot)

        # -- رمز الجلسة للواجهة المحلية --------------------------------
        @app.get("/api/local/session")
        def local_session(request: Request) -> dict[str, str]:
            """تقرأ منه الواجهة رمزها.

            محمي بفحص الأصل: الواجهة تُخدَم من الـRuntime نفسه، فطلبها بلا
            `Origin` أو بأصل محلي مطابق. صفحةٌ على نطاق خارجي يرسل المتصفح
            أصلها، فتُرفض.
            """
            origin = request.headers.get("origin")
            if origin and not origin.startswith(
                (f"http://127.0.0.1:{self.config.port}", "http://localhost")
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="طلب من أصل غير مسموح.",
                )
            return {"token": self.session_token}

        # -- الحالة والتحكّم: كلها برمز الجلسة -------------------------
        @app.get("/api/status", dependencies=[guard])
        def status_endpoint() -> dict[str, object]:
            return self.service.state.snapshot()

        @app.post("/api/model/download", dependencies=[guard])
        def start_download() -> dict[str, object]:
            self.service.start_background_preparation()
            return self.service.state.snapshot()

        @app.post("/api/model/cancel", dependencies=[guard])
        def cancel_download() -> dict[str, object]:
            self.service.cancel_download()
            return self.service.state.snapshot()

        @app.post("/api/model/start", dependencies=[guard])
        def start_model() -> dict[str, object]:
            self.service.start_model()
            return self.service.state.snapshot()

        @app.post("/api/model/stop", dependencies=[guard])
        def stop_model() -> dict[str, object]:
            self.service.stop_model()
            return self.service.state.snapshot()

        @app.post("/api/model/restart", dependencies=[guard])
        def restart_model() -> dict[str, object]:
            self.service.restart_model()
            return self.service.state.snapshot()

        @app.post("/api/entitlement/refresh", dependencies=[guard])
        def refresh() -> dict[str, object]:
            self.service.refresh_entitlement()
            return self.service.state.snapshot()

        self._mount_ui(app)
        return app

    def _mount_ui(self, app: FastAPI) -> None:
        """يخدم واجهة GovMind الثابتة من الـRuntime نفسه.

        الواجهة تصدير ساكن لتطبيق Next.js — **لا Node.js على جهاز العميل**.
        غيابها لا يمنع الـRuntime من العمل: الإضافة تحتاج `/health` فقط،
        ورسالة واضحة أفضل من انهيار عند الإقلاع.
        """
        ui_dir = self.config.ui_dir
        if not ui_dir.is_dir():
            logger.warning("ملفات الواجهة غير موجودة في هذا التثبيت.")

            @app.get("/")
            def missing_ui() -> JSONResponse:
                return JSONResponse(
                    {
                        "detail": (
                            "ملفات واجهة GovMind ناقصة من هذا التثبيت. "
                            "أعد تثبيت GovMind."
                        )
                    },
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            return

        index = ui_dir / "index.html"

        @app.get("/")
        def home() -> FileResponse:
            return FileResponse(index)

        # `html=True` يجعل المسارات الفرعية تعود إلى ملفاتها الثابتة كما
        # يصدّرها Next.js.
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")
