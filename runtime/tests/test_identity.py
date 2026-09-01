"""هوية الجهاز — التوليد والحماية والاستقرار.

على ويندوز تعمل هذه الاختبارات على **DPAPI الحقيقي** لا على مزيّف: حماية
سرّ الجهاز هي جوهر «جهاز واحد لكل اشتراك»، واختبارها بمزيّف يختبر المزيّف.
"""

from __future__ import annotations

import sys

import pytest

from govmind_runtime.identity import DeviceIdentity, IdentityError, SECRET_BYTES


def test_generates_a_secret_on_first_start(tmp_path, protector):
    identity = DeviceIdentity(tmp_path, protector)
    assert identity.load() is None

    secret = identity.ensure()
    assert secret
    # `token_urlsafe(32)` ينتج ٤٣ حرفًا — ٢٥٦ بت عشوائية.
    assert len(secret) >= SECRET_BYTES


def test_secret_is_stable_across_restarts(tmp_path, protector):
    """**أهم اختبار هنا.** سرّ يتغيّر عند كل إقلاع يهجر التفعيل في كل مرة."""
    first = DeviceIdentity(tmp_path, protector).ensure()
    second = DeviceIdentity(tmp_path, protector).ensure()
    third = DeviceIdentity(tmp_path, protector).load()

    assert first == second == third


def test_two_installations_get_different_secrets(tmp_path, protector):
    a = DeviceIdentity(tmp_path / "a", protector).ensure()
    b = DeviceIdentity(tmp_path / "b", protector).ensure()
    assert a != b


def test_secret_is_never_stored_in_clear(tmp_path, protector):
    """⚠️ الملف على القرص لا يحتوي السرّ بأي ترميز مباشر."""
    identity = DeviceIdentity(tmp_path, protector)
    secret = identity.ensure()
    raw = identity.path.read_bytes()

    assert secret.encode("ascii") not in raw
    assert secret.encode("utf-16-le") not in raw


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI متاح على ويندوز فقط")
def test_windows_uses_real_dpapi(tmp_path):
    """على ويندوز يُستعمل DPAPI فعلًا لا بديل نصّي."""
    identity = DeviceIdentity(tmp_path)
    identity.ensure()
    assert identity._protector.name == "dpapi-local-machine"
    # ترويسة blob من DPAPI تبدأ بـGUID الموفّر المعروف.
    assert len(identity.path.read_bytes()) > 100


def test_corrupt_file_is_treated_as_missing(tmp_path, protector):
    """نسخ من جهاز آخر أو إعادة تثبيت ويندوز: لا يُفكّ، فيُعامَل كغياب."""
    identity = DeviceIdentity(tmp_path, protector)
    identity.ensure()
    identity.path.write_bytes(b"not-a-valid-blob")

    assert identity.load() is None


def test_corrupt_file_regenerates_with_a_new_secret(tmp_path, protector):
    identity = DeviceIdentity(tmp_path, protector)
    original = identity.ensure()
    identity.path.write_bytes(b"not-a-valid-blob")

    replacement = identity.ensure()
    assert replacement != original
    assert identity.load() == replacement


def test_unreadable_file_raises_instead_of_regenerating(tmp_path, protector):
    """**تعذّر القراءة ليس تعذّر الفكّ.**

    خللٌ عابر في الصلاحيات يجب ألا يولّد هوية جديدة: ذلك يهجر تفعيلًا
    قائمًا ويجبر العميل على مراجعة مسؤوله بلا سبب.
    """
    identity = DeviceIdentity(tmp_path, protector)
    identity.ensure()

    original_read = type(identity.path).read_bytes

    def deny(self, *args, **kwargs):
        raise PermissionError("مرفوض")

    type(identity.path).read_bytes = deny
    try:
        with pytest.raises(IdentityError):
            identity.load()
    finally:
        type(identity.path).read_bytes = original_read


def test_clear_removes_the_secret(tmp_path, protector):
    identity = DeviceIdentity(tmp_path, protector)
    identity.ensure()
    identity.clear()

    assert not identity.exists()
    assert identity.load() is None


def test_clear_is_safe_when_nothing_exists(tmp_path, protector):
    DeviceIdentity(tmp_path, protector).clear()  # لا يرفع شيئًا


def test_no_plaintext_fallback_protector_exists():
    """⚠️ لا بديل نصّي صريح في الشيفرة بحال.

    التخزين بلا تعمية يجعل نسخ ملف واحد كافيًا لانتحال الجهاز، وهو أسوأ
    من التوقّف برسالة واضحة.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "govmind_runtime" / "identity.py"
    ).read_text(encoding="utf-8")

    assert "PlaintextProtector" not in source
    assert "def default_protector" in source
    # الدالة تعيد DPAPI أو ترفع — لا فرع ثالث.
    tail = source.split("def default_protector", 1)[1].split("\n\n\n", 1)[0]
    assert "return DpapiProtector()" in tail
    assert "except" not in tail
