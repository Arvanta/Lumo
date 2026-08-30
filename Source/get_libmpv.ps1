# ============================================================================
#  get_libmpv.ps1  —  automatically download libmpv-2.dll (the mpv engine)
#
#  Downloads the latest "mpv-dev-x86_64" build from GitHub, extracts it with
#  the built-in Windows `tar` (bsdtar handles .7z) and copies libmpv-2.dll
#  into this folder, next to main.py.
#
#  Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File get_libmpv.ps1
#          (or simply double-click get_libmpv.bat)
# ============================================================================

$proj   = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $proj "libmpv-2.dll"

if (Test-Path $target) {
    Write-Host "libmpv-2.dll already exists:" -ForegroundColor Green
    Write-Host "  $target"
    exit 0
}

# detect Python bitness so we fetch a matching build
$pyBits = ""
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    $out = & python -c "import struct;print(struct.calcsize('P')*8)" 2>$null
    $pyBits = ($out | Out-String).Trim()
}
if ($pyBits -eq "32") {
    Write-Host "You are using 32-bit Python." -ForegroundColor Yellow
    Write-Host "The GitHub mpv builds are 64-bit only, so this script can't help." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Download the 32-bit (i686) dev build instead:" -ForegroundColor Yellow
    Write-Host "  https://sourceforge.net/projects/mpv-player-windows/files/libmpv/" -ForegroundColor Yellow
    Write-Host "  -> choose a file starting with  mpv-dev-i686-" -ForegroundColor Yellow
    Write-Host "Extract it and copy libmpv-2.dll next to main.py." -ForegroundColor Yellow
    exit 1
}
if ($pyBits -and $pyBits -ne "64") {
    Write-Host "Note: could not confirm Python bitness ('$pyBits'), assuming 64-bit." -ForegroundColor DarkGray
}

Write-Host "Looking up the latest libmpv dev build on GitHub..." -ForegroundColor Cyan

try {
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/zhongfly/mpv-winbuild/releases/latest" `
                             -Headers @{ "User-Agent" = "mpv-player-get-libmpv" }
} catch {
    Write-Host "Could not reach GitHub API: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Manual download options:" -ForegroundColor Yellow
    Write-Host "  1) https://sourceforge.net/projects/mpv-player-windows/files/libmpv/"
    Write-Host "     -> download the file starting with  mpv-dev-x86_64-  (NOT mpv-x86_64-)"
    Write-Host "  2) https://github.com/zhongfly/mpv-winbuild/releases/latest"
    Write-Host "     -> download  mpv-dev-x86_64-*.7z"
    Write-Host "Then extract it and copy  libmpv-2.dll  into this folder."
    exit 1
}

# prefer the plain x86_64 (max CPU compatibility), non-v3, non-lgpl build
$asset = $rel.assets | Where-Object {
    $_.name -like "mpv-dev-x86_64-*.7z" -and
    $_.name -notlike "*v3*"     -and
    $_.name -notlike "*lgpl*"
} | Select-Object -First 1

if (-not $asset) {
    $asset = $rel.assets | Where-Object { $_.name -like "mpv-dev-x86_64-*.7z" } | Select-Object -First 1
}

if (-not $asset) {
    Write-Host "No mpv-dev-x86_64 asset found in the latest release." -ForegroundColor Red
    exit 1
}

Write-Host "Downloading $($asset.name) ($([math]::Round($asset.size/1MB,1)) MB)..." -ForegroundColor Cyan

$tmp = Join-Path $env:TEMP ("mpv-dev-" + [guid]::NewGuid().ToString("N") + ".7z")
$extract = Join-Path $env:TEMP "mpv-dev-extract"

try {
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tmp
} catch {
    Write-Host "Download failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
New-Item -ItemType Directory -Path $extract | Out-Null

Write-Host "Extracting..." -ForegroundColor Cyan

$ok = $false
& tar -xf $tmp -C $extract 2>$null
if ($LASTEXITCODE -eq 0) { $ok = $true }
else {
    $seven = Get-Command 7z -ErrorAction SilentlyContinue
    if ($seven) {
        & $seven.Source x $tmp "-o$extract" -y | Out-Null
        if ($LASTEXITCODE -eq 0) { $ok = $true }
    }
}

Remove-Item $tmp -Force -ErrorAction SilentlyContinue

if (-not $ok) {
    Write-Host "Extraction failed. Please extract the archive manually with 7-Zip and" -ForegroundColor Red
    Write-Host "copy libmpv-2.dll into this folder." -ForegroundColor Red
    exit 1
}

$dll = Get-ChildItem -Path $extract -Recurse -Filter "libmpv-2.dll" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $dll) {
    Write-Host "libmpv-2.dll was not found inside the archive." -ForegroundColor Red
    exit 1
}

Copy-Item $dll.FullName $target -Force
Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done! libmpv-2.dll was copied to:" -ForegroundColor Green
Write-Host "  $target"
