param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($null -ne $uvCommand) {
    $uv = $uvCommand.Source
}
else {
    $legacyUv = Join-Path $env:APPDATA "Python\Python313\Scripts\uv.exe"
    if (-not (Test-Path -LiteralPath $legacyUv)) {
        throw "uv.exe was not found. Install uv and make sure the 'uv' command is available in PATH."
    }
    $uv = $legacyUv
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

    $archivePath = Join-Path $projectRoot "dist\SlideGuard.zip"
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
    Compress-Archive -Path (Join-Path $releaseRoot "*") -DestinationPath $archivePath -CompressionLevel Optimal

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        $entryNames = $archive.Entries.FullName -replace '\\', '/'
        foreach ($required in @("SlideGuard.exe", "data/config/sensitive-terms.txt")) {
            if ($required -notin $entryNames) {
                throw "Release archive is missing $required"
            }
        }
    }
    finally {
        $archive.Dispose()
    }
}
finally {
    Pop-Location
}
