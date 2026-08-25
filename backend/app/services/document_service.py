"""معالجة المستند المرفوع: استخراج ← تقطيع ← متجهات ← حفظ.

يفصل هذا الملف الترتيب العام عن تفاصيل كل خطوة، فيمكن اختبار كل خطوة وحدها،
ويمكن تشغيل المسار كله بلا Oracle عبر `process_document` التي تقف قبل الحفظ.
"""

from dataclasses import dataclass

from ..ai.embeddings import get_embedding_provider
from .chunking import TextChunk, chunk_text
from .retrieval import get_chunk_store
from .text_extraction import extract_text


@dataclass(frozen=True)
class ProcessedDocument:
    """نتيجة المعالجة قبل الحفظ — لا تحتاج قاعدة بيانات."""

    filename: str
    text: str
    chunks: list[TextChunk]
    embeddings: list[list[float]]
    embedding_provider: str

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


@dataclass(frozen=True)
class IngestionResult:
    """نتيجة المعالجة بعد الحفظ في قاعدة البيانات."""

    file_id: int
    organization_id: int
    filename: str
    chunk_count: int
    embedding_provider: str
    #: المخزن الذي حُفظت فيه المقاطع: memory أو oracle.
    store: str


def process_document(filename: str, data: bytes) -> ProcessedDocument:
    """يستخرج النص ويقطّعه ويولّد متجهاته، بلا أي لمس لقاعدة البيانات.

    Raises:
        FileExtractionError: امتداد غير مدعوم، حجم زائد، ملف تالف أو بلا نص.
        ModelProviderError: إذا فشل توليد المتجهات.
    """
    text = extract_text(filename, data)
    chunks = chunk_text(text)

    provider = get_embedding_provider()
    embeddings = provider.embed([chunk.content for chunk in chunks])

    return ProcessedDocument(
        filename=filename,
        text=text,
        chunks=chunks,
        embeddings=embeddings,
        embedding_provider=provider.name,
    )


def ingest_document(
    *, file_id: int, organization_id: int, filename: str, data: bytes
) -> IngestionResult:
    """المسار الكامل: معالجة الملف ثم حفظ مقاطعه ضمن جهة المستخدم.

    Args:
        file_id: معرّف الملف في جدول files.
        organization_id: جهة المستخدم — تُمرَّر إلى كل عبارة حفظ.

    الحفظ يمر عبر المخزن المفعّل في RETRIEVAL_PROVIDER: مخزن الذاكرة المحلي
    افتراضيًا، أو جدول document_chunks في Oracle عند تفعيلها.

    Raises:
        FileExtractionError: فشل في قراءة الملف.
        ModelProviderError: فشل في توليد المتجهات.
        RetrievalError: مخزن غير مدعوم.
        DatabaseError: فشل في الاتصال بالقاعدة أو الحفظ (مخزن oracle فقط).
    """
    processed = process_document(filename, data)
    store = get_chunk_store()
    saved = store.save(
        file_id=file_id,
        organization_id=organization_id,
        file_name=filename,
        chunks=processed.chunks,
        embeddings=processed.embeddings,
    )
    return IngestionResult(
        file_id=file_id,
        organization_id=organization_id,
        filename=filename,
        chunk_count=saved,
        embedding_provider=processed.embedding_provider,
        store=store.name,
    )
