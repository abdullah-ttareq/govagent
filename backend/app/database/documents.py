"""حفظ مقاطع المستندات في جدول document_chunks.

**قاعدة العزل:** كل استعلام هنا مقيّد بـ`organization_id` بلا استثناء — في
الإدراج وفي الحذف وفي القراءة. لا توجد دالة واحدة تقبل تجاهل القيد، ولا
مسار يقرأ مقطعًا دون أن يذكر جهة المستخدم.

الاتصال كسول: هذا الملف لا يفتح شيئًا حتى يُستدعى فعلًا.
"""

from __future__ import annotations

import array
from collections.abc import Sequence
from typing import TYPE_CHECKING

from .oracle import get_connection

if TYPE_CHECKING:  # يُستورد للتلميح النوعي فقط.
    # طبقة قاعدة البيانات لا تعتمد على طبقة الخدمات وقت التشغيل: الاتجاه
    # دائمًا services ← database، وعكسه يصنع استيرادًا دائريًا.
    from ..services.chunking import TextChunk

#: عمود VECTOR في Oracle يقبل array.array بدقة float32.
_VECTOR_TYPECODE = "f"

_DELETE_CHUNKS = """
    DELETE FROM document_chunks
     WHERE file_id = :file_id
       AND organization_id = :organization_id
"""

_INSERT_CHUNK = """
    INSERT INTO document_chunks
        (file_id, organization_id, chunk_index, content, embedding)
    VALUES
        (:file_id, :organization_id, :chunk_index, :content, :embedding)
"""

_COUNT_CHUNKS = """
    SELECT COUNT(*)
      FROM document_chunks
     WHERE file_id = :file_id
       AND organization_id = :organization_id
"""

# Oracle Vector Search: أقرب الجيران بمسافة جيبية.
#
# العزل هنا مضاعف عمدًا: شرط على مقاطع الجهة، وشرط ثانٍ على الملف داخل
# الـJOIN. لو أخطأ أحدهما يومًا يبقى الآخر مانعًا. لا يوجد شكل آخر لهذا
# الاستعلام في المشروع، ولا مسار يستدعيه بلا organization_id.
_SEARCH_CHUNKS = """
    SELECT c.file_id,
           f.original_name,
           c.chunk_index,
           c.content,
           VECTOR_DISTANCE(c.embedding, :query_vector, COSINE) AS distance
      FROM document_chunks c
      JOIN files f
        ON f.id = c.file_id
       AND f.organization_id = c.organization_id
     WHERE c.organization_id = :organization_id
       AND c.embedding IS NOT NULL
     ORDER BY distance
     FETCH FIRST :max_rows ROWS ONLY
"""


class ChunkPersistenceError(Exception):
    """خطأ في حفظ مقاطع المستند، برسالة عربية صالحة للعرض."""


def _to_vector(values: Sequence[float]) -> array.array:
    """يحوّل المتجه إلى الشكل الذي يقبله عمود VECTOR."""
    return array.array(_VECTOR_TYPECODE, [float(value) for value in values])


def save_chunks(
    *,
    file_id: int,
    organization_id: int,
    chunks: Sequence[TextChunk],
    embeddings: Sequence[Sequence[float]],
) -> int:
    """يحفظ مقاطع ملف واحد مع متجهاتها، ويعيد عدد الصفوف المحفوظة.

    العملية **استبدالية**: تُحذف مقاطع الملف السابقة أولًا حتى لا تتضاعف عند
    إعادة المعالجة. الحذف والإدراج داخل معاملة واحدة.

    Args:
        file_id: معرّف الملف في جدول files.
        organization_id: جهة المستخدم — يدخل في كل عبارة SQL هنا.
        chunks: المقاطع بترتيبها.
        embeddings: متجه لكل مقطع، بالترتيب نفسه.

    Raises:
        ChunkPersistenceError: إذا اختلف عدد المقاطع عن عدد المتجهات.
    """
    if len(chunks) != len(embeddings):
        raise ChunkPersistenceError(
            f"عدد المقاطع ({len(chunks)}) لا يساوي عدد المتجهات "
            f"({len(embeddings)}). أُلغي الحفظ لتفادي بيانات غير متسقة."
        )

    rows = [
        {
            "file_id": file_id,
            "organization_id": organization_id,
            "chunk_index": chunk.index,
            "content": chunk.content,
            "embedding": _to_vector(embedding),
        }
        for chunk, embedding in zip(chunks, embeddings)
    ]

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _DELETE_CHUNKS,
                {"file_id": file_id, "organization_id": organization_id},
            )
            if rows:
                cursor.executemany(_INSERT_CHUNK, rows)
        connection.commit()

    return len(rows)


def delete_chunks(*, file_id: int, organization_id: int) -> int:
    """يحذف مقاطع ملف **داخل جهته** ويعيد عدد الصفوف المحذوفة.

    شرط الجهة جزء من عبارة الحذف نفسها: مقاطع جهة أخرى لا يمكن أن تُحذف
    بها حتى لو مُرِّر معرّف ملف فيها.
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _DELETE_CHUNKS,
                {"file_id": file_id, "organization_id": organization_id},
            )
            removed = cursor.rowcount
        connection.commit()
    return removed


def search_chunks(
    *,
    organization_id: int,
    query_embedding: Sequence[float],
    limit: int,
) -> list[dict]:
    """يعيد أقرب المقاطع لمتجه السؤال **داخل جهة المستخدم فقط**.

    Args:
        organization_id: جهة المستخدم. شرط إلزامي في الاستعلام، وليس مرشِّحًا
            اختياريًا يمكن تجاوزه.
        query_embedding: متجه السؤال.
        limit: أقصى عدد مقاطع تُعاد.

    Returns:
        صفوف مرتبة من الأقرب إلى الأبعد، كل صف قاموس فيه file_id و
        file_name و chunk_index و content و distance.
    """
    if limit <= 0:
        return []

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _SEARCH_CHUNKS,
                {
                    "query_vector": _to_vector(query_embedding),
                    "organization_id": organization_id,
                    "max_rows": limit,
                },
            )
            rows = cursor.fetchall()

    return [
        {
            "file_id": row[0],
            "file_name": row[1],
            "chunk_index": row[2],
            "content": _read_lob(row[3]),
            "distance": float(row[4]),
        }
        for row in rows
    ]


def _read_lob(value) -> str:
    """محتوى المقطع عمود CLOB، فيصل كـLOB أو كنص حسب إعداد الدرايفر."""
    if value is None:
        return ""
    reader = getattr(value, "read", None)
    return reader() if callable(reader) else str(value)


def count_chunks(*, file_id: int, organization_id: int) -> int:
    """يعيد عدد مقاطع ملف داخل جهة معيّنة. يُستخدم للتحقق وللعرض."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _COUNT_CHUNKS,
                {"file_id": file_id, "organization_id": organization_id},
            )
            row = cursor.fetchone()
    return int(row[0]) if row else 0
