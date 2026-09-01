"""هوية الجهاز — سرّ عشوائي محميّ بـWindows DPAPI.

**سرّ عشوائي لا بصمة عتاد.** عنوان MAC واسم المستخدم ورقم القرص كلها إمّا
غير مستقرة (تتغيّر ببطاقة شبكة أو محاكاة أو تحديث)، أو قابلة للانتحال، أو
تكشف هوية المستخدم بلا داعٍ. سرٌّ عشوائي ٣٢ بايت يولَّد مرة ويُخزَّن يصف ما
نريد وصفه بالضبط: **هذا التركيب على هذا الجهاز** — ولا يحمل عن صاحبه شيئًا.

**الحماية: DPAPI بنطاق الجهاز** (`CRYPTPROTECT_LOCAL_MACHINE`) عبر
`crypt32.dll` بـ`ctypes` — لا حزمة إضافية ولا اعتماد على `pywin32`. مع
`entropy` ثابت للتطبيق، فلا يفكّ الملفَّ برنامجٌ آخر بمجرد استدعاء DPAPI
عليه.

⚠️ **حدّ يجب ذكره صراحة:** DPAPI بنطاق الجهاز يمنع فكّ الملف على **جهاز
آخر**، ولا يمنع مستخدمًا إداريًا على **الجهاز نفسه**. لا يوجد على ويندوز
بلا عتاد TPM مخصّص ما يمنع مالك الجهاز من قراءة سرّ يستعمله برنامجه هو.
هذا حدّ معماري لا عيب تنفيذ؛ سياسة «جهاز واحد» تبقى مفروضة في القاعدة لا
على ثقة بالعميل.

⚠️ **لا يُسجَّل السرّ الخام أبدًا** — لا في سجلّ ولا في رسالة خطأ ولا في
استثناء. الدوال هنا تعيده إلى المستدعي ولا تكتبه في أي مكان غير الملف
المحميّ.
"""

from __future__ import annotations

import base64
import ctypes
import logging
import os
import secrets
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

#: طول السرّ بالبايت. ٣٢ بايت = ٢٥٦ بت.
SECRET_BYTES = 32

#: عشوائية إضافية تدخل في التعمية. **ليست سرًّا** — هي في الشيفرة — وفائدتها
#: أن ملفًّا مسروقًا لا يُفكّ باستدعاء DPAPI عام، بل يلزم معرفة هذه القيمة.
_ENTROPY = b"GovMind.DeviceSecret.v1"

#: أعلام DPAPI.
_CRYPTPROTECT_UI_FORBIDDEN = 0x01
_CRYPTPROTECT_LOCAL_MACHINE = 0x04


class IdentityError(Exception):
    """خطأ في هوية الجهاز، برسالة عربية صالحة للعرض."""


class ProtectionUnavailableError(IdentityError):
    """تعذّرت حماية السرّ بـDPAPI.

    **لا بديل نصّي صريح.** تخزين سرّ الجهاز بلا تعمية يجعل نسخ ملف واحد
    كافيًا لانتحال الجهاز على أي حاسب آخر، وهو أسوأ من التوقّف برسالة
    واضحة.
    """


class SecretProtector(Protocol):
    """يعمّي السرّ ويفكّه. تنفيذ واحد في الإنتاج، وبديل في الاختبارات."""

    name: str

    def protect(self, secret: bytes) -> bytes: ...

    def unprotect(self, blob: bytes) -> bytes: ...


# ---------------------------------------------------------------------------
# DPAPI
# ---------------------------------------------------------------------------
class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob(data: bytes) -> _DataBlob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _read_blob(blob: _DataBlob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


class DpapiProtector:
    """تعمية بمفتاح الجهاز عبر `crypt32.dll`."""

    name = "dpapi-local-machine"

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise ProtectionUnavailableError(
                "حماية سرّ الجهاز تعتمد على Windows DPAPI، وهذا النظام ليس ويندوز."
            )
        try:
            self._crypt32 = ctypes.WinDLL("crypt32.dll")
            self._kernel32 = ctypes.WinDLL("kernel32.dll")
        except OSError as exc:  # pragma: no cover - يستحيل على ويندوز سليم
            raise ProtectionUnavailableError(
                "تعذّر تحميل crypt32.dll على هذا الجهاز."
            ) from exc

    def _call(self, function, data: bytes, failure: str) -> bytes:
        data_in = _blob(data)
        entropy = _blob(_ENTROPY)
        data_out = _DataBlob()

        ok = function(
            ctypes.byref(data_in),
            None,
            ctypes.byref(entropy),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN | _CRYPTPROTECT_LOCAL_MACHINE,
            ctypes.byref(data_out),
        )
        if not ok:
            # ⚠️ رمز الخطأ فقط. لا يُمرَّر أي جزء من `data` إلى الرسالة.
            code = ctypes.get_last_error() or ctypes.GetLastError()
            raise ProtectionUnavailableError(f"{failure} (رمز ويندوز: {code})")

        try:
            return _read_blob(data_out)
        finally:
            self._kernel32.LocalFree(data_out.pbData)

    def protect(self, secret: bytes) -> bytes:
        return self._call(
            self._crypt32.CryptProtectData, secret, "تعذّرت حماية سرّ الجهاز"
        )

    def unprotect(self, blob: bytes) -> bytes:
        return self._call(
            self._crypt32.CryptUnprotectData, blob, "تعذّر فكّ حماية سرّ الجهاز"
        )


def default_protector() -> SecretProtector:
    """يعيد حامي الأسرار المناسب، أو يرفع خطأً واضحًا.

    **لا يعيد بديلًا نصّيًا صريحًا في أي حال.** غياب DPAPI يوقف التفعيل
    برسالة مفهومة بدل أن يخزّن سرًّا مكشوفًا بصمت.
    """
    return DpapiProtector()


# ---------------------------------------------------------------------------
# مخزن السرّ
# ---------------------------------------------------------------------------
class DeviceIdentity:
    """يقرأ سرّ الجهاز أو يولّده عند أول إقلاع.

    الملف تحت مجلد بيانات التركيب على الجهاز، **لا في المتصفح ولا في مجلد
    المستخدم المتنقّل**: الهوية للجهاز لا للمستخدم.
    """

    #: اسم الملف. الامتداد `bin` لا `txt`: محتواه ثنائي معمّى لا نصّ.
    FILE_NAME = "device.bin"

    def __init__(
        self, data_dir: Path, protector: SecretProtector | None = None
    ) -> None:
        self._path = Path(data_dir) / self.FILE_NAME
        self._protector = protector or default_protector()

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.is_file()

    def load(self) -> str | None:
        """يعيد السرّ الخام، أو ``None`` إن لم يوجد أو تعذّر فكّه.

        **ملف تالف أو غير قابل للفكّ يُعامَل كغيابه**: نسخة من جهاز آخر،
        أو ويندوز أُعيد تثبيته فضاعت مفاتيح DPAPI. المطلوب حينها تفعيل
        جديد، لا محاولة العمل بهوية مجهولة.

        ⚠️ **تعذّر القراءة ليس تعذّر الفكّ.** ملفٌ موجود لا نملك صلاحية
        قراءته خللٌ عابر في الصلاحيات، وتوليد سرّ جديد عنده يهجر تفعيلًا
        قائمًا ويجبر العميل على مراجعة مسؤوله بلا سبب. لذلك يُرفع الخطأ
        هنا ولا يُبتلع.

        Raises:
            IdentityError: إذا وُجد الملف وتعذّرت **قراءته** من القرص.
        """
        if not self.exists():
            return None

        try:
            blob = self._path.read_bytes()
        except OSError as exc:
            raise IdentityError(
                "تعذّرت قراءة ملف هوية الجهاز. تأكد من صلاحيات مجلد تثبيت "
                "GovMind ثم أعد تشغيل الخدمة."
            ) from exc

        try:
            return base64.b64decode(self._protector.unprotect(blob)).decode("ascii")
        except Exception:
            # ⚠️ بلا `exc_info`: أثر الاستثناء قد يحمل جزءًا من المحتوى.
            logger.warning("تعذّر فكّ سرّ الجهاز؛ سيُعامَل الجهاز كغير مفعَّل.")
            return None

    def create(self) -> str:
        """يولّد سرًّا جديدًا ويحفظه محميًّا. يستبدل أي ملف قائم."""
        secret = secrets.token_urlsafe(SECRET_BYTES)
        blob = self._protector.protect(base64.b64encode(secret.encode("ascii")))

        self._path.parent.mkdir(parents=True, exist_ok=True)
        # كتابة ذرّية: انقطاع كهرباء أثناء الكتابة لا يترك ملفًا نصفه سرّ
        # قديم ونصفه جديد — وكلاهما غير قابل للفكّ.
        temporary = self._path.with_suffix(".tmp")
        temporary.write_bytes(blob)
        os.replace(temporary, self._path)
        _restrict_permissions(self._path)

        logger.info("وُلّد سرّ جهاز جديد وحُفظ محميًّا.")
        return secret

    def ensure(self) -> str:
        """يعيد السرّ القائم أو يولّد واحدًا. مُعادة التنفيذ.

        استبدال ملف موجود لكن غير قابل للفكّ **يُسجَّل صراحة**: هو يعني أن
        التفعيل السابق صار يتيمًا وسيحتاج إبطالًا من المسؤول، وهذا خبر
        يستحق سطرًا في السجل لا أن يمرّ صامتًا.
        """
        existing = self.load()
        if existing is not None:
            return existing
        if self.exists():
            logger.warning(
                "ملف هوية الجهاز موجود لكنه غير قابل للفكّ (نسخ من جهاز آخر "
                "أو إعادة تثبيت ويندوز). سيُولَّد سرّ جديد، وقد يحتاج التفعيل "
                "السابق إبطالًا من مسؤول النظام."
            )
        return self.create()

    def clear(self) -> None:
        """يحذف السرّ — لإلغاء التثبيت أو بعد إبطال التفعيل."""
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            logger.warning("تعذّر حذف ملف سرّ الجهاز.")


def _current_user_sid() -> str | None:
    """SID لحساب العملية الحالية، أو ``None`` إن تعذّر تحديده."""
    try:
        import subprocess

        result = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return None
        # الصيغة: "DOMAIN\user","S-1-5-21-..."
        parts = [part.strip().strip('"') for part in result.stdout.strip().split(",")]
        for part in parts:
            if part.startswith("S-1-"):
                return part
    except Exception:
        return None
    return None


def _restrict_permissions(path: Path) -> None:
    """يقصر الوصول إلى الملف على النظام والمسؤولين **وصاحب العملية**.

    طبقة ثانية فوق DPAPI: الأولى تمنع الفكّ على جهاز آخر، وهذه تمنع
    القراءة أصلًا من حساب مستخدم آخر على الجهاز نفسه.

    ⚠️ **صاحب العملية يُمنح صراحةً، وإلا حبس البرنامجُ نفسَه خارج ملفه.**
    الـRuntime قد يعمل خدمةً بحساب SYSTEM أو مباشرةً بحساب المستخدم حسب
    نوع التثبيت؛ منح SYSTEM والمسؤولين وحدهم يجعل التشغيل بحساب مستخدم
    عاديّ يفشل في قراءة السرّ — فيولّد غيره في كل إقلاع ويهجر التفعيل.

    وإن تعذّر تحديد صاحب العملية **لا تُعدَّل الصلاحيات إطلاقًا**: تعمية
    DPAPI قائمة على أي حال، وقفلٌ ناقص أسوأ من لا قفل.
    """
    if sys.platform != "win32":
        return

    owner = _current_user_sid()
    if owner is None:
        logger.debug("تعذّر تحديد صاحب العملية؛ تُركت صلاحيات الملف كما هي.")
        return

    try:
        import subprocess

        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                "*S-1-5-18:(F)",  # NT AUTHORITY\SYSTEM
                "/grant:r",
                "*S-1-5-32-544:(F)",  # BUILTIN\Administrators
                "/grant:r",
                f"*{owner}:(F)",  # صاحب العملية
            ],
            check=False,
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        logger.debug("تعذّر ضبط صلاحيات ملف سرّ الجهاز.", exc_info=False)
