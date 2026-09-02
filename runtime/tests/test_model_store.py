"""تنزيل المودل والتحقق منه — الحالات التي تفسد ملفًا بالجيجابايتات.

**القاعدة التي تحرسها هذه الاختبارات:** لا يُعامَل ملفٌ غير مُتحقَّق منه
كمثبَّت أبدًا. تنزيل ناقص، أو حجم خاطئ، أو تجزئة خاطئة — كلها تترك النظام
بلا مودل، لا بمودل نصفه.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest

from govmind_runtime.model_store import (
    DownloadCancelled,
    InsufficientDiskSpaceError,
    ModelArtifact,
    ModelError,
    ModelStore,
    ModelVerificationError,
    sha256_of,
)

CONTENT = b"GGUF" + bytes(range(256)) * 400  # ~100 KiB محتوى محدَّد
SHA = hashlib.sha256(CONTENT).hexdigest()
SIGNED_URL = "https://acct.blob.core.windows.net/models/m.gguf?sv=2022&sig=SECRET"


def artifact(**overrides) -> ModelArtifact:
    values = {
        "download_url": SIGNED_URL,
        "file_name": "govmind-model.gguf",
        "sha256": SHA,
        "size_bytes": len(CONTENT),
    }
    values.update(overrides)
    return ModelArtifact(**values)


def make_store(tmp_path, handler):
    """مخزن يتحدّث إلى ناقل مزيّف بدل الشبكة."""
    return ModelStore(
        model_path=tmp_path / "model.gguf",
        part_path=tmp_path / "model.gguf.part",
        client_factory=lambda: httpx.Client(
            transport=httpx.MockTransport(handler), timeout=5.0
        ),
    )


def full_response(request: httpx.Request) -> httpx.Response:
    """يخدم الملف كاملًا، ويحترم `Range` إن طُلب."""
    range_header = request.headers.get("Range")
    if range_header:
        start = int(range_header.split("=")[1].split("-")[0])
        return httpx.Response(
            206,
            content=CONTENT[start:],
            headers={"Content-Range": f"bytes {start}-{len(CONTENT) - 1}/{len(CONTENT)}"},
        )
    return httpx.Response(200, content=CONTENT)


# ===========================================================================
# المسار السليم
# ===========================================================================
def test_downloads_verifies_and_installs(tmp_path):
    store = make_store(tmp_path, full_response)
    path = store.download(artifact())

    assert path.is_file()
    assert path.read_bytes() == CONTENT
    assert store.is_installed()
    # `‎.part` لا يبقى بعد النجاح.
    assert not (tmp_path / "model.gguf.part").exists()


def test_progress_reaches_one_hundred(tmp_path):
    store = make_store(tmp_path, full_response)
    seen: list[int] = []
    store.download(artifact(), on_progress=lambda p: seen.append(p.percent))

    assert seen, "لم يُبلَّغ عن أي تقدّم"
    assert seen[-1] == 100
    assert seen == sorted(seen), "التقدّم يجب ألا يتراجع"


def test_sha256_of_matches_hashlib(tmp_path):
    target = tmp_path / "f.bin"
    target.write_bytes(CONTENT)
    assert sha256_of(target) == SHA


# ===========================================================================
# التحقق — لا يُقبل ملف غير مطابق
# ===========================================================================
def test_wrong_checksum_is_rejected_and_deleted(tmp_path):
    """**ملف تالف أو مستبدَل**: حجم صحيح وتجزئة خاطئة."""
    tampered = bytearray(CONTENT)
    tampered[10] ^= 0xFF  # بايت واحد يكفي

    store = make_store(
        tmp_path, lambda request: httpx.Response(200, content=bytes(tampered))
    )
    with pytest.raises(ModelVerificationError) as caught:
        store.download(artifact())

    assert "تالف" in str(caught.value)
    assert not store.is_installed()
    assert not (tmp_path / "model.gguf.part").exists()


def test_wrong_size_is_rejected_and_deleted(tmp_path):
    store = make_store(tmp_path, lambda request: httpx.Response(200, content=CONTENT))
    with pytest.raises(ModelVerificationError):
        store.download(artifact(size_bytes=len(CONTENT) + 5000))

    assert not store.is_installed()
    assert not (tmp_path / "model.gguf.part").exists()


def test_missing_checksum_refuses_installation(tmp_path):
    """بلا تجزئة لا تحقّق، وبلا تحقّق لا تثبيت."""
    store = make_store(tmp_path, lambda request: httpx.Response(200, content=CONTENT))
    with pytest.raises(ModelVerificationError):
        store.download(artifact(sha256=""))
    assert not store.is_installed()


def test_partial_file_is_never_treated_as_installed(tmp_path):
    """`‎.part` مهما كبر ليس مودلًا مثبَّتًا."""
    (tmp_path / "model.gguf.part").write_bytes(CONTENT)
    store = make_store(tmp_path, full_response)
    assert store.is_installed() is False
    assert store.partial_bytes() == len(CONTENT)


# ===========================================================================
# الاستئناف بعد الانقطاع
# ===========================================================================
def test_resumes_from_partial_download(tmp_path):
    """الانقطاع يترك `‎.part`، والمحاولة التالية تكمل من حيث توقّفت."""
    half = len(CONTENT) // 2
    (tmp_path / "model.gguf.part").write_bytes(CONTENT[:half])

    ranges: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ranges.append(request.headers.get("Range"))
        return full_response(request)

    store = make_store(tmp_path, handler)
    store.download(artifact())

    assert ranges[0] == f"bytes={half}-", "لم يُطلب استئناف"
    assert store.model_path.read_bytes() == CONTENT


def test_interrupted_download_keeps_partial_for_resume(tmp_path):
    """انقطاع الشبكة في المنتصف: يبقى ما نُزّل ولا يُحذف."""

    def dropping(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("انقطع الاتصال")

    store = make_store(tmp_path, dropping)
    with pytest.raises(ModelError):
        store.download(artifact())
    assert not store.is_installed()


def test_server_ignoring_range_restarts_cleanly(tmp_path):
    """خادم يتجاهل `Range` ويعيد ٢٠٠: يُعاد التنزيل بدل إلحاق يفسد الملف."""
    half = len(CONTENT) // 2
    (tmp_path / "model.gguf.part").write_bytes(CONTENT[:half])

    store = make_store(tmp_path, lambda request: httpx.Response(200, content=CONTENT))
    store.download(artifact())

    # لو أُلحق لكان الحجم أكبر ولفشلت التجزئة.
    assert store.model_path.read_bytes() == CONTENT


def test_oversized_partial_is_discarded(tmp_path):
    """بقايا تنزيل لنسخة أخرى أكبر من المتوقّع: تُحذف ويُبدأ من جديد."""
    (tmp_path / "model.gguf.part").write_bytes(CONTENT * 2)
    store = make_store(tmp_path, lambda request: httpx.Response(200, content=CONTENT))
    store.download(artifact())
    assert store.model_path.read_bytes() == CONTENT


# ===========================================================================
# رابط SAS منتهٍ، والإلغاء، والمساحة
# ===========================================================================
@pytest.mark.parametrize("code", [401, 403])
def test_expired_sas_gives_a_clear_message(tmp_path, code):
    store = make_store(tmp_path, lambda request: httpx.Response(code))
    with pytest.raises(ModelError) as caught:
        store.download(artifact())

    assert "انتهت صلاحية رابط" in str(caught.value)
    assert not store.is_installed()


def test_error_messages_never_leak_the_signed_url(tmp_path):
    """⚠️ الرابط الموقّع لا يظهر في أي رسالة خطأ."""
    for handler in (
        lambda request: httpx.Response(403),
        lambda request: httpx.Response(500),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("boom")),
    ):
        store = make_store(tmp_path, handler)
        with pytest.raises(ModelError) as caught:
            store.download(artifact())
        assert "sig=" not in str(caught.value)
        assert "SECRET" not in str(caught.value)


def test_cancel_mid_download_keeps_partial_for_resume(tmp_path):
    """الإلغاء **أثناء** التنزيل: يتوقف، وما نُزّل يبقى ليُستأنف منه.

    الإلغاء يُطلب من ردّ التقدّم لا قبل البدء: `download` تصفّر العلم عند
    الدخول عمدًا، وإلا ورث تنزيلٌ جديد إلغاءً قديمًا فتعذّر أن يبدأ أصلًا.
    """
    big = b"G" * (3 << 20)  # ثلاث قطع
    big_sha = hashlib.sha256(big).hexdigest()

    store = make_store(tmp_path, lambda request: httpx.Response(200, content=big))

    def cancel_after_first(progress) -> None:
        if progress.received >= (1 << 20):
            store.cancel()

    with pytest.raises(DownloadCancelled):
        store.download(
            artifact(sha256=big_sha, size_bytes=len(big)),
            on_progress=cancel_after_first,
        )

    assert not store.is_installed()
    # ما نُزّل محفوظ: الإلغاء ليس حذفًا.
    assert 0 < store.partial_bytes() < len(big)


def test_download_clears_a_stale_cancel_flag(tmp_path):
    """إلغاءٌ سابق لا يمنع تنزيلًا جديدًا من البدء."""
    store = make_store(tmp_path, full_response)
    store.cancel()
    store.download(artifact())
    assert store.is_installed()


def test_insufficient_disk_space_is_refused_before_downloading(tmp_path, monkeypatch):
    """الفحص **قبل** البدء لا بعد ساعة من التنزيل."""
    monkeypatch.setattr(
        "govmind_runtime.model_store.free_space", lambda path: 1024
    )
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        calls.append("called")
        return httpx.Response(200, content=CONTENT)

    store = make_store(tmp_path, handler)
    with pytest.raises(InsufficientDiskSpaceError) as caught:
        store.download(artifact(size_bytes=10 << 30))

    assert "فرّغ مساحة" in str(caught.value)
    assert calls == [], "لا يجوز أن يبدأ التنزيل والمساحة لا تكفي"
