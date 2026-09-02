"""اختبارات المتجهات وحفظ المقاطع والمسار الكامل للمستند.

لا توجد قاعدة Oracle حية: الحفظ يُختبر باتصال وهمي يسجّل عبارات SQL وقيمها،
فيمكن إثبات أن `organization_id` يدخل في كل عبارة دون قاعدة بيانات. الاختبار
الفعلي مقابل Oracle مؤجَّل — انظر آخر الملف.
"""

import math
from types import SimpleNamespace

import pytest

from app.ai import ModelProviderError
from app.ai.embeddings import (
    SUPPORTED_EMBEDDING_PROVIDERS,
    MockEmbeddingProvider,
    OracleEmbeddingProvider,
    get_embedding_provider,
)
from app.core.config import settings
from app.database import documents
from app.database.documents import ChunkPersistenceError, save_chunks
from app.services.chunking import TextChunk
from app.services.retrieval import MemoryChunkStore
from app.services.document_service import ingest_document, process_document
from app.services.text_extraction import UnsupportedFileTypeError


# ---------------------------------------------------------------------------
# اتصال وهمي يسجّل كل ما يصل إلى قاعدة البيانات
# ---------------------------------------------------------------------------
class RecordingCursor:
    def __init__(self, log: list, rows: list | None = None):
        self._log = log
        self._rows = rows or [(0,)]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self._log.append(("execute", sql, params))

    def executemany(self, sql, rows):
        self._log.append(("executemany", sql, rows))

    def fetchone(self):
        return self._rows[0]


class RecordingConnection:
    def __init__(self, log: list, rows: list | None = None):
        self._log = log
        self._rows = rows
        self.committed = False

    def cursor(self):
        return RecordingCursor(self._log, self._rows)

    def commit(self):
        self.committed = True
        self._log.append(("commit", None, None))


@pytest.fixture
def fake_db(monkeypatch):
    """يستبدل get_connection بواحد وهمي ويعيد سجل ما نُفِّذ."""
    log: list = []
    connection = RecordingConnection(log)

    from contextlib import contextmanager

    @contextmanager
    def fake_get_connection():
        yield connection

    monkeypatch.setattr(documents, "get_connection", fake_get_connection)
    return SimpleNamespace(log=log, connection=connection)


def chunks_of(*texts: str) -> list[TextChunk]:
    return [TextChunk(index=i, content=text) for i, text in enumerate(texts)]


# ---------------------------------------------------------------------------
# 1) المزود التجريبي للمتجهات — يعمل بلا أي خدمة خارجية
# ---------------------------------------------------------------------------
def test_mock_embeddings_are_deterministic():
    provider = MockEmbeddingProvider(dimensions=64)
    first = provider.embed(["نص الاختبار"])
    second = provider.embed(["نص الاختبار"])
    assert first == second


def test_mock_embeddings_have_the_configured_dimensions():
    provider = MockEmbeddingProvider(dimensions=128)
    [vector] = provider.embed(["خطاب رسمي"])
    assert len(vector) == 128


def test_mock_embeddings_are_unit_length():
    provider = MockEmbeddingProvider(dimensions=64)
    [vector] = provider.embed(["تقرير الميزانية السنوية"])
    length = math.sqrt(sum(value * value for value in vector))
    assert length == pytest.approx(1.0)


def test_mock_embeddings_return_one_vector_per_text():
    provider = MockEmbeddingProvider(dimensions=32)
    assert len(provider.embed(["أ", "ب", "ج"])) == 3


def test_mock_embeddings_of_empty_list_is_empty():
    assert MockEmbeddingProvider(dimensions=32).embed([]) == []


def test_similar_texts_are_closer_than_unrelated_ones():
    """شرط أن يكون البحث المتجهي المحلي ذا معنى في P1-04."""
    provider = MockEmbeddingProvider(dimensions=512)
    base, similar, unrelated = provider.embed(
        [
            "تقرير عن ميزانية الجهة السنوية",
            "تقرير الميزانية السنوية للجهة",
            "دليل صيانة أجهزة التكييف",
        ]
    )

    def cosine(a, b):
        return sum(x * y for x, y in zip(a, b))

    assert cosine(base, similar) > cosine(base, unrelated)


def test_text_without_words_still_gets_a_vector():
    [vector] = MockEmbeddingProvider(dimensions=32).embed(["12345 !!!"])
    assert any(value != 0 for value in vector)


# ---------------------------------------------------------------------------
# 2) اختيار مزود المتجهات
# ---------------------------------------------------------------------------
def test_mock_is_the_default_embedding_provider():
    assert isinstance(get_embedding_provider(), MockEmbeddingProvider)


def test_unknown_embedding_provider_lists_supported_values():
    with pytest.raises(ModelProviderError) as exc:
        get_embedding_provider("gemini")

    message = str(exc.value)
    assert "gemini" in message
    for name in SUPPORTED_EMBEDDING_PROVIDERS:
        assert name in message


def test_oracle_embeddings_with_missing_configuration(monkeypatch):
    monkeypatch.setattr(settings, "oci_region", "")
    monkeypatch.setattr(settings, "oci_compartment_id", "")
    monkeypatch.setattr(settings, "oci_embedding_model_id", "")

    with pytest.raises(ModelProviderError) as exc:
        OracleEmbeddingProvider().embed(["نص"])

    message = str(exc.value)
    assert "OCI_EMBEDDING_MODEL_ID" in message
    assert "mock" in message


def test_oracle_embeddings_of_empty_list_never_calls_the_service():
    """قائمة فارغة لا تستدعي أي خدمة ولا تحتاج إعدادًا."""
    assert OracleEmbeddingProvider().embed([]) == []


# ---------------------------------------------------------------------------
# 3) الحفظ — العزل بـorganization_id
# ---------------------------------------------------------------------------
def test_saved_chunks_carry_the_file_and_organization(fake_db):
    saved = save_chunks(
        file_id=7,
        organization_id=3,
        chunks=chunks_of("المقطع الأول", "المقطع الثاني"),
        embeddings=[[0.1, 0.2], [0.3, 0.4]],
    )

    assert saved == 2
    inserts = [entry for entry in fake_db.log if entry[0] == "executemany"]
    assert len(inserts) == 1
    rows = inserts[0][2]
    assert [row["chunk_index"] for row in rows] == [0, 1]
    assert all(row["organization_id"] == 3 for row in rows)
    assert all(row["file_id"] == 7 for row in rows)
    assert rows[0]["content"] == "المقطع الأول"


def test_every_statement_is_scoped_by_organization_id(fake_db):
    """أخطر شرط في المشروع: لا عبارة تمس المقاطع بلا organization_id."""
    save_chunks(
        file_id=7,
        organization_id=3,
        chunks=chunks_of("نص"),
        embeddings=[[0.5, 0.5]],
    )

    statements = [entry for entry in fake_db.log if entry[0] in ("execute", "executemany")]
    assert statements
    for _kind, sql, _params in statements:
        assert "organization_id" in sql


def test_previous_chunks_are_deleted_before_inserting(fake_db):
    """إعادة معالجة الملف لا تضاعف مقاطعه."""
    save_chunks(
        file_id=7,
        organization_id=3,
        chunks=chunks_of("نص"),
        embeddings=[[1.0, 0.0]],
    )

    kinds = [entry[0] for entry in fake_db.log]
    assert kinds.index("execute") < kinds.index("executemany")
    delete_sql = fake_db.log[0][1]
    assert "DELETE" in delete_sql
    assert fake_db.log[0][2] == {"file_id": 7, "organization_id": 3}


def test_save_commits_the_transaction(fake_db):
    save_chunks(
        file_id=1, organization_id=1, chunks=chunks_of("نص"), embeddings=[[1.0]]
    )
    assert fake_db.connection.committed is True


def test_embeddings_are_converted_to_a_vector_type(fake_db):
    save_chunks(
        file_id=1, organization_id=1, chunks=chunks_of("نص"), embeddings=[[0.25, 0.75]]
    )
    row = fake_db.log[1][2][0]
    assert row["embedding"].typecode == "f"
    assert list(row["embedding"]) == pytest.approx([0.25, 0.75])


def test_mismatched_chunk_and_embedding_counts_are_refused(fake_db):
    with pytest.raises(ChunkPersistenceError) as exc:
        save_chunks(
            file_id=1,
            organization_id=1,
            chunks=chunks_of("أ", "ب"),
            embeddings=[[1.0]],
        )

    assert "لا يساوي" in str(exc.value)
    # لا شيء وصل إلى قاعدة البيانات.
    assert fake_db.log == []


def test_saving_no_chunks_still_clears_the_old_ones(fake_db):
    saved = save_chunks(file_id=7, organization_id=3, chunks=[], embeddings=[])

    assert saved == 0
    kinds = [entry[0] for entry in fake_db.log]
    assert "execute" in kinds
    assert "executemany" not in kinds


# ---------------------------------------------------------------------------
# 4) المسار الكامل
# ---------------------------------------------------------------------------
def test_process_document_runs_without_any_database():
    text = "الفقرة الأولى من التقرير.\n\n" + ("تفاصيل كثيرة جدًا. " * 80)
    processed = process_document("تقرير.txt", text.encode("utf-8"))

    assert processed.chunk_count > 1
    assert processed.embedding_provider == "mock"
    assert len(processed.embeddings) == processed.chunk_count
    assert all(
        len(vector) == settings.embedding_dimensions for vector in processed.embeddings
    )


def test_process_document_rejects_unsupported_files_before_embedding():
    with pytest.raises(UnsupportedFileTypeError):
        process_document("صورة.png", b"data")


def test_ingest_document_uses_the_local_store_by_default(fake_db):
    """المسار الافتراضي لا يلمس قاعدة البيانات إطلاقًا."""
    MemoryChunkStore.clear()
    text = "محضر الاجتماع.\n\n" + ("بند من بنود المحضر. " * 60)
    result = ingest_document(
        file_id=42,
        organization_id=9,
        filename="محضر.txt",
        data=text.encode("utf-8"),
    )

    assert result.file_id == 42
    assert result.organization_id == 9
    assert result.chunk_count > 1
    assert result.embedding_provider == "mock"
    assert result.store == "memory"
    assert fake_db.log == []


def test_ingest_document_writes_to_oracle_when_activated(fake_db, monkeypatch):
    """تفعيل RETRIEVAL_PROVIDER=oracle يوجّه الحفظ إلى document_chunks."""
    monkeypatch.setattr(settings, "retrieval_provider", "oracle")
    text = "محضر الاجتماع.\n\n" + ("بند من بنود المحضر. " * 60)
    result = ingest_document(
        file_id=42,
        organization_id=9,
        filename="محضر.txt",
        data=text.encode("utf-8"),
    )

    assert result.store == "oracle"
    rows = [entry for entry in fake_db.log if entry[0] == "executemany"][0][2]
    assert len(rows) == result.chunk_count
    assert all(row["organization_id"] == 9 for row in rows)


def test_ingest_does_not_touch_the_database_when_the_file_is_rejected(fake_db):
    with pytest.raises(UnsupportedFileTypeError):
        ingest_document(
            file_id=1, organization_id=1, filename="ملف.zip", data=b"data"
        )
    assert fake_db.log == []


# ---------------------------------------------------------------------------
# 5) الاختبار الحي — مؤجَّل
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason=(
        "Pending Oracle Setup — لا توجد قاعدة Oracle حية، فلا يمكن التحقق من "
        "الإدراج الفعلي في document_chunks ولا من قبول عمود VECTOR للمتجه. "
        "يُفعَّل بعد تجهيز القاعدة وتشغيل database/schema.sql."
    )
)
def test_chunks_are_persisted_in_oracle_pending_oracle_setup():
    """حفظ مقاطع فعليًا في Oracle والتحقق من عددها ضمن الجهة نفسها."""
    from app.database.documents import count_chunks

    result = ingest_document(
        file_id=1,
        organization_id=1,
        filename="تجربة.txt",
        data=("نص تجريبي طويل. " * 300).encode("utf-8"),
    )
    assert count_chunks(file_id=1, organization_id=1) == result.chunk_count
