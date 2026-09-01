<#
.SYNOPSIS
    ينزّل ثنائيات llama.cpp الرسمية إلى runtime\vendor\llama.cpp.

.DESCRIPTION
    من إصدارات ggml-org/llama.cpp على GitHub — **رخصة MIT وقابلة لإعادة
    التوزيع**، وهي ما يُحزَم في المثبّت.

    ⚠️ **لا تستعمل نسخة LM Studio** الموجودة في
    `%USERPROFILE%\.lmstudio\extensions\backends`. تلك بناءٌ خاص بـLM Studio
    مع مكتباتها (`llama-server-impl.dll` و `lmstudiocore.dll`)، وليست
    مرخّصة لإعادة التوزيع، ووجودها في منتجنا يناقض شرط «لا LM Studio».

    المخرجات في `.gitignore`: الثنائيات لا تُودَع في المستودع.

.PARAMETER Variant
    نوع البناء: cpu (الافتراضي) أو cuda-12.4 أو cuda-13.3.
    نبدأ بـcpu: يعمل على كل جهاز، والتسريع بالكرت خطوة لاحقة.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\fetch-llama.ps1
#>
[CmdletBinding()]
param(
    [ValidateSet("cpu", "cuda-12.4", "cuda-13.3")]
    [string]$Variant = "cpu",
    [string]$Tag = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Vendor   = Join-Path $RepoRoot "runtime\vendor\llama.cpp"
$Api      = "https://api.github.com/repos/ggml-org/llama.cpp/releases"

Write-Host "==> البحث عن إصدار فيه ثنائيات ويندوز x64" -ForegroundColor Cyan

$headers = @{ "User-Agent" = "GovMind-Build" }
$releases = Invoke-RestMethod -Uri "${Api}?per_page=10" -Headers $headers

$pattern = "bin-win-$Variant-x64"
$release = $null
foreach ($candidate in $releases) {
    if ($Tag -and $candidate.tag_name -ne $Tag) { continue }
    if ($candidate.assets | Where-Object { $_.name -like "*$pattern*" }) {
        $release = $candidate
        break
    }
}
if (-not $release) { throw "لم يُعثر على إصدار فيه '$pattern'." }

$asset = $release.assets | Where-Object { $_.name -like "*$pattern*" } | Select-Object -First 1
Write-Host "    الإصدار: $($release.tag_name)"
Write-Host "    الملف  : $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) م.ب)"

$temp = Join-Path $env:TEMP $asset.name
Write-Host "==> التنزيل" -ForegroundColor Cyan
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $temp -Headers $headers

Write-Host "==> فكّ الضغط إلى $Vendor" -ForegroundColor Cyan
if (Test-Path $Vendor) { Remove-Item $Vendor -Recurse -Force }
New-Item -ItemType Directory -Path $Vendor -Force | Out-Null
Expand-Archive -Path $temp -DestinationPath $Vendor -Force
Remove-Item $temp -Force

# بعض الإصدارات تضع الملفات داخل مجلد فرعي — تُرفع إلى الجذر.
$nested = Get-ChildItem $Vendor -Directory
if ($nested.Count -eq 1 -and -not (Test-Path (Join-Path $Vendor "llama-server.exe"))) {
    Get-ChildItem $nested[0].FullName | Move-Item -Destination $Vendor -Force
    Remove-Item $nested[0].FullName -Recurse -Force
}

$server = Join-Path $Vendor "llama-server.exe"
if (-not (Test-Path $server)) { throw "لم يوجد llama-server.exe بعد فكّ الضغط." }

"$($release.tag_name)`n$($asset.name)`n" |
    Set-Content -Path (Join-Path $Vendor "VERSION.txt") -Encoding utf8

Write-Host ""
Write-Host "جاهز: $server" -ForegroundColor Green
& $server --version
Write-Host ""
Write-Host "⚠️ رخصة MIT — انسخ نصّها إلى installer\licenses قبل التوزيع." -ForegroundColor Yellow
