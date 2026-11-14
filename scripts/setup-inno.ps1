param([string]$Directory = (Join-Path (Split-Path -Parent $PSScriptRoot) '.tools\InnoSetup6'))
$ErrorActionPreference = 'Stop'
$compiler = Join-Path $Directory 'ISCC.exe'
if (Test-Path -LiteralPath $compiler) { Write-Output $compiler; exit 0 }
$download = Join-Path ([IO.Path]::GetTempPath()) ('vtt-inno-' + [Guid]::NewGuid().ToString('N') + '.exe')
try {
    Invoke-WebRequest -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe' -OutFile $download
    $signature = Get-AuthenticodeSignature -LiteralPath $download
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*O=Pyrsys B.V.*') {
        throw 'Inno Setup 安装程序签名无效，已停止。'
    }
    $process = Start-Process -FilePath $download -ArgumentList @('/CURRENTUSER','/VERYSILENT',
        '/SUPPRESSMSGBOXES','/NORESTART','/NOICONS',('/DIR="' + $Directory + '"')) -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $compiler)) { throw 'Inno Setup 编译器安装失败。' }
    Write-Output $compiler
} finally {
    Remove-Item -LiteralPath $download -Force -ErrorAction SilentlyContinue
}
