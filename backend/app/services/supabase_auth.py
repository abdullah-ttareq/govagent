"""المصادقة عبر Supabase Auth (`auth.users`) — بلا نظام كلمات مرور خاص.

**لماذا يمرّ تسجيل الدخول بالـBackend بدل أن تنادي الإضافة Supabase مباشرة؟**
لأن الشرط أن **لا يُدخل المستخدم رابطًا ولا مفتاحًا ولا عنوان سيرفر**. لو
نادت الإضافة Supabase مباشرة لوجب أن تحمل `SUPABASE_URL` والمفتاح العام
داخلها، ولصار للنظام عنوانان يجب أن يتطابقا. بمرور الدخول بالـBackend لا
تعرف الإضافة سوى عنوان واحد مثبَّت وقت البناء، ويبقى كل ما عداه على السيرفر.

المفتاح العام (`anon`) يُستعمل في هذا الملف وحده، ولا يخرج منه إلى أي رد.
مفتاح `service_role` **لا يُستعمل هنا إطلاقًا**: تسجيل الدخول عملية تخصّ
المستخدم، ورمزها يجب أن يصدر باسمه هو لا باسم الخدمة.

**التحقق من الرمز محلّي**: يُفحص توقيعه في العملية نفسها بلا نداء شبكي في
كل طلب. رمز منتهٍ أو موقّع بمفتاح آخر يُرفض قبل لمس القاعدة.

**خوارزميتان لا واحدة.** مشاريع Supabase الحديثة توقّع رموز المستخدمين
بمفتاح غير متماثل (ES256/RS256) وتنشر نظيره العام في JWKS؛ والمشاريع
القديمة توقّع بـHS256 بسرّ المشروع. يُدعم المساران، ويُختار المسار من
خوارزمية الرمز **بعد حصرها في قائمة سماح صريحة**.

⚠️ **لا خلط خوارزميات.** ترويسة الرمز يكتبها من أصدره — ومن زوّره. فهي
تُستعمل لاختيار المسار وحده، ثم:

* في المسار غير المتماثل تُؤخذ الخوارزمية من **مفتاح JWKS نفسه** لا من
  الترويسة، ويُمرَّر إلى ``jwt.decode`` اسمُ خوارزمية واحد لا قائمة.
* في مسار HS256 يُمرَّر ``["HS256"]`` وحدها، والسرّ لا يُستعمل مفتاحًا
  لخوارزمية أخرى أبدًا.

بهذا لا يمكن لرمز موقَّع بـHS256 والمفتاح العام سرًّا (`alg confusion`) أن
يُقبل: المسار العام لا يقبل HS256 أصلًا.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from ..core.config import settings
from ..database import supabase
from . import supabase_jwks

logger = logging.getLogger(__name__)

#: الخوارزميات غير المتماثلة المقبولة — ما تصدره Supabase Auth فعلًا.
#: **قائمة سماح صريحة**، فلا `none` ولا `HS*` تصل هذا المسار.
ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256"})

#: الخوارزمية المتماثلة الوحيدة المقبولة، للمشاريع التي لم تنتقل بعد.
SYMMETRIC_ALGORITHM = "HS256"

#: نوع المفتاح ⇐ بادئة الخوارزميات التي يجوز أن يوقّع بها.
#: يُستعمل حين لا يعلن مفتاح JWKS خوارزميته: مفتاح EC لا يوقّع RS256.
_KEY_TYPE_PREFIX = {"EC": "ES", "RSA": ("RS", "PS"), "OKP": "Ed"}

#: هامش انزياح الساعات بين السيرفر وSupabase. ثوانٍ قليلة لا دقائق:
#: الهامش الواسع يمدّ عمر رمزٍ منتهٍ.
CLOCK_SKEW_SECONDS = 10


class SupabaseAuthError(Exception):
    """خطأ مصادقة، برسالة عربية صالحة للعرض."""


class InvalidCredentialsError(SupabaseAuthError):
    """البريد أو كلمة المرور غير صحيحة."""


class InvalidSupabaseTokenError(SupabaseAuthError):
    """الرمز مفقود أو تالف أو منتهي الصلاحية."""


class SupabaseAuthNotConfiguredError(SupabaseAuthError):
    """إعداد Supabase ناقص على السيرفر — خلل تركيب لا خطأ مستخدم."""


@dataclass(frozen=True)
class SupabaseIdentity:
    """هوية صاحب الرمز كما استُخرجت منه. **لا تحمل أي بيانات عمل.**

    الجهة والدور والاشتراك تُقرأ من القاعدة بهذا المعرّف، لا من الرمز:
    ما في الرمز يعكس لحظة إصداره، وقد تكون العضوية تغيّرت بعدها.
    """

    user_id: str
    email: str


@dataclass(frozen=True)
class SupabaseSession:
    """جلسة صادرة عن Supabase Auth بعد تسجيل دخول ناجح."""

    access_token: str
    refresh_token: str
    expires_in: int
    user_id: str
    email: str


def _require_anon_key() -> str:
    key = (settings.supabase_anon_key or "").strip()
    if not key or not (settings.supabase_url or "").strip():
        raise SupabaseAuthNotConfiguredError(
            "تسجيل الدخول غير مهيّأ على هذا السيرفر. المتغيرات المطلوبة: "
            "SUPABASE_URL و SUPABASE_ANON_KEY."
        )
    return key


def sign_in(email: str, password: str) -> SupabaseSession:
    """يسجّل الدخول عبر Supabase Auth ويعيد الجلسة.

    كلمة المرور تمرّ عبر هذه الدالة إلى Supabase ولا تُحفظ ولا تُسجَّل في
    أي مكان: النظام لا يملك جدول كلمات مرور أصلًا.

    Raises:
        SupabaseAuthNotConfiguredError: إعداد ناقص على السيرفر.
        InvalidCredentialsError: بيانات دخول غير صحيحة.
        SupabaseAuthError: تعذّر الوصول إلى خدمة المصادقة.
    """
    key = _require_anon_key()

    try:
        response = httpx.post(
            f"{supabase.auth_base_url()}/token",
            params={"grant_type": "password"},
            headers={"apikey": key, "Content-Type": "application/json"},
            json={"email": email.strip().lower(), "password": password},
            timeout=settings.supabase_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise SupabaseAuthError(
            "تعذّر الوصول إلى خدمة المصادقة. تأكد من اتصال السيرفر بالإنترنت."
        ) from exc

    if response.status_code in (400, 401, 403):
        # لا يُفرَّق بين «بريد غير مسجّل» و«كلمة مرور خاطئة»: التفريق يكشف
        # من له حساب في النظام لمن يجرّب البُرد.
        raise InvalidCredentialsError(
            "البريد الإلكتروني أو كلمة المرور غير صحيحة."
        )
    if response.status_code == 429:
        raise SupabaseAuthError(
            "محاولات تسجيل دخول كثيرة خلال وقت قصير. انتظر قليلًا ثم أعد "
            "المحاولة."
        )
    if not response.is_success:
        raise SupabaseAuthError(
            "خدمة المصادقة لا تستجيب حاليًا. أعد المحاولة بعد قليل."
        )

    payload: dict[str, Any] = response.json()
    user = payload.get("user") or {}
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        raise SupabaseAuthError("رد خدمة المصادقة غير مكتمل. راجع مسؤول النظام.")

    return SupabaseSession(
        access_token=str(payload.get("access_token") or ""),
        refresh_token=str(payload.get("refresh_token") or ""),
        expires_in=int(payload.get("expires_in") or 0),
        user_id=user_id,
        email=str(user.get("email") or "").strip().lower(),
    )


def _expected_issuer() -> str:
    """مُصدِر الرموز المتوقَّع: ``{SUPABASE_URL}/auth/v1``.

    اشتراطه يمنع قبول رمزٍ صحيح التوقيع صادرٍ عن **مشروع Supabase آخر**.
    """
    return supabase.auth_base_url()


def _algorithm_for(key: jwt.PyJWK, header_alg: str) -> str:
    """يختار خوارزمية التحقق **من المفتاح لا من الترويسة**.

    مفتاح JWKS عند Supabase يعلن ``alg`` صراحةً، فهي المصدر. وإن غاب —
    وهو جائز في المعيار — تُقبل خوارزمية الترويسة بشرطين: أن تكون في
    قائمة السماح، **وأن توافق نوع المفتاح**. مفتاح EC لا يوقّع RS256،
    ومفتاح RSA لا يوقّع ES256، ولا أحدهما يوقّع HS256.

    Raises:
        InvalidSupabaseTokenError: خوارزمية غير مسموحة أو لا توافق المفتاح.
    """
    declared = str(getattr(key, "algorithm_name", "") or "").strip()
    if declared:
        if declared not in ASYMMETRIC_ALGORITHMS:
            raise InvalidSupabaseTokenError(
                "رمز الدخول موقَّع بطريقة غير مدعومة. سجّل الدخول مرة أخرى."
            )
        return declared

    key_type = str((key.key_type or "")).upper()
    prefixes = _KEY_TYPE_PREFIX.get(key_type, ())
    if (
        header_alg not in ASYMMETRIC_ALGORITHMS
        or not prefixes
        or not header_alg.startswith(prefixes)
    ):
        raise InvalidSupabaseTokenError(
            "رمز الدخول موقَّع بطريقة غير مدعومة. سجّل الدخول مرة أخرى."
        )
    return header_alg


def _decode(token: str, key: Any, algorithm: str) -> dict[str, Any]:
    """يفكّ الرمز ويتحقق من التوقيع والمدة والمُصدِر والجمهور والهوية.

    ``algorithms`` تحمل **اسمًا واحدًا** دائمًا: تمرير قائمة يترك لمن يصوغ
    الترويسة أن يختار من بينها.
    """
    return jwt.decode(
        token,
        key,
        algorithms=[algorithm],
        # كل رموز مستخدمي Supabase جمهورها "authenticated". اشتراطه يمنع
        # قبول رمز خدمة أو رمز مشروع آخر في مسار مستخدم.
        audience="authenticated",
        issuer=_expected_issuer(),
        leeway=CLOCK_SKEW_SECONDS,
        options={
            "require": ["exp", "sub", "aud", "iss"],
            "verify_signature": True,
            "verify_exp": True,
            "verify_aud": True,
            "verify_iss": True,
        },
    )


def _verify_asymmetric(token: str, header: dict[str, Any]) -> dict[str, Any]:
    """يتحقق من رمز ES256/RS256 بمفتاح JWKS الموافق لـ``kid``."""
    if not (settings.supabase_url or "").strip():
        raise SupabaseAuthNotConfiguredError(
            "التحقق من رموز الدخول غير مهيّأ على هذا السيرفر. المتغير "
            "الناقص: SUPABASE_URL."
        )

    kid = str(header.get("kid") or "").strip()
    if not kid:
        # مفاتيح Supabase كلها تحمل `kid`. غيابه يعني رمزًا ليس منها.
        raise InvalidSupabaseTokenError(
            "رمز الدخول غير صالح. سجّل الدخول مرة أخرى."
        )

    try:
        key = supabase_jwks.signing_key(kid)
    except supabase_jwks.UnknownSigningKeyError as exc:
        # قد يكون المشروع دوّر مفاتيحه؛ الجلسة القديمة لم تعد قابلة للتحقق.
        raise InvalidSupabaseTokenError(
            "لم تعد جلستك صالحة على هذا السيرفر. سجّل الدخول مرة أخرى."
        ) from exc
    except supabase_jwks.JwksUnavailableError as exc:
        # ⚠️ **ليست جلسةً ساقطة**: خلل شبكة أو إعداد. لو رُدّت 401 لأخرجت
        # كل المستخدمين من حساباتهم بسبب عطل عابر في Supabase.
        raise SupabaseAuthNotConfiguredError(
            "تعذّر التحقق من الجلسة حاليًا. أعد المحاولة بعد قليل."
        ) from exc

    return _decode(token, key.key, _algorithm_for(key, str(header.get("alg") or "")))


def _verify_symmetric(token: str) -> dict[str, Any]:
    """يتحقق من رمز HS256 بـ``SUPABASE_JWT_SECRET`` (المشاريع القديمة)."""
    secret = (settings.supabase_jwt_secret or "").strip()
    if not secret:
        raise SupabaseAuthNotConfiguredError(
            "التحقق من رموز الدخول غير مهيّأ على هذا السيرفر. المتغير "
            "الناقص: SUPABASE_JWT_SECRET."
        )
    return _decode(token, secret, SYMMETRIC_ALGORITHM)


def verify_access_token(token: str) -> SupabaseIdentity:
    """يتحقق من رمز Supabase محليًا ويعيد هوية صاحبه.

    يدعم توقيع المشاريع الحديثة (ES256/RS256 عبر JWKS) والقديمة (HS256
    بسرّ المشروع)، **ولا يطلب من العميل تغيير إعداد التوقيع**.

    Raises:
        SupabaseAuthNotConfiguredError: إعداد ناقص، أو تعذّر جلب JWKS.
        InvalidSupabaseTokenError: رمز مفقود أو تالف أو منتهٍ أو لجمهور
            أو مُصدِر آخر، أو موقَّع بخوارزمية غير مسموحة.
    """
    token = (token or "").strip()
    if not token:
        raise InvalidSupabaseTokenError("رمز الدخول مفقود. سجّل الدخول أولًا.")

    # ⚠️ الترويسة **غير موثوقة**؛ تُقرأ لاختيار المسار وحده، ثم تُحصر في
    # قائمة سماح قبل أن تُستعمل في أي شيء.
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise InvalidSupabaseTokenError(
            "رمز الدخول غير صالح. سجّل الدخول مرة أخرى."
        ) from exc

    algorithm = str(header.get("alg") or "").strip()

    try:
        if algorithm in ASYMMETRIC_ALGORITHMS:
            claims = _verify_asymmetric(token, header)
        elif algorithm == SYMMETRIC_ALGORITHM:
            claims = _verify_symmetric(token)
        else:
            # `none` وكل ما عداها. **لا تخمين ولا محاولة ثانية بمفتاح آخر.**
            logger.info("رمز بخوارزمية غير مسموحة: %r", algorithm[:16])
            raise InvalidSupabaseTokenError(
                "رمز الدخول موقَّع بطريقة غير مدعومة. سجّل الدخول مرة أخرى."
            )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidSupabaseTokenError(
            "انتهت صلاحية جلستك. سجّل الدخول مرة أخرى."
        ) from exc
    except jwt.InvalidIssuerError as exc:
        raise InvalidSupabaseTokenError(
            "رمز الدخول صادر عن جهة أخرى. سجّل الدخول مرة أخرى."
        ) from exc
    except jwt.InvalidAudienceError as exc:
        raise InvalidSupabaseTokenError(
            "رمز الدخول ليس رمز مستخدم. سجّل الدخول مرة أخرى."
        ) from exc
    except jwt.InvalidTokenError as exc:
        # ⚠️ **لا يُسجَّل الرمز ولا أي جزء منه.** نوع الخطأ وحده يكفي للتشخيص.
        logger.info("رُفض رمز دخول: %s", type(exc).__name__)
        raise InvalidSupabaseTokenError(
            "رمز الدخول غير صالح. سجّل الدخول مرة أخرى."
        ) from exc

    user_id = str(claims.get("sub") or "").strip()
    if not user_id:
        raise InvalidSupabaseTokenError("رمز الدخول لا يحمل هوية صاحبه.")

    return SupabaseIdentity(
        user_id=user_id, email=str(claims.get("email") or "").strip().lower()
    )
