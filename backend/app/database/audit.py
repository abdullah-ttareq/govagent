"""سجل التدقيق في جدول audit_logs.

**قاعدة العزل:** كل قراءة مقيّدة بـ``organization_id``، ولا توجد هنا عبارة
تقرأ السجل كله ولا عبارة تعدّله أو تحذفه — السجل يُضاف إليه فقط.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .oracle import get_connection

if TYPE_CHECKING:  # يُستورد للتلميح النوعي فقط.
    from ..services.audit_store import AuditEvent
    from ..services.conversation_store import Page

_EVENT_COLUMNS = """
    a.id, a.organization_id, a.user_id, a.action, a.details, a.created_at
"""

_INSERT_EVENT = """
    INSERT INTO audit_logs (organization_id, user_id, action, details)
    VALUES (:organization_id, :user_id, :action, :details)
    RETURNING id, created_at INTO :new_id, :created_at
"""

# الشرطان الاختياريان: NULL في أيهما يعني «بلا تصفية» لا «القيمة فارغة».
_EVENT_FILTERS = """
     WHERE a.organization_id = :organization_id
       AND (:action IS NULL OR a.action = :action)
       AND (:user_id IS NULL OR a.user_id = :user_id)
"""

_FETCH_EVENTS = f"""
    SELECT {_EVENT_COLUMNS}
      FROM audit_logs a
    {_EVENT_FILTERS}
     ORDER BY a.created_at DESC, a.id DESC
     OFFSET :row_offset ROWS FETCH NEXT :row_limit ROWS ONLY
"""

_COUNT_EVENTS = f"""
    SELECT COUNT(*)
      FROM audit_logs a
    {_EVENT_FILTERS}
"""


def _row_to_event(row) -> AuditEvent:
    from ..services.audit_store import AuditEvent

    return AuditEvent(
        id=int(row[0]),
        organization_id=int(row[1]),
        user_id=None if row[2] is None else int(row[2]),
        action=row[3],
        details=row[4],
        created_at=row[5],
    )


def _returned(variable):
    """يقرأ قيمة من متغير RETURNING (الدرايفر يعيد قائمة لعبارات DML)."""
    value = variable.getvalue()
    return value[0] if isinstance(value, list) else value


def insert_event(
    *,
    organization_id: int,
    user_id: int | None,
    action: str,
    details: str | None,
) -> AuditEvent:
    """يضيف حدثًا ويعيده بمعرّفه وطابعه الزمني المولَّدين."""
    import oracledb

    from ..services.audit_store import AuditEvent

    with get_connection() as connection:
        with connection.cursor() as cursor:
            new_id = cursor.var(int)
            created_at = cursor.var(oracledb.DB_TYPE_TIMESTAMP)
            cursor.execute(
                _INSERT_EVENT,
                {
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "action": action,
                    "details": details,
                    "new_id": new_id,
                    "created_at": created_at,
                },
            )
            event_id = int(_returned(new_id))
            created = _returned(created_at)
        connection.commit()

    return AuditEvent(
        id=event_id,
        organization_id=organization_id,
        user_id=user_id,
        action=action,
        details=details,
        created_at=created,
    )


def fetch_events(
    *,
    organization_id: int,
    action: str | None,
    user_id: int | None,
    limit: int,
    offset: int,
) -> Page:
    """يعيد صفحة من أحداث جهة واحدة، من الأحدث."""
    from ..services.conversation_store import Page

    scope = {
        "organization_id": organization_id,
        "action": action,
        "user_id": user_id,
    }
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _FETCH_EVENTS, {**scope, "row_offset": offset, "row_limit": limit}
            )
            rows = cursor.fetchall()
            cursor.execute(_COUNT_EVENTS, scope)
            total = int(cursor.fetchone()[0])

    return Page(
        items=[_row_to_event(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
