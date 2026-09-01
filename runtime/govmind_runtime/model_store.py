"""تنزيل ملف المودل والتحقق منه.

**لا يُحزَم المودل داخل المثبّت.** حجمه بالجيجابايتات، وحزمه يجعل كل تحديث
صغير في البرنامج يعيد تنزيله كاملًا. يُنزَّل مرة بعد التفعيل من مدوّنة Azure
منفصلة برابط SAS قصير العمر يطلبه الـRuntime من Backend المستضاف.

**قاعدة واحدة تحكم هذه الوحدة: لا يُعامَل ملفٌ غير مُتحقَّق منه كمثبَّت.**
التنزيل يكتب في `‎.part`، ولا يُعاد التسمية إلى `‎.gguf` إلا بعد مطابقة
الحجم **والتجزئة** معًا. انقطاعُ التنزيل يترك `‎.part` يُستأنف منه، وفشلُ
التحقق يحذفه.

⚠️ **رابط SAS لا يُعرض ولا يُسجَّل ولا يُكتب على القرص.** يُطلب عند الحاجة
ويُستهلك فورًا، ولا يظهر في أي رسالة خطأ.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

#: حجم القطعة عند القراءة والكتابة والتجزئة.
CHUNK_BYTES = 1 << 20  # 1 MiB

#: هامش المساحة فوق حجم الملف. التنزيل يكتب `‎.part` ثم يعيد تسميته، فلا
#: يحتاج ضعف الحجم — لكن هامشًا معقولًا يمنع امتلاء القرص عند آخر ميغابايت.
DISK_MARGIN_BYTES = 512 << 20  # 512 MiB


class ModelError(Exception):
    """خطأ في المودل، برسالة عربية صالحة للعرض على المستخدم."""


class InsufficientDiskSpaceError(ModelError):
    """المساحة الحرة لا تكفي الملف وهامشه."""


class ModelVerificationError(ModelError):
    """الحجم أو التجزئة لا تطابق المتوقَّع — ملف تالف أو مستبدَل."""


class DownloadCancelled(ModelError):
    """أُلغي التنزيل بطلب من المستخدم."""


@dataclass(frozen=True)
class ModelArtifact:
    """وصف الملف المتوقَّع كما أعطاه الـBackend."""

    download_url: str
    file_name: str
    sha256: str
    size_bytes: int


@dataclass
class DownloadProgress:
    """تقدّم التنزيل كما يُعرض بالعربية."""

    received: int
    total: int

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        return min(100, int(self.received * 100 / self.total))


ProgressCallback = Callable[[DownloadProgress], None]


def free_space(path: Path) -> int:
    """المساحة الحرة على القرص الذي يحوي المسار (يُنشأ إن لزم)."""
    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path).free


def sha256_of(path: Path, *, on_progress: ProgressCallback | None = None) -> str:
    """يحسب تجزئة ملف على دفعات — لا يُحمَّل ملف بالجيجابايتات في الذاكرة."""
    digest = hashlib.sha256()
    total = path.stat().st_size
    read = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            read += len(chunk)
            if on_progress is not None:
                on_progress(DownloadProgress(received=read, total=total))
    return digest.hexdigest()


class ModelStore:
    """يدير ملف المودل على القرص: تنزيلًا واستئنافًا وتحققًا."""

    def __init__(
        self,
        *,
        model_path: Path,
        part_path: Path,
        client_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self._model_path = Path(model_path)
        self._part_path = Path(part_path)
        self._client_factory = client_factory or (lambda: httpx.Client(timeout=60.0))
        self._cancelled = False

    # -- الحالة ---------------------------------------------------------
    @property
    def model_path(self) -> Path:
        return self._model_path

    def is_installed(self) -> bool:
        """هل يوجد مودل **مُتحقَّق منه**؟

        وجود `‎.gguf` وحده كافٍ: لا يصل الملف إلى هذا الاسم إلا بعد مطابقة
        الحجم والتجزئة. `‎.part` مهما كبر ليس مودلًا مثبَّتًا.
        """
        return self._model_path.is_file() and self._model_path.stat().st_size > 0

    def partial_bytes(self) -> int:
        """ما نُزّل حتى الآن من محاولة سابقة، أو صفر."""
        return self._part_path.stat().st_size if self._part_path.is_file() else 0

    def cancel(self) -> None:
        """يطلب إيقاف التنزيل الجاري. `‎.part` **يبقى** ليُستأنف منه."""
        self._cancelled = True

    def reset_cancel(self) -> None:
        self._cancelled = False

    def discard_partial(self) -> None:
        self._part_path.unlink(missing_ok=True)

    # -- التنزيل --------------------------------------------------------
    def ensure_space(self, artifact: ModelArtifact) -> None:
        """يتحقق من المساحة **قبل** بدء التنزيل.

        الفحص المسبق أفضل من اكتشاف الامتلاء بعد ساعة من التنزيل، ورسالته
        تذكر الرقمين فيعرف المستخدم كم يحتاج أن يفرّغ.
        """
        needed = max(0, artifact.size_bytes - self.partial_bytes())
        available = free_space(self._part_path.parent)
        if available < needed + DISK_MARGIN_BYTES:
            raise InsufficientDiskSpaceError(
                f"المساحة الحرة لا تكفي لتنزيل المودل. المطلوب نحو "
                f"{_gib(needed + DISK_MARGIN_BYTES)}، والمتاح "
                f"{_gib(available)}. فرّغ مساحة ثم أعد المحاولة."
            )

    def download(
        self,
        artifact: ModelArtifact,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """ينزّل المودل ويتحقق منه ويعيد مساره النهائي.

        **يستأنف تلقائيًا** من `‎.part` إن وُجد، بترويسة `Range`. خادم لا
        يدعم الاستئناف يعيد ٢٠٠ بدل ٢٠٦، فيُعاد التنزيل من الصفر بدل أن
        يُلحَق الجديد بالقديم فيفسد الملف.

        Raises:
            InsufficientDiskSpaceError | ModelVerificationError |
            DownloadCancelled | ModelError
        """
        self.reset_cancel()
        self.ensure_space(artifact)
        self._part_path.parent.mkdir(parents=True, exist_ok=True)

        resume_from = self.partial_bytes()
        if resume_from > artifact.size_bytes:
            # ملف أكبر من المتوقّع: بقايا تنزيل لنسخة أخرى من المودل.
            logger.warning("ملف جزئي أكبر من الحجم المتوقّع؛ سيُحذف ويُعاد التنزيل.")
            self.discard_partial()
            resume_from = 0

        headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}

        try:
            with self._client_factory() as client:
                with client.stream(
                    "GET", artifact.download_url, headers=headers
                ) as response:
                    resume_from = self._open_stream(response, resume_from)
                    self._write_stream(
                        response, artifact, resume_from, on_progress
                    )
        except (DownloadCancelled, ModelError):
            raise
        except httpx.HTTPError as exc:
            # ⚠️ لا يُمرَّر نص الاستثناء: قد يحمل الرابط الموقّع.
            raise ModelError(
                "انقطع الاتصال أثناء تنزيل المودل. سيُستأنف من حيث توقّف عند "
                "إعادة المحاولة."
            ) from exc

        return self.verify_and_install(artifact, on_progress=on_progress)

    def _open_stream(self, response: httpx.Response, resume_from: int) -> int:
        """يفحص رد الخادم ويعيد نقطة البدء الفعلية."""
        if response.status_code in (401, 403):
            raise ModelError(
                "انتهت صلاحية رابط تنزيل المودل. أعد المحاولة للحصول على رابط جديد."
            )
        if response.status_code == 416:
            # النطاق المطلوب خارج الملف — الجزئي أكبر من المصدر.
            self.discard_partial()
            raise ModelError(
                "الملف الجزئي لا يطابق المودل على الخادم. أعد المحاولة ليبدأ "
                "التنزيل من جديد."
            )
        if response.status_code not in (200, 206):
            raise ModelError(
                f"تعذّر تنزيل المودل (رمز {response.status_code}). أعد المحاولة."
            )

        if resume_from and response.status_code == 200:
            # الخادم تجاهل `Range`. الإلحاق هنا يفسد الملف، فيُبدأ من الصفر.
            logger.warning("الخادم لا يدعم الاستئناف؛ سيُعاد التنزيل من البداية.")
            self.discard_partial()
            return 0
        return resume_from

    def _write_stream(
        self,
        response: httpx.Response,
        artifact: ModelArtifact,
        resume_from: int,
        on_progress: ProgressCallback | None,
    ) -> None:
        mode = "ab" if resume_from else "wb"
        received = resume_from

        with self._part_path.open(mode) as handle:
            for chunk in response.iter_bytes(CHUNK_BYTES):
                if self._cancelled:
                    handle.flush()
                    raise DownloadCancelled(
                        "أُلغي تنزيل المودل. ما نُزّل محفوظ، وسيُستأنف عند "
                        "إعادة المحاولة."
                    )
                handle.write(chunk)
                received += len(chunk)
                if on_progress is not None:
                    on_progress(
                        DownloadProgress(received=received, total=artifact.size_bytes)
                    )

    # -- التحقق ---------------------------------------------------------
    def verify_and_install(
        self,
        artifact: ModelArtifact,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """يتحقق من الحجم والتجزئة ثم يعيد التسمية إلى `‎.gguf`.

        **الترتيب مقصود:** الحجم أولًا لأنه فحص فوري يلتقط التنزيل الناقص،
        والتجزئة بعده لأنها تقرأ الملف كاملًا. ملف بحجم صحيح وتجزئة خاطئة
        ملفٌ **مستبدَل أو تالف**، ويُحذف كما يُحذف الناقص.

        Raises:
            ModelVerificationError: مع حذف `‎.part` في الحالتين.
        """
        if not self._part_path.is_file():
            raise ModelError("لا يوجد ملف مودل لتثبيته. أعد التنزيل.")

        actual_size = self._part_path.stat().st_size
        if actual_size != artifact.size_bytes:
            self.discard_partial()
            raise ModelVerificationError(
                "ملف المودل غير مكتمل أو لا يطابق الحجم المتوقّع. حُذف "
                "الملف، وسيبدأ التنزيل من جديد عند إعادة المحاولة."
            )

        expected = (artifact.sha256 or "").strip().lower()
        if not expected:
            self.discard_partial()
            raise ModelVerificationError(
                "لم يصل من الخادم تجزئة المودل، فلا يمكن التحقق منه. راجع "
                "مسؤول النظام."
            )

        actual = sha256_of(self._part_path, on_progress=on_progress)
        if actual != expected:
            # ⚠️ لا تُطبع التجزئتان: لا فائدة منهما للمستخدم، وطباعتهما
            # تشجّع على تجاوز الفحص يدويًا.
            logger.error("تجزئة المودل لا تطابق المتوقّع؛ حُذف الملف.")
            self.discard_partial()
            raise ModelVerificationError(
                "ملف المودل تالف أو غير مطابق. حُذف الملف حفاظًا على سلامة "
                "النظام، وسيبدأ التنزيل من جديد عند إعادة المحاولة."
            )

        self._model_path.parent.mkdir(parents=True, exist_ok=True)
        self._part_path.replace(self._model_path)
        logger.info("اكتمل تثبيت المودل بعد التحقق منه.")
        return self._model_path


def _gib(value: int) -> str:
    return f"{value / (1 << 30):.1f} ج.ب"


def iter_progress_percent(
    progress: Iterator[DownloadProgress],
) -> Iterator[int]:  # pragma: no cover - أداة عرض
    """يحوّل تدفّق التقدّم إلى نسب مئوية متغيّرة فقط."""
    last = -1
    for item in progress:
        if item.percent != last:
            last = item.percent
            yield last
