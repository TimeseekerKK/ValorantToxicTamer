param([string]$InnoCompiler = $env:INNO_SETUP_COMPILER, [switch]$SkipInstaller)
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
    if (-not $SkipInstaller) {
        if (-not $InnoCompiler) {
            $InnoCompiler = @(
                (Join-Path $projectRoot '.tools\InnoSetup6\ISCC.exe'),
                "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                "$env:ProgramFiles\Inno Setup 7\ISCC.exe"
            ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        }
        if (-not $InnoCompiler) {
            throw '未找到 Inno Setup 编译器，请安装 Inno Setup 6.7.4+ 并设置 INNO_SETUP_COMPILER。仅构建免安装版可使用 -SkipInstaller。'
        }
        & $InnoCompiler "/DAppVersion=$($appVersion.Trim())" "/DAppExe=$outputPath" (Join-Path $projectRoot 'installer\ValorantToxicTamer.iss')
        if ($LASTEXITCODE -ne 0) { throw '安装包编译失败。' }
        Copy-Item -LiteralPath $outputPath -Destination (Join-Path $projectRoot 'dist\ValorantToxicTamer.exe') -Force
        Write-Host "安装包完成：dist\ValorantToxicTamer-Setup-v$($appVersion.Trim()).exe"
    }
} finally {
    $env:PATH = $originalPath
    Pop-Location
}
