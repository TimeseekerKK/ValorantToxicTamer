param([Parameter(Mandatory = $true)][string]$Manifest)
$ErrorActionPreference = 'Stop'
$update = $null
$replaced = $false
$backup = $null
try {
    # A caller launched from PowerShell 7 may pass its module search path to
    # Windows PowerShell 5.1. Load the matching system utility module explicitly.
    Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -Force
    $update = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
    $target = [IO.Path]::GetFullPath($update.target)
    $staged = [IO.Path]::GetFullPath($update.staged)
    if ([IO.Path]::GetDirectoryName($target) -ne [IO.Path]::GetDirectoryName($staged) -or
        $target -eq $staged -or -not [IO.File]::Exists($target)) {
        throw 'Invalid update paths.'
    }
    if ((Get-FileHash -LiteralPath $staged -Algorithm SHA256).Hash -ne $update.sha256) {
        throw 'Update checksum mismatch.'
    }
    $backup = $staged + '.bak'
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'ready'), 'ready')
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    while (-not [IO.File]::Exists((Join-Path $PSScriptRoot 'proceed'))) {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Update handoff timed out.' }
        Start-Sleep -Milliseconds 100
    }
    # Give Qt time to release held keys, hotkeys and its single-instance lock.
    Wait-Process -Id $update.pid -Timeout 5 -ErrorAction SilentlyContinue
    # A one-file build also has a bootloader process. Match the full EXE path;
    # never terminate by image name or touch the game or another installation.
    $running = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $target })
    foreach ($item in $running) {
        Stop-Process -Id $item.ProcessId -Force -ErrorAction SilentlyContinue
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while (-not $replaced) {
        try {
            [IO.File]::Replace($staged, $target, $backup)
            $replaced = $true
        } catch {
            if ([DateTime]::UtcNow -gt $deadline) { throw }
            Start-Sleep -Milliseconds 250
        }
    }
    Start-Process -FilePath $target -WorkingDirectory ([IO.Path]::GetDirectoryName($target)) -WindowStyle Hidden
    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
} catch {
    $message = $_.Exception.Message
    if ($replaced -and [IO.File]::Exists($backup)) {
        try {
            [IO.File]::Replace($backup, $target, $null)
            Start-Process -FilePath $target -WorkingDirectory ([IO.Path]::GetDirectoryName($target)) -WindowStyle Hidden
        } catch { $message += "`nRollback failed: " + $_.Exception.Message }
    }
    $logPath = Join-Path $PSScriptRoot 'error.txt'
    [IO.File]::WriteAllText($logPath, $message)
    if ([IO.File]::Exists((Join-Path $PSScriptRoot 'proceed'))) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show("Update failed. The original EXE was kept or restored.`n$message`nLog: $logPath", 'ValorantToxicTamer') | Out-Null
    }
} finally {
    if ($update -and $staged -and [IO.File]::Exists($staged)) {
        Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue
    }
    # Delete only known helper files; retain the error log for diagnosis.
    foreach ($name in @('ready', 'proceed', 'update.json', 'install.ps1')) {
        Remove-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Force -ErrorAction SilentlyContinue
    }
    if (-not [IO.File]::Exists((Join-Path $PSScriptRoot 'error.txt'))) {
        Remove-Item -LiteralPath $PSScriptRoot -ErrorAction SilentlyContinue
    }
}
