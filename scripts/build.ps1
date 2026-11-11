$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '请先按 README 创建 Python 3.11 .venv 并安装 requirements-build.txt。'
}
Push-Location $projectRoot
$originalPath = $env:PATH
try {
    # Prevent unrelated tools on PATH from supplying incompatible ICU/UCRT DLLs.
    $env:PATH = @(
        (Split-Path -Parent $pythonPath),
        (Join-Path $env:SystemRoot 'System32'),
        $env:SystemRoot
    ) -join ';'
    $appVersion = & $pythonPath -B -c "from valorant_toxic_tamer.app_version import VERSION; print(VERSION)"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($appVersion)) {
        throw '读取应用版本失败。'
    }
    $appName = "ValorantToxicTamer-v$($appVersion.Trim())"
    $outputPath = Join-Path $projectRoot "dist\$appName.exe"
    $updateHelper = Join-Path $projectRoot 'valorant_toxic_tamer\update_install.ps1'
    $appIcon = Join-Path $projectRoot 'valorant_toxic_tamer\assets\app.ico'
    $entryPoint = Join-Path $projectRoot 'main.py'
    & $pythonPath -m PyInstaller --clean --noconfirm --onefile --windowed --specpath build --icon $appIcon --add-data "${appIcon};valorant_toxic_tamer/assets" --add-data "${updateHelper};valorant_toxic_tamer" --name $appName $entryPoint
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 打包失败。' }
    & $pythonPath tests/check_package.py $outputPath
    if ($LASTEXITCODE -ne 0) { throw '打包依赖检查失败，不能分发此 EXE。' }
    Write-Host "打包完成：$outputPath"
} finally {
    $env:PATH = $originalPath
    Pop-Location
}
