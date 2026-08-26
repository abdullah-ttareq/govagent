"""البحث المتجهي في مقاطع المستندات (RAG).

مخزنان خلف واجهة واحدة، يُختاران من `RETRIEVAL_PROVIDER`:

* ``memory`` (الافتراضي) — مخزن داخل ذاكرة العملية مع حساب تشابه جيبي محلي.
  يعمل بلا قاعدة بيانات إطلاقًا، فيكفي لتطوير الـRAG وعرضه واختباره قبل
  توفّر Oracle. **غير دائم:** يفرغ عند إعادة تشغيل الـBackend، ولا يصلح
  لأكثر من عملية واحدة. للتطوير والعرض لا للإنتاج.
* ``oracle`` — Oracle Vector Search فوق جدول ``document_chunks``. جاهز
  للتفعيل بتغيير متغير بيئة واحد بعد تجهيز القاعدة.

**قاعدة العزل:** كل بحث هنا مقيّد بـ`organization_id`. المخزن المحلي مفهرس
بالجهة أولًا، فالوصول إلى مقاطع جهة أخرى غير ممكن بنيويًا لا بشرط يمكن
نسيانه؛ واستعلام Oracle يحمل الشرط مرتين. لا توجد دالة بحث بلا جهة.
"""

from __future__ import annotations

import math
import threading
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..core.config import settings

if TYPE_CHECKING:
    from .chunking import TextChunk


class RetrievalError(Exception):
    """خطأ في البحث المتجهي، برسالة عربية صالحة للعرض."""


@dataclass(frozen=True)
class RetrievedChunk:
    """مقطع مسترجَع مع مصدره ودرجة قربه من السؤال."""

    file_id: int
    file_name: str
    chunk_index: int
    content: str
    #: درجة التشابه من 0 إلى 1 تقريبًا، الأعلى أقرب.
    score: float


class ChunkStore(ABC):
    """واجهة تخزين المقاطع والبحث فيها."""

    name: str = "base"

    @abstractmethod
    def save(
        self,
        *,
        file_id: int,
        organization_id: int,
        file_name: str,
        chunks: Sequence[TextChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> int:
        """يحفظ مقاطع ملف واحد ويعيد عددها."""
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        *,
        organization_id: int,
        query_embedding: Sequence[float],
        limit: int,
    ) -> list[RetrievedChunk]:
        """يعيد أقرب المقاطع للسؤال داخل الجهة المحددة فقط."""
        raise NotImplementedError

    @abstractmethod
    def delete_file_chunks(self, *, file_id: int, organization_id: int) -> int:
        """يحذف مقاطع ملف داخل جهته ويعيد عددها.

        يُستدعى عند حذف الملف: مقاطع باقية بعد اختفاء سجل الملف تعني
        محتوى يظل قابلًا للاستشهاد به من ملف لم يعد موجودًا.
        """
        raise NotImplementedError


def cosine_similarity(first: Sequence[float], second: Sequence[float]) -> float:
    """تشابه جيبي بين متجهين. يعيد 0 إذا اختلفت الأبعاد أو كان أحدهما صفريًا."""
    if len(first) != len(second):
        return 0.0
    dot = sum(a * b for a, b in zip(first, second))
    norm_first = math.sqrt(sum(a * a for a in first))
    norm_second = math.sqrt(sum(b * b for b in second))
    if norm_first == 0 or norm_second == 0:
        return 0.0
    return dot / (norm_first * norm_second)


# ---------------------------------------------------------------------------
# المخزن المحلي
# ---------------------------------------------------------------------------
@dataclass
class _StoredFile:
    """مقاطع ملف واحد داخل المخزن المحلي."""

    file_name: str
    chunks: list[tuple[int, str, list[float]]] = field(default_factory=list)


class MemoryChunkStore(ChunkStore):
    """مخزن مقاطع داخل ذاكرة العملية، مفهرس بالجهة ثم بالملف.

    البنية ``{organization_id: {file_id: _StoredFile}}`` مقصودة: البحث يبدأ
    من قاموس الجهة، فلا يرى أصلًا مقاطع جهة أخرى.
    """

    name = "memory"

    #: الحالة على مستوى الصنف حتى تشترك فيها كل النسخ داخل العملية.
    _data: dict[int, dict[int, _StoredFile]] = {}
    _lock = threading.Lock()

    def save(
        self,
        *,
        file_id: int,
        organization_id: int,
        file_name: str,
        chunks: Sequence[TextChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> int:
        if len(chunks) != len(embeddings):
            raise RetrievalError(
                f"عدد المقاطع ({len(chunks)}) لا يساوي عدد المتجهات "
                f"({len(embeddings)}). أُلغي الحفظ لتفادي بيانات غير متسقة."
            )

        stored = _StoredFile(
            file_name=file_name,
            chunks=[
                (chunk.index, chunk.content, [float(v) for v in embedding])
                for chunk, embedding in zip(chunks, embeddings)
            ],
        )
        with self._lock:
            # الاستبدال يمنع تضاعف المقاطع عند إعادة معالجة الملف نفسه.
            MemoryChunkStore._data.setdefault(organization_id, {})[file_id] = stored
        return len(stored.chunks)

    def search(
        self,
        *,
        organization_id: int,
        query_embedding: Sequence[float],
        limit: int,
    ) -> list[RetrievedChunk]:
        if limit <= 0:
            return []

        with self._lock:
            # نسخة سطحية حتى لا يتغيّر المخزن أثناء الترتيب.
            files = dict(MemoryChunkStore._data.get(organization_id, {}))

        results: list[RetrievedChunk] = []
        for file_id, stored in files.items():
            for chunk_index, content, embedding in stored.chunks:
                results.append(
                    RetrievedChunk(
                        file_id=file_id,
                        file_name=stored.file_name,
                        chunk_index=chunk_index,
                        content=content,
                        score=cosine_similarity(query_embedding, embedding),
                    )
                )

        # الأقرب أولًا، ثم ترتيب ثابت عند تساوي الدرجات حتى لا تتقلب النتائج.
        results.sort(key=lambda item: (-item.score, item.file_id, item.chunk_index))
        return results[:limit]

    def delete_file_chunks(self, *, file_id: int, organization_id: int) -> int:
        with self._lock:
            files = MemoryChunkStore._data.get(organization_id)
            if not files:
                return 0
            # الحذف من قاموس الجهة: ملف جهة أخرى غير مرئي أصلًا من هنا.
            removed = files.pop(file_id, None)
        return 0 if removed is None else len(removed.chunks)

    @classmethod
    def clear(cls) -> None:
        """يفرغ المخزن. للاختبارات ولإعادة التشغيل النظيفة."""
        with cls._lock:
            cls._data = {}


# ---------------------------------------------------------------------------
# مخزن Oracle
# ---------------------------------------------------------------------------
class OracleChunkStore(ChunkStore):
    """يحفظ ويبحث في جدول document_chunks عبر Oracle Vector Search."""

    name = "oracle"

    def save(
        self,
        *,
        file_id: int,
        organization_id: int,
        file_name: str,
        chunks: Sequence[TextChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> int:
        # اسم الملف مخزَّن في جدول files، فلا يتكرر هنا.
        from ..database.documents import save_chunks

        return save_chunks(
            file_id=file_id,
            organization_id=organization_id,
            chunks=chunks,
            embeddings=embeddings,
        )

    def delete_file_chunks(self, *, file_id: int, organization_id: int) -> int:
        from ..database.documents import delete_chunks

        return delete_chunks(file_id=file_id, organization_id=organization_id)

    def search(
        self,
        *,
        organization_id: int,
        query_embedding: Sequence[float],
        limit: int,
    ) -> list[RetrievedChunk]:
        from ..database.documents import search_chunks

        rows = search_chunks(
            organization_id=organization_id,
            query_embedding=query_embedding,
            limit=limit,
        )
        # المسافة الجيبية في Oracle من 0 (متطابق) إلى 2، فالتشابه = 1 - المسافة.
        return [
            RetrievedChunk(
                file_id=row["file_id"],
                file_name=row["file_name"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                score=1.0 - row["distance"],
            )
            for row in rows
        ]


_STORES: dict[str, type[ChunkStore]] = {
    "memory": MemoryChunkStore,
    "oracle": OracleChunkStore,
}

#: القيم المقبولة لـRETRIEVAL_PROVIDER.
SUPPORTED_RETRIEVAL_PROVIDERS: tuple[str, ...] = tuple(sorted(_STORES))


def get_chunk_store(name: str | None = None) -> ChunkStore:
    """يعيد مخزن المقاطع المفعّل.

    Raises:
        RetrievalError: إذا كان الاسم غير مدعوم.
    """
    store_name = (name or settings.retrieval_provider or "memory").strip().lower()
    store_class = _STORES.get(store_name)
    if store_class is None:
        supported = "، ".join(SUPPORTED_RETRIEVAL_PROVIDERS)
        raise RetrievalError(
            f"RETRIEVAL_PROVIDER='{store_name}' غير مدعوم. "
            f"القيم المدعومة: {supported}."
        )
    return store_class()


def search_relevant_chunks(
    *,
    organization_id: int,
    query_embedding: Sequence[float],
    limit: int | None = None,
    min_score: float | None = None,
) -> list[RetrievedChunk]:
    """يبحث في مقاطع الجهة ويعيد الأقرب بعد تصفية الضعيف منها."""
    top_k = settings.retrieval_top_k if limit is None else limit
    threshold = settings.retrieval_min_score if min_score is None else min_score

    results = get_chunk_store().search(
        organization_id=organization_id,
        query_embedding=query_embedding,
        limit=top_k,
    )
    return [chunk for chunk in results if chunk.score >= threshold]
