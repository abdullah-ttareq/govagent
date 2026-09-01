"""نقطة الدخول عند التشغيل بـ`python -m govmind_runtime` أو من الملف المجمَّع."""

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
