param([Parameter(Mandatory = $true)][string]$Manifest)
$ErrorActionPreference = 'Stop'
$update = $null
$staged = $null
try {
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
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'ready'), 'ready')
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while (-not [IO.File]::Exists((Join-Path $PSScriptRoot 'proceed'))) {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Update handoff timed out.' }
        Start-Sleep -Milliseconds 100
    }
    # Wait for normal shutdown, including the one-file bootloader. Never kill it.
    do {
        $running = $false
        foreach ($candidate in [Diagnostics.Process]::GetProcessesByName([IO.Path]::GetFileNameWithoutExtension($target))) {
            try {
                if ($candidate.MainModule.FileName -eq $target) { $running = $true }
            } catch [InvalidOperationException] {
                # The process exited while its path was being read.
            } finally { $candidate.Dispose() }
        }
        if (-not $running) { break }
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Please close the running application and retry.' }
        Start-Sleep -Milliseconds 250
    } while ($true)
    $installDir = [IO.Path]::GetDirectoryName($target)
    $parameters = @(
        ('/DIR="' + $installDir + '"'),
        ('/DATASOURCE="' + (Join-Path $installDir 'data') + '"'),
        ('/LOG="' + (Join-Path $PSScriptRoot 'setup.log') + '"'),
        '/NORESTART'
    )
    # The interactive installation wizard is intentional.
    $installer = Start-Process -FilePath $staged -ArgumentList $parameters -WorkingDirectory $PSScriptRoot -WindowStyle Normal -PassThru
    # Wait for the installer itself, not the application launched at Finish.
    $installer.WaitForExit()
    if ($installer.ExitCode -eq 2) {
        Start-Process -FilePath $target -WorkingDirectory $installDir -WindowStyle Hidden
    } elseif ($installer.ExitCode -ne 0) {
        throw "Installer failed with exit code $($installer.ExitCode). See setup.log."
    }
} catch {
    $message = $_.Exception.Message
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'error.txt'), $message)
    if ([IO.File]::Exists((Join-Path $PSScriptRoot 'proceed'))) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show("Update was not completed.`n$message`nLog: $PSScriptRoot", 'ValorantToxicTamer') | Out-Null
    }
} finally {
    if ($staged -and [IO.File]::Exists($staged)) {
        Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue
    }
    foreach ($name in @('ready', 'proceed', 'update.json', 'install.ps1')) {
        Remove-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Force -ErrorAction SilentlyContinue
    }
    if (-not [IO.File]::Exists((Join-Path $PSScriptRoot 'error.txt')) -and
        -not [IO.File]::Exists((Join-Path $PSScriptRoot 'setup.log'))) {
        Remove-Item -LiteralPath $PSScriptRoot -ErrorAction SilentlyContinue
    }
}
