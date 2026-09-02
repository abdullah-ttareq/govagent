"""سجلّ المحادثات: **يملكه الـRuntime، ويُفصل بالحساب**.

ما يثبته هذا الملف:

* الحفظ يبقى بعد إعادة الإنشاء — أي بعد إغلاق التطبيق وإعادة فتحه.
* حسابان على الجهاز نفسه لا يريان محادثات بعضهما.
* الترتيب الأحدث أولًا.
* العنوان يُشتقّ من أول رسالة مستخدم، بالعربية، بلا نداء مودل.
* لا بريد ولا سرّ في اسم ملف ولا في محتواه.
"""

from __future__ import annotations

import json

import pytest

from govmind_runtime.conversations import (
    UNTITLED,
    ConversationStore,
    account_key,
    derive_title,
)

A = "owner@example.test"
B = "other@example.test"


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "data")


# ===========================================================================
# ١) الحفظ والاستعادة
# ===========================================================================
def test_a_new_conversation_starts_empty_and_untitled(store):
    created = store.create(A)

    assert created["messages"] == []
    assert created["title"] == UNTITLED
    assert created["id"]


def test_conversations_survive_a_fresh_store(store, tmp_path):
    """⚠️ **الاستعادة بعد إعادة التشغيل.**

    مخزنُ متصفح كان يفقد هذا عند مسح بيانات الموقع؛ الملف لا يفقده.
    """
    created = store.create(A)
    store.append(
        A, created["id"], user_message="ما نظام العمل؟", assistant_message="الرد."
    )

    reopened = ConversationStore(tmp_path / "data")
    restored = reopened.get(A, created["id"])

    assert restored is not None
    assert [m["content"] for m in restored["messages"]] == ["ما نظام العمل؟", "الرد."]


def test_deleting_removes_it_permanently(store, tmp_path):
    created = store.create(A)

    assert store.delete(A, created["id"]) is True
    assert store.get(A, created["id"]) is None
    assert ConversationStore(tmp_path / "data").get(A, created["id"]) is None


def test_deleting_an_unknown_id_is_reported_not_silent(store):
    # صمتٌ عند الفشل يجعل الواجهة تعرض «حُذفت» لشيء ما زال موجودًا.
    assert store.delete(A, "does-not-exist") is False


def test_a_corrupt_file_does_not_crash_the_app(store, tmp_path):
    """ملف تالف يُعامَل كفارغ — لا شاشة بيضاء."""
    store.create(A)
    path = tmp_path / "data" / "conversations" / f"{account_key(A)}.json"
    path.write_text("{ this is not json", encoding="utf-8")

    assert store.list(A) == []


# ===========================================================================
# ٢) الفصل بالحساب
# ===========================================================================
def test_two_accounts_never_see_each_other(store):
    """⚠️ **الحدّ الذي لا يوفّره مخزن المتصفح.**

    `localStorage` مرتبط بالأصل، والأصل واحد لكل من يفتح الجهاز — فحسابان
    على حاسب مشترك كانا سيتقاسمان السجلّ.
    """
    mine = store.create(A)
    store.append(A, mine["id"], user_message="سرّي", assistant_message="رد")

    assert store.list(B) == []
    assert store.get(B, mine["id"]) is None
    assert store.delete(B, mine["id"]) is False
    assert len(store.list(A)) == 1


def test_the_account_key_is_not_the_email(store, tmp_path):
    """اسم الملف يظهر في النسخ الاحتياطي؛ لا يحمل هوية أحد."""
    store.create(A)
    names = [p.name for p in (tmp_path / "data" / "conversations").iterdir()]

    assert names
    for name in names:
        assert A not in name
        assert "owner" not in name
        assert "@" not in name


def test_no_credential_or_secret_is_written(store, tmp_path):
    store.create(A)
    store.append(A, store.list(A)[0]["id"], user_message="س", assistant_message="ج")
    blob = (tmp_path / "data" / "conversations" / f"{account_key(A)}.json").read_text(
        encoding="utf-8"
    )
    payload = json.loads(blob)

    for forbidden in ("credential", "token", "secret", "password", "@"):
        assert forbidden not in blob.lower()
    assert set(payload[0]) == {
        "id",
        "title",
        "created_at",
        "updated_at",
        "message_count",
        "messages",
    }


def test_an_unlinked_device_gets_its_own_bucket(store):
    """قبل الربط لا بريد. المحادثات تُحفظ ولا تختلط بحساب ربط لاحقًا."""
    anonymous = store.create(None)

    assert store.list(None)[0]["id"] == anonymous["id"]
    assert store.list(A) == []


# ===========================================================================
# ٣) الترتيب والعنوان
# ===========================================================================
def test_the_list_is_newest_first(store):
    first = store.create(A)
    second = store.create(A)
    # لمسُ الأقدم يرفعه إلى الأعلى: الترتيب بآخر نشاط لا بلحظة الإنشاء.
    store.append(A, first["id"], user_message="س", assistant_message="ج")

    assert [c["id"] for c in store.list(A)] == [first["id"], second["id"]]


def test_the_list_carries_no_message_bodies(store):
    """قائمةٌ تحمل كل النصوص تنقل ميجابايتات لا يعرضها أحد."""
    created = store.create(A)
    store.append(A, created["id"], user_message="نصّ طويل", assistant_message="ج")

    summary = store.list(A)[0]
    assert "messages" not in summary
    assert summary["message_count"] == 2


def test_the_title_comes_from_the_first_user_message(store):
    created = store.create(A)

    store.append(
        A, created["id"], user_message="ما نظام العمل السعودي؟", assistant_message="ج"
    )

    assert store.list(A)[0]["title"] == "ما نظام العمل السعودي؟"


def test_the_title_is_not_rewritten_by_later_messages(store):
    created = store.create(A)
    store.append(A, created["id"], user_message="السؤال الأول", assistant_message="ج")
    store.append(A, created["id"], user_message="سؤال آخر تمامًا", assistant_message="ج")

    assert store.list(A)[0]["title"] == "السؤال الأول"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("مرحبا", "مرحبا"),
        ("   مرحبا   بك   ", "مرحبا بك"),
        ("", UNTITLED),
        ("   ", UNTITLED),
    ],
)
def test_derive_title_handles_short_and_empty(text, expected):
    assert derive_title(text) == expected


def test_a_long_title_is_cut_at_a_word_boundary():
    """قصٌّ في منتصف كلمة يُقرأ أسوأ من قصٍّ عند مسافة."""
    long_text = "ما هي أهم النقاط التي يجب مراجعتها قبل توقيع عقد توريد حكومي كبير"

    title = derive_title(long_text)

    assert title.endswith("…")
    assert len(title) <= 41
    assert not title[:-1].endswith(" ")


def test_appending_to_a_missing_conversation_reports_failure(store):
    assert store.append(A, "nope", user_message="س", assistant_message="ج") is None
