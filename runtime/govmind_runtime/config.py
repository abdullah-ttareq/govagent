"""إعداد GovMind Runtime — **إعداد عام فقط، بلا أي سرّ سحابي**.

⚠️ **ما لا يوجد في هذا الملف ولا في أي ملف يُثبَّت على جهاز العميل:**
`SUPABASE_SERVICE_ROLE_KEY` و `SUPABASE_JWT_SECRET` و
`AZURE_STORAGE_CONNECTION_STRING` و `DEVICE_HASH_PEPPER`. كلها تبقى على
Backend المستضاف. الـRuntime برنامج على جهاز عميل — يجب افتراض أن العميل
يستطيع قراءة كل بايت فيه، فما يُوضع فيه يُعتبر منشورًا.

ما يعرفه الـRuntime: عنوان Backend المستضاف، ومسارات التثبيت. لا أكثر.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: أسماء متغيرات يُمنع وجودها في بيئة الـRuntime أو ملفات إعداده.
#: يفحصها الـRuntime عند الإقلاع ويفحصها اختبارُ تفتيش الحزمة.
FORBIDDEN_SETTING_NAMES: tuple[str, ...] = (
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWT_SECRET",
    "AZURE_STORAGE_CONNECTION_STRING",
    "DEVICE_HASH_PEPPER",
    "PROVISIONING_KEY",
    "JWT_SECRET",
)

#: عنوان Backend المستضاف. يُثبَّت وقت البناء ويُكتب في ملف الإعداد الذي
#: ينشره المثبّت. **لا يُدخله المستخدم في أي شاشة.**
DEFAULT_CONTROL_PLANE_URL = "http://localhost:8000"

#: منفذ الـRuntime المفضَّل. إن كان مشغولًا يُجرَّب ما بعده.
DEFAULT_PORT = 8765

#: عدد المنافذ التي تُجرَّب بعد المفضَّل قبل الاستسلام.
PORT_SEARCH_RANGE = 20

#: اسم مجلد بيانات التركيب تحت %ProgramData%.
APP_DIR_NAME = "GovMind"


def default_data_dir() -> Path:
    """مجلد بيانات التركيب.

    `%ProgramData%` لا `%APPDATA%`: الهوية والمودل يخصّان **الجهاز** لا
    المستخدم المتنقّل، ويجب أن يجدهما الـRuntime أيًّا كان الحساب الذي
    يشغّله.
    """
    base = os.environ.get("PROGRAMDATA") or os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME.lower()}"


def install_root() -> Path:
    """مجلد التثبيت — حيث يوضع llama.cpp وملفات الواجهة."""
    override = os.environ.get("GOVMIND_INSTALL_ROOT")
    if override:
        return Path(override)
    # عند التجميع بـPyInstaller يكون المجلد هو مجلد الملف التنفيذي.
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RuntimeConfig:
    """إعداد التشغيل الفعّال."""

    control_plane_url: str
    data_dir: Path
    install_root: Path
    port: int

    @property
    def model_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def model_path(self) -> Path:
        """مسار المودل المكتمل والمتحقَّق منه.

        **الامتداد `.gguf` يعني «مُتحقَّق منه»**: التنزيل يكتب `.part`،
        ولا يُعاد التسمية إلا بعد مطابقة الحجم والتجزئة.
        """
        return self.model_dir / "govmind-model.gguf"

    @property
    def part_path(self) -> Path:
        return self.model_dir / "govmind-model.gguf.part"

    @property
    def llama_server(self) -> Path:
        return self.install_root / "llama.cpp" / "llama-server.exe"

    @property
    def ui_dir(self) -> Path:
        return self.install_root / "ui"

    @property
    def session_file(self) -> Path:
        """رمز الجلسة المحلي الذي تقرؤه الواجهة."""
        return self.data_dir / "session.txt"

    @property
    def log_file(self) -> Path:
        return self.data_dir / "logs" / "runtime.log"


def load_config() -> RuntimeConfig:
    """يبني الإعداد من البيئة والمسارات الافتراضية.

    Raises:
        RuntimeError: إذا وُجد في البيئة أي سرّ سحابي — وجوده يعني أن
            المثبّت أو بيئة التشغيل حُقنت بما لا يجوز أن يصل جهاز عميل.
    """
    leaked = [name for name in FORBIDDEN_SETTING_NAMES if os.environ.get(name)]
    if leaked:
        raise RuntimeError(
            "أسرار خادم موجودة في بيئة الـRuntime ولا يجوز أن تكون هنا: "
            + "، ".join(leaked)
        )

    return RuntimeConfig(
        control_plane_url=(
            os.environ.get("GOVMIND_CONTROL_PLANE_URL") or DEFAULT_CONTROL_PLANE_URL
        ).rstrip("/"),
        data_dir=Path(os.environ.get("GOVMIND_DATA_DIR") or default_data_dir()),
        install_root=install_root(),
        port=int(os.environ.get("GOVMIND_PORT") or DEFAULT_PORT),
    )
