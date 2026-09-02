"""مفاتيح التوقيع العامة لمشروع Supabase (JWKS) — جلبٌ وتخزينٌ مؤقّت.

**لماذا وُجد هذا الملف.** مشاريع Supabase الحديثة توقّع رموز المستخدمين
بمفتاح **غير متماثل** (ES256 أو RS256) وتنشر نظيره العام على
``/auth/v1/.well-known/jwks.json``. لم يعد ``SUPABASE_JWT_SECRET`` — وهو
سرّ متماثل — يصلح للتحقق منها، ولا يملك السيرفر أصلًا المفتاح الخاص.

فالتحقق صار: اقرأ ``kid`` من ترويسة الرمز، هات نظيره العام من هنا، وافحص
التوقيع به.

**الجلب مخزَّن مؤقتًا لا لكل طلب.** JWKS ثابتة لأشهر، ونداء شبكي في كل
طلب محمي يضيف تأخيرًا ويجعل انقطاع الشبكة عن Supabase انقطاعًا عن النظام.

⚠️ **التحديث عند `kid` مجهول محكوم بمهلة.** من يرسل ``kid`` عشوائيًا في كل
طلب كان سيجرّ السيرفر إلى نداء صعودي لكل طلب — إغراقٌ نُطلقه نحن على
Supabase بأمر مهاجم. فالتحديث القسري لا يقع أكثر من مرة كل
:data:`MIN_REFRESH_SECONDS`، والرمز المجهول يُرفض بعده.

⚠️ **لا يُسجَّل هنا رمز ولا سرّ.** ما يُسجَّل: ``kid`` (معرّف عام يُنشر في
JWKS نفسها) وعدد المفاتيح ونوع الخطأ. المفاتيح العامة نفسها لا تُطبع.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx
import jwt

from ..core.config import settings
from ..database import supabase

logger = logging.getLogger(__name__)

#: عمر المخزون قبل تحديث دوري. المفاتيح تدوم أشهرًا، فالساعة كافية.
CACHE_TTL_SECONDS = 3600

#: أقل فاصل بين تحديثين قسريين (عند `kid` مجهول). يمنع الإغراق الصعودي.
MIN_REFRESH_SECONDS = 30


class JwksUnavailableError(Exception):
    """تعذّر جلب مفاتيح التوقيع — خلل تشغيل لا خطأ مستخدم."""


class UnknownSigningKeyError(Exception):
    """لا مفتاح عام بهذا ``kid`` حتى بعد تحديث المخزون."""


class _Cache:
    """مخزون مؤقّت لمفاتيح JWKS، آمن مع الخيوط.

    القفل واحد لكل العملية: قراءتان متزامنتان بعد انتهاء العمر كانتا
    ستجلبان الشبكة مرتين لنتيجة واحدة.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float = 0.0
        self._last_forced_refresh: float = 0.0

    # -- للاختبارات ولإعادة الضبط بعد تغيّر الإعداد ---------------------
    def clear(self) -> None:
        with self._lock:
            self._keys = {}
            self._fetched_at = 0.0
            self._last_forced_refresh = 0.0

    def snapshot(self) -> dict[str, jwt.PyJWK]:
        with self._lock:
            return dict(self._keys)

    # -- الجلب ----------------------------------------------------------
    def _fetch_locked(self) -> None:
        """يجلب JWKS ويستبدل المخزون. **يُنادى والقفل مُمسك.**"""
        url = f"{supabase.auth_base_url()}/.well-known/jwks.json"

        try:
            response = httpx.get(url, timeout=settings.supabase_timeout_seconds)
        except httpx.HTTPError as exc:
            raise JwksUnavailableError(
                "تعذّر الوصول إلى مفاتيح التحقق من الجلسة."
            ) from exc

        if not response.is_success:
            # ⚠️ لا يُسجَّل جسم الرد: قد يحمل تفاصيل إعداد.
            logger.warning("جلب JWKS رجع بحالة %s", response.status_code)
            raise JwksUnavailableError(
                "تعذّر الوصول إلى مفاتيح التحقق من الجلسة."
            )

        try:
            document: dict[str, Any] = response.json()
            raw_keys = document.get("keys") or []
        except ValueError as exc:
            raise JwksUnavailableError(
                "رد مفاتيح التحقق غير مقروء."
            ) from exc

        keys: dict[str, jwt.PyJWK] = {}
        for raw in raw_keys:
            if not isinstance(raw, dict):
                continue
            kid = str(raw.get("kid") or "").strip()
            if not kid:
                # بلا `kid` لا يمكن ربط المفتاح برمز. تخطٍّ صامت لا فشل:
                # وجود مفتاح واحد شاذّ لا يجوز أن يعطّل البقية.
                continue
            try:
                keys[kid] = jwt.PyJWK.from_dict(raw)
            except Exception:  # noqa: BLE001 — أي مفتاح مشوَّه يُتخطّى
                logger.warning("مفتاح JWKS غير مقروء، kid=%s", kid)

        if not keys:
            raise JwksUnavailableError("لا مفاتيح توقيع منشورة للمشروع.")

        self._keys = keys
        self._fetched_at = time.monotonic()
        logger.info("حُدّثت مفاتيح JWKS: %d مفتاحًا", len(keys))

    def get(self, kid: str) -> jwt.PyJWK:
        """يعيد المفتاح العام لهذا ``kid``، مع تحديث واحد عند الحاجة.

        Raises:
            UnknownSigningKeyError: لا مفتاح بهذا المعرّف بعد التحديث.
            JwksUnavailableError: تعذّر جلب المفاتيح أصلًا.
        """
        now = time.monotonic()

        with self._lock:
            expired = (now - self._fetched_at) >= CACHE_TTL_SECONDS
            if not self._keys or expired:
                self._fetch_locked()

            key = self._keys.get(kid)
            if key is not None:
                return key

            # `kid` مجهول: قد يكون المشروع دوّر مفاتيحه للتوّ. **تحديث واحد.**
            since_forced = time.monotonic() - self._last_forced_refresh
            if since_forced < MIN_REFRESH_SECONDS:
                logger.info("kid مجهول والتحديث القسري ضمن المهلة: %s", kid)
                raise UnknownSigningKeyError(kid)

            self._last_forced_refresh = time.monotonic()
            self._fetch_locked()

            key = self._keys.get(kid)
            if key is None:
                logger.info("kid مجهول بعد التحديث: %s", kid)
                raise UnknownSigningKeyError(kid)
            return key


_cache = _Cache()


def signing_key(kid: str) -> jwt.PyJWK:
    """المفتاح العام الموافق لـ``kid``. انظر :meth:`_Cache.get`."""
    return _cache.get(kid)


def reset_cache() -> None:
    """يفرّغ المخزون. للاختبارات، ولإعادة الضبط بعد تغيّر ``SUPABASE_URL``."""
    _cache.clear()


def cached_kids() -> list[str]:
    """معرّفات المفاتيح المخزونة الآن. **معرّفات فقط، لا مادة مفاتيح.**"""
    return sorted(_cache.snapshot())
