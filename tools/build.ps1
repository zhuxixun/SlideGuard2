param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$uv = Join-Path $env:APPDATA "Python\Python313\Scripts\uv.exe"

if (-not (Test-Path -LiteralPath $uv)) {
    throw "uv.exe was not found"
}

Push-Location $projectRoot
try {
    $env:UV_CACHE_DIR = Join-Path $projectRoot ".uv-cache"
    & $uv run pyinstaller packaging/slideguard.spec --noconfirm --clean
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }

    $releaseRoot = Join-Path $projectRoot "dist\SlideGuard"
    $dataRoot = Join-Path $releaseRoot "data"
    New-Item -ItemType Directory -Force -Path `
        (Join-Path $dataRoot "config"), `
        (Join-Path $dataRoot "logs"), `
        (Join-Path $dataRoot "sessions"), `
        (Join-Path $dataRoot "temp") | Out-Null
    Copy-Item -LiteralPath `
        (Join-Path $projectRoot "data\config\sensitive-terms.txt") `
        -Destination (Join-Path $dataRoot "config\sensitive-terms.txt") `
        -Force
}
finally {
    Pop-Location
}

