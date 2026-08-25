"""اختبارات طبقة الاتصال بـOracle.

لا يوجد هنا أي اتصال حقيقي بقاعدة بيانات ولا أي بيانات اعتماد: المُختبَر هو
كسل الاتصال، والتحقق من الإعدادات، وترجمة أخطاء الدرايفر إلى رسائل عربية،
والإغلاق النظيف. الاختبار الفعلي مقابل قاعدة حقيقية مؤجَّل — انظر
test_schema_runs_on_a_clean_database_pending_oracle_setup في آخر الملف.
"""

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.database import oracle
from app.database import (
    DatabaseError,
    DatabaseNotConfiguredError,
    check_status,
    close_pool,
    get_connection,
    is_configured,
    missing_settings,
)


@pytest.fixture(autouse=True)
def clean_pool():
    """يضمن ألا يتسرب Pool وهمي من اختبار إلى آخر."""
    oracle._pool = None
    yield
    oracle._pool = None


@pytest.fixture
def oracle_settings(monkeypatch):
    def apply(dsn: str = "", user: str = "", password: str = "") -> None:
        monkeypatch.setattr(settings, "oracle_dsn", dsn)
        monkeypatch.setattr(settings, "oracle_user", user)
        monkeypatch.setattr(settings, "oracle_password", password)

    return apply


FULL_CONFIG = {
    "dsn": "localhost:1521/FREEPDB1",
    "user": "govagent",
    "password": "secret",
}


# ---------------------------------------------------------------------------
# 1) الإعدادات الناقصة
# ---------------------------------------------------------------------------
def test_missing_settings_lists_every_empty_variable(oracle_settings):
    oracle_settings()
    assert missing_settings() == ["ORACLE_DSN", "ORACLE_USER", "ORACLE_PASSWORD"]
    assert is_configured() is False


def test_whitespace_only_settings_count_as_missing(oracle_settings):
    oracle_settings(dsn="   ", user="govagent", password="secret")
    assert missing_settings() == ["ORACLE_DSN"]


def test_full_settings_are_recognised(oracle_settings):
    oracle_settings(**FULL_CONFIG)
    assert missing_settings() == []
    assert is_configured() is True


def test_connection_without_configuration_raises_a_clear_arabic_error(
    oracle_settings,
):
    oracle_settings()
    with pytest.raises(DatabaseNotConfiguredError) as exc:
        with get_connection():
            pass

    message = str(exc.value)
    assert "ORACLE_DSN" in message
    assert "ORACLE_USER" in message
    assert "ORACLE_PASSWORD" in message
    assert isinstance(exc.value, DatabaseError)


# ---------------------------------------------------------------------------
# 2) كسل الاتصال
# ---------------------------------------------------------------------------
def test_no_pool_is_created_before_first_use(oracle_settings):
    """مجرد ضبط المتغيرات لا يفتح أي اتصال."""
    oracle_settings(**FULL_CONFIG)
    assert oracle._pool is None
    assert is_configured() is True
    assert oracle._pool is None


def test_driver_is_not_imported_when_configuration_is_missing(
    oracle_settings, monkeypatch
):
    """الإعداد الناقص يُكتشف قبل أي محاولة استيراد للدرايفر."""
    oracle_settings()

    def fail() -> None:
        raise AssertionError("لا يجوز استيراد oracledb قبل التحقق من الإعدادات")

    monkeypatch.setattr(oracle, "_import_oracledb", fail)
    with pytest.raises(DatabaseNotConfiguredError):
        oracle.get_pool()


def test_pool_is_created_once_and_reused(oracle_settings, monkeypatch):
    oracle_settings(**FULL_CONFIG)
    calls = []

    def fake_create_pool(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(close=lambda force=False: None)

    monkeypatch.setattr(
        oracle,
        "_import_oracledb",
        lambda: SimpleNamespace(create_pool=fake_create_pool),
    )

    first = oracle.get_pool()
    second = oracle.get_pool()

    assert first is second
    assert len(calls) == 1
    assert calls[0]["dsn"] == FULL_CONFIG["dsn"]
    assert calls[0]["user"] == FULL_CONFIG["user"]
    assert calls[0]["min"] == settings.oracle_pool_min
    assert calls[0]["max"] == settings.oracle_pool_max


# ---------------------------------------------------------------------------
# 3) ترجمة أخطاء الدرايفر إلى رسائل عربية
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ORA-01017: invalid username/password", "كلمة المرور"),
        ("DPY-4000: cannot parse connect string", "ORACLE_DSN"),
        ("ORA-12541: TNS:no listener", "تعذّر الوصول"),
        ("DPY-4024: connection timed out", "مهلة"),
        ("ORA-28000: the account is locked", "مقفل"),
        ("ORA-99999: something unexpected", "ORA-99999"),
    ],
)
def test_driver_errors_become_arabic_messages(raw, expected):
    assert expected in oracle._translate_error(Exception(raw))


def test_pool_creation_failure_is_wrapped_without_stack_trace(
    oracle_settings, monkeypatch
):
    oracle_settings(**FULL_CONFIG)

    def failing_create_pool(**_kwargs):
        raise Exception("ORA-01017: invalid username/password")

    monkeypatch.setattr(
        oracle,
        "_import_oracledb",
        lambda: SimpleNamespace(create_pool=failing_create_pool),
    )

    with pytest.raises(DatabaseError) as exc:
        oracle.get_pool()

    message = str(exc.value)
    assert "كلمة المرور" in message
    assert "Traceback" not in message


# ---------------------------------------------------------------------------
# 4) الإغلاق النظيف
# ---------------------------------------------------------------------------
def test_close_pool_is_safe_when_no_pool_exists():
    close_pool()  # لا يرفع شيئًا
    assert oracle._pool is None


def test_close_pool_closes_and_clears(monkeypatch):
    closed = []
    oracle._pool = SimpleNamespace(close=lambda force=False: closed.append(force))

    close_pool()

    assert closed == [True]
    assert oracle._pool is None


def test_close_pool_survives_a_broken_pool():
    """الإيقاف يجب ألا يفشل بسبب Pool تالف."""

    def broken(force=False):
        raise Exception("DPY-1001: not connected")

    oracle._pool = SimpleNamespace(close=broken)
    close_pool()
    assert oracle._pool is None


# ---------------------------------------------------------------------------
# 5) فحص الحالة لا يرفع استثناءً أبدًا
# ---------------------------------------------------------------------------
def test_status_when_not_configured(oracle_settings):
    oracle_settings()
    status = check_status()
    assert status.configured is False
    assert status.status == "not_configured"
    assert "ORACLE_DSN" in status.detail


def test_status_reports_error_instead_of_raising(oracle_settings, monkeypatch):
    oracle_settings(**FULL_CONFIG)

    def failing_create_pool(**_kwargs):
        raise Exception("ORA-12541: TNS:no listener")

    monkeypatch.setattr(
        oracle,
        "_import_oracledb",
        lambda: SimpleNamespace(create_pool=failing_create_pool),
    )

    status = check_status()

    assert status.configured is True
    assert status.status == "error"
    assert "تعذّر الوصول" in status.detail


def test_status_ok_when_the_probe_query_succeeds(oracle_settings, monkeypatch):
    oracle_settings(**FULL_CONFIG)
    executed = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql):
            executed.append(sql)

        def fetchone(self):
            return (1,)

    released = []
    connection = SimpleNamespace(cursor=FakeCursor)
    pool = SimpleNamespace(
        acquire=lambda: connection,
        release=released.append,
        close=lambda force=False: None,
    )
    monkeypatch.setattr(
        oracle, "_import_oracledb", lambda: SimpleNamespace(create_pool=lambda **k: pool)
    )

    status = check_status()

    assert status.status == "ok"
    assert status.detail is None
    assert executed == ["SELECT 1 FROM dual"]
    # الاتصال يعود إلى الـPool دائمًا.
    assert released == [connection]


def test_connection_is_released_even_when_the_caller_raises(
    oracle_settings, monkeypatch
):
    oracle_settings(**FULL_CONFIG)
    released = []
    connection = object()
    pool = SimpleNamespace(acquire=lambda: connection, release=released.append)
    monkeypatch.setattr(
        oracle, "_import_oracledb", lambda: SimpleNamespace(create_pool=lambda **k: pool)
    )

    with pytest.raises(ValueError):
        with get_connection():
            raise ValueError("فشل في منطق الاستدعاء")

    assert released == [connection]


# ---------------------------------------------------------------------------
# 6) الاختبار الحي — مؤجَّل
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason=(
        "Pending Oracle Setup — لا توجد حتى الآن قاعدة Oracle ولا بيانات دخول، "
        "فلا يمكن تشغيل database/schema.sql فعليًا ولا التحقق من الجداول "
        "التسعة. يُفعَّل هذا الاختبار بعد تجهيز القاعدة."
    )
)
def test_schema_runs_on_a_clean_database_pending_oracle_setup():
    """تشغيل database/schema.sql على قاعدة نظيفة والتحقق من الجداول التسعة."""
    expected = {
        "ORGANIZATIONS",
        "USERS",
        "SUBSCRIPTIONS",
        "CONVERSATIONS",
        "MESSAGES",
        "FILES",
        "DOCUMENT_CHUNKS",
        "MODEL_SETTINGS",
        "AUDIT_LOGS",
    }
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT table_name FROM user_tables")
            tables = {row[0] for row in cursor.fetchall()}
    assert expected <= tables
