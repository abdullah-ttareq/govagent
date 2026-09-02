"""نقطة دخول الملف المجمَّع بـPyInstaller.

**لماذا ملف منفصل عن `govmind_runtime/__main__.py`؟** لأن PyInstaller ينفّذ
سكربت البداية **كوحدة عليا** لا كجزء من حزمة، فالاستيراد النسبي
(`from .main import ...`) يفشل بـ«attempted relative import with no known
parent package». هذا الملف يستورد بالمسار المطلق فيعمل في الحالتين.

`__main__.py` يبقى لتشغيل `python -m govmind_runtime` أثناء التطوير.
"""

from govmind_runtime.main import main

if __name__ == "__main__":
    raise SystemExit(main())
