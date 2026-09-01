"""عميل Backend المستضاف — الطرف الوحيد الذي يتحدّث إليه الـRuntime عبر الشبكة.

**لا يتحدّث الـRuntime إلى Supabase ولا إلى Azure مباشرة.** لا يملك مفتاح
`service_role` ولا سلسلة اتصال Azure ولا مِلح التجزئة — ولا يجوز أن يملكها،
فهو برنامج على جهاز عميل. كل ما يحتاجه يمرّ بـBackend المستضاف الذي يفرض
الاستحقاق ويوقّع الروابط.

**المصادقة:** سرّ الجهاز في ترويسة `X-GovMind-Device-Secret`. سرّ لا يفتح
شيئًا غير اشتراك هذا الجهاز، ولا يُخزَّن على السيرفر إلا مجزّأً.

⚠️ **لا يُسجَّل السرّ ولا رابط SAS ولا رمز التركيب.** رسائل الخطأ هنا
مكتوبة يدويًا ولا تمرّر جسم رد ولا رابطًا.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEVICE_HEADER = "X-GovMind-Device-Secret"

#: مهلة قصيرة: كلها نداءات تحكّم صغيرة لا تنزيل ولا توليد.
DEFAULT_TIMEOUT = 30.0


class ControlPlaneError(Exception):
    """خطأ من Backend المستضاف، برسالة عربية صالحة للعرض."""


class OfflineError(ControlPlaneError):
    """لم يصل الطلب أصلًا — لا شبكة أو الخدمة متوقفة."""


class DeviceNotActivatedError(ControlPlaneError):
    """الجهاز غير مفعَّل أو أُبطل تفعيله."""


class SubscriptionBlockedError(ControlPlaneError):
    """الاشتراك لا يسمح بالخدمة، والرسالة تشرح السبب."""


class ActivationRejectedError(ControlPlaneError):
    """رُفض التفعيل: رمز غير صالح، أو جهاز آخر مفعّل."""


@dataclass(frozen=True)
class Entitlement:
    """حالة الاشتراك كما يراها هذا الجهاز."""

    status: str
    expires_at: str
    is_usable: bool
    blocked_reason: str | None
    device_name: str


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

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        device_secret: str | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if device_secret:
            headers[DEVICE_HEADER] = device_secret

        client = self._client or httpx.Client(timeout=self._timeout)
        owns_client = self._client is None
        try:
            response = client.request(
                method, f"{self._base_url}{path}", json=json, headers=headers
            )
        except httpx.HTTPError as exc:
            raise OfflineError(
                "تعذّر الاتصال بخدمة GovMind. تأكد من اتصال الجهاز بالإنترنت."
            ) from exc
        finally:
            if owns_client:
                client.close()

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
                or "هذا الاشتراك مفعّل على جهاز آخر. راجع مسؤول النظام في جهتك."
            )
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
    ) -> dict[str, Any]:
        """يستبدل رمز التركيب بتفعيل جهاز.

        ⚠️ الرمز والسرّ يمرّان في الجسم ولا يُسجَّلان.
        """
        logger.info("إرسال طلب تفعيل الجهاز إلى خدمة GovMind.")
        return self._request(
            "POST",
            "/api/runtime/activate",
            json={
                "token": token,
                "device_secret": device_secret,
                "device_name": device_name,
            },
        )

    def entitlement(self, device_secret: str) -> Entitlement:
        """يقرأ حالة الاشتراك لهذا الجهاز."""
        data = self._request(
            "GET", "/api/runtime/entitlement", device_secret=device_secret
        )
        return Entitlement(
            status=str(data.get("status") or ""),
            expires_at=str(data.get("expires_at") or ""),
            is_usable=bool(data.get("is_usable")),
            blocked_reason=data.get("blocked_reason"),
            device_name=str(data.get("device_name") or ""),
        )

    def model_artifact(self, device_secret: str) -> ModelArtifactInfo:
        """يطلب رابط تنزيل المودل وبيانات التحقق منه.

        ⚠️ الرابط **يُستهلك فورًا ولا يُحفظ**: قصير العمر ويعمل بلا هوية.
        """
        data = self._request(
            "GET", "/api/runtime/model", device_secret=device_secret
        )
        return ModelArtifactInfo(
            download_url=str(data.get("download_url") or ""),
            file_name=str(data.get("file_name") or "govmind-model.gguf"),
            sha256=str(data.get("sha256") or ""),
            size_bytes=int(data.get("size_bytes") or 0),
        )
