# -*- mode: python ; coding: utf-8 -*-
"""مواصفة PyInstaller لـGovMind Runtime.

**الغرض: ملف تنفيذي واحد لا يحتاج بايثون على جهاز العميل.** الشرط صريح —
لا يُفترض وجود Node.js ولا Python على حاسب المشتري.

⚠️ **لا يُحزَم أي سرّ ولا ملف `.env`.** الإعداد الوحيد الذي يحتاجه الـRuntime
هو عنوان Backend المستضاف، وينشره المثبّت في `govmind.config.json` بجانب
الملف التنفيذي — قيمة عامة لا سرّ.

⚠️ **لا يُحزَم المودل ولا ثنائيات llama.cpp هنا.** الأول بالجيجابايتات
ويُنزَّل بعد التفعيل، والثانية ينسخها المثبّت من `runtime/vendor/`.
"""

import sys
from pathlib import Path

block_cipher = None

# `SPECPATH` يعطيه PyInstaller — مجلد هذا الملف.
ROOT = Path(SPECPATH).resolve()  # noqa: F821

a = Analysis(
    # ⚠️ `launcher.py` لا `govmind_runtime/__main__.py`: PyInstaller ينفّذ
    # سكربت البداية كوحدة عليا، فالاستيراد النسبي داخله يفشل.
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    # الواجهة الثابتة يضعها المثبّت بجانب الملف التنفيذي لا داخله: تحديث
    # الواجهة وحدها يجب ألا يستلزم إعادة بناء المفسّر كله.
    datas=[],
    hiddenimports=[
        # uvicorn يحمّل هذه ديناميكيًا، فلا يراها المحلّل الساكن.
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # حزم ثقيلة لا يحتاجها الـRuntime — استبعادها يقلّص الملف كثيرًا.
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "PIL",
        "pytest",
        "PyInstaller",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="govmind-runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # ⚠️ **بلا نافذة طرفية.** العميل يجب ألا يرى نافذة سوداء عند الإقلاع.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # التوقيع خطوة لاحقة تحتاج شهادة Code Signing — انظر installer/README.md.
    icon=None,
)
