"""التاريخ في تعليمات النظام: **يُحقن عند كل طلب، بتوقيت الرياض**.

بلا هذا كان المودل يخمّن التاريخ من تدريبه، فيحسب المدد والمواعيد على يوم
خاطئ ويقولها بثقة. وتاريخٌ مكتوب في ثابت يصير خطأً صامتًا في اليوم التالي.
"""

from datetime import UTC, datetime, timedelta

from app.ai.system_prompt import RIYADH, SYSTEM_PROMPT, build_system_prompt


def test_the_prompt_carries_todays_date():
    moment = datetime(2026, 9, 2, 14, 30, tzinfo=RIYADH)

    prompt = build_system_prompt("", now=moment)

    assert "2026-09-02" in prompt
    assert "14:30" in prompt
    assert "الأربعاء" in prompt
    assert "بتوقيت الرياض" in prompt


def test_riyadh_is_utc_plus_three():
    """السعودية بلا توقيت صيفي — الإزاحة ثابتة طوال العام."""
    for month in (1, 6, 12):
        moment = datetime(2026, month, 15, 12, 0, tzinfo=RIYADH)
        assert moment.utcoffset() == timedelta(hours=3)


def test_a_utc_moment_is_converted_not_copied():
    """⚠️ توقيت السيرفر ليس توقيت المكتب.

    منتصفُ ليل UTC هو الثالثة فجرًا في الرياض — **من اليوم التالي**. نسخُ
    ساعة السيرفر كان سيعطي الموظف يومًا خاطئًا كل ليلة.
    """
    utc_midnight = datetime(2026, 9, 2, 23, 30, tzinfo=UTC)

    prompt = build_system_prompt("", now=utc_midnight)

    assert "2026-09-03" in prompt
    assert "2026-09-02" not in prompt


def test_no_date_is_hard_coded_in_the_static_prompt():
    """الثابت نفسه خالٍ من أي تاريخ — وإلا تناقض مع المحقون."""
    import re

    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", SYSTEM_PROMPT)


def test_the_model_is_told_not_to_trust_its_own_sense_of_time():
    prompt = build_system_prompt("", now=datetime(2026, 9, 2, 9, 0, tzinfo=RIYADH))

    assert "لا تعتمد على تاريخ من معرفتك المسبقة" in prompt


def test_the_date_appears_with_and_without_file_context():
    moment = datetime(2026, 9, 2, 9, 0, tzinfo=RIYADH)

    assert "2026-09-02" in build_system_prompt("", now=moment)
    assert "2026-09-02" in build_system_prompt("مقطع من ملف", now=moment)


def test_the_clock_is_read_per_call_not_frozen_at_import():
    a = build_system_prompt("", now=datetime(2026, 1, 1, 8, 0, tzinfo=RIYADH))
    b = build_system_prompt("", now=datetime(2027, 5, 9, 8, 0, tzinfo=RIYADH))

    assert "2026-01-01" in a
    assert "2027-05-09" in b
