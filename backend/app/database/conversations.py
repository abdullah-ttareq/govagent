"""المحادثات والرسائل في جدولي conversations و messages.

**قاعدة العزل:** كل عبارة على المحادثات تحمل ``organization_id`` **و**
``user_id`` معًا — المحادثة خاصة بصاحبها لا بجهته. الشرطان جزء من عبارة SQL
نفسها لا مرشِّح بعدها، فصف موظف آخر لا يمكن أن يُقرأ ولا أن يتغيّر بها.

عبارات الرسائل مقيّدة بالمحادثة وبالجهة، وتحقُّق الملكية يسبقها في
`conversation_service`.

كل القيم تُمرَّر كمتغيرات مربوطة (`:name`) لا بدمج نصي، فلا مجال لحقن SQL.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from .oracle import get_connection

if TYPE_CHECKING:  # يُستورد للتلميح النوعي فقط.
    from ..services.conversation_store import Conversation, Message, Page

_CONVERSATION_COLUMNS = """
    c.id, c.organization_id, c.user_id, c.title, c.created_at, c.updated_at,
    (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id)
"""

_MESSAGE_COLUMNS = """
    m.id, m.conversation_id, m.organization_id, m.role, m.content, m.created_at
"""

_INSERT_CONVERSATION = """
    INSERT INTO conversations (organization_id, user_id, title)
    VALUES (:organization_id, :user_id, :title)
    RETURNING id, created_at, updated_at INTO :new_id, :created_at, :updated_at
"""

_FETCH_CONVERSATION = f"""
    SELECT {_CONVERSATION_COLUMNS}
      FROM conversations c
     WHERE c.id = :conversation_id
       AND c.organization_id = :organization_id
       AND c.user_id = :user_id
"""

# الأحدث تعديلًا أولًا، والمعرّف يحسم التساوي فلا يتقلب الترتيب بين صفحتين.
_FETCH_CONVERSATIONS = f"""
    SELECT {_CONVERSATION_COLUMNS}
      FROM conversations c
     WHERE c.organization_id = :organization_id
       AND c.user_id = :user_id
     ORDER BY c.updated_at DESC, c.id DESC
     OFFSET :row_offset ROWS FETCH NEXT :row_limit ROWS ONLY
"""

_COUNT_CONVERSATIONS = """
    SELECT COUNT(*)
      FROM conversations c
     WHERE c.organization_id = :organization_id
       AND c.user_id = :user_id
"""

_UPDATE_CONVERSATION_TITLE = """
    UPDATE conversations
       SET title = :title,
           updated_at = SYSTIMESTAMP
     WHERE id = :conversation_id
       AND organization_id = :organization_id
       AND user_id = :user_id
"""

# رسائل المحادثة تذهب معها بـON DELETE CASCADE في المخطط، فلا حذف يدوي لها.
_DELETE_CONVERSATION = """
    DELETE FROM conversations
     WHERE id = :conversation_id
       AND organization_id = :organization_id
       AND user_id = :user_id
"""

_INSERT_MESSAGE = """
    INSERT INTO messages (conversation_id, organization_id, role, content)
    VALUES (:conversation_id, :organization_id, :role, :content)
"""

_TOUCH_CONVERSATION = """
    UPDATE conversations
       SET updated_at = SYSTIMESTAMP
     WHERE id = :conversation_id
       AND organization_id = :organization_id
"""

# الترتيب بالمعرّف بعد الوقت: رسالتا التبادل الواحد تُدرجان في المعاملة نفسها
# فتحملان الطابع الزمني نفسه، والمعرّف وحده يحسم أيهما السؤال وأيهما الجواب.
_FETCH_MESSAGES = f"""
    SELECT {_MESSAGE_COLUMNS}
      FROM messages m
     WHERE m.conversation_id = :conversation_id
       AND m.organization_id = :organization_id
     ORDER BY m.created_at, m.id
     OFFSET :row_offset ROWS FETCH NEXT :row_limit ROWS ONLY
"""

_COUNT_MESSAGES = """
    SELECT COUNT(*)
      FROM messages m
     WHERE m.conversation_id = :conversation_id
       AND m.organization_id = :organization_id
"""

# آخر الرسائل: تُقرأ تنازليًا ثم تُقلب في بايثون. الترتيب الصاعد مع
# FETCH FIRST كان سيعطي أقدمها لا أحدثها.
_FETCH_RECENT_MESSAGES = f"""
    SELECT {_MESSAGE_COLUMNS}
      FROM messages m
     WHERE m.conversation_id = :conversation_id
       AND m.organization_id = :organization_id
     ORDER BY m.created_at DESC, m.id DESC
     FETCH FIRST :row_limit ROWS ONLY
"""


def _read_lob(value) -> str:
    """محتوى الرسالة عمود CLOB، فيصل كـLOB أو كنص حسب إعداد الدرايفر."""
    if value is None:
        return ""
    reader = getattr(value, "read", None)
    return reader() if callable(reader) else str(value)


def _row_to_conversation(row) -> Conversation:
    from ..services.conversation_store import Conversation

    return Conversation(
        id=int(row[0]),
        organization_id=int(row[1]),
        user_id=int(row[2]),
        title=row[3],
        created_at=row[4],
        updated_at=row[5],
        message_count=int(row[6]),
    )


def _row_to_message(row) -> Message:
    from ..services.conversation_store import Message

    return Message(
        id=int(row[0]),
        conversation_id=int(row[1]),
        organization_id=int(row[2]),
        role=row[3],
        content=_read_lob(row[4]),
        created_at=row[5],
    )


def _returned(variable):
    """يقرأ قيمة من متغير RETURNING (الدرايفر يعيد قائمة لعبارات DML)."""
    value = variable.getvalue()
    return value[0] if isinstance(value, list) else value


# ---------------------------------------------------------------------------
# المحادثات
# ---------------------------------------------------------------------------
def insert_conversation(
    *, organization_id: int, user_id: int, title: str
) -> Conversation:
    """ينشئ محادثة ويعيدها بمعرّفها وطوابعها الزمنية المولَّدة."""
    import oracledb

    from ..services.conversation_store import Conversation

    with get_connection() as connection:
        with connection.cursor() as cursor:
            new_id = cursor.var(int)
            created_at = cursor.var(oracledb.DB_TYPE_TIMESTAMP)
            updated_at = cursor.var(oracledb.DB_TYPE_TIMESTAMP)
            cursor.execute(
                _INSERT_CONVERSATION,
                {
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "title": title,
                    "new_id": new_id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                },
            )
            conversation_id = int(_returned(new_id))
            created = _returned(created_at)
            updated = _returned(updated_at)
        connection.commit()

    return Conversation(
        id=conversation_id,
        organization_id=organization_id,
        user_id=user_id,
        title=title,
        created_at=created,
        updated_at=updated,
        message_count=0,
    )


def fetch_conversation(
    *, conversation_id: int, organization_id: int, user_id: int
) -> Conversation | None:
    """يقرأ محادثة **لصاحبها داخل جهته**، أو None."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _FETCH_CONVERSATION,
                {
                    "conversation_id": conversation_id,
                    "organization_id": organization_id,
                    "user_id": user_id,
                },
            )
            row = cursor.fetchone()

    return _row_to_conversation(row) if row else None


def fetch_conversations(
    *, organization_id: int, user_id: int, limit: int, offset: int
) -> Page:
    """يعيد صفحة من محادثات الموظف مع إجمالي عددها."""
    from ..services.conversation_store import Page

    scope = {"organization_id": organization_id, "user_id": user_id}
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _FETCH_CONVERSATIONS,
                {**scope, "row_offset": offset, "row_limit": limit},
            )
            rows = cursor.fetchall()
            cursor.execute(_COUNT_CONVERSATIONS, scope)
            total = int(cursor.fetchone()[0])

    return Page(
        items=[_row_to_conversation(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def update_conversation_title(
    *, conversation_id: int, organization_id: int, user_id: int, title: str
) -> Conversation | None:
    """يغيّر عنوان محادثة الموظف ويعيدها، أو None إن لم يملكها."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _UPDATE_CONVERSATION_TITLE,
                {
                    "conversation_id": conversation_id,
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "title": title,
                },
            )
            if cursor.rowcount == 0:
                return None
        connection.commit()

    return fetch_conversation(
        conversation_id=conversation_id,
        organization_id=organization_id,
        user_id=user_id,
    )


def delete_conversation_row(
    *, conversation_id: int, organization_id: int, user_id: int
) -> bool:
    """يحذف محادثة الموظف. يعيد False إن لم يملكها."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _DELETE_CONVERSATION,
                {
                    "conversation_id": conversation_id,
                    "organization_id": organization_id,
                    "user_id": user_id,
                },
            )
            deleted = cursor.rowcount > 0
        if deleted:
            connection.commit()
    return deleted


# ---------------------------------------------------------------------------
# الرسائل
# ---------------------------------------------------------------------------
def insert_messages(
    *,
    conversation_id: int,
    organization_id: int,
    entries: Sequence[tuple[str, str]],
) -> list[Message]:
    """يدرج رسائل التبادل الواحد ويحدّث updated_at، في معاملة واحدة.

    الإدراج والتحديث معًا: تبادل نصفه محفوظ يترك سؤالًا بلا جواب في الواجهة.
    """
    if not entries:
        return []

    rows = [
        {
            "conversation_id": conversation_id,
            "organization_id": organization_id,
            "role": role,
            "content": content,
        }
        for role, content in entries
    ]

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(_INSERT_MESSAGE, rows)
            cursor.execute(
                _TOUCH_CONVERSATION,
                {
                    "conversation_id": conversation_id,
                    "organization_id": organization_id,
                },
            )
        connection.commit()

    # تُقرأ بعد الحفظ لتحمل معرّفاتها وطوابعها كما ولّدتها القاعدة.
    return fetch_recent_messages(
        conversation_id=conversation_id,
        organization_id=organization_id,
        limit=len(entries),
    )


def fetch_messages(
    *, conversation_id: int, organization_id: int, limit: int, offset: int
) -> Page:
    """يعيد صفحة من رسائل المحادثة بالترتيب الزمني الصاعد."""
    from ..services.conversation_store import Page

    scope = {
        "conversation_id": conversation_id,
        "organization_id": organization_id,
    }
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _FETCH_MESSAGES,
                {**scope, "row_offset": offset, "row_limit": limit},
            )
            rows = cursor.fetchall()
            cursor.execute(_COUNT_MESSAGES, scope)
            total = int(cursor.fetchone()[0])

    return Page(
        items=[_row_to_message(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def fetch_recent_messages(
    *, conversation_id: int, organization_id: int, limit: int
) -> list[Message]:
    """يعيد آخر ``limit`` رسالة بالترتيب الزمني الصاعد."""
    if limit <= 0:
        return []

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _FETCH_RECENT_MESSAGES,
                {
                    "conversation_id": conversation_id,
                    "organization_id": organization_id,
                    "row_limit": limit,
                },
            )
            rows = cursor.fetchall()

    # قُرئت من الأحدث، وتُعاد من الأقدم لأن المزود يقرأ المحادثة بترتيبها.
    return [_row_to_message(row) for row in reversed(rows)]
