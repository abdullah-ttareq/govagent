"""المصادقة عبر Supabase Auth (`auth.users`) — بلا نظام كلمات مرور خاص.

**لماذا يمرّ تسجيل الدخول بالـBackend بدل أن تنادي الإضافة Supabase مباشرة؟**
لأن الشرط أن **لا يُدخل المستخدم رابطًا ولا مفتاحًا ولا عنوان سيرفر**. لو
نادت الإضافة Supabase مباشرة لوجب أن تحمل `SUPABASE_URL` والمفتاح العام
داخلها، ولصار للنظام عنوانان يجب أن يتطابقا. بمرور الدخول بالـBackend لا
تعرف الإضافة سوى عنوان واحد مثبَّت وقت البناء، ويبقى كل ما عداه على السيرفر.

المفتاح العام (`anon`) يُستعمل في هذا الملف وحده، ولا يخرج منه إلى أي رد.
مفتاح `service_role` **لا يُستعمل هنا إطلاقًا**: تسجيل الدخول عملية تخصّ
المستخدم، ورمزها يجب أن يصدر باسمه هو لا باسم الخدمة.

**التحقق من الرمز محلّي**: يُفكّ توقيعه بـ`SUPABASE_JWT_SECRET` بلا نداء
شبكي في كل طلب. رمز منتهٍ أو موقّع بسرّ آخر يُرفض قبل لمس القاعدة.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from ..core.config import settings
from ..database import supabase


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


def verify_access_token(token: str) -> SupabaseIdentity:
    """يتحقق من رمز Supabase محليًا ويعيد هوية صاحبه.

    Raises:
        SupabaseAuthNotConfiguredError: إذا لم يُضبط ``SUPABASE_JWT_SECRET``.
        InvalidSupabaseTokenError: رمز مفقود أو تالف أو منتهٍ أو لجمهور آخر.
    """
    secret = (settings.supabase_jwt_secret or "").strip()
    if not secret:
        raise SupabaseAuthNotConfiguredError(
            "التحقق من رموز الدخول غير مهيّأ على هذا السيرفر. المتغير "
            "الناقص: SUPABASE_JWT_SECRET."
        )

    if not token or not token.strip():
        raise InvalidSupabaseTokenError("رمز الدخول مفقود. سجّل الدخول أولًا.")

    try:
        claims = jwt.decode(
            token.strip(),
            secret,
            algorithms=["HS256"],
            # كل رموز مستخدمي Supabase جمهورها "authenticated". اشتراطه يمنع
            # قبول رمز خدمة أو رمز مشروع آخر في مسار مستخدم.
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidSupabaseTokenError(
            "انتهت صلاحية جلستك. سجّل الدخول مرة أخرى."
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidSupabaseTokenError(
            "رمز الدخول غير صالح. سجّل الدخول مرة أخرى."
        ) from exc

    user_id = str(claims.get("sub") or "").strip()
    if not user_id:
        raise InvalidSupabaseTokenError("رمز الدخول لا يحمل هوية صاحبه.")

    return SupabaseIdentity(
        user_id=user_id, email=str(claims.get("email") or "").strip().lower()
    )
