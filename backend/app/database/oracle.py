"""طبقة الاتصال بـOracle Database.

**الاتصال كسول عمدًا:** لا تُستورد حزمة `oracledb` ولا يُنشأ Connection Pool
إلا عند أول استخدام فعلي للقاعدة. المشروع يقلع ويعمل بالكامل بـ
MODEL_PROVIDER=mock وحقول Oracle فارغة، ولا تُلمَس الشبكة إطلاقًا حينها.

لا توجد أي بيانات اعتماد في هذا الملف؛ تُقرأ كلها من متغيرات البيئة.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ..core.config import settings

#: المتغيرات التي بدونها لا يمكن الاتصال، بأسمائها كما تظهر في ملف .env.
_REQUIRED_SETTINGS: tuple[tuple[str, str], ...] = (
    ("ORACLE_DSN", "oracle_dsn"),
    ("ORACLE_USER", "oracle_user"),
    ("ORACLE_PASSWORD", "oracle_password"),
)


class DatabaseError(Exception):
    """خطأ في التعامل مع قاعدة البيانات، برسالة عربية صالحة للعرض.

    الرسالة مكتوبة لتُعرض للمستخدم مباشرة: لا Stack Trace ولا نص إنجليزي خام.
    """


class DatabaseNotConfiguredError(DatabaseError):
    """إعدادات Oracle ناقصة — حالة متوقعة في التشغيل المحلي بـmock."""


@dataclass(frozen=True)
class OracleStatus:
    """نتيجة فحص حالة القاعدة. تُستخدم في /health ولا ترفع استثناءً أبدًا."""

    configured: bool
    #: not_configured | ok | error
    status: str
    detail: str | None = None


_pool: Any = None
_pool_lock = threading.Lock()


# ---------------------------------------------------------------------------
# الإعدادات
# ---------------------------------------------------------------------------
def missing_settings() -> list[str]:
    """يعيد أسماء متغيرات Oracle الناقصة (الفارغة) كما تظهر في .env."""
    return [
        env_name
        for env_name, field in _REQUIRED_SETTINGS
        if not (getattr(settings, field, "") or "").strip()
    ]


def is_configured() -> bool:
    """هل ضُبطت كل متغيرات Oracle المطلوبة؟ لا يفتح أي اتصال."""
    return not missing_settings()


def _require_configuration() -> None:
    missing = missing_settings()
    if missing:
        raise DatabaseNotConfiguredError(
            "إعداد قاعدة بيانات Oracle غير مكتمل. المتغيرات الناقصة: "
            f"{'، '.join(missing)}. اضبطها في ملف .env على السيرفر. "
            "المشروع يعمل بدون قاعدة بيانات في وضع التطوير."
        )


# ---------------------------------------------------------------------------
# الاستيراد الكسول وإنشاء الـPool
# ---------------------------------------------------------------------------
def _import_oracledb() -> Any:
    """يستورد oracledb عند الحاجة فقط، ويشرح الحل إن كانت غير مثبّتة."""
    try:
        import oracledb
    except ImportError as exc:
        raise DatabaseError(
            "حزمة oracledb غير مثبّتة على هذا السيرفر، ولا يمكن الاتصال بقاعدة "
            "بيانات Oracle. ثبّتها عبر: pip install -r requirements.txt"
        ) from exc
    return oracledb


def _translate_error(exc: Exception) -> str:
    """يحوّل خطأ الدرايفر إلى رسالة عربية مفهومة بلا Stack Trace خام."""
    raw = str(exc)

    if "ORA-01017" in raw or "DPY-4001" in raw:
        return (
            "بيانات الدخول إلى قاعدة Oracle غير صحيحة (اسم المستخدم أو كلمة "
            "المرور). راجع ORACLE_USER و ORACLE_PASSWORD."
        )
    if "ORA-12154" in raw or "DPY-4000" in raw or "DPY-4027" in raw:
        return (
            "تعذّر تحديد قاعدة البيانات من ORACLE_DSN. راجع صيغة الـDSN "
            "(مثال: host:1521/service_name)."
        )
    if "ORA-12541" in raw or "DPY-6005" in raw or "DPY-4011" in raw:
        return (
            "تعذّر الوصول إلى سيرفر قاعدة Oracle. تأكد من تشغيل القاعدة ومن أن "
            "الشبكة والمنفذ يسمحان بالاتصال."
        )
    if "DPY-4024" in raw or "timeout" in raw.lower():
        return (
            "انتهت مهلة الاتصال بقاعدة Oracle قبل استجابة السيرفر. راجع الشبكة "
            "وقيمة ORACLE_DSN."
        )
    if "ORA-28000" in raw:
        return (
            "حساب المستخدم في قاعدة Oracle مقفل. اطلب من مسؤول القاعدة فكّ "
            "القفل عن ORACLE_USER."
        )

    # رمز الدرايفر (ORA-xxxxx أو DPY-xxxx) مفيد للدعم الفني بلا كشف تفاصيل.
    code = raw.split(":", 1)[0].strip() or "غير معروف"
    return (
        "تعذّر الاتصال بقاعدة بيانات Oracle. راجع ORACLE_DSN و ORACLE_USER و "
        f"ORACLE_PASSWORD. رمز الخطأ من الدرايفر: {code}"
    )


def get_pool() -> Any:
    """يعيد الـConnection Pool، وينشئه عند أول استدعاء فقط.

    Raises:
        DatabaseNotConfiguredError: إذا كانت متغيرات Oracle ناقصة.
        DatabaseError: إذا فشل إنشاء الـPool (بيانات خاطئة أو تعذّر الوصول).
    """
    global _pool
    if _pool is not None:
        return _pool

    _require_configuration()
    oracledb = _import_oracledb()

    with _pool_lock:
        # قد يكون خيط آخر أنشأ الـPool أثناء انتظار القفل.
        if _pool is not None:
            return _pool
        try:
            _pool = oracledb.create_pool(
                user=settings.oracle_user.strip(),
                password=settings.oracle_password,
                dsn=settings.oracle_dsn.strip(),
                min=settings.oracle_pool_min,
                max=settings.oracle_pool_max,
                increment=1,
                timeout=settings.oracle_pool_idle_timeout,
            )
        except Exception as exc:
            raise DatabaseError(_translate_error(exc)) from exc
    return _pool


@contextmanager
def get_connection() -> Iterator[Any]:
    """يعطي اتصالًا من الـPool ويعيده إليه تلقائيًا عند الخروج.

    مثال::

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM dual")

    Raises:
        DatabaseNotConfiguredError: إذا كانت متغيرات Oracle ناقصة.
        DatabaseError: إذا تعذّر الحصول على اتصال.
    """
    pool = get_pool()
    try:
        connection = pool.acquire()
    except Exception as exc:
        raise DatabaseError(_translate_error(exc)) from exc

    try:
        yield connection
    finally:
        try:
            pool.release(connection)
        except Exception:
            # إعادة الاتصال إلى الـPool يجب ألا تُسقط الطلب الأصلي.
            pass


def close_pool() -> None:
    """يغلق الـPool عند إيقاف التطبيق. آمن الاستدعاء ولو لم يُنشأ Pool أصلًا."""
    global _pool
    with _pool_lock:
        if _pool is None:
            return
        try:
            _pool.close(force=True)
        except Exception:
            # إيقاف التطبيق يجب ألا يفشل بسبب Pool تالف.
            pass
        finally:
            _pool = None


# ---------------------------------------------------------------------------
# فحص الحالة — لا يرفع استثناءً أبدًا
# ---------------------------------------------------------------------------
def check_status() -> OracleStatus:
    """يفحص القاعدة لأجل /health دون أن يُفشل الفحص عند غياب الإعداد."""
    missing = missing_settings()
    if missing:
        return OracleStatus(
            configured=False,
            status="not_configured",
            detail=(
                "قاعدة Oracle غير مضبوطة (المتغيرات الناقصة: "
                f"{'، '.join(missing)}). النظام يعمل بدونها في وضع التطوير."
            ),
        )

    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM dual")
                cursor.fetchone()
    except DatabaseError as exc:
        return OracleStatus(configured=True, status="error", detail=str(exc))
    except Exception as exc:
        return OracleStatus(
            configured=True, status="error", detail=_translate_error(exc)
        )
    return OracleStatus(configured=True, status="ok", detail=None)
