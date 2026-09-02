<#
.SYNOPSIS
    يبني مثبّت GovMind كاملًا من المصدر.

.DESCRIPTION
    خطوات البناء بالترتيب:

      ١) واجهة GovMind  — تصدير Next.js ساكن (لا Node.js على جهاز العميل).
      ٢) GovMind Runtime — ملف تنفيذي بـPyInstaller (لا Python على جهازه).
      ٣) llama.cpp       — ثنائيات رسمية من ggml-org (رخصة MIT).
      ٤) التراخيص        — تُنسخ كما هي، وهي إلزامية للتوزيع.
      ٥) المثبّت         — Inno Setup.

    كل مخرجات البناء تحت `installer\staging` و `installer\output`، وكلاهما
    خارج المستودع (.gitignore).

    ⚠️ **لا يُحزَم أي سرّ.** الإعداد الوحيد المنشور هو عنوان Backend
    المستضاف — قيمة عامة يعرفها كل من يفتح البرنامج.

    ⚠️ **المخرَج غير موقّع.** ويندوز سيقول «ناشر غير معروف». انظر README.md.

.PARAMETER ControlPlaneUrl
    عنوان Backend المستضاف الذي يُثبَّت في البرنامج.

.PARAMETER SkipUi
    يتخطّى بناء الواجهة (لإعادة بناء سريعة أثناء التطوير).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\build.ps1 `
        -ControlPlaneUrl "https://api.govmind.example"
#>
[CmdletBinding()]
param(
    [string]$ControlPlaneUrl = "http://localhost:8000",
    [switch]$SkipUi,
    [switch]$SkipRuntime,

    # قناة الإصدار. **`development` هو الافتراضي عمدًا**: بناءٌ غير موقّع
    # ولا مُختبَر حيًّا لا يجوز أن يبدو إنتاجيًا لمن يجده على قرص لاحقًا.
    # `production` يُمرَّر صراحةً، ويبقى غير مقبول بلا شهادة توقيع.
    [ValidateSet("development", "production")]
    [string]$Channel = "development",

    # مفسّر بايثون الذي يحمل PyInstaller. **لا يُفترض أن `python` على
    # المسار هو الصحيح**: كثير من أجهزة التطوير فيها أكثر من نسخة، وواحدة
    # منها فقط فيها تبعيات الـRuntime.
    [string]$PythonExe = "python",

    # --- وضع العرض الأكاديمي -------------------------------------------
    # ⚠️ **فارغة افتراضيًا = بناء إنتاجي بلا تغيير.** تمريرها يبني نسخة
    # عرض تستعمل محرّكًا مثبَّتًا على جهاز العميل بدل تنزيل مودل من Azure.
    # العنوان يجب أن يكون على الاسترجاع المحلي، ويرفض الـRuntime غيره.
    [string]$DemoEngineUrl = "",
    [ValidateSet("", "ollama")]
    [string]$DemoEngineType = "",
    [string]$DemoModel = "",

    # --- مكان معالجة المحادثة ------------------------------------------
    # ⚠️ **فارغة = محلي، وهو الافتراض الأحفظ للخصوصية**: لا يغادر نصّ
    # المستخدم جهازه إلا بقرار مكتوب هنا.
    #
    # `cloud` يجعل الـRuntime يمرّر المحادثة إلى خدمة GovMind ببيان اعتماد
    # الجهاز، ولا يُنزَّل مودل ولا يُشغَّل `llama-server`. **مفتاح المزوّد
    # يبقى على السيرفر ولا يدخل هذه الحزمة.**
    [ValidateSet("", "local", "cloud")]
    [string]$ChatMode = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$Installer  = Join-Path $RepoRoot "installer"
$Staging    = Join-Path $Installer "staging"
$Output     = Join-Path $Installer "output"
$RuntimeDir = Join-Path $RepoRoot "runtime"
$Frontend   = Join-Path $RepoRoot "frontend"
$Vendor     = Join-Path $RuntimeDir "vendor\llama.cpp"

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Require-Command($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "الأداة '$name' غير موجودة. $hint"
    }
}

# ---------------------------------------------------------------------------
Write-Step "تجهيز مجلدات البناء"
if (Test-Path $Staging) { Remove-Item $Staging -Recurse -Force }
New-Item -ItemType Directory -Path $Staging -Force | Out-Null
New-Item -ItemType Directory -Path $Output -Force | Out-Null

# ---------------------------------------------------------------------------
# ١) واجهة GovMind — تصدير ساكن
# ---------------------------------------------------------------------------
if (-not $SkipUi) {
    Write-Step "بناء واجهة GovMind (تصدير ساكن)"
    Require-Command "npm" "ثبّت Node.js ثم أعد المحاولة."

    Push-Location $Frontend
    try {
        # ⚠️ **تنظيف مخرجات بناء سابق قبل البدء.** بناء الويب وبناء سطح
        # المكتب يتشاركان مجلد `.next`، ويولّد كلٌّ منهما أنواع مسارات
        # لشجرته هو. بقايا بناء الويب تجعل فحص الأنواع في بناء سطح المكتب
        # يشير إلى مسارات لا يبنيها (`/admin` و`/login`) فيفشل بلا سبب
        # ظاهر في الشيفرة.
        Remove-Item (Join-Path $Frontend ".next") -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item (Join-Path $Frontend "out")   -Recurse -Force -ErrorAction SilentlyContinue

        # `GOVMIND_DESKTOP` يفعّل `output: export` **ويقصر شجرة المسارات
        # على `*.desktop.tsx`**، فلا تُبنى صفحة دخول ولا لوحة إدارة ولا
        # صفحة إعدادات سيرفر. و`NEXT_PUBLIC_...` يجعل الواجهة تنادي الأصل
        # نفسه بلا أي عنوان مكتوب.
        $env:GOVMIND_DESKTOP = "1"
        $env:NEXT_PUBLIC_GOVMIND_DESKTOP = "1"
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "فشل بناء الواجهة." }
    }
    finally {
        Remove-Item Env:\GOVMIND_DESKTOP -ErrorAction SilentlyContinue
        Remove-Item Env:\NEXT_PUBLIC_GOVMIND_DESKTOP -ErrorAction SilentlyContinue
        Pop-Location
    }

    $UiOut = Join-Path $Frontend "out"
    if (-not (Test-Path (Join-Path $UiOut "index.html"))) {
        throw "لم يُنتج تصدير الواجهة ملف index.html."
    }

    # ⚠️ **لا صفحة دخول في التثبيت.** فحصٌ صريح لا اعتماد على الإعداد:
    # عودةُ `/login/` تعني عودةَ العطل الذي رآه العميل — نموذج دخول ثانٍ
    # يردّ «Method Not Allowed».
    foreach ($forbiddenRoute in @("login", "admin", "settings")) {
        if (Test-Path (Join-Path $UiOut $forbiddenRoute)) {
            throw "تصدير الواجهة يحتوي مسار '$forbiddenRoute' ولا يجوز أن يحتويه."
        }
    }

    $UiStage = Join-Path $Staging "ui"
    Copy-Item $UiOut $UiStage -Recurse -Force

    # ملفات نسخة الويب لا مكان لها في تثبيت سطح المكتب: هيكل سطح المكتب
    # لا يسجّل عامل خدمة، والتطبيق مثبَّت على ويندوز لا مضاف إلى شاشة هاتف.
    foreach ($webOnly in @("sw.js", "offline.html", "manifest.webmanifest")) {
        Remove-Item (Join-Path $UiStage $webOnly) -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# ٢) GovMind Runtime — ملف تنفيذي واحد
# ---------------------------------------------------------------------------
if (-not $SkipRuntime) {
    Write-Step "بناء GovMind Runtime بـPyInstaller"
    Require-Command $PythonExe "ثبّت Python 3.12+ ثم: pip install -r runtime\requirements.txt"

    Push-Location $RuntimeDir
    try {
        # PyInstaller يكتب سطور INFO على stderr. مع
        # `$ErrorActionPreference = "Stop"` تحوّلها PowerShell إلى خطأ
        # قاتل (`NativeCommandError`) **رغم أن البناء نجح**. الحكم هنا
        # لرمز الخروج وحده، وهو ما تقوله الأداة فعلًا عن نفسها.
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $PythonExe -m PyInstaller --noconfirm --clean govmind-runtime.spec
        }
        finally { $ErrorActionPreference = $previousPreference }
        if ($LASTEXITCODE -ne 0) { throw "فشل بناء الـRuntime." }
    }
    finally { Pop-Location }

    $Exe = Join-Path $RuntimeDir "dist\govmind-runtime.exe"
    if (-not (Test-Path $Exe)) { throw "لم يُنتج PyInstaller الملف التنفيذي." }
    Copy-Item $Exe $Staging -Force
}

# ---------------------------------------------------------------------------
# ٣) llama.cpp — ثنائيات رسمية
# ---------------------------------------------------------------------------
Write-Step "نسخ ثنائيات llama.cpp"
if (-not (Test-Path (Join-Path $Vendor "llama-server.exe"))) {
    throw @"
ثنائيات llama.cpp غير موجودة في:
  $Vendor

نزّلها أولًا بـ:
  powershell -ExecutionPolicy Bypass -File installer\fetch-llama.ps1

⚠️ لا تستعمل نسخة LM Studio: تلك بناءٌ خاص بها وغير قابل لإعادة التوزيع.
"@
}
Copy-Item $Vendor (Join-Path $Staging "llama.cpp") -Recurse -Force

# ---------------------------------------------------------------------------
# ٤) الإعداد العام والتراخيص
# ---------------------------------------------------------------------------
Write-Step "كتابة الإعداد العام"
# ⚠️ عنوان فقط. أي مفتاح هنا يعني تسريبه إلى كل جهاز عميل.
$ConfigMap = [ordered]@{
    control_plane_url = $ControlPlaneUrl
    # القناة تُكتب في الإعداد كذلك لا في اسم الملف وحده: من يفتح تثبيتًا
    # على جهاز بعد شهور يجب أن يعرف من أين جاء.
    channel           = $Channel
    built_at          = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

# ⚠️ **الثلاثة معًا أو لا شيء.** إعدادٌ ناقص يجعل الـRuntime يتردّد بين
# وضعين، والأوضح أن يرفض البناء بدل أن يشحن التباسًا.
$DemoParts = @($DemoEngineUrl, $DemoEngineType, $DemoModel) | Where-Object { $_ }
if ($DemoParts.Count -gt 0 -and $DemoParts.Count -lt 3) {
    throw "وضع العرض يحتاج -DemoEngineUrl و -DemoEngineType و -DemoModel معًا."
}
if ($DemoParts.Count -eq 3) {
    $ConfigMap.demo_engine_url  = $DemoEngineUrl
    $ConfigMap.demo_engine_type = $DemoEngineType
    $ConfigMap.demo_model       = $DemoModel
    Write-Host "    وضع العرض: $DemoEngineType / $DemoModel" -ForegroundColor Yellow
    Write-Host "    (لا يُنزَّل مودل من Azure، ولا يُشغَّل llama-server)" -ForegroundColor Yellow
}

# ⚠️ **يتعارض مع وضع العرض.** كلاهما يلغي المودل المرفق، وشحنُ الاثنين
# معًا يشحن التباسًا: أيّهما يعمل يقرّره الـRuntime لا من بنى الحزمة.
if ($ChatMode -eq "cloud" -and $DemoParts.Count -eq 3) {
    throw "-ChatMode cloud لا يجتمع مع وضع العرض. اختر واحدًا."
}
if ($ChatMode) {
    $ConfigMap.chat_mode = $ChatMode
    if ($ChatMode -eq "cloud") {
        Write-Host "    معالجة المحادثة: سحابية عبر خدمة GovMind" -ForegroundColor Yellow
        Write-Host "    (لا يُنزَّل مودل، ولا يُشغَّل llama-server)" -ForegroundColor Yellow
        Write-Host "    (نصّ المستخدم يغادر الجهاز - تعرضه الواجهة صراحة)" -ForegroundColor Yellow
    }
}

$ConfigMap | ConvertTo-Json |
    Set-Content -Path (Join-Path $Staging "govmind.config.json") -Encoding utf8

if ($Channel -eq "development") {
    Write-Host "    قناة: development — بناء تطوير غير موقّع" -ForegroundColor Yellow
}

Write-Step "نسخ التراخيص"
Copy-Item (Join-Path $Installer "licenses") (Join-Path $Staging "licenses") -Recurse -Force

# فحص أخير: لا يخرج أي اسم سرّ في حزمة التثبيت.
Write-Step "فحص الحزمة من الأسرار"
$Forbidden = @(
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWT_SECRET",
    "AZURE_STORAGE_CONNECTION_STRING",
    "DEVICE_HASH_PEPPER",
    "AccountKey="
)

# ⚠️ **ألفاظ لا مكان لها في منتج فردي.** المنتج حساب واحد واشتراك واحد
# وجهاز فعّال واحد؛ لا جهة ولا مسؤول نظام يراجعه العميل. وجود أيٍّ منها في
# واجهة مثبَّتة يعني أن نصًّا من المنتج القديم تسرّب إلى حزمة العميل.
$ForbiddenWords = @(
    [char]0x0645 + "سؤول النظام",
    [char]0x0645 + "سؤول الجهة",
    [char]0x062C + "هتك",
    [char]0x0628 + "ريد العمل"
)
$UiStagePath = Join-Path $Staging "ui"
if (Test-Path $UiStagePath) {
    foreach ($word in $ForbiddenWords) {
        $wordHits = Get-ChildItem $UiStagePath -Recurse -File |
            Select-String -Pattern $word -SimpleMatch -List -ErrorAction SilentlyContinue
        if ($wordHits) {
            throw "واجهة التثبيت تحتوي لفظًا من المنتج القديم: '$word' في $($wordHits[0].Path)"
        }
    }
}
foreach ($needle in $Forbidden) {
    $hits = Select-String -Path (Join-Path $Staging "*") -Pattern $needle `
        -SimpleMatch -List -ErrorAction SilentlyContinue
    if ($hits) {
        throw "⚠️ سرّ محتمل داخل حزمة التثبيت: $needle في $($hits.Path)"
    }
}
Write-Host "    لا أسرار في الحزمة ✔" -ForegroundColor Green

# ---------------------------------------------------------------------------
# ٥) المثبّت
# ---------------------------------------------------------------------------
Write-Step "بناء المثبّت بـInno Setup"
$Iscc = Get-Command "iscc" -ErrorAction SilentlyContinue
if ($Iscc) { $Iscc = $Iscc.Source }
if (-not $Iscc) {
    # ⚠️ **مسار المستخدم مشمول عمدًا.** `winget` بلا صلاحيات مسؤول يثبّت
    # Inno Setup تحت %LOCALAPPDATA%\Programs لا تحت Program Files، ولا يضيفه
    # إلى PATH. البحث في المسارين الأخيرين وحدهما يجعل البناء يفشل بـ«غير
    # مثبَّت» على جهاز مثبَّتة فيه فعلًا.
    foreach ($candidate in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )) {
        if (Test-Path $candidate) { $Iscc = $candidate; break }
    }
}
if (-not $Iscc) {
    throw @"
Inno Setup غير مثبَّت على هذا الجهاز.

ثبّته بأحد الأمرين ثم أعد تشغيل هذا السكربت:
  winget install --id JRSoftware.InnoSetup -e
  choco install innosetup -y

يُبحث عنه في:
  %ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
  %ProgramFiles%\Inno Setup 6\ISCC.exe
  %LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe   (تثبيت winget بلا صلاحيات)

كل الخطوات السابقة اكتملت، ومخرجاتها جاهزة في:
  $Staging
"@
}

& $Iscc "/Q" "/DChannel=$Channel" "/DControlPlaneUrl=$ControlPlaneUrl" `
    (Join-Path $Installer "govmind.iss")
if ($LASTEXITCODE -ne 0) { throw "فشل بناء المثبّت." }

Write-Step "اكتمل البناء"
Write-Host "المثبّت: $(Join-Path $Output 'GovMindSetup.exe')" -ForegroundColor Green
Write-Host ""
Write-Host "القناة: $Channel   |   عنوان الخدمة: $ControlPlaneUrl"
Write-Host ""
Write-Host "⚠️ هذا المثبّت غير موقّع. ويندوز سيعرض «ناشر غير معروف»." -ForegroundColor Yellow
Write-Host "   للإنتاج: وقّعه بشهادة Code Signing — انظر installer\README.md" -ForegroundColor Yellow
