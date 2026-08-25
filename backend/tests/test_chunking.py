"""اختبارات تقطيع النص.

دوال التقطيع نقية تمامًا: لا قاعدة بيانات ولا شبكة ولا ملفات. كل ما هنا
يعمل بنص ثابت مكتوب داخل الاختبار.
"""

import pytest

from app.services.chunking import (
    ChunkingError,
    TextChunk,
    chunk_text,
    normalize_text,
)


def _paragraphs(count: int, length: int = 120) -> str:
    return "\n\n".join(f"الفقرة رقم {i} " + ("نص " * (length // 4)) for i in range(count))


# ---------------------------------------------------------------------------
# التنظيف
# ---------------------------------------------------------------------------
def test_normalize_unifies_line_endings():
    assert normalize_text("سطر\r\nثانٍ\rثالث") == "سطر\nثانٍ\nثالث"


def test_normalize_collapses_extra_blank_lines_but_keeps_paragraphs():
    assert normalize_text("أولى\n\n\n\n\nثانية") == "أولى\n\nثانية"


def test_normalize_trims_edges():
    assert normalize_text("   \n نص \n  ") == "نص"


# ---------------------------------------------------------------------------
# الحالات الحدية
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["", "   ", "\n\n\n", "\t"])
def test_empty_text_gives_no_chunks(text):
    assert chunk_text(text) == []


def test_short_text_stays_one_chunk():
    chunks = chunk_text("خطاب قصير جدًا.", size=1000, overlap=100)
    assert chunks == [TextChunk(index=0, content="خطاب قصير جدًا.")]


def test_text_exactly_at_the_limit_stays_one_chunk():
    text = "أ" * 100
    chunks = chunk_text(text, size=100, overlap=10)
    assert len(chunks) == 1
    assert chunks[0].content == text


# ---------------------------------------------------------------------------
# الترقيم والتغطية
# ---------------------------------------------------------------------------
def test_chunks_are_numbered_in_order_from_zero():
    chunks = chunk_text(_paragraphs(12), size=300, overlap=50)
    assert len(chunks) > 1
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_no_chunk_exceeds_the_requested_size():
    chunks = chunk_text(_paragraphs(20), size=250, overlap=40)
    assert chunks
    assert all(len(chunk.content) <= 250 for chunk in chunks)


def test_no_chunk_is_blank():
    chunks = chunk_text(_paragraphs(15), size=200, overlap=30)
    assert all(chunk.content.strip() for chunk in chunks)


def test_every_word_survives_the_chunking():
    """لا تضيع كلمة بين المقاطع."""
    text = " ".join(f"كلمة{i}" for i in range(400))
    chunks = chunk_text(text, size=300, overlap=50)

    joined = " ".join(chunk.content for chunk in chunks)
    for index in range(400):
        assert f"كلمة{index}" in joined


# ---------------------------------------------------------------------------
# التداخل
# ---------------------------------------------------------------------------
def test_consecutive_chunks_actually_overlap():
    text = " ".join(f"كلمة{i}" for i in range(500))
    chunks = chunk_text(text, size=300, overlap=80)
    assert len(chunks) > 2

    for previous, following in zip(chunks, chunks[1:]):
        tail = previous.content[-40:]
        # جزء من ذيل المقطع السابق يجب أن يظهر في بداية التالي.
        assert any(word in following.content for word in tail.split() if word)


def test_zero_overlap_is_allowed():
    chunks = chunk_text(_paragraphs(10), size=250, overlap=0)
    assert len(chunks) > 1


# ---------------------------------------------------------------------------
# احترام حدود الفقرات
# ---------------------------------------------------------------------------
def test_paragraph_boundaries_are_preferred():
    """عند وجود حد فقرة داخل النافذة، يُقطع عنده لا في منتصف الجملة."""
    first = "الفقرة الأولى " * 12
    second = "الفقرة الثانية " * 12
    chunks = chunk_text(f"{first.strip()}\n\n{second.strip()}", size=220, overlap=20)

    assert len(chunks) > 1
    # المقطع الأول ينتهي بنهاية كلمة، لا بحرف مبتور.
    assert not chunks[0].content.endswith("الفقر")


def test_sentence_boundary_is_used_when_no_paragraph_break():
    text = ("هذه جملة كاملة عن إجراءات الجهة. " * 20).strip()
    chunks = chunk_text(text, size=200, overlap=20)

    assert len(chunks) > 1
    # أغلب المقاطع تنتهي بنقطة لأن حد الجملة متاح.
    ending_with_period = sum(1 for c in chunks if c.content.endswith("."))
    assert ending_with_period >= len(chunks) - 1


def test_a_single_word_longer_than_the_size_is_still_split():
    """كلمة واحدة أطول من الحجم لا توقف التقطيع."""
    chunks = chunk_text("أ" * 500, size=100, overlap=10)
    assert len(chunks) > 1
    assert all(len(chunk.content) <= 100 for chunk in chunks)


# ---------------------------------------------------------------------------
# إعدادات غير صالحة
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("size", "overlap", "expected"),
    [
        (0, 10, "موجب"),
        (-5, 10, "موجب"),
        (100, -1, "سالب"),
        (100, 100, "أصغر"),
        (100, 200, "أصغر"),
    ],
)
def test_invalid_settings_raise_a_clear_arabic_error(size, overlap, expected):
    with pytest.raises(ChunkingError) as exc:
        chunk_text("نص", size=size, overlap=overlap)
    assert expected in str(exc.value)


def test_defaults_come_from_settings(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "chunk_size", 120)
    monkeypatch.setattr(settings, "chunk_overlap", 20)

    chunks = chunk_text(_paragraphs(6))
    assert all(len(chunk.content) <= 120 for chunk in chunks)
