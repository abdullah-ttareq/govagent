"""تجزئة كلمات المرور وإصدار التوكن والتحقق منه.

هذا الملف هو **المكان الوحيد** الذي يلمس كلمة المرور الصريحة أو سر التوكن.
لا تُخزَّن كلمة المرور صريحة في أي مكان: تدخل هنا مرة واحدة لتُجزَّأ أو
لتُقارن بالتجزئة، ولا تُكتب في سجل ولا في رد ولا في قاعدة بيانات.

السر لا يوجد له قيمة افتراضية في الكود عمدًا: سر ثابت داخل المستودع يعني أن
كل من يملك نسخة منه يستطيع تزوير توكن صالح لأي مستخدم.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from .config import settings

#: bcrypt يقصّ ما زاد على ٧٢ بايت بصمت (وترفضه bcrypt‏ 4.1+ بخطأ). الحد
#: يُفحص بالبايت لا بالحرف: الحرف العربي يشغل بايتين في UTF-8، فكلمة مرور
#: عربية من ٤٠ حرفًا تتجاوز الحد رغم قصرها ظاهريًا.
MAX_PASSWORD_BYTES = 72

#: أقل طول مقبول لكلمة المرور عند إنشائها.
MIN_PASSWORD_LENGTH = 8


class SecurityError(Exception):
    """خطأ في المصادقة أو في التوكن، برسالة عربية صالحة للعرض مباشرة."""


class InvalidTokenError(SecurityError):
    """توكن تالف أو موقّع بسر آخر."""


class ExpiredTokenError(SecurityError):
    """توكن انتهت صلاحيته."""


@dataclass(frozen=True)
class TokenPayload:
    """محتوى التوكن بعد التحقق منه.

    هذه هي هوية صاحب الطلب كما يثق بها الـBackend. أي قيمة هنا مصدرها
    التوقيع، لا جسم الطلب — وهو أساس عزل الجهات في P2-02.
    """

    user_id: int
    organization_id: int
    role: str
    expires_at: datetime


# ---------------------------------------------------------------------------
# كلمات المرور
# ---------------------------------------------------------------------------
def _encode_password(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise SecurityError(
            f"كلمة المرور أطول من الحد المسموح ({MAX_PASSWORD_BYTES} بايت). "
            "الحروف العربية تشغل بايتين لكل حرف، فاختصر كلمة المرور."
        )
    return raw


def hash_password(password: str) -> str:
    """يعيد تجزئة bcrypt لكلمة المرور، صالحة للتخزين في users.password_hash.

    Raises:
        SecurityError: إذا كانت كلمة المرور قصيرة أو أطول من حد bcrypt.
    """
    if len(password.strip()) < MIN_PASSWORD_LENGTH:
        raise SecurityError(
            f"كلمة المرور قصيرة. الحد الأدنى {MIN_PASSWORD_LENGTH} أحرف."
        )
    return bcrypt.hashpw(_encode_password(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """يطابق كلمة مرور مع تجزئتها. يعيد False بدل رفع استثناء عند أي خلل.

    الطول الزائد أو التجزئة التالفة تعني "لا تطابق" لا "خطأ في النظام": مسار
    تسجيل الدخول يجب أن يعطي الرد نفسه في كل حالات الفشل حتى لا يكشف الفرق.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


#: تجزئة جاهزة لكلمة مرور عشوائية، تُستهلك عند فشل إيجاد المستخدم حتى يستغرق
#: الرد الزمن نفسه سواء وُجد البريد أم لا. بدونها يكشف فرق التوقيت أي بريد
#: مسجّل في النظام (تعداد المستخدمين).
_DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode("utf-8")


def waste_password_comparison() -> None:
    """يستهلك زمن تحقق bcrypt دون أن يطابق شيئًا."""
    bcrypt.checkpw(b"no-such-user", _DUMMY_HASH.encode("utf-8"))


# ---------------------------------------------------------------------------
# سر التوكن
# ---------------------------------------------------------------------------
_ephemeral_secret: str | None = None
_secret_lock = threading.Lock()


def get_jwt_secret() -> str:
    """يعيد سر توقيع التوكن.

    في التطوير: إن كان ``JWT_SECRET`` فارغًا يُولَّد سر عشوائي في الذاكرة مرة
    واحدة لكل تشغيل، فيعمل المشروع بعد ``cp .env.example .env`` مباشرة. أثره
    الوحيد أن التوكنات القديمة تسقط عند كل إعادة تشغيل، وهو مقبول محليًا.

    خارج التطوير: السر الفارغ يوقف الطلب برسالة واضحة، لأن سرًا يتغيّر عند كل
    إقلاع يعني خروج كل الموظفين عند كل نشر، وسرًا مكتوبًا في الكود يعني تزوير
    التوكن من أي نسخة من المستودع.

    Raises:
        SecurityError: إذا كان السر فارغًا خارج بيئة التطوير.
    """
    global _ephemeral_secret

    configured = settings.jwt_secret.strip()
    if configured:
        return configured

    if settings.app_env.strip().lower() != "development":
        raise SecurityError(
            "متغير JWT_SECRET غير مضبوط على هذا السيرفر، ولا يمكن إصدار توكن "
            "بدونه. اضبطه في ملف .env بقيمة عشوائية طويلة، مثلًا عبر: "
            "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )

    with _secret_lock:
        if _ephemeral_secret is None:
            _ephemeral_secret = secrets.token_urlsafe(48)
    return _ephemeral_secret


# ---------------------------------------------------------------------------
# إصدار التوكن والتحقق منه
# ---------------------------------------------------------------------------
def create_access_token(
    *,
    user_id: int,
    organization_id: int,
    role: str,
    expires_minutes: int | None = None,
) -> tuple[str, datetime]:
    """يصدر توكن دخول موقّعًا ويعيده مع لحظة انتهائه.

    الحمولة تحمل ``user_id`` و ``organization_id`` و ``role`` لأن كل مسار محمي
    يقرأ الجهة والدور من هنا لا من جسم الطلب.

    Returns:
        (التوكن، لحظة الانتهاء بتوقيت UTC).

    Raises:
        SecurityError: إذا تعذّر الحصول على سر التوقيع.
    """
    minutes = settings.jwt_expire_minutes if expires_minutes is None else expires_minutes
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=minutes)

    payload: dict[str, Any] = {
        # sub نصّي التزامًا بمواصفة JWT، ويُعاد إلى int عند القراءة.
        "sub": str(user_id),
        "organization_id": organization_id,
        "role": role,
        "iat": issued_at,
        "exp": expires_at,
    }
    token = jwt.encode(payload, get_jwt_secret(), algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(token: str) -> TokenPayload:
    """يتحقق من توقيع التوكن وصلاحيته ويعيد هوية صاحبه.

    Raises:
        ExpiredTokenError: إذا انتهت صلاحية التوكن.
        InvalidTokenError: إذا كان التوقيع خاطئًا أو الشكل تالفًا أو الحمولة ناقصة.
        SecurityError: إذا تعذّر الحصول على سر التوقيع.
    """
    secret = get_jwt_secret()
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[settings.jwt_algorithm],
            # الخوارزمية مثبّتة أعلاه، فتوكن بـalg=none أو بخوارزمية أخرى
            # يُرفض. مع اشتراط وجود exp حتى لا يمر توكن أبدي.
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ExpiredTokenError(
            "انتهت صلاحية جلستك. سجّل الدخول من جديد للمتابعة."
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(
            "رمز الدخول غير صالح. سجّل الدخول من جديد للمتابعة."
        ) from exc

    try:
        user_id = int(claims["sub"])
        organization_id = int(claims["organization_id"])
        role = str(claims["role"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidTokenError(
            "رمز الدخول ناقص أو غير مفهوم. سجّل الدخول من جديد للمتابعة."
        ) from exc

    return TokenPayload(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
    )
