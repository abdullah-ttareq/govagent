"""طبقة الوصول إلى Oracle Database.

الاتصال كسول: لا يُفتح Pool ولا تُستورد حزمة oracledb إلا عند أول استخدام
فعلي. المخطط في database/schema.sql، وخطوات التشغيل في database/README.md.
الـRepositories تأتي في مهام لاحقة (P1-03 و P1-04).
"""

from .documents import (
    ChunkPersistenceError,
    count_chunks,
    delete_chunks,
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
from .audit import fetch_events, insert_event
from .organization_settings import (
    fetch_model_settings,
    fetch_subscription,
    save_model_settings,
    save_subscription,
)
from .conversations import (
    delete_conversation_row,
    fetch_conversation,
    fetch_conversations,
    fetch_messages,
    fetch_recent_messages,
    insert_conversation,
    insert_messages,
    update_conversation_title,
)
from .files import (
    delete_file_row,
    fetch_file,
    fetch_files,
    insert_file,
    update_file_status,
)
from .users import (
    count_active_users,
    email_exists,
    fetch_organization,
    fetch_organization_by_slug,
    fetch_user,
    fetch_user_by_email,
    fetch_users,
    find_users_by_email,
    insert_organization,
    insert_user,
    update_organization_row,
    update_user_row,
)

__all__ = [
    # الاشتراك وإعدادات المودل وسجل التدقيق
    "fetch_events",
    "fetch_model_settings",
    "fetch_subscription",
    "insert_event",
    "save_model_settings",
    "save_subscription",
    # المحادثات والرسائل والملفات
    "delete_conversation_row",
    "delete_file_row",
    "fetch_conversation",
    "fetch_conversations",
    "fetch_file",
    "fetch_files",
    "fetch_messages",
    "fetch_recent_messages",
    "insert_conversation",
    "insert_file",
    "insert_messages",
    "update_conversation_title",
    "update_file_status",
    "ChunkPersistenceError",
    "count_chunks",
    "delete_chunks",
    "save_chunks",
    "search_chunks",
    "count_active_users",
    "email_exists",
    "fetch_organization",
    "fetch_organization_by_slug",
    "fetch_user",
    "fetch_user_by_email",
    "fetch_users",
    "find_users_by_email",
    "insert_organization",
    "insert_user",
    "update_organization_row",
    "update_user_row",
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
