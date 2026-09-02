"""محرّك وضع العرض الأكاديمي — Ollama على الاسترجاع المحلي.

**لماذا وضع عرض أصلًا؟** المسار الإنتاجي ينزّل مودلًا بالجيجابايتات من
Azure ويشغّله بـ`llama-server.exe`. ذلك يحتاج تخزينًا سحابيًا مدفوعًا،
وثنائيات موقَّعة رقميًا. للعرض الأكاديمي يكفي محرّك مثبَّت على الجهاز
أصلًا، بلا تخزين سحابي وبلا تشغيل أي ملف تنفيذي مرفق.

**ما يفعله هذا الوضع، وما لا يفعله:**

* ينادي ``POST /api/chat`` بـ``stream=false`` على العنوان المحلي وحده.
* **لا يشغّل `llama-server.exe`** — ولا يلمسه.
* **لا ينزّل أي مودل من Azure**، ولا يحتاج `AZURE_MODEL_*` إطلاقًا.
* **لا يعيد ردًّا مصطنعًا بحال.** كل ردّ يخرج من هنا جاء من المحرّك؛ وإن
  تعذّر ذلك خرج **خطأ** لا نصّ ملفَّق. ردٌّ مزيّف في منتج محادثة كذبٌ على
  المستخدم، لا «تجربة أفضل».

⚠️ **لا يُسجَّل نصّ المستخدم ولا ردّ المحرّك.** السجلّ يحمل أحداثًا وأرقامًا:
«أُرسل طلب»، ورمز الحالة، وزمن الرد. لا محتوى.

⚠️ **رسائل الخطأ عربية ومصنَّفة**، لأن إجراء المستخدم يختلف بينها: محرّك
لم يبدأ يُشغَّل، ومودل ناقص يُنزَّل، ومودل يُحمَّل يُنتظر، ومهلة تُعاد.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

#: مهلة الاتصال — قصيرة: محرّك لا يعمل يُعرف فورًا، ولا معنى لانتظاره.
CONNECT_TIMEOUT = 5.0

#: مهلة قراءة الرد — طويلة: التوليد على المعالج قد يستغرق دقائق على أول
#: طلب، لأن المودل يُحمَّل في الذاكرة عندها.
READ_TIMEOUT = 300.0

#: مهلة نداءات الاستطلاع القصيرة (`/api/tags` و`/api/ps`).
PROBE_TIMEOUT = 10.0


class DemoEngineError(Exception):
    """خطأ في محرّك العرض، برسالة عربية صالحة للعرض مباشرة."""


class DemoEngineUnavailableError(DemoEngineError):
    """المحرّك لا يستجيب — لم يُشغَّل، أو أُغلق."""


class DemoModelMissingError(DemoEngineError):
    """المحرّك يعمل لكن المودل المطلوب غير مثبَّت فيه."""


class DemoModelLoadingError(DemoEngineError):
    """المودل ما زال يُحمَّل في الذاكرة — انتظارٌ لا خطأ دائم."""


class DemoEngineTimeoutError(DemoEngineError):
    """انتهت المهلة قبل أن يكمل المحرّك ردّه."""


class DemoEngineRejectedError(DemoEngineError):
    """ردّ المحرّك بخطأ."""


class OllamaEngine:
    """عميل Ollama — **قراءة ومحادثة فقط**، بلا تشغيل عمليات ولا تنزيل.

    ⚠️ **لا يطلق `ollama.exe` ولا أي عملية.** تشغيل المحرّك مسؤولية
    الجهاز؛ وإن لم يعمل قيل ذلك للمستخدم برسالة يفهمها. إطلاق برامج من
    داخل الـRuntime سلوك لا يخصّه، ويجعل الفشل صامتًا.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model.strip()
        self._client = client
        self._owned: httpx.Client | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    @property
    def model(self) -> str:
        return self._model

    def _session(self) -> httpx.Client:
        """عميل واحد يعيش بعمر العملية — كما في `control_plane`.

        إنشاء عميل لكل طلب يعيد بناء سياق TLS في كل مرة، وهو ما أسقط
        نداءات الاستحقاق في بناء مجمَّع سابق. المهلة مركَّبة: اتصالٌ قصير
        وقراءةٌ طويلة، فالبطء المتوقّع هو التوليد لا بلوغ المحرّك.
        """
        if self._client is not None:
            return self._client
        with self._lock:
            if self._owned is None:
                self._owned = httpx.Client(
                    timeout=httpx.Timeout(
                        connect=CONNECT_TIMEOUT,
                        read=READ_TIMEOUT,
                        write=30.0,
                        pool=CONNECT_TIMEOUT,
                    )
                )
            return self._owned

    def close(self) -> None:
        with self._lock:
            if self._owned is not None:
                self._owned.close()
                self._owned = None

    # ------------------------------------------------------------------
    def installed_models(self) -> list[str]:
        """أسماء المودلات المثبَّتة في المحرّك.

        Raises:
            DemoEngineUnavailableError: المحرّك لا يستجيب.
        """
        try:
            response = self._session().get(
                f"{self._base_url}/api/tags", timeout=PROBE_TIMEOUT
            )
        except (httpx.HTTPError, OSError) as exc:
            raise DemoEngineUnavailableError(self._unavailable_message()) from exc

        if response.status_code != 200:
            raise DemoEngineUnavailableError(self._unavailable_message())

        try:
            payload = response.json()
        except ValueError as exc:
            raise DemoEngineUnavailableError(self._unavailable_message()) from exc

        return [
            str(item.get("name") or "")
            for item in (payload.get("models") or [])
            if item.get("name")
        ]

    def probe(self) -> None:
        """يتحقق أن المحرّك يعمل وأن المودل المطلوب مثبَّت فيه.

        Raises:
            DemoEngineUnavailableError | DemoModelMissingError
        """
        names = self.installed_models()
        if self._model not in names:
            raise DemoModelMissingError(
                f"المودل «{self._model}» غير مثبَّت في محرّك GovMind على هذا "
                f"الجهاز. ثبّته ثم أعد المحاولة."
            )
        logger.info("محرّك العرض جاهز، والمودل المطلوب مثبَّت.")

    def is_loaded(self) -> bool:
        """هل المودل محمَّل في الذاكرة الآن؟ للتفريق بين «يُحمَّل» و«تأخّر»."""
        try:
            response = self._session().get(
                f"{self._base_url}/api/ps", timeout=PROBE_TIMEOUT
            )
            if response.status_code != 200:
                return False
            loaded = {
                str(item.get("name") or "")
                for item in (response.json().get("models") or [])
            }
            return self._model in loaded
        except (httpx.HTTPError, OSError, ValueError):
            return False

    # ------------------------------------------------------------------
    def chat(self, system_prompt: str, message: str) -> str:
        """يرسل رسالة واحدة ويعيد ردّ المحرّك كما ورد.

        ⚠️ **لا يُسجَّل النصّ المرسَل ولا الرد** — أحداثٌ وأرقام فقط.

        Raises:
            DemoEngineError: بفروعه، كلها برسالة عربية جاهزة للعرض.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            # ⚠️ **بلا بثّ.** الواجهة تنتظر ردًّا واحدًا؛ والبثّ يحتاج مسارًا
            # مختلفًا في الـRuntime والواجهة معًا، ولا يفيد عرضًا أكاديميًا.
            "stream": False,
        }

        started = time.monotonic()
        try:
            response = self._session().post(
                f"{self._base_url}/api/chat", json=payload
            )
        except httpx.TimeoutException as exc:
            raise self._timeout_error() from exc
        except (httpx.HTTPError, OSError) as exc:
            raise DemoEngineUnavailableError(self._unavailable_message()) from exc

        elapsed = time.monotonic() - started
        logger.info(
            "ردّ محرّك العرض برمز %s في %.1f ثانية.", response.status_code, elapsed
        )

        if response.status_code != 200:
            raise self._classify_status(response)

        try:
            body = response.json()
        except ValueError as exc:
            raise DemoEngineRejectedError(
                "وصل ردٌّ غير مفهوم من محرّك GovMind على هذا الجهاز. أعد المحاولة."
            ) from exc

        # ⚠️ حتى في النجاح: خطأ في الجسم يعني فشلًا لا ردًّا.
        if body.get("error"):
            raise DemoEngineRejectedError(self._rejected_message())

        content = ((body.get("message") or {}).get("content") or "").strip()
        if not content:
            # **لا يُخترع ردّ.** ردٌّ فارغ فشلٌ يُقال.
            raise DemoEngineRejectedError(
                "لم يُنتج المودل ردًّا على هذا الطلب. أعد صياغة سؤالك وحاول "
                "مرة أخرى."
            )
        return content

    # ------------------------------------------------------------------
    def _unavailable_message(self) -> str:
        return (
            "محرّك GovMind لا يعمل على هذا الجهاز. شغّله ثم اضغط «إعادة "
            "التحقق»."
        )

    def _rejected_message(self) -> str:
        # ⚠️ **لا يُمرَّر نصّ خطأ المحرّك.** إنجليزيّ، وقد يحمل مسارات ملفات.
        return (
            "رفض محرّك GovMind هذا الطلب. أعد المحاولة، وإن تكرر فأعد تشغيل "
            "المحرّك."
        )

    def _timeout_error(self) -> DemoEngineError:
        """يفرّق بين «ما زال يُحمَّل» و«تأخّر أكثر من اللازم».

        الفرق يقرّر ما يفعله المستخدم: الأول ينتظر، والثاني يعيد المحاولة
        أو يختار سؤالًا أقصر. و`‎/api/ps` هو ما يحسم أيّهما.
        """
        if not self.is_loaded():
            return DemoModelLoadingError(
                "ما زال المودل يُحمَّل في ذاكرة هذا الجهاز. انتظر قليلًا ثم "
                "أعد المحاولة — أول طلب هو الأبطأ."
            )
        return DemoEngineTimeoutError(
            "استغرق الرد وقتًا أطول من المتوقّع. أعد المحاولة، أو اجعل سؤالك "
            "أقصر."
        )

    def _classify_status(self, response: httpx.Response) -> DemoEngineError:
        """يصنّف رمز الحالة إلى خطأ برسالة تقول ما يُفعل."""
        code = response.status_code

        # 404 من Ollama يعني غالبًا «المودل غير موجود».
        if code == 404:
            return DemoModelMissingError(
                f"المودل «{self._model}» غير مثبَّت في محرّك GovMind على هذا "
                f"الجهاز. ثبّته ثم أعد المحاولة."
            )
        # 503 يعني أن المحرّك مشغول بالتحميل.
        if code == 503:
            return DemoModelLoadingError(
                "ما زال المودل يُحمَّل في ذاكرة هذا الجهاز. انتظر قليلًا ثم "
                "أعد المحاولة."
            )
        return DemoEngineRejectedError(self._rejected_message())
