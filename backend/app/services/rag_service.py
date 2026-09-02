"""ربط البحث المتجهي بمسار المحادثة.

المسؤولية هنا: تحويل سؤال المستخدم إلى مقاطع من ملفات جهته، ثم تركيبها في
سياق مضغوط يُمرَّر إلى المودل.

**مبدأ ثابت:** فشل الاسترجاع لا يُسقط المحادثة. إن كانت Oracle غير مضبوطة، أو
تعذّر الاتصال بها، أو فشل توليد متجه السؤال، يُكمل الإيجنت من معرفته العامة
بلا سياق وبلا خطأ. الاسترجاع تحسين للجودة، لا شرط لعمل النظام.
"""

import logging
from dataclasses import dataclass, field

from ..ai.embeddings import get_embedding_provider
from ..core.config import settings
from .retrieval import RetrievedChunk, search_relevant_chunks

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalOutcome:
    """نتيجة محاولة الاسترجاع، ناجحة كانت أو لا."""

    chunks: list[RetrievedChunk] = field(default_factory=list)
    context: str = ""
    #: يُملأ عند فشل الاسترجاع، ويُسجَّل ولا يُعرض للمستخدم كخطأ.
    failure: str | None = None

    @property
    def has_context(self) -> bool:
        return bool(self.chunks and self.context)


def build_context_block(
    chunks: list[RetrievedChunk], max_chars: int | None = None
) -> str:
    """يركّب المقاطع في نص واحد مضغوط، كل مقطع بمصدره.

    يتوقف عند سقف الطول حتى لا يبتلع السياق نافذة المودل. المقاطع مرتبة
    بالأقرب أولًا، فالقطع من آخرها يحذف الأقل صلة.
    """
    limit = settings.retrieval_context_chars if max_chars is None else max_chars
    parts: list[str] = []
    used = 0

    for chunk in chunks:
        block = (
            f"[المصدر: {chunk.file_name} — المقطع {chunk.chunk_index}]\n"
            f"{chunk.content.strip()}"
        )
        if used + len(block) > limit and parts:
            break
        parts.append(block)
        used += len(block)

    return "\n\n---\n\n".join(parts)


def retrieve_context(*, question: str, organization_id: int) -> RetrievalOutcome:
    """يبحث عن مقاطع تخص السؤال داخل جهة المستخدم، ولا يرمي استثناءً أبدًا.

    Args:
        question: نص سؤال المستخدم.
        organization_id: جهة المستخدم. لا يوجد استدعاء بلا جهة.

    Returns:
        RetrievalOutcome فيها المقاطع والسياق، أو فارغة مع سبب الفشل.
    """
    if not question.strip():
        return RetrievalOutcome()

    try:
        provider = get_embedding_provider()
        [query_embedding] = provider.embed([question])
        chunks = search_relevant_chunks(
            organization_id=organization_id,
            query_embedding=query_embedding,
        )
    except Exception as exc:
        # كل فشل هنا متوقَّع ومسموح: قاعدة غير مضبوطة، اتصال متعذّر، مزود
        # متجهات ناقص الإعداد. المحادثة تكمل من المعرفة العامة.
        logger.warning("تعذّر استرجاع مقاطع الجهة %s: %s", organization_id, exc)
        return RetrievalOutcome(failure=str(exc))

    if not chunks:
        return RetrievalOutcome()

    return RetrievalOutcome(chunks=chunks, context=build_context_block(chunks))
