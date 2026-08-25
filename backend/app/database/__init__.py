"""طبقة الوصول إلى Oracle Database.

الاتصال كسول: لا يُفتح Pool ولا تُستورد حزمة oracledb إلا عند أول استخدام
فعلي. المخطط في database/schema.sql، وخطوات التشغيل في database/README.md.
الـRepositories تأتي في مهام لاحقة (P1-03 و P1-04).
"""

from .documents import (
    ChunkPersistenceError,
    count_chunks,
    save_chunks,
    search_chunks,
)
from .oracle import (
    DatabaseError,
    DatabaseNotConfiguredError,
    OracleStatus,
    check_status,
    close_pool,
    get_connection,
    get_pool,
    is_configured,
    missing_settings,
)

__all__ = [
    "ChunkPersistenceError",
    "count_chunks",
    "save_chunks",
    "search_chunks",
    "DatabaseError",
    "DatabaseNotConfiguredError",
    "OracleStatus",
    "check_status",
    "close_pool",
    "get_connection",
    "get_pool",
    "is_configured",
    "missing_settings",
]
