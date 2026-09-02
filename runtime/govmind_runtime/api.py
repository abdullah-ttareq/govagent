"""واجهة GovMind Runtime المحلية — **على `127.0.0.1` وحدها**.

⚠️ **لا يُربط الخادم بـ`0.0.0.0` بحال.** ربطُه بكل الواجهات يعرض مودلًا
ومسارَ تفعيل لكل جهاز على شبكة الجهة.

⚠️ **لا مسار OpenAI عام بلا مصادقة.** كل مسار هنا — عدا `/health`
و`/activate` — يتطلّب **رمز الجلسة المحلي**: قيمة عشوائية تُولَّد عند كل
إقلاع وتُكتب في ملف داخل مجلد بيانات التركيب. الواجهة تقرؤها من
`/api/local/session` المحمي بفحص أصل الطلب، وموقعُ ويب مفتوح في المتصفح
نفسه لا يستطيع قراءتها ولا استهلاك المودل.

`/health` وحده بلا رمز: تحتاجه الإضافة قبل أن تملك شيئًا، وهو لا يكشف إلا
مرحلة الـRuntime ورسالتها العربية.

--------------------------------------------------------------------------
العطل الحيّ الذي أصلحه هذا الملف: **405 Method Not Allowed**
--------------------------------------------------------------------------
الواجهة المصدَّرة تُخدَم من `StaticFiles` المركَّب على `/`. و`StaticFiles`
لا يعرف إلا `GET` و`HEAD`؛ أي فعل آخر يردّ عليه بـ**405** بجسم
`{"detail":"Method Not Allowed"}`. وكان بناء سطح المكتب يجعل الواجهة تنادي
`POST /api/auth/login` على **الأصل نفسه**، فلا يجد الطلب مسارًا في هذا
الملف، فيلتقطه التركيب ويردّ 405. هذا هو النصّ الذي رآه العميل بالضبط.

الإصلاح هنا شقّان، وكلاهما ضروري:

1. **لا نموذج دخول ثانٍ أصلًا.** الواجهة المثبَّتة لا تسجّل دخولًا: العميل
   سجّل دخوله في الإضافة، والـRuntime استبدل جلسة التركيب وصار يملك بيان
   اعتماد الجهاز. مسارات `/api/app/*` أدناه تخدم التطبيق من الأصل نفسه.
2. **مصائد صريحة قبل التركيب.** أي مسار تحت `/api/` غير معروف يردّ
   **404 برسالة عربية**، وأي فعل غير `GET`/`HEAD` على أي مسار آخر يردّ
   404 كذلك — **لا 405 إنجليزية عارية في أي حال**. الرسالة تقول ما يجب
   فعله بدل أن تترك العميل أمام نصّ HTTP خام.

⚠️ **لا يوجد وكيل مفتوح.** الواجهة المحلية لا تستطيع أن تطلب من الـRuntime
مناداة أي عنوان: `control_plane.ALLOWED_ROUTES` قائمة بيضاء حرفية، والـ
Runtime هو من يلصق بيان الاعتماد في جانب الخادم. **لا يصل بيان الاعتماد إلى
JavaScript في المتصفح بحال.**
"""

from __future__ import annotations

import logging
import secrets
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import RuntimeConfig
from .control_plane import ActivationRejectedError, ControlPlaneError
from .identity import IdentityError
from .service import ChatUnavailableError, RuntimeService

logger = logging.getLogger(__name__)

SESSION_HEADER = "X-GovMind-Session"

#: أصول مسموح لها بمناداة الـRuntime. الإضافة أصلها `chrome-extension://`،
#: والواجهة تُخدَم من الـRuntime نفسه.
_EXTENSION_ORIGIN = r"^chrome-extension://[a-p]{32}$"

#: رسالة المسار المجهول تحت `/api/`. **بالعربية وتقول ما يُفعل** — بديل
#: `Method Not Allowed` التي كان يردّها التركيب الساكن.
_UNKNOWN_API = (
    "هذا الطلب غير معروف لخدمة GovMind على هذا الجهاز. "
    "أعد فتح GovMind من اختصاره، وإن تكرر الأمر فأعد تثبيته."
)


class ActivateRequest(BaseModel):
    """رمز التركيب الذي تسلّمه الإضافة.

    ⚠️ **لا يُسجَّل الرمز**، ولا يُعاد في أي رد.
    """

    token: str = Field(..., min_length=16, max_length=512)


class ChatTurn(BaseModel):
    """دور واحد من سياق المحادثة كما تحفظه الواجهة المثبَّتة.

    ⚠️ **دوران فقط.** لا `system`: تعليمة النظام يبنيها الطرف الذي يولّد،
    ولا تُقبل من الواجهة — قبولها يجعل حدود الإيجنت قابلة للإلغاء من صفحة
    معدَّلة في المتصفح.
    """

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    """رسالة من التطبيق المثبَّت مع سياق المحادثة.

    ⚠️ **أين تذهب يعتمد على وضع التشغيل، ويُعلَن في الرد:**

    - المسار المحلي: إلى محرّك على الاسترجاع المحلي، ولا تغادر الجهاز.
    - المسار السحابي: تمرّ بخدمة GovMind إلى مزوّد استدلال خارجي.

    الرد يحمل ``cloud`` ليعرض التطبيق أيّهما جرى — بلا ادّعاء محليّة.

    ⚠️ **لا يحمل الطلب بيان اعتماد ولا رمز جهاز.** الواجهة في المتصفح لا
    تملك سرًّا أصلًا؛ الـRuntime وحده يضيفه في الترويسة إلى السيرفر.
    """

    message: str = Field(..., min_length=1, max_length=8000)
    #: سياق المحادثة بالترتيب الزمني، بلا الرسالة الحالية. **محدود عمدًا**:
    #: سياق بلا سقف يجعل تبويبةً واحدة تستهلك حصة الاستدلال كلها.
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    #: المحادثة التي يُحفظ فيها الدور. غيابه يعني محادثة عابرة لا تُحفظ.
    conversation_id: str | None = Field(default=None, max_length=64)


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
                "واجهة محلية على 127.0.0.1 لإدارة ربط الجهاز وتنزيل المودل "
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

        # -- الصحة: بلا رمز، وهو أحد مسارين بلا رمز -------------------
        @app.get("/health")
        def health() -> dict[str, object]:
            """تستطلعه الإضافة لتعرف أن الـRuntime يعمل وأي مرحلة بلغ.

            **لا يكشف شيئًا حسّاسًا**: لا منفذ المحرّك ولا مسارات ولا رمز
            ولا بريد صاحب الحساب — انظر `state.snapshot`.
            """
            snapshot = self.service.state.snapshot()
            return {"service": "govmind-runtime", **snapshot}

        # -- التفعيل: بلا رمز جلسة، فالإضافة لا تملكه ------------------
        @app.post("/activate")
        def activate(payload: ActivateRequest) -> JSONResponse:
            """يستبدل رمز التركيب بربط هذا الجهاز.

            **لا يحتاج رمز الجلسة المحلي**: الإضافة لا تملكه، ورمز التركيب
            نفسه هو إثبات الصلاحية — صادر من الـBackend، لمرة واحدة،
            وقصير العمر.

            ⚠️ **الرد لقطة حالة لا أكثر.** بيان اعتماد الجهاز الذي يصله من
            السيرفر يُحفظ بـDPAPI ولا يخرج في هذا الرد ولا في غيره، فلا
            تراه الإضافة ولا أي صفحة.
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
            except IdentityError as exc:
                # تعذّرت حماية بيان الاعتماد أو حفظه على القرص. **لا يُخزَّن
                # بديل مكشوف**؛ الرسالة عربية والعميل يعيد المحاولة.
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(exc),
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

        # ==============================================================
        # التطبيق المثبَّت — **من الأصل نفسه، وبلا تسجيل دخول ثانٍ**
        # ==============================================================
        @app.get("/api/app/session", dependencies=[guard])
        def app_session() -> dict[str, object]:
            """حالة ربط هذا الجهاز، كما يقرؤها التطبيق المثبَّت عند فتحه.

            **هذا ما حلّ محلّ `GET /api/auth/me`.** لا بريد ولا كلمة مرور
            يُطلبان: `linked` تقول إن كان استبدال جلسة التركيب قد تمّ، فإن
            تمّ فتح التطبيقُ مباشرة، وإلا عُرضت تعليمة الإضافة.

            ⚠️ **لا يخرج من هنا بيان اعتماد الجهاز ولا تجزئته ولا سرّ
            هويته.** الحقول كلها عرضٌ للعميل عن حسابه هو.
            """
            return self._session_payload()

        @app.post("/api/app/recheck", dependencies=[guard])
        def app_recheck() -> dict[str, object]:
            """يعيد فحص الربط الآن — زرّ «إعادة التحقق» في التطبيق.

            **يعمل في الطلب نفسه لا في الخلفية:** العميل ضغط زرًّا وينتظر
            جوابًا، وردٌّ يقول «سنخبرك لاحقًا» هو الانتظار بلا نهاية الذي
            نصلحه.
            """
            if self.service.is_activated:
                self.service.refresh_entitlement()
                self.service.start_background_preparation()
            return self._session_payload()

        @app.post("/api/app/chat", dependencies=[guard])
        def app_chat(payload: ChatRequest) -> dict[str, object]:
            """يولّد ردًّا عبر المسار المفعَّل على هذا الجهاز.

            ⚠️ **الواجهة لا تعرف الوجهة ولا تختارها.** تنادي هذا العنوان
            المحلي وحده؛ والـRuntime يقرّر: محرّك على الجهاز، أو خدمة
            GovMind ببيان اعتماد يضيفه هو. لو اختارت الواجهة، لاحتاجت
            عنوان السيرفر وسرَّ الجهاز في شيفرة يقرؤها أي أحد.

            ⚠️ **لا يُسجَّل النصّ ولا الردّ ولا السياق.**

            يعيد ``cloud`` صريحةً: الواجهة تعرضها ليعرف العميل أن نصّه
            غادر الجهاز حين يغادره.
            """
            try:
                result = self.service.chat(
                    payload.message,
                    [{"role": t.role, "content": t.content} for t in payload.history],
                )
            except ChatUnavailableError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail=str(exc)
                ) from exc
            # ⚠️ **يُحفظ بعد نجاح الردّ لا قبله.** حفظُ سؤالٍ فشل توليد
            # ردّه يترك المحادثة بدور ناقص يراه المستخدم عطلًا.
            if payload.conversation_id:
                self.service.remember_turn(
                    payload.conversation_id,
                    user_message=payload.message,
                    assistant_message=result.reply,
                )
            return {
                "reply": result.reply,
                "engine": result.engine,
                "cloud": result.cloud,
            }

        # -- المحادثات المحفوظة: كلها برمز الجلسة ----------------------
        #
        # ⚠️ **الحساب يُقرأ من حالة الـRuntime لا من الطلب.** لو أرسلت
        # الصفحة البريد، لصار تبديلُ حرف فيه بابًا لقراءة محادثات حساب
        # آخر على الجهاز نفسه.
        @app.get("/api/app/conversations", dependencies=[guard])
        def list_conversations() -> dict[str, object]:
            """ملخّصات المحادثات، **الأحدث أولًا**. بلا نصوص الرسائل."""
            return {"conversations": self.service.list_conversations()}

        @app.post("/api/app/conversations", dependencies=[guard])
        def create_conversation() -> dict[str, object]:
            return self.service.create_conversation()

        @app.get("/api/app/conversations/{conversation_id}", dependencies=[guard])
        def read_conversation(conversation_id: str) -> dict[str, object]:
            found = self.service.get_conversation(conversation_id)
            if found is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="لم تعد هذه المحادثة موجودة.",
                )
            return found

        @app.delete("/api/app/conversations/{conversation_id}", dependencies=[guard])
        def delete_conversation(conversation_id: str) -> dict[str, object]:
            """يحذف محادثة **نهائيًا**. تأكيدُ المستخدم يقع في الواجهة."""
            if not self.service.delete_conversation(conversation_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="لم تعد هذه المحادثة موجودة.",
                )
            return {"deleted": True}

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

        self._install_fallbacks(app)
        self._mount_ui(app)
        return app

    # ------------------------------------------------------------------
    def _session_payload(self) -> dict[str, object]:
        """الشكل الذي يقرؤه التطبيق المثبَّت.

        `linked` مشتقّة من امتلاك بيان اعتماد لا من مرحلة العرض: مرحلةٌ قد
        تكون `error` لسبب عابر بينما الجهاز مربوط تمامًا.
        """
        snapshot = self.service.state.account_snapshot()
        return {
            "service": "govmind-runtime",
            "linked": self.service.is_activated,
            # اسم المحرّك ووضعه — للتشخيص وللتحقق، ولا سرّ فيهما. **لا
            # يخرجان في `/health`** المفتوح بلا مصادقة.
            "engine": self.service.engine_name,
            "demo_mode": self.service.is_demo,
            # ⚠️ **تصل الواجهة قبل أول رسالة**، لتقول للعميل أين ستُعالَج
            # قبل أن يكتب — لا بعد أن أرسل.
            "cloud_mode": self.service.is_cloud,
            **snapshot,
        }

    def _install_fallbacks(self, app: FastAPI) -> None:
        """يمنع عودة **405 Method Not Allowed** إلى العميل، بطبقتين.

        ⚠️ **مصدر العطل الحيّ.** `StaticFiles` المركَّب على `/` يلتقط كل
        ما لم يُطابَق قبله ولا يعرف إلا `GET`/`HEAD`؛ أي فعل آخر يخرج منه
        بـ405 وجسمٍ إنجليزي `{"detail":"Method Not Allowed"}`. وهو ما رآه
        العميل حين أرسلت الواجهة `POST /api/auth/login` إلى الأصل نفسه.

        **الطبقة الأولى — مسار صريح قبل التركيب.** أي مسار تحت `/api/`
        غير معروف يردّ 404 برسالة عربية تقول ما يُفعل. مسجَّل قبل التركيب،
        و Starlette يطابق بترتيب التسجيل.

        **الطبقة الثانية — معالِج استثناء عام.** أي 405 من أي مصدر — من
        التركيب الساكن، أو من فعل خاطئ على مسار من مساراتنا — يتحوّل إلى
        404 بالرسالة نفسها. طبقةٌ واحدة لا تكفي: مسار عام `"/{rest:path}"`
        محدَّد بأفعال الكتابة كان **يصنع** 405 بنفسه على `GET` لمسار مجهول،
        فينتقل العطل من التركيب إلى المصيدة.
        """

        @app.api_route(
            "/api/{rest:path}",
            methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
            include_in_schema=False,
        )
        def unknown_api(rest: str) -> JSONResponse:
            # ⚠️ يُسجَّل المسار وحده — لا جسم الطلب ولا ترويسته.
            logger.info("طلب إلى مسار غير معروف في خدمة GovMind: /api/%s", rest)
            return JSONResponse(
                {"detail": _UNKNOWN_API},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        @app.exception_handler(StarletteHTTPException)
        async def http_exception(
            request: Request, exc: StarletteHTTPException
        ) -> JSONResponse:
            if exc.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
                logger.info(
                    "فعل غير مدعوم على مسار محلي: %s %s",
                    request.method,
                    request.url.path,
                )
                return JSONResponse(
                    {"detail": _UNKNOWN_API},
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            return JSONResponse(
                {"detail": exc.detail}, status_code=exc.status_code,
                headers=getattr(exc, "headers", None),
            )

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
