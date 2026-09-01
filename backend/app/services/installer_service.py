"""رابط تحميل مثبّت GovMind من Azure Blob Storage.

**الرابط قصير العمر ويولّده الـBackend وحده.** سلسلة اتصال Azure تحمل مفتاح
الحساب، ولا تخرج من هذه الوحدة إلى أي رد ولا سجل ولا رسالة خطأ. ما يصل إلى
العميل هو رابط SAS موقّع لمدة `DOWNLOAD_LINK_TTL_MINUTES` دقيقة على مدوّنة
(Blob) واحدة بصلاحية **قراءة فقط**.

**لماذا التوقيع مكتوب هنا بدل حزمة `azure-storage-blob`؟** لأن التوقيع
خوارزمية HMAC-SHA256 على نص محدَّد في وثائق Azure، وكتابته بالمكتبة القياسية
تغني عن حزمة ثقيلة وتبعياتها، وتجعل المسار **قابلًا للاختبار بالكامل بلا
شبكة ولا حساب Azure** — وهو شرط في هذه المرحلة، إذ لا تُنشأ موارد Azure
تلقائيًا ولا تُودَع أسرار.

⚠️ **قبل الإنتاج:** جرّب الرابط الناتج مرة واحدة على حساب تخزين حقيقي.
التوقيع مكتوب على مواصفة `sv=2022-11-02`، وأي خطأ فيه يظهر كـ
`AuthenticationFailed` من Azure لا كخطأ هنا.

المرحلة الحالية: الواجهة والمسار الآمن جاهزان، **وملف المثبّت نفسه لم
يُبنَ بعد** — انظر `docs/INSTALLER_PLACEHOLDER.md`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlencode

from ..core.config import settings

#: نسخة مواصفة SAS التي بُني عليها نص التوقيع أدناه. **تغييرها يستلزم تعديل
#: ترتيب حقول النص**: كل نسخة تضيف حقولًا في مواضع محددة.
SAS_VERSION = "2022-11-02"

#: المتغيرات التي بدونها لا يمكن توليد رابط، بأسمائها كما تظهر في .env.
_REQUIRED_SETTINGS: tuple[tuple[str, str], ...] = (
    ("AZURE_STORAGE_ACCOUNT", "azure_storage_account"),
    ("AZURE_STORAGE_CONTAINER", "azure_storage_container"),
    ("AZURE_STORAGE_BLOB_NAME", "azure_storage_blob_name"),
    ("AZURE_STORAGE_CONNECTION_STRING", "azure_storage_connection_string"),
)


class InstallerError(Exception):
    """خطأ في تجهيز رابط التحميل، برسالة عربية صالحة للعرض."""


class InstallerNotConfiguredError(InstallerError):
    """إعداد Azure ناقص — خلل تركيب على السيرفر لا خطأ من المستخدم."""


@dataclass(frozen=True)
class DownloadLink:
    """رابط تحميل مؤقّت ووقت انتهائه.

    ``url`` يُعاد إلى الإضافة لتمرّره إلى ``chrome.downloads`` مباشرة، **ولا
    يُعرض للمستخدم**: عنوان Azure تفصيلٌ داخلي، وإظهاره يدعو إلى مشاركته.
    """

    url: str
    expires_at: datetime
    file_name: str


def missing_settings() -> list[str]:
    """يعيد أسماء متغيرات Azure الناقصة كما تظهر في .env."""
    return [
        env_name
        for env_name, field in _REQUIRED_SETTINGS
        if not (getattr(settings, field, "") or "").strip()
    ]


def is_configured() -> bool:
    """هل ضُبطت كل متغيرات Azure؟ لا يلمس الشبكة."""
    return not missing_settings()


def _parse_connection_string(value: str) -> dict[str, str]:
    """يحلّل سلسلة اتصال Azure إلى قاموس مفاتيحها بأحرف صغيرة.

    الصيغة: ``Key=Value;Key=Value``. القيمة قد تحوي ``=`` (مفتاح Base64)،
    فالتقسيم على أول ``=`` وحده.
    """
    parsed: dict[str, str] = {}
    for part in value.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, item = part.partition("=")
        parsed[key.strip().lower()] = item.strip()
    return parsed


def _account_key() -> str:
    """يستخرج مفتاح الحساب من سلسلة الاتصال.

    Raises:
        InstallerNotConfiguredError: إذا خلت السلسلة من المفتاح.
    """
    parsed = _parse_connection_string(settings.azure_storage_connection_string)
    key = parsed.get("accountkey", "")
    if not key:
        raise InstallerNotConfiguredError(
            "سلسلة اتصال Azure لا تحتوي AccountKey. راجع "
            "AZURE_STORAGE_CONNECTION_STRING في ملف .env على السيرفر."
        )
    return key


def blob_endpoint() -> str:
    """عنوان خدمة المدوّنات، من سلسلة الاتصال إن ذُكر أو المشتق منه.

    البيئات المحلية (Azurite) والسحابات السيادية تستعمل عنوانًا مختلفًا عن
    ``blob.core.windows.net``، وسلسلة الاتصال تذكره صراحة حينها.
    """
    parsed = _parse_connection_string(settings.azure_storage_connection_string)
    endpoint = parsed.get("blobendpoint", "").rstrip("/")
    if endpoint:
        return endpoint

    account = settings.azure_storage_account.strip()
    suffix = parsed.get("endpointsuffix", "core.windows.net").strip()
    scheme = parsed.get("defaultendpointsprotocol", "https").strip() or "https"
    return f"{scheme}://{account}.blob.{suffix}"


def _format_moment(moment: datetime) -> str:
    """الصيغة التي تقبلها Azure: ISO-8601 بدقة الثانية وبـZ."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sign(string_to_sign: str, account_key: str) -> str:
    try:
        key = base64.b64decode(account_key)
    except Exception as exc:
        raise InstallerNotConfiguredError(
            "مفتاح حساب Azure في سلسلة الاتصال ليس بترميز Base64 صالح."
        ) from exc

    digest = hmac.new(
        key, string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def build_download_link(*, now: datetime | None = None) -> DownloadLink:
    """يولّد رابط SAS للقراءة على مدوّنة المثبّت.

    **لا يفحص شيئًا عن المستخدم:** الاستحقاق تفحصه
    `entitlement_service.authorize_installer_download` قبل استدعاء هذه
    الدالة. فصلُ الاثنين يجعل كل واحد قابلًا للاختبار وحده.

    Raises:
        InstallerNotConfiguredError: إذا كان إعداد Azure ناقصًا أو تالفًا.
    """
    missing = missing_settings()
    if missing:
        raise InstallerNotConfiguredError(
            "تحميل المثبّت غير مهيّأ على هذا السيرفر. المتغيرات الناقصة: "
            f"{'، '.join(missing)}."
        )

    account = settings.azure_storage_account.strip()
    container = settings.azure_storage_container.strip().strip("/")
    blob_name = settings.azure_storage_blob_name.strip().lstrip("/")
    account_key = _account_key()

    moment = (now or datetime.now(UTC)).astimezone(UTC)
    # البداية قبل خمس دقائق: ساعة السيرفر وساعة Azure قد تختلفان بثوانٍ،
    # وبداية في المستقبل تجعل الرابط مرفوضًا لحظة إصداره.
    start = moment - timedelta(minutes=5)
    expiry = moment + timedelta(minutes=max(1, settings.download_link_ttl_minutes))

    permissions = "r"  # قراءة فقط. لا كتابة ولا حذف ولا سرد.
    resource = "b"  # مدوّنة واحدة، لا الحاوية كلها.
    canonical = f"/blob/{account}/{container}/{blob_name}"

    # ⚠️ **ترتيب الحقول جزء من المواصفة، وسطر فارغ محذوف يُفسد التوقيع.**
    # الترتيب أدناه هو ترتيب Service SAS للنسخة 2020-12-06 فما بعد:
    # الصلاحيات، البداية، الانتهاء، المورد القانوني، السياسة المخزّنة،
    # عنوان IP، البروتوكول، النسخة، نوع المورد، لحظة اللقطة، نطاق التعمية،
    # ثم ترويسات الرد الخمس (cache-control، content-disposition،
    # content-encoding، content-language، content-type).
    string_to_sign = "\n".join(
        [
            permissions,
            _format_moment(start),
            _format_moment(expiry),
            canonical,
            "",  # signedIdentifier — لا سياسة مخزّنة
            "",  # signedIP — بلا تقييد عنوان
            "https",  # signedProtocol
            SAS_VERSION,
            resource,
            "",  # signedSnapshotTime
            "",  # signedEncryptionScope
            "",  # rscc
            "",  # rscd
            "",  # rsce
            "",  # rscl
            "",  # rsct
        ]
    )

    query = urlencode(
        {
            "sv": SAS_VERSION,
            "sr": resource,
            "sp": permissions,
            "st": _format_moment(start),
            "se": _format_moment(expiry),
            "spr": "https",
            "sig": _sign(string_to_sign, account_key),
        }
    )

    path = f"{quote(container)}/{quote(blob_name)}"
    return DownloadLink(
        url=f"{blob_endpoint()}/{path}?{query}",
        expires_at=expiry,
        file_name=blob_name.rsplit("/", 1)[-1],
    )
