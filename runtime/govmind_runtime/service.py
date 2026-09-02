"""تنسيق عمل الـRuntime: التفعيل ثم المودل ثم التشغيل.

هذه الوحدة هي **المنطق**، و`api.py` غلاف HTTP رفيع فوقها. الفصل يجعل كل
مسار التفعيل والتنزيل قابلًا للاختبار بلا خادم HTTP ولا منافذ.

**ترتيب الإقلاع:**

1. هل يوجد **بيان اعتماد جهاز**؟ لا ⇒ ``AWAITING_ACTIVATION`` وانتظار رمز
   تركيب من الإضافة.
2. نعم ⇒ اسأل الـBackend عن الاستحقاق. ممنوع ⇒ ``BLOCKED``.
3. مسموح ⇒ هل المودل مثبَّت ومُتحقَّق منه؟ لا ⇒ نزّله.
4. نعم ⇒ شغّل `llama-server` وانتظر جاهزيته ⇒ ``READY``.

**«مربوط» = يملك بيان اعتماد، لا يملك ملف هوية.** كان الشرط وجودَ ملف
الهوية — وهو سرّ يولّده هذا البرنامج نفسه، فوجوده لا يثبت أن أحدًا أذن
لهذا الجهاز. تثبيتٌ ولّد هويته ثم فشل التفعيل كان يبدو «مفعَّلًا» ويفشل
كل نداء بعده بلا سبب مفهوم.

**بلا إنترنت أثناء تحديث الاستحقاق:** الـRuntime **لا يتوقف**. اشتراك
تحقّقنا منه قبل ساعة لا يصير باطلًا لأن الشبكة انقطعت الآن، ومنعُ موظف من
العمل بسبب شبكته عقوبةٌ على غير ذنب. يُسجَّل التعذّر ويُعاد المحاولة.

--------------------------------------------------------------------------
وضع العرض الأكاديمي
--------------------------------------------------------------------------
حين يكون ``config.is_demo`` صحيحًا، تُستبدل **الخطوتان ٣ و٤ وحدهما**
بمحرّك محلي مثبَّت على الجهاز (Ollama):

* **لا يُنزَّل مودل من Azure**، ولا تُقرأ `AZURE_MODEL_*` إطلاقًا.
* **لا يُشغَّل `llama-server.exe`** ولا يُلمس.
* الاستحقاق والاشتراك وبيان اعتماد الجهاز **كما هي بلا تغيير**: العرض
  يخصّ المحرّك وحده، لا من يملك حقّ الاستعمال.

وما دون ذلك — الهوية، والربط، وDPAPI، والـControl Plane — لا يمسّه هذا
الوضع بحرف.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import RuntimeConfig
from .control_plane import (
    ControlPlaneClient,
    ControlPlaneError,
    DeviceNotActivatedError,
    OfflineError,
    SubscriptionBlockedError,
)
from .conversations import ConversationStore
from .demo_engine import DemoEngineError, OllamaEngine
from .identity import DeviceCredentialStore, DeviceIdentity, IdentityError
from .llama_supervisor import LlamaOptions, LlamaSupervisor, SupervisorError
from .model_store import (
    DownloadCancelled,
    ModelArtifact,
    ModelError,
    ModelStore,
)
from .state import Phase, RuntimeState

logger = logging.getLogger(__name__)

#: تعليمة النظام **للمسار المحلي وحده** — المودل المرفق ومحرّك العرض.
#:
#: **بلا أي ذكر لجهة أو مسؤول أو دور.** المنتج حساب فردي واحد، والتعليمة
#: تصف مساعدًا لا موظفًا في مؤسسة.
#:
#: ⚠️ **لا تُستعمل في المسار السحابي.** هناك يبنيها السيرفر: قبولُ تعليمة
#: نظام من جهاز عميل يجعل كل حدود الإيجنت قابلة للإلغاء من نسخة معدَّلة.
#: وجملةُ «يعمل بالكامل على حاسب المستخدم» صحيحة هنا وحدها.
SYSTEM_PROMPT = (
    "أنت GovMind، مساعد ذكي يعمل بالكامل على حاسب المستخدم. "
    "أجب بالعربية الفصحى بإيجاز ووضوح. "
    "إن لم تعرف الإجابة فقل ذلك صراحة ولا تخمّن."
)

#: أقصى عدد رسائل سياق يمرّرها الـRuntime. **يطابق سقف السيرفر**: تجاوزه
#: يعني ردًّا بـ٤٢٢ يراه العميل خطأً غامضًا، فيُقلَّم هنا بدل ذلك.
MAX_HISTORY = 40

#: مهلة توليد الرد من المودل المحلي. أطول من مهل التحكّم بكثير: التوليد
#: على المعالج قد يستغرق دقيقة على جهاز متواضع.
CHAT_TIMEOUT_SECONDS = 180.0


@dataclass(frozen=True)
class ChatReply:
    """ردّ محادثة واحد، **ومعه أين عولج**.

    ⚠️ ``cloud`` ليس تفصيلًا داخليًا: تعرضه الواجهة المثبَّتة ليعرف العميل
    أن نصّه غادر الجهاز. إخفاؤه يجعل الواجهة تدّعي محليةً لا وجود لها.
    """

    reply: str
    engine: str
    cloud: bool = False


class ChatUnavailableError(Exception):
    """تعذّر توليد ردّ، برسالة عربية صالحة للعرض.

    تغطي المسارات الثلاثة: المودل المرفق، ومحرّك العرض، والمسار السحابي.
    الرسالة وحدها ما يصل العميل — لا رمز حالة ولا اسم استثناء ولا منفذ.
    """


def _recent(history: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    """آخر ``limit`` رسالة. **الأقدم يسقط أولًا** — أقلّها أثرًا في الرد."""
    return history[-limit:] if limit > 0 else []


def describe_platform() -> str:
    """اسم وصفي للجهاز — **بلا اسم مستخدم ولا معرّف عتاد**."""
    import platform

    release = platform.release() or ""
    return f"حاسب ويندوز {release}".strip()


class RuntimeService:
    """يجمع الهوية والاستحقاق والمودل والمحرّك في مسار واحد."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        identity: DeviceIdentity | None = None,
        credentials: DeviceCredentialStore | None = None,
        control_plane: ControlPlaneClient | None = None,
        model_store: ModelStore | None = None,
        supervisor: LlamaSupervisor | None = None,
        demo_engine: OllamaEngine | None = None,
        conversations: ConversationStore | None = None,
    ) -> None:
        self.config = config
        self.state = RuntimeState()

        #: سجلّ المحادثات — **ملفات يملكها الـRuntime لا مخزن المتصفح**.
        self._conversations = conversations or ConversationStore(config.data_dir)

        self._identity = identity or DeviceIdentity(config.data_dir)
        self._credentials = credentials or DeviceCredentialStore(config.data_dir)
        self._control = control_plane or ControlPlaneClient(config.control_plane_url)
        self._models = model_store or ModelStore(
            model_path=config.model_path, part_path=config.part_path
        )
        self._supervisor = supervisor or LlamaSupervisor(
            config.llama_server, LlamaOptions(model_path=config.model_path)
        )
        # ⚠️ **لا يُبنى محرّك عرض في التشغيل الإنتاجي.** `None` هنا هو ما
        # يجعل كل فرع أدناه يسلك المسار الأصلي بلا شرط إضافي.
        self._demo = demo_engine or (
            OllamaEngine(config.demo_engine_url, config.demo_model)
            if config.is_demo
            else None
        )
        # ⚠️ `RLock` لا `Lock`: مسار التفعيل المُعاد يستدعي
        # `start_background_preparation` وهو **داخل** القفل، وقفلٌ غير قابل
        # لإعادة الدخول يتجمّد هناك.
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None

    # ------------------------------------------------------------------
    # الهوية والربط
    # ------------------------------------------------------------------
    @property
    def is_activated(self) -> bool:
        """هل هذا الجهاز **مربوط**؟

        المعيار وجود بيان اعتماد صادر عن السيرفر، لا وجود ملف هوية ولّده
        هذا البرنامج. الأول إذنٌ من مالك الاشتراك، والثاني ملفٌّ يستطيع أي
        تثبيت أن يكتبه لنفسه.
        """
        try:
            return self._credentials.load() is not None
        except IdentityError:
            return False

    @property
    def credential_protection(self) -> str:
        """اسم آلية حماية بيان الاعتماد — للتشخيص وللاختبارات.

        ⚠️ **اسم الآلية لا قيمتها.** لا مسار في هذا البرنامج يعيد القيمة.
        """
        return self._credentials.protection

    def _device_credential(self) -> str | None:
        """بيان اعتماد هذا الجهاز، أو ``None`` إن لم يكن مربوطًا.

        ⚠️ **لا يُسجَّل ولا يدخل أي رسالة حالة.** يخرج من هنا إلى عميل
        الـControl Plane وحده.
        """
        try:
            return self._credentials.load()
        except IdentityError as exc:
            self.state.set(Phase.ERROR, str(exc))
            return None

    def _forget_credential(self, message: str) -> None:
        """يمحو بيان اعتماد رفضه السيرفر ويعود إلى انتظار ربط جديد.

        **الاحتفاظ ببيان مرفوض يترك البرنامج يعيد إرساله إلى ما لا نهاية**
        ويعرض «مربوط» لجهاز لم يعد كذلك. الأصحّ أن يطلب ربطًا من الإضافة.
        """
        self._credentials.clear()
        self._supervisor.stop()
        self.state.set(Phase.AWAITING_ACTIVATION, message)

    # ------------------------------------------------------------------
    # التفعيل
    # ------------------------------------------------------------------
    def activate(self, token: str) -> dict[str, object]:
        """يستبدل رمز التركيب بربط هذا الجهاز، ويحفظ بيان الاعتماد.

        **ترتيب مقصود:**

        1. مربوط أصلًا ⇒ لا شيء يُفعل. الإضافة قد تعيد الإرسال بعد انقطاع
           بين النجاح ووصول الرد، وذلك ليس خطأً.
        2. **يُعاد استعمال ملف الهوية القائم إن وُجد** ولا يُولَّد غيره:
           هويةٌ جديدة على الجهاز نفسه تجعل القاعدة تراه جهازًا ثانيًا
           فتصطدم بقيد «جهاز فعّال واحد». وجودُ هوية بلا بيان اعتماد حالةٌ
           واقعية — تثبيتٌ سابق تعثّر بعد توليد هويته.
        3. السيرفر يستبدل الرمز، ويعيد بيان الاعتماد **مرة واحدة**.
        4. يُحفظ بـDPAPI **قبل** أن تُعلن نجاح الربط: بيانٌ لم يُحفظ يعني
           جهازًا مربوطًا في القاعدة بلا وسيلة مصادقة على القرص.

        ⚠️ **لا يُعاد بيان الاعتماد إلى المستدعي.** اللقطة العائدة هي
        لقطة الحالة نفسها التي يقرؤها `/health` — بلا سرّ.

        Raises:
            ControlPlaneError: بفروعه — رمز مرفوض أو جهاز آخر أو انقطاع.
            IdentityError: إذا تعذّرت حماية بيان الاعتماد أو حفظه.
        """
        with self._lock:
            if self._device_credential() is not None:
                logger.info("طلب ربط لجهاز مربوط مسبقًا — يُتجاهل بلا خطأ.")
                self._resume_after_activation()
                return self.state.snapshot()

            self.state.set(Phase.ACTIVATING)

            # هوية قائمة تُستعمل كما هي؛ وغيابها وحده يستدعي توليدًا.
            fresh_identity = not self._identity.exists()
            secret = self._identity.ensure()

            try:
                result = self._control.activate(
                    token=token,
                    device_secret=secret,
                    device_name=describe_platform(),
                )
                self._credentials.store(result.credential)
            except (ControlPlaneError, IdentityError):
                # لا تبقَ هوية وُلّدت لأجل ربط فشل. أمّا هوية كانت قائمة
                # قبل هذا النداء فتبقى: قد يكون عليها تفعيل قائم.
                if fresh_identity:
                    self._identity.clear()
                self._credentials.clear()
                self.state.set(Phase.AWAITING_ACTIVATION)
                raise

            self.state.set_account(
                status=result.status or None,
                expires_at=result.expires_at or None,
            )

        logger.info("رُبط هذا الجهاز بالحساب بنجاح.")
        self._resume_after_activation()
        return self.state.snapshot()

    def _resume_after_activation(self) -> None:
        """يبدأ تجهيز المودل في خيط منفصل بعد نجاح التفعيل."""
        self.start_background_preparation()

    @property
    def is_demo(self) -> bool:
        """هل يعمل هذا التركيب بوضع العرض الأكاديمي؟"""
        return self._demo is not None

    @property
    def is_cloud(self) -> bool:
        """هل يغادر نصّ المحادثة هذا الجهاز؟

        **تُعرض للعميل في الواجهة المثبَّتة**، ولا تُخفى: من حقّه أن يعرف
        أين يُعالَج ما يكتبه قبل أن يكتبه.
        """
        return self.config.is_cloud_chat

    @property
    def engine_name(self) -> str:
        """اسم المحرّك للعرض والتشخيص — لا سرّ فيه.

        ⚠️ **لا يذكر مفتاح مزوّد ولا عنوانه**: اسمٌ وصفي فقط، والردّ نفسه
        يحمل اسم المزوّد الذي أجاب.
        """
        if self._demo is not None:
            return f"{self.config.demo_engine_type}:{self._demo.model}"
        if self.config.is_cloud_chat:
            return "استدلال سحابي"
        return "llama.cpp"

    # ------------------------------------------------------------------
    # الاستحقاق
    # ------------------------------------------------------------------
    def refresh_entitlement(self) -> bool:
        """يحدّث حالة الاشتراك. يعيد ``True`` إن كان يسمح بالخدمة.

        **الانقطاع ليس منعًا:** تعذّر الوصول يعيد ``True`` ويُسجَّل، فلا
        يتوقف موظف عن العمل لأن شبكته انقطعت.
        """
        credential = self._device_credential()
        if credential is None:
            self.state.set(Phase.AWAITING_ACTIVATION)
            return False

        try:
            entitlement = self._control.entitlement(credential)
        except OfflineError:
            logger.warning("تعذّر تحديث الاستحقاق (لا اتصال) — يستمر العمل.")
            return True
        except DeviceNotActivatedError as exc:
            # ⚠️ **جهاز أُبطل أو استُبدل، أو بيان اعتماد مُدوَّر.** يُمحى
            # البيان ويعود البرنامج إلى انتظار ربط جديد من الإضافة —
            # لا إلى شاشة «ممنوع» لا مخرج منها.
            logger.warning("رُفض بيان اعتماد هذا الجهاز؛ سيُطلب ربط جديد.")
            self._forget_credential(str(exc))
            return False
        except SubscriptionBlockedError as exc:
            self.state.set(Phase.BLOCKED, str(exc))
            self._supervisor.stop()
            return False
        except ControlPlaneError as exc:
            logger.warning("رفض الاستحقاق: %s", exc)
            self._supervisor.stop()
            self.state.set(Phase.BLOCKED, str(exc))
            return False

        self.state.set_account(
            email=entitlement.account_email,
            device_name=entitlement.device_name,
            status=entitlement.status,
            expires_at=entitlement.expires_at,
        )

        if not entitlement.is_usable:
            self._supervisor.stop()
            self.state.set(
                Phase.BLOCKED,
                entitlement.blocked_reason
                or "الاشتراك لا يسمح باستخدام GovMind حاليًا.",
            )
            return False
        return True

    # ------------------------------------------------------------------
    # المودل
    # ------------------------------------------------------------------
    def download_model(self) -> None:
        """ينزّل المودل ويتحقق منه، محدّثًا الحالة خطوة بخطوة."""
        if self._demo is not None:
            # ⚠️ **لا تنزيل في وضع العرض بحال** — ولا حتى إن نودي المسار
            # يدويًا من الواجهة. المودل على الجهاز أصلًا.
            logger.info("طلب تنزيل مودل في وضع العرض — يُتجاهل.")
            self._prepare_demo()
            return

        if self.config.is_cloud_chat:
            # ⚠️ **لا تنزيل في الوضع السحابي بحال** — ولا حتى إن نودي
            # المسار يدويًا من الواجهة. لا مودل يُنزَّل على هذا الجهاز.
            logger.info("طلب تنزيل مودل في الوضع السحابي — يُتجاهل.")
            self.state.set(Phase.READY)
            return

        credential = self._device_credential()
        if credential is None:
            self.state.set(Phase.AWAITING_ACTIVATION)
            return

        self.state.set(Phase.DOWNLOADING_MODEL, progress=0)
        try:
            info = self._control.model_artifact(credential)
        except DeviceNotActivatedError as exc:
            self._forget_credential(str(exc))
            return
        except ControlPlaneError as exc:
            self.state.set(Phase.ERROR, str(exc))
            return

        artifact = ModelArtifact(
            download_url=info.download_url,
            file_name=info.file_name,
            sha256=info.sha256,
            size_bytes=info.size_bytes,
        )

        def on_download(progress) -> None:
            self.state.set_progress(
                progress.percent, progress.received, progress.total
            )

        try:
            self._models.download(artifact, on_progress=on_download)
        except DownloadCancelled as exc:
            self.state.set(Phase.MODEL_MISSING, str(exc))
            return
        except ModelError as exc:
            self.state.set(Phase.ERROR, str(exc))
            return

        self.state.set(Phase.VERIFYING_MODEL)
        self.start_model()

    def cancel_download(self) -> None:
        """يلغي التنزيل الجاري. ما نُزّل يبقى ليُستأنف."""
        self._models.cancel()

    # ------------------------------------------------------------------
    # المحرّك
    # ------------------------------------------------------------------
    def start_model(self) -> None:
        """يشغّل `llama-server` وينتظر جاهزيته."""
        if self._demo is not None:
            # ⚠️ **لا يُشغَّل `llama-server.exe` في وضع العرض إطلاقًا.**
            logger.info("طلب تشغيل المحرّك المرفق في وضع العرض — يُتجاهل.")
            self._prepare_demo()
            return

        if self.config.is_cloud_chat:
            # ⚠️ **لا يُشغَّل `llama-server.exe` في الوضع السحابي إطلاقًا.**
            logger.info("طلب تشغيل المحرّك المرفق في الوضع السحابي — يُتجاهل.")
            self.state.set(Phase.READY)
            return

        if not self._models.is_installed():
            self.state.set(Phase.MODEL_MISSING)
            return

        self.state.set(Phase.STARTING_MODEL)
        try:
            self._supervisor.start()
        except SupervisorError as exc:
            self.state.set(Phase.ERROR, str(exc))
            return
        self.state.set(Phase.READY)

    def stop_model(self) -> None:
        if self._demo is not None:
            # المحرّك ليس عمليةً نملكها؛ إيقافه ليس من شأن هذا البرنامج.
            logger.info("طلب إيقاف المحرّك في وضع العرض — يُتجاهل.")
            return
        if self.config.is_cloud_chat:
            logger.info("طلب إيقاف المحرّك في الوضع السحابي — يُتجاهل.")
            return
        self._supervisor.stop()
        self.state.set(Phase.MODEL_MISSING, "أُوقف المودل.")

    def restart_model(self) -> None:
        if self._demo is not None:
            self._prepare_demo()
            return
        if self.config.is_cloud_chat:
            self.state.set(Phase.READY)
            return
        self._supervisor.stop()
        self.start_model()

    @property
    def model_base_url(self) -> str | None:
        """عنوان المحرّك المتوافق مع OpenAI — **داخلي، لا يُعرض للعميل**."""
        return self._supervisor.base_url

    # ------------------------------------------------------------------
    # المحادثات المحفوظة
    # ------------------------------------------------------------------
    #
    # ⚠️ **الفصل بالحساب يقع هنا، مرة واحدة.** كل دالة تمرّر البريد الحالي
    # من حالة الـRuntime؛ لا تستقبله من الشبكة ولا تخمّنه. حسابان على حاسب
    # واحد لا يريان محادثات بعضهما.
    def _account(self) -> str | None:
        return self.state.account_email

    def list_conversations(self) -> list[dict]:
        return self._conversations.list(self._account())

    def create_conversation(self) -> dict:
        return self._conversations.create(self._account())

    def get_conversation(self, conversation_id: str) -> dict | None:
        return self._conversations.get(self._account(), conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        return self._conversations.delete(self._account(), conversation_id)

    def remember_turn(
        self, conversation_id: str, *, user_message: str, assistant_message: str
    ) -> dict | None:
        return self._conversations.append(
            self._account(),
            conversation_id,
            user_message=user_message,
            assistant_message=assistant_message,
        )

    # ------------------------------------------------------------------
    # المحادثة المحلية
    # ------------------------------------------------------------------
    def chat(
        self, message: str, history: list[dict[str, str]] | None = None
    ) -> ChatReply:
        """يولّد ردًّا على رسالة العميل عبر المسار المفعَّل.

        ثلاثة مسارات، ومكان المعالجة يختلف بينها **ويُعلَن للعميل**:

        - المودل المرفق أو محرّك العرض: النصّ لا يغادر الجهاز.
        - المسار السحابي: يمرّ النصّ بخدمة GovMind إلى مزوّد استدلال.

        ⚠️ **بيان الاعتماد لا يمرّ من هنا إلى المتصفح أبدًا.** الواجهة
        المثبَّتة تنادي هذا الـRuntime بلا أي سرّ، وهو من يضيف بيان
        الاعتماد في الترويسة إلى السيرفر. عكسُ ذلك يضع سرّ الجهاز في
        شيفرة يقرأها أي أحد بأدوات المطوّر.

        ⚠️ **المنفذ لا يظهر في أي رسالة خطأ**: هو تفصيل داخلي، ورقمٌ في
        رسالة لموظف غير تقني لا يفيده.

        ⚠️ **لا يُسجَّل النصّ ولا الردّ ولا السياق** في أي مسار.

        Raises:
            ChatUnavailableError: المودل غير جاهز، أو الاشتراك لا يسمح،
                أو تعذّر الوصول إلى المحرّك أو إلى الخدمة.
        """
        if self.state.phase is Phase.BLOCKED:
            raise ChatUnavailableError(self.state.message)
        if not self.is_activated:
            raise ChatUnavailableError(
                "أكمل تثبيت وربط GovMind من إضافة المتصفح."
            )

        # ⚠️ **المسار السحابي قبل فحص جهوزية المحرّك المحلي**: لا محرّك
        # محليًّا هنا أصلًا، وفحصُ `Phase.READY` الخاص به يرفض محادثةً
        # صالحة.
        if self.config.is_cloud_chat:
            return self._chat_cloud(message, history or [])

        # ⚠️ **وضع العرض: المحرّك المحلي، وأخطاؤه المصنَّفة كما هي.**
        # رسائل `demo_engine` عربية وتقول ما يُفعل، فتُمرَّر بلا تغليف يضيع
        # التفريق بين «لم يبدأ» و«يُحمَّل» و«تأخّر».
        if self._demo is not None:
            try:
                reply = self._demo.chat(SYSTEM_PROMPT, message)
            except DemoEngineError as exc:
                raise ChatUnavailableError(str(exc)) from exc
            return ChatReply(reply=reply, engine=self.engine_name, cloud=False)

        base_url = self._supervisor.base_url
        if base_url is None or self.state.phase is not Phase.READY:
            raise ChatUnavailableError(
                self.state.message or "GovMind لم يجهز بعد على هذا الجهاز."
            )

        try:
            response = httpx.post(
                f"{base_url}/chat/completions",
                json={
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": message},
                    ],
                    "stream": False,
                },
                timeout=CHAT_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            # ⚠️ لا يُمرَّر نصّ الاستثناء: قد يحمل العنوان والمنفذ.
            raise ChatUnavailableError(
                "تعذّر الوصول إلى مودل GovMind على هذا الجهاز. "
                "أعد تشغيل GovMind ثم حاول مرة أخرى."
            ) from exc

        if response.status_code != 200:
            raise ChatUnavailableError(
                "تعذّر توليد الرد على هذا الجهاز. أعد المحاولة."
            )

        try:
            payload = response.json()
            reply = payload["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ChatUnavailableError(
                "وصل ردٌّ غير مفهوم من مودل GovMind. أعد تشغيل GovMind."
            ) from exc

        return ChatReply(
            reply=str(reply or "").strip(), engine=self.engine_name, cloud=False
        )

    def _chat_cloud(self, message: str, history: list[dict[str, str]]) -> ChatReply:
        """يمرّر الرسالة إلى السيرفر ببيان اعتماد هذا الجهاز.

        ⚠️ **السيرفر يعيد الفحوص كلها.** ما يفحصه الـRuntime هنا راحةٌ
        للعميل لا حراسة: بيان الاعتماد قد يكون أُبطل قبل ثانية، والاشتراك
        قد يكون انتهى، والحكم للسيرفر وحده.
        """
        credential = self._device_credential()
        if credential is None:
            raise ChatUnavailableError(
                "أكمل تثبيت وربط GovMind من إضافة المتصفح."
            )

        try:
            data = self._control.chat(
                device_credential=credential,
                message=message,
                # ⚠️ **يُقلَّم هنا لا في السيرفر**: تجاوز السقف يعود بخطأ
                # تحقّق لا يفهمه العميل، وأقدمُ الرسائل أقلّها أثرًا.
                history=_recent(history, MAX_HISTORY),
            )
        except DeviceNotActivatedError as exc:
            # ⚠️ **بيان أُبطل = يُنسى فورًا.** إبقاؤه يعني إعادة إرساله في
            # كل رسالة ورفضًا متكرّرًا، والعميل يرى الرسالة نفسها بلا مخرج.
            self._forget_credential(str(exc))
            raise ChatUnavailableError(str(exc)) from exc
        except SubscriptionBlockedError as exc:
            # الرسالة تحمل السبب والتاريخ من السيرفر — تُعرض كما وردت.
            self.state.set(Phase.BLOCKED, str(exc))
            raise ChatUnavailableError(str(exc)) from exc
        except ControlPlaneError as exc:
            # يغطي انقطاع الشبكة، وتوقّف المزوّد، ونفاد الحصة، وتجاوز
            # المهلة — كلها برسائل عربية مصنَّفة من طبقة الـControl Plane.
            raise ChatUnavailableError(str(exc)) from exc

        reply = str(data.get("reply") or "").strip()
        if not reply:
            raise ChatUnavailableError(
                "وصل ردٌّ فارغ من خدمة GovMind. أعد المحاولة."
            )
        return ChatReply(
            reply=reply,
            engine=str(data.get("provider") or self.engine_name),
            # ⚠️ **من ردّ السيرفر لا من إعداد الجهاز.** السيرفر يعرف أين
            # عالج فعلًا؛ ملفُّ إعداد على جهاز العميل قد يكذب.
            cloud=bool(data.get("cloud")),
        )

    # ------------------------------------------------------------------
    # الإقلاع
    # ------------------------------------------------------------------
    def prepare(self) -> None:
        """المسار الكامل من الإقلاع إلى الجاهزية.

        يُستدعى في خيط منفصل: تحميل مودل بالجيجابايتات قد يستغرق دقائق،
        وحجب خيط الخادم طوالها يجعل `/health` نفسه لا يستجيب — وهو ما
        تستطلعه الإضافة لتعرف أن الـRuntime يعمل.
        """
        if not self.is_activated:
            self.state.set(Phase.AWAITING_ACTIVATION)
            return

        if not self.refresh_entitlement():
            return

        # ⚠️ **وضع العرض يتفرّع هنا، بعد الاستحقاق لا قبله.** من لا يملك
        # اشتراكًا ساريًا لا يستعمل GovMind ولو كان المحرّك على جهازه.
        if self._demo is not None:
            self._prepare_demo()
            return

        # ⚠️ **الوضع السحابي: لا تنزيل ولا محرّك.** جهوزيةُ التطبيق هنا
        # هي الاستحقاق الساري وحده، وقد تحقّق قبل سطرين. عرضُ شاشة تنزيل
        # لمودل لن يُنزَّل هو العطل نفسه الذي أُصلح في الإضافة.
        if self.config.is_cloud_chat:
            self.state.set(Phase.READY)
            return

        if not self._models.is_installed():
            self.download_model()
            return

        self.start_model()

    def _prepare_demo(self) -> None:
        """يتحقق أن محرّك العرض يعمل وأن مودله مثبَّت.

        **لا تنزيل ولا تشغيل عملية.** نجاحُ الفحص وحده يعني الجهوزية؛
        وفشلُه رسالةٌ عربية تقول ما يفعله المستخدم — لا شاشة تقدّم بلا
        نهاية عن تنزيل لا يجري.
        """
        assert self._demo is not None
        self.state.set(Phase.STARTING_MODEL)
        try:
            self._demo.probe()
        except DemoEngineError as exc:
            self.state.set(Phase.ERROR, str(exc))
            return
        self.state.set(Phase.READY)

    def start_background_preparation(self) -> None:
        """يبدأ :meth:`prepare` في خيط، ولا يبدأ ثانيًا إن كان يعمل."""
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._guarded_prepare, name="govmind-prepare", daemon=True
            )
            self._worker.start()

    def _guarded_prepare(self) -> None:
        try:
            self.prepare()
        except Exception as exc:  # pragma: no cover - شبكة أمان
            logger.exception("فشل تجهيز الـRuntime")
            self.state.set(
                Phase.ERROR,
                "حدث خطأ غير متوقع أثناء التجهيز. أعد تشغيل GovMind.",
            )
            del exc

    def shutdown(self) -> None:
        """إيقاف نظيف — **لا تُترك عملية ابنة يتيمة ولا اتصال مفتوح**."""
        self._supervisor.stop()
        if self._demo is not None:
            self._demo.close()
        close = getattr(self._control, "close", None)
        if callable(close):
            close()
