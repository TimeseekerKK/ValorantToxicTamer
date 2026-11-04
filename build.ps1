$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '请先按 README 创建 Python 3.11 .venv 并安装 requirements-build.txt。'
}
Push-Location $PSScriptRoot
$originalPath = $env:PATH
try {
    # Prevent unrelated tools on PATH from supplying incompatible ICU/UCRT DLLs.
    $env:PATH = @(
        (Split-Path -Parent $pythonPath),
        (Join-Path $env:SystemRoot 'System32'),
        $env:SystemRoot
    ) -join ';'
    & $pythonPath -m PyInstaller --clean --onefile --windowed --add-data 'update_install.ps1;.' --name ValorantToxicTamer main.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 打包失败。' }
    & $pythonPath tests/check_package.py dist/ValorantToxicTamer.exe
    if ($LASTEXITCODE -ne 0) { throw '打包依赖检查失败，不能分发此 EXE。' }
} finally {
    $env:PATH = $originalPath
    Pop-Location
}
