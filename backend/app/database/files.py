"""بيانات الملفات المرفوعة في جدول files.

**قاعدة العزل:** كل عبارة هنا مقيّدة بـ``organization_id``. الملفات معرفةٌ
مشتركة داخل الجهة — محتواها متاح لكل موظفيها عبر البحث المتجهي — فبياناتها
كذلك. صلاحية **التعديل والحذف** (الرافع أو مسؤول الجهة) تُفحص في
`file_service` قبل الوصول إلى هنا، فلا تتكرر في عبارات SQL.

الجدول يحمل **المسار** لا محتوى الملف؛ المحتوى على قرص السيرفر.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .oracle import get_connection

if TYPE_CHECKING:  # يُستورد للتلميح النوعي فقط.
    from ..services.conversation_store import Page
    from ..services.file_store import FileRecord

_FILE_COLUMNS = """
    f.id, f.organization_id, f.user_id, f.conversation_id, f.original_name,
    f.storage_path, f.mime_type, f.size_bytes, f.status, f.created_at
"""

_INSERT_FILE = """
    INSERT INTO files
        (organization_id, user_id, conversation_id, original_name,
         storage_path, mime_type, size_bytes)
    VALUES
        (:organization_id, :user_id, :conversation_id, :original_name,
         :storage_path, :mime_type, :size_bytes)
    RETURNING id, created_at INTO :new_id, :created_at
"""

_FETCH_FILE = f"""
    SELECT {_FILE_COLUMNS}
      FROM files f
     WHERE f.id = :file_id
       AND f.organization_id = :organization_id
"""

# الشرطان الاختياريان: NULL في أيهما يعني «بلا تصفية» لا «القيمة فارغة».
# uploaded_by يقصر القائمة على رافع بعينه، و conversation_id على محادثة.
_FILE_FILTERS = """
     WHERE f.organization_id = :organization_id
       AND (:uploaded_by IS NULL OR f.user_id = :uploaded_by)
       AND (:conversation_id IS NULL OR f.conversation_id = :conversation_id)
"""

_FETCH_FILES = f"""
    SELECT {_FILE_COLUMNS}
      FROM files f
    {_FILE_FILTERS}
     ORDER BY f.created_at DESC, f.id DESC
     OFFSET :row_offset ROWS FETCH NEXT :row_limit ROWS ONLY
"""

_COUNT_FILES = f"""
    SELECT COUNT(*)
      FROM files f
    {_FILE_FILTERS}
"""

_DELETE_FILE = """
    DELETE FROM files
     WHERE id = :file_id
       AND organization_id = :organization_id
"""

_UPDATE_STATUS = """
    UPDATE files
       SET status = :status
     WHERE id = :file_id
       AND organization_id = :organization_id
"""


def _row_to_file(row) -> FileRecord:
    from ..services.file_store import FileRecord

    return FileRecord(
        id=int(row[0]),
        organization_id=int(row[1]),
        user_id=int(row[2]),
        conversation_id=None if row[3] is None else int(row[3]),
        original_name=row[4],
        storage_path=row[5],
        mime_type=row[6],
        size_bytes=int(row[7]),
        status=row[8],
        created_at=row[9],
    )


def _returned(variable):
    """يقرأ قيمة من متغير RETURNING (الدرايفر يعيد قائمة لعبارات DML)."""
    value = variable.getvalue()
    return value[0] if isinstance(value, list) else value


def insert_file(
    *,
    organization_id: int,
    user_id: int,
    conversation_id: int | None,
    original_name: str,
    storage_path: str,
    mime_type: str,
    size_bytes: int,
) -> FileRecord:
    """يسجّل ملفًا بحالة pending ويعيده بمعرّفه المولَّد."""
    import oracledb

    from ..services.file_store import FileRecord

    with get_connection() as connection:
        with connection.cursor() as cursor:
            new_id = cursor.var(int)
            created_at = cursor.var(oracledb.DB_TYPE_TIMESTAMP)
            cursor.execute(
                _INSERT_FILE,
                {
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "original_name": original_name,
                    "storage_path": storage_path,
                    "mime_type": mime_type,
                    "size_bytes": size_bytes,
                    "new_id": new_id,
                    "created_at": created_at,
                },
            )
            file_id = int(_returned(new_id))
            created = _returned(created_at)
        connection.commit()

    return FileRecord(
        id=file_id,
        organization_id=organization_id,
        user_id=user_id,
        conversation_id=conversation_id,
        original_name=original_name,
        storage_path=storage_path,
        mime_type=mime_type,
        size_bytes=size_bytes,
        status="pending",
        created_at=created,
    )


def fetch_file(*, file_id: int, organization_id: int) -> FileRecord | None:
    """يقرأ ملفًا **داخل جهته**، أو None. أي موظف في الجهة يقرؤه."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _FETCH_FILE,
                {"file_id": file_id, "organization_id": organization_id},
            )
            row = cursor.fetchone()

    return _row_to_file(row) if row else None


def fetch_files(
    *,
    organization_id: int,
    uploaded_by: int | None,
    conversation_id: int | None,
    limit: int,
    offset: int,
) -> Page:
    """يعيد صفحة من ملفات الجهة مع إجمالي عددها."""
    from ..services.conversation_store import Page

    scope = {
        "organization_id": organization_id,
        "uploaded_by": uploaded_by,
        "conversation_id": conversation_id,
    }
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _FETCH_FILES, {**scope, "row_offset": offset, "row_limit": limit}
            )
            rows = cursor.fetchall()
            cursor.execute(_COUNT_FILES, scope)
            total = int(cursor.fetchone()[0])

    return Page(
        items=[_row_to_file(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def update_file_status(
    *, file_id: int, organization_id: int, status: str
) -> FileRecord | None:
    """يحدّث حالة استخراج النص، ويعيد الصف بعد التحديث."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _UPDATE_STATUS,
                {
                    "file_id": file_id,
                    "organization_id": organization_id,
                    "status": status,
                },
            )
            if cursor.rowcount == 0:
                return None
            connection.commit()
            cursor.execute(
                f"SELECT {_FILE_COLUMNS} FROM files f WHERE f.id = :file_id "
                "AND f.organization_id = :organization_id",
                {"file_id": file_id, "organization_id": organization_id},
            )
            row = cursor.fetchone()

    return _row_to_file(row) if row else None


def delete_file_row(*, file_id: int, organization_id: int) -> bool:
    """يحذف سجل ملف **داخل جهته**. يعيد False إن لم يوجد فيها.

    مقاطع الملف تذهب معه بـON DELETE CASCADE على fk_chunks_file في المخطط،
    ويحذفها `file_service` صراحةً كذلك لأن مخزن المقاطع قد يكون في الذاكرة
    لا في القاعدة (RETRIEVAL_PROVIDER=memory).
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _DELETE_FILE,
                {"file_id": file_id, "organization_id": organization_id},
            )
            deleted = cursor.rowcount > 0
        if deleted:
            connection.commit()
    return deleted
