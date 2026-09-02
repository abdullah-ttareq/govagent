"""عميل Backend المستضاف — الطرف الوحيد الذي يتحدّث إليه الـRuntime عبر الشبكة.

**لا يتحدّث الـRuntime إلى Supabase ولا إلى Azure مباشرة.** لا يملك مفتاح
`service_role` ولا سلسلة اتصال Azure ولا مِلح التجزئة — ولا يجوز أن يملكها،
فهو برنامج على جهاز عميل. كل ما يحتاجه يمرّ بـBackend المستضاف الذي يفرض
الاستحقاق ويوقّع الروابط.

**المصادقة:** بيان اعتماد الجهاز في ترويسة `X-GovMind-Device-Credential`.
يصدره السيرفر لحظةَ نجاح استبدال جلسة التركيب، ولا يُخزَّن على السيرفر إلا
مجزّأً. **يُلصق هنا، في جانب الخادم من الـRuntime** — ولا يمرّ بأي شيفرة
تعمل في المتصفح.

⚠️ **قائمة بيضاء صريحة للمسارات.** لا يوجد وكيل مفتوح: كل مسار يمرّ من
هنا يجب أن يكون في :data:`ALLOWED_ROUTES`، وإلا رُفض قبل أن يُفتح اتصال.
الواجهة المحلية تنادي الـRuntime وحده، والـRuntime ينادي هذه المسارات
وحدها. سببه المباشر: أي «مرّر ما يصلك» هنا يحوّل الـRuntime إلى بوابة
يستطيع بها موقعٌ محلي أو برنامج على الجهاز أن ينادي الـControl Plane
ببيان اعتماد العميل.

⚠️ **لا يُسجَّل بيان الاعتماد ولا رابط SAS ولا رمز التركيب.** رسائل الخطأ
هنا مكتوبة يدويًا ولا تمرّر جسم رد ولا رابطًا.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEVICE_HEADER = "X-GovMind-Device-Credential"

#: مهلة قصيرة: كلها نداءات تحكّم صغيرة لا تنزيل ولا توليد.
DEFAULT_TIMEOUT = 30.0

#: مهلة المحادثة وحدها — **أطول لأن خلفها توليد نصّ لا استعلام جدول**.
#:
#: ⚠️ **منتهية عمدًا.** بلا سقف، ردٌّ لا يأتي يترك التطبيق على شاشة انتظار
#: بلا نهاية — وهو العطل نفسه الذي أُصلح في الإضافة. وهي أقصر من مهلة
#: السيرفر تجاه المزوّد، ليصل الخطأ المصنَّف بدل قطعٍ غامض.
CHAT_TIMEOUT = 90.0

#: ⚠️ **كل مسار يستطيع الـRuntime مناداته على الـControl Plane، بلا استثناء.**
#:
#: القائمة أزواج `(method, path)` مطابقة حرفية — لا أنماط ولا بادئات: نمطٌ
#: مثل `/api/runtime/*` يصير وكيلًا مفتوحًا على كل ما يُضاف إلى ذلك الحيّز
#: لاحقًا، بلا قرار من أحد.
#:
#: إضافة مسار هنا **قرار أمني**: معناه أن هذا المسار يُنادى ببيان اعتماد
#: جهاز عميل. ويحرس ذلك اختبار في `tests/test_control_plane.py`.
ALLOWED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        # استبدال جلسة التركيب. **بلا بيان اعتماد** — هو المسار الذي يصدره.
        ("POST", "/api/runtime/activate"),
        # حالة الاشتراك لهذا الجهاز.
        ("GET", "/api/runtime/entitlement"),
        # رابط تنزيل المودل وبيانات التحقق منه.
        ("GET", "/api/runtime/model"),
        # المحادثة. **المسار الوحيد المضاف من أجل الاستدلال السحابي**:
        # السيرفر يحمل مفتاح المزوّد، والجهاز يحمل بيان اعتماده هو.
        ("POST", "/api/runtime/chat"),
    }
)


class ControlPlaneError(Exception):
    """خطأ من Backend المستضاف، برسالة عربية صالحة للعرض."""


class RouteNotAllowedError(ControlPlaneError):
    """مسار خارج القائمة البيضاء. **عطل برمجي لا حالة تشغيل.**

    يُرفع قبل فتح أي اتصال وقبل قراءة بيان الاعتماد، فلا يخرج شيء من
    الجهاز على مسار لم يُقرَّر.
    """


class OfflineError(ControlPlaneError):
    """لم يصل الطلب أصلًا — لا شبكة أو الخدمة متوقفة."""


class DeviceNotActivatedError(ControlPlaneError):
    """الجهاز غير مفعَّل أو أُبطل تفعيله."""


class SubscriptionBlockedError(ControlPlaneError):
    """الاشتراك لا يسمح بالخدمة، والرسالة تشرح السبب."""


class ActivationRejectedError(ControlPlaneError):
    """رُفض التفعيل: رمز غير صالح، أو جهاز آخر مفعّل."""


class ModelUnavailableError(ControlPlaneError):
    """تعذّر توليد ردّ: المزوّد متوقف، أو نفدت الحصة، أو تجاوز المهلة.

    ⚠️ **منفصل عن :class:`OfflineError`.** هذا يعني أن السيرفر ردّ وشرح
    السبب، وذاك يعني أنه لم يُبلَغ أصلًا — والفرق يغيّر ما يفعله العميل.
    """


@dataclass(frozen=True)
class Entitlement:
    """حالة الاشتراك كما يراها هذا الجهاز."""

    status: str
    expires_at: str
    is_usable: bool
    blocked_reason: str | None
    device_name: str
    #: بريد صاحب الحساب — يعرضه التطبيق المثبَّت. **بلا اسم جهة ولا دور.**
    account_email: str = ""


@dataclass(frozen=True)
class ActivationResult:
    """نتيجة استبدال جلسة التركيب.

    ⚠️ ``credential`` سرّ يصل **مرة واحدة**. يُحفظ بـDPAPI فورًا، ولا
    يُسجَّل ولا يُعاد في أي رد يصل المتصفح أو الإضافة.
    """

    credential: str
    activation_id: int
    status: str
    expires_at: str


@dataclass(frozen=True)
class ModelArtifactInfo:
    """رابط المودل وبيانات التحقق منه."""

    download_url: str
    file_name: str
    sha256: str
    size_bytes: int


class ControlPlaneClient:
    """نداءات الـRuntime إلى Backend المستضاف."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout
        #: عميل يملكه هذا الصنف ويعيش بعمر العملية — انظر :meth:`_session`.
        self._owned: httpx.Client | None = None
        self._owned_lock = threading.Lock()

    def _session(self) -> httpx.Client:
        """يعيد عميل HTTP، **مُنشَأً مرة واحدة ومُعاد استعماله**.

        ⚠️ **هذا إصلاح عطل حيّ، لا تحسين أداء.**

        كان كل طلب ينشئ `httpx.Client()` جديدًا، وإنشاؤه يبني سياق TLS
        بقراءة ملف شهادات `certifi`. في البناء المجمَّع بـPyInstaller
        (`--onefile`) يُفكّ ذلك الملف إلى مجلد مؤقّت باسم `_MEI…`، وحين
        يختفي ذلك الملف من تحت العملية الحيّة — تنظيف مجلد مؤقّت، أو مضادّ
        فيروسات — يفشل كل طلب بعدها بـ`FileNotFoundError` من
        `ssl.create_default_context`. وهو ما يُقرأ في سجلّ الجهاز حرفيًا:

            File "govmind_runtime\control_plane.py", line 98, in _request
            File "ssl.py", line 717, in create_default_context
            FileNotFoundError: [Errno 2] No such file or directory

        الأثر أن **تحديث الاستحقاق الدوري يسقط بعد ساعة من الإقلاع**، ومعه
        كل نداء إلى خدمة GovMind — بلا رسالة يفهمها العميل.

        العميل الواحد يقرأ الشهادات **مرة واحدة عند أول نداء**، وهو يقع بعد
        ثوانٍ من الإقلاع بينما الملف المؤقّت سليم، ثم يعيش بعمر العملية.
        وفائدته الثانية إعادة استعمال الاتصال بدل فتح TLS جديد كل ساعة.

        الإنشاء تحت قفل: خيط الاستحقاق الدوري وخيط التجهيز قد يبلغانه معًا
        عند أول نداء، فينشئان عميلين ويُهمل أحدهما بلا إغلاق.
        """
        if self._client is not None:
            return self._client
        with self._owned_lock:
            if self._owned is None:
                self._owned = httpx.Client(timeout=self._timeout)
            return self._owned

    def close(self) -> None:
        """يغلق العميل الذي يملكه هذا الصنف. **لا يغلق عميلًا مُمرَّرًا**.

        العميل المُمرَّر يملكه من مرّره — إغلاقه هنا يكسر مستدعيًا يظنّه
        حيًّا، وهو ما يقع في الاختبارات حين يُشارَك عميل بين حالتين.
        """
        with self._owned_lock:
            if self._owned is not None:
                self._owned.close()
                self._owned = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        device_credential: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """ينفّذ نداءً على الـControl Plane، **بعد فحص القائمة البيضاء**.

        ⚠️ الفحص أول سطر عمل في الدالة: قبل بناء الترويسات وقبل فتح أي
        اتصال. مسار خارج القائمة لا يخرج منه بايت واحد من هذا الجهاز.
        """
        route = (method.upper(), path)
        if route not in ALLOWED_ROUTES:
            # ⚠️ السطر يذكر الفعل والمسار لا بيان الاعتماد ولا الجسم.
            logger.error(
                "رُفض مسار خارج قائمة GovMind المسموح بها: %s %s", route[0], route[1]
            )
            raise RouteNotAllowedError(
                "هذا الطلب غير مسموح به من GovMind على هذا الجهاز."
            )

        headers: dict[str, str] = {}
        if device_credential:
            headers[DEVICE_HEADER] = device_credential

        try:
            response = self._session().request(
                method,
                f"{self._base_url}{path}",
                json=json,
                headers=headers,
                # مهلة هذا النداء وحده حين تُطلب — نداء التوليد أطول من
                # نداءات التحكّم، ولا يصحّ أن يرفع مهلتها كلها معه.
                **({} if timeout is None else {"timeout": timeout}),
            )
        except OSError as exc:
            # ⚠️ `OSError` لا `httpx.HTTPError` وحده.
            #
            # فشلُ بناء سياق TLS يخرج `FileNotFoundError` — وهو `OSError` لا
            # `HTTPError` — فكان يمرّ بلا التقاط ويسقط خيط الاستحقاق كله
            # بأثر بايثون خام في السجلّ. الآن يصير «تعذّر الاتصال»، وهي
            # الرسالة الصحيحة للعميل: لا شيء يستطيع فعله غير المحاولة.
            logger.warning("تعذّر تنفيذ نداء خدمة GovMind: %s", type(exc).__name__)
            raise OfflineError(
                "تعذّر الاتصال بخدمة GovMind. تأكد من اتصال الجهاز بالإنترنت."
            ) from exc
        except httpx.HTTPError as exc:
            raise OfflineError(
                "تعذّر الاتصال بخدمة GovMind. تأكد من اتصال الجهاز بالإنترنت."
            ) from exc

        return self._read(response)

    @staticmethod
    def _read(response: httpx.Response) -> dict[str, Any]:
        """يحوّل الرد إلى بيانات أو إلى خطأ مصنَّف برسالة السيرفر العربية."""
        detail = ""
        payload: Any = None
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("detail") or "")
        except Exception:
            payload = None

        if response.is_success:
            return payload if isinstance(payload, dict) else {}

        if response.status_code in (401, 403):
            # ٤٠١ على مسار التفعيل = رمز غير صالح؛ وعلى غيره = جهاز غير مفعّل.
            if "/activate" in str(response.request.url):
                raise ActivationRejectedError(
                    detail or "رمز التركيب غير صالح أو انتهت صلاحيته."
                )
            if response.status_code == 403 and detail:
                # رسالة الاشتراك تحمل السبب والتاريخ، فتُعرض كما وردت.
                raise SubscriptionBlockedError(detail)
            raise DeviceNotActivatedError(
                detail or "هذا الجهاز غير مفعَّل. أعد التفعيل من إضافة GovMind."
            )
        if response.status_code == 409:
            raise ActivationRejectedError(
                detail
                or "هذا الاشتراك مفعّل على جهاز آخر. استبدل الجهاز من "
                "إضافة GovMind في المتصفح."
            )
        if response.status_code == 503 and detail:
            # ⚠️ **قبل فرع الـ5xx العام عمدًا.**
            #
            # السيرفر يردّ بـ٥٠٣ ورسالة عربية تقول أيّ عطل وقع: المزوّد
            # متوقف، أو نفدت الحصة، أو تجاوز التوليد المهلة. طيُّها في
            # «الخدمة لا تستجيب» يمحو الفرق، والعميل يحتاجه: نفادُ الحصة
            # لا يُصلحه انتظارُ دقيقة.
            raise ModelUnavailableError(detail)
        if response.status_code >= 500:
            raise ControlPlaneError(
                "خدمة GovMind لا تستجيب حاليًا. أعد المحاولة بعد قليل."
            )
        raise ControlPlaneError(
            detail or "تعذّر إتمام العملية. أعد المحاولة بعد قليل."
        )

    # -- المسارات -------------------------------------------------------
    def activate(
        self, *, token: str, device_secret: str, device_name: str
    ) -> ActivationResult:
        """يستبدل رمز التركيب بتفعيل جهاز، **ويستلم بيان الاعتماد**.

        ⚠️ الرمز وسرّ الهوية يمرّان في الجسم ولا يُسجَّلان، **وبيان الاعتماد
        العائد لا يُسجَّل ولا يُعاد إلى أي مستدعٍ غير خدمة الـRuntime.**

        Raises:
            ActivationRejectedError: رمز مرفوض أو جهاز آخر مفعّل.
            ControlPlaneError: بفروعه — انقطاع أو خطأ خدمة أو ردٌّ بلا ربط.
        """
        logger.info("إرسال طلب ربط الجهاز إلى خدمة GovMind.")
        data = self._request(
            "POST",
            "/api/runtime/activate",
            json={
                "token": token,
                "device_secret": device_secret,
                "device_name": device_name,
            },
        )

        credential = str(data.get("device_credential") or "").strip()
        if not credential:
            # سيرفر لا يصدر بيان اعتماد يترك الجهاز مربوطًا بلا وسيلة
            # مصادقة — وهو فشل، لا نجاح ناقص.
            raise ControlPlaneError(
                "لم تُصدر خدمة GovMind ربطًا لهذا الجهاز. أعد المحاولة."
            )

        return ActivationResult(
            credential=credential,
            activation_id=int(data.get("activation_id") or 0),
            status=str(data.get("status") or ""),
            expires_at=str(data.get("expires_at") or ""),
        )

    def entitlement(self, device_credential: str) -> Entitlement:
        """يقرأ حالة الاشتراك لهذا الجهاز."""
        data = self._request(
            "GET", "/api/runtime/entitlement", device_credential=device_credential
        )
        return Entitlement(
            status=str(data.get("status") or ""),
            expires_at=str(data.get("expires_at") or ""),
            is_usable=bool(data.get("is_usable")),
            blocked_reason=data.get("blocked_reason"),
            device_name=str(data.get("device_name") or ""),
            account_email=str(data.get("account_email") or ""),
        )

    def chat(
        self,
        *,
        device_credential: str,
        message: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """يمرّر رسالة العميل إلى السيرفر ويعيد الرد.

        ⚠️ **الجهاز لا ينادي المزوّد.** مفتاح المزوّد سرّ سيرفر؛ وضعه هنا
        يعني نشره على كل جهاز عميل. فالجهاز يصادق ببيان اعتماده، والسيرفر
        يحمل المفتاح ويناديه.

        ⚠️ **لا يُسجَّل نصّ الرسالة ولا الرد ولا بيان الاعتماد** — الأخير
        يمرّ في الترويسة كبقية المسارات ولا يظهر في أي سطر سجلّ.
        """
        payload: dict[str, Any] = {"message": message, "history": history or []}
        return self._request(
            "POST",
            "/api/runtime/chat",
            json=payload,
            device_credential=device_credential,
            timeout=CHAT_TIMEOUT,
        )

    def model_artifact(self, device_credential: str) -> ModelArtifactInfo:
        """يطلب رابط تنزيل المودل وبيانات التحقق منه.

        ⚠️ الرابط **يُستهلك فورًا ولا يُحفظ**: قصير العمر ويعمل بلا هوية.
        """
        data = self._request(
            "GET", "/api/runtime/model", device_credential=device_credential
        )
        return ModelArtifactInfo(
            download_url=str(data.get("download_url") or ""),
            file_name=str(data.get("file_name") or "govmind-model.gguf"),
            sha256=str(data.get("sha256") or ""),
            size_bytes=int(data.get("size_bytes") or 0),
        )
