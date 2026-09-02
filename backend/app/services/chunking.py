"""تقطيع النص إلى مقاطع (Chunks) استعدادًا للبحث المتجهي.

دوال هذا الملف **نقية**: لا تلمس قاعدة بيانات ولا شبكة ولا نظام ملفات، فهي
قابلة للاختبار كاملة بدون Oracle.

المبدأ: نافذة منزلقة بحجم ثابت مع تداخل بسيط، لكن حدّ كل مقطع يُزحلق إلى
أقرب حد فقرة، ثم حد جملة، ثم مسافة — حتى لا تُقطع الكلمة أو الفكرة في
منتصفها. طول أي مقطع لا يتجاوز الحجم المطلوب أبدًا.
"""

import re
from dataclasses import dataclass

from ..core.config import settings

#: أقل نسبة من حجم المقطع يجب أن تمتلئ قبل قبول حد فقرة/جملة مبكر.
#: بدونها قد ينتج عن فقرة قصيرة في أول النافذة مقاطع صغيرة جدًا.
_MIN_FILL_RATIO = 0.6

#: علامات نهاية الجملة، بالعربية والإنجليزية.
_SENTENCE_ENDINGS = ".!?؟।\n"

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_TRAILING_SPACES = re.compile(r"[ \t]+(\n)")
_MANY_NEWLINES = re.compile(r"\n{3,}")


class ChunkingError(ValueError):
    """إعداد تقطيع غير صالح."""


@dataclass(frozen=True)
class TextChunk:
    """مقطع نصي واحد بترتيبه داخل المستند."""

    index: int
    content: str


def normalize_text(text: str) -> str:
    """يوحّد المسافات وفواصل الأسطر دون إتلاف حدود الفقرات."""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace(" ", " ")  # مسافة غير قابلة للكسر
    cleaned = _TRAILING_SPACES.sub(r"\1", cleaned)
    # ثلاثة أسطر فأكثر تُختزل إلى سطرين: حد فقرة واحد يكفي.
    cleaned = _MANY_NEWLINES.sub("\n\n", cleaned)
    return cleaned.strip()


def _snap_boundary(text: str, start: int, end: int, min_end: int) -> int:
    """يزحلق حد المقطع إلى أقرب حد طبيعي قبل end، إن وُجد بعد min_end."""
    window = text[start:end]

    # 1) حد فقرة — الأفضل دائمًا.
    matches = list(_PARAGRAPH_BREAK.finditer(window))
    for match in reversed(matches):
        candidate = start + match.end()
        if candidate >= min_end:
            return candidate

    # 2) نهاية جملة.
    for offset in range(len(window) - 1, -1, -1):
        if window[offset] in _SENTENCE_ENDINGS:
            candidate = start + offset + 1
            if candidate >= min_end:
                return candidate

    # 3) مسافة — آخر ما يمنع قطع الكلمة.
    space = window.rfind(" ")
    if space != -1 and start + space + 1 >= min_end:
        return start + space + 1

    # 4) لا حد طبيعي (كلمة واحدة أطول من الحجم): نقطع كما هو.
    return end


def chunk_text(
    text: str,
    *,
    size: int | None = None,
    overlap: int | None = None,
) -> list[TextChunk]:
    """يقطّع النص إلى مقاطع متداخلة، ويحترم حدود الفقرات قدر الإمكان.

    Args:
        text: النص الكامل للمستند.
        size: أقصى طول للمقطع بالحروف. الافتراضي CHUNK_SIZE من الإعدادات.
        overlap: عدد الحروف المتداخلة بين مقطع والذي يليه. الافتراضي
            CHUNK_OVERLAP. يجب أن يكون أصغر من size.

    Returns:
        قائمة مقاطع مرقّمة من صفر بالترتيب. نص فارغ يعطي قائمة فارغة.

    Raises:
        ChunkingError: إذا كان الحجم غير موجب أو التداخل ≥ الحجم.
    """
    chunk_size = settings.chunk_size if size is None else size
    chunk_overlap = settings.chunk_overlap if overlap is None else overlap

    if chunk_size <= 0:
        raise ChunkingError("حجم المقطع يجب أن يكون رقمًا موجبًا.")
    if chunk_overlap < 0:
        raise ChunkingError("التداخل بين المقاطع لا يمكن أن يكون سالبًا.")
    if chunk_overlap >= chunk_size:
        raise ChunkingError(
            f"التداخل ({chunk_overlap}) يجب أن يكون أصغر من حجم المقطع "
            f"({chunk_size})، وإلا لن ينتهي التقطيع."
        )

    cleaned = normalize_text(text)
    if not cleaned:
        return []

    total = len(cleaned)
    min_fill = max(1, int(chunk_size * _MIN_FILL_RATIO))
    pieces: list[str] = []
    start = 0

    while start < total:
        end = min(start + chunk_size, total)
        if end < total:
            end = _snap_boundary(cleaned, start, end, min_end=start + min_fill)

        piece = cleaned[start:end].strip()
        if piece:
            pieces.append(piece)

        if end >= total:
            break
        # التقدّم بخطوة موجبة دائمًا حتى لا تدور الحلقة إلى ما لا نهاية.
        start = max(end - chunk_overlap, start + 1)

    return [TextChunk(index=index, content=piece) for index, piece in enumerate(pieces)]
