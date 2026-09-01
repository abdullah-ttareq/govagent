"""إعداد مشترك لاختبارات GovMind Runtime.

**بلا شبكة وبلا Azure وبلا Supabase وبلا `llama-server` حقيقي.** كل ما
يخرج عن العملية يُستبدل بمزيّف يحاكي السلوك — بما فيه فشل الشبكة في منتصف
التنزيل، ورابط SAS منتهٍ، وملف بتجزئة خاطئة.

`DpapiProtector` **لا يُستبدل في اختبارات ويندوز**: هو جوهر حماية هوية
الجهاز، واختباره بمزيّف يختبر المزيّف. الحامي البديل هنا لغير ويندوز وحده،
حتى تمرّ الاختبارات على أي جهاز — ولا يُستعمل في التشغيل أبدًا.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from govmind_runtime.config import RuntimeConfig


class InMemoryProtector:
    """حامٍ بديل **للاختبارات على غير ويندوز فقط**.

    ⚠️ لا يعمّي شيئًا. لا يُستعمل في التشغيل بحال — `default_protector`
    يرفع خطأً بدل أن يعود بمثله.
    """

    name = "test-inmemory"

    def protect(self, secret: bytes) -> bytes:
        return b"TESTBLOB:" + secret

    def unprotect(self, blob: bytes) -> bytes:
        if not blob.startswith(b"TESTBLOB:"):
            raise ValueError("blob غير معروف")
        return blob[len(b"TESTBLOB:") :]


@pytest.fixture
def protector():
    """DPAPI حقيقي على ويندوز، وبديل في الذاكرة على غيره."""
    if sys.platform == "win32":
        from govmind_runtime.identity import DpapiProtector

        return DpapiProtector()
    return InMemoryProtector()


@pytest.fixture
def config(tmp_path: Path) -> RuntimeConfig:
    """إعداد يعمل داخل مجلد مؤقت — لا يلمس %ProgramData% الحقيقي."""
    return RuntimeConfig(
        control_plane_url="https://control.govmind.test",
        data_dir=tmp_path / "data",
        install_root=tmp_path / "install",
        port=8765,
    )
