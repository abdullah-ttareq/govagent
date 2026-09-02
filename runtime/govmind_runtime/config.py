"""إعداد GovMind Runtime — **إعداد عام فقط، بلا أي سرّ سحابي**.

⚠️ **ما لا يوجد في هذا الملف ولا في أي ملف يُثبَّت على جهاز العميل:**
`SUPABASE_SERVICE_ROLE_KEY` و `SUPABASE_JWT_SECRET` و
`AZURE_STORAGE_CONNECTION_STRING` و `DEVICE_HASH_PEPPER`. كلها تبقى على
Backend المستضاف. الـRuntime برنامج على جهاز عميل — يجب افتراض أن العميل
يستطيع قراءة كل بايت فيه، فما يُوضع فيه يُعتبر منشورًا.

ما يعرفه الـRuntime: عنوان Backend المستضاف، ومسارات التثبيت. لا أكثر.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

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

#: ملف الإعداد العام الذي ينشره المثبّت بجوار الملف التنفيذي.
#:
#: ⚠️ **قيمة عامة لا سرّ.** فيه عنوان Backend المستضاف وقناة الإصدار، ولا
#: شيء غيرهما — انظر `FORBIDDEN_SETTING_NAMES` أعلاه ويحرسه فحص الحزمة في
#: `installer/build.ps1`.
CONFIG_FILE_NAME = "govmind.config.json"

#: المفاتيح المقروءة من ملف الإعداد. **قائمة بيضاء صريحة**: مفتاح لم يُذكر
#: هنا يُتجاهَل، فلا يستطيع ملفٌ معدَّل على جهاز العميل أن يحقن إعدادًا لم
#: يُصمَّم له البرنامج.
ALLOWED_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "control_plane_url",
        "channel",
        # وضع العرض الأكاديمي — انظر الشرح أدناه.
        "demo_engine_url",
        "demo_engine_type",
        "demo_model",
        # مكان معالجة المحادثة — انظر :data:`CHAT_MODES`.
        "chat_mode",
    }
)

#: أنواع محرّكات العرض المدعومة. **قائمة مغلقة**: نوع مجهول يُهمَل ويعود
#: البرنامج إلى المسار الإنتاجي بدل أن يحاول التحدّث إلى ما لا يعرفه.
DEMO_ENGINE_TYPES: frozenset[str] = frozenset({"ollama"})

#: أين تُعالَج المحادثة. **قائمة مغلقة**، وقيمة مجهولة تعود إلى `local`.
#:
#: - ``local``: مودل يعمل على جهاز العميل، ونصّه لا يغادره.
#: - ``cloud``: يمرّ النصّ بـBackend المستضاف إلى مزوّد استدلال خارجي.
#:
#: ⚠️ **الفرق يُعرض للعميل ولا يُخفى**: في `cloud` يغادر نصّ المحادثة
#: الجهاز، وله أن يعرف ذلك قبل أن يكتب.
CHAT_MODES: frozenset[str] = frozenset({"local", "cloud"})

#: المضيفات المقبولة لمحرّك العرض.
#:
#: ⚠️ **الاسترجاع المحلي وحده، ولا استثناء.** وضعُ العرض يرسل نصّ العميل
#: إلى محرّك؛ عنوانٌ غير محلي يخرج به من الجهاز. الشرط مفروض في
#: :func:`normalize_demo_url` لا في التوثيق، ويحرسه اختبار.
LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


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


def read_config_file(root: Path) -> dict[str, str]:
    """يقرأ `govmind.config.json` بجوار الملف التنفيذي.

    ⚠️ **هذا هو مصدر عنوان الـControl Plane في التثبيت الحقيقي.** كان
    البرنامج يقرأ متغيّر بيئة فقط، فيسقط على القيمة المبنيّة وقت التطوير
    (`localhost:8000`) على كل جهاز عميل مهما كتب المثبّت في هذا الملف.

    **غياب الملف أو تلفه ليس خطأً قاتلًا**: يُسجَّل ويُستعمل الافتراضي، فلا
    يتوقف البرنامج على جهاز عميل بسبب ملف إعداد.

    Returns:
        القيم النصّية المسموح بها وحدها، بلا أي مفتاح خارج
        :data:`ALLOWED_CONFIG_KEYS`.
    """
    path = root / CONFIG_FILE_NAME
    if not path.is_file():
        return {}

    try:
        # `utf-8-sig` لا `utf-8`: PowerShell يكتب علامة ترتيب بايت في مقدمة
        # الملف، وقارئٌ لا يتوقّعها يفشل على أول محرف.
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        logger.warning("تعذّرت قراءة ملف إعداد GovMind؛ ستُستعمل القيم الافتراضية.")
        return {}

    if not isinstance(raw, dict):
        logger.warning("ملف إعداد GovMind بصيغة غير متوقّعة؛ يُتجاهَل.")
        return {}

    return {
        key: str(value).strip()
        for key, value in raw.items()
        if key in ALLOWED_CONFIG_KEYS and isinstance(value, str) and value.strip()
    }


def normalize_demo_url(value: str) -> str:
    """يتحقق أن عنوان محرّك العرض **محلي**، ويعيده بلا شرطة أخيرة.

    ⚠️ **يعيد نصًّا فارغًا لأي عنوان غير محلي.** وضع العرض يمرّر نصّ العميل
    إلى المحرّك؛ عنوانٌ على شبكة أو إنترنت يخرج بذلك النصّ من الجهاز، وهو
    نقيض ما يَعِد به المنتج. والرفض صامتٌ إلى عدم تفعيل الوضع أصلًا: أفضل
    من تشغيله على وجهة لم يُقصد إرسال شيء إليها.
    """
    from urllib.parse import urlparse

    cleaned = (value or "").strip().rstrip("/")
    if not cleaned:
        return ""

    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        logger.warning("عنوان محرّك العرض بلا بروتوكول مفهوم؛ يُتجاهَل.")
        return ""
    if (parsed.hostname or "") not in LOOPBACK_HOSTS:
        # ⚠️ لا يُطبع العنوان: قد يحمل مضيفًا داخليًا لا داعي لنشره.
        logger.warning(
            "عنوان محرّك العرض ليس على الاسترجاع المحلي؛ لن يُفعَّل وضع العرض."
        )
        return ""
    return cleaned


def _read_chat_mode(published: dict[str, str]) -> str:
    """يقرأ وضع المعالجة، **ويردّ المجهول إلى `local`**.

    قيمةٌ مكتوبة خطأً في ملف على جهاز العميل لا يجوز أن تعطّل البرنامج،
    ولا أن تُفسَّر تفسيرًا موسّعًا. فالمجهول يعود إلى الوضع الذي يُبقي
    النصّ على الجهاز.
    """
    raw = (
        os.environ.get("GOVMIND_CHAT_MODE") or published.get("chat_mode") or ""
    ).strip().lower()
    if raw and raw not in CHAT_MODES:
        logger.warning("وضع معالجة غير معروف في الإعداد؛ سيُعتمد المسار المحلي.")
        return ""
    return raw


@dataclass(frozen=True)
class RuntimeConfig:
    """إعداد التشغيل الفعّال."""

    control_plane_url: str
    data_dir: Path
    install_root: Path
    port: int

    # ------------------------------------------------------------------
    # وضع العرض الأكاديمي
    # ------------------------------------------------------------------
    #: عنوان محرّك العرض المحلي، أو نصّ فارغ في التشغيل الإنتاجي.
    demo_engine_url: str = ""
    #: نوع المحرّك — `ollama` وحده اليوم.
    demo_engine_type: str = ""
    #: اسم المودل كما يعرفه المحرّك، مثل `qwen2.5:1.5b`.
    demo_model: str = ""

    # ------------------------------------------------------------------
    # مكان المعالجة
    # ------------------------------------------------------------------
    #: `local` أو `cloud`. فارغٌ يعني `local` — **الافتراضي الأحفظ
    #: للخصوصية**: لا يخرج نصّ إلا بقرار مكتوب.
    chat_mode: str = ""

    @property
    def is_demo(self) -> bool:
        """هل وضع العرض مفعَّل **بالكامل**؟

        الثلاثة مطلوبة معًا: عنوان محلي صالح، ونوع محرّك معروف، واسم مودل.
        نقصُ واحدٍ منها يبقي البرنامج على المسار الإنتاجي كما هو — لا
        نصف وضع عرض يتصرّف تصرّفًا لا يفهمه أحد.
        """
        return bool(
            self.demo_engine_url
            and self.demo_model.strip()
            and self.demo_engine_type in DEMO_ENGINE_TYPES
        )

    @property
    def is_cloud_chat(self) -> bool:
        """هل تُعالَج المحادثة خارج الجهاز؟

        ⚠️ **وضع العرض يسبقه.** لو ضُبط الاثنان معًا، المحرّك المحلي أولى:
        الوضع الذي يُبقي النصّ على الجهاز هو الذي يُرجَّح عند التعارض.
        """
        return self.chat_mode == "cloud" and not self.is_demo

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
    def credential_file(self) -> Path:
        """بيان اعتماد الجهاز، **معمّى بـDPAPI**.

        ⚠️ الامتداد `bin` لا `txt`: محتواه ثنائي معمّى لا نصّ. ولا يُقرأ
        من الواجهة المحلية ولا يخرج في أي رد.
        """
        return self.data_dir / "credential.bin"

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

    root = install_root()
    published = read_config_file(root)

    # الأولوية: متغيّر البيئة (للتطوير والاختبار) ثم ملف المثبّت ثم افتراضي
    # البناء. البيئة أولًا لأنها الأضيق نطاقًا والأوضح قصدًا.
    config = RuntimeConfig(
        control_plane_url=(
            os.environ.get("GOVMIND_CONTROL_PLANE_URL")
            or published.get("control_plane_url")
            or DEFAULT_CONTROL_PLANE_URL
        ).rstrip("/"),
        data_dir=Path(os.environ.get("GOVMIND_DATA_DIR") or default_data_dir()),
        install_root=root,
        port=int(os.environ.get("GOVMIND_PORT") or DEFAULT_PORT),
        # وضع العرض: البيئة أولًا (للتطوير)، ثم ما نشره المثبّت.
        demo_engine_url=normalize_demo_url(
            os.environ.get("GOVMIND_DEMO_ENGINE_URL")
            or published.get("demo_engine_url")
            or ""
        ),
        demo_engine_type=(
            os.environ.get("GOVMIND_DEMO_ENGINE_TYPE")
            or published.get("demo_engine_type")
            or ""
        ).strip().lower(),
        demo_model=(
            os.environ.get("GOVMIND_DEMO_MODEL")
            or published.get("demo_model")
            or ""
        ).strip(),
        chat_mode=_read_chat_mode(published),
    )

    if config.is_demo:
        # ⚠️ يُسجَّل النوع والمودل — لا شيء منهما سرّ — ولا يُسجَّل أي نصّ
        # يرسله العميل لاحقًا.
        logger.info(
            "وضع العرض الأكاديمي مفعَّل: محرّك %s، مودل %s.",
            config.demo_engine_type,
            config.demo_model,
        )
    if config.is_cloud_chat:
        # ⚠️ يُسجَّل الوضع لا النصّ. ووجودُ السطر مقصود: قرارُ إخراج نصّ
        # العميل من جهازه يجب أن يكون مقروءًا في سجلّ الجهاز نفسه.
        logger.info(
            "معالجة المحادثة سحابية: يمرّ النصّ بخدمة GovMind إلى مزوّد استدلال."
        )
    elif config.demo_engine_type or config.demo_model:
        # إعداد ناقص أو عنوان غير محلي: يُقال صراحةً بدل أن يُظنّ مفعَّلًا.
        logger.warning(
            "إعداد وضع العرض ناقص أو غير مقبول؛ سيعمل GovMind بالمسار الإنتاجي."
        )

    return config
