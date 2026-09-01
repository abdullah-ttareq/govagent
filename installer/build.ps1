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

    # مفسّر بايثون الذي يحمل PyInstaller. **لا يُفترض أن `python` على
    # المسار هو الصحيح**: كثير من أجهزة التطوير فيها أكثر من نسخة، وواحدة
    # منها فقط فيها تبعيات الـRuntime.
    [string]$PythonExe = "python"
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
        # `GOVMIND_DESKTOP` يفعّل `output: export`، و`NEXT_PUBLIC_...`
        # يجعل الواجهة تنادي الأصل نفسه بلا أي عنوان مكتوب.
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
    Copy-Item $UiOut (Join-Path $Staging "ui") -Recurse -Force
}

# ---------------------------------------------------------------------------
# ٢) GovMind Runtime — ملف تنفيذي واحد
# ---------------------------------------------------------------------------
if (-not $SkipRuntime) {
    Write-Step "بناء GovMind Runtime بـPyInstaller"
    Require-Command $PythonExe "ثبّت Python 3.12+ ثم: pip install -r runtime\requirements.txt"

    Push-Location $RuntimeDir
    try {
        & $PythonExe -m PyInstaller --noconfirm --clean govmind-runtime.spec
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
@{ control_plane_url = $ControlPlaneUrl } |
    ConvertTo-Json |
    Set-Content -Path (Join-Path $Staging "govmind.config.json") -Encoding utf8

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
if (-not $Iscc) {
    foreach ($candidate in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
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

كل الخطوات السابقة اكتملت، ومخرجاتها جاهزة في:
  $Staging
"@
}

& $Iscc "/Q" (Join-Path $Installer "govmind.iss")
if ($LASTEXITCODE -ne 0) { throw "فشل بناء المثبّت." }

Write-Step "اكتمل البناء"
Write-Host "المثبّت: $(Join-Path $Output 'GovMindSetup.exe')" -ForegroundColor Green
Write-Host ""
Write-Host "⚠️ هذا المثبّت غير موقّع. ويندوز سيعرض «ناشر غير معروف»." -ForegroundColor Yellow
Write-Host "   للإنتاج: وقّعه بشهادة Code Signing — انظر installer\README.md" -ForegroundColor Yellow
