# Builds dist\SysMonitor-Setup-<version>.exe. Tools: py -3.12 and Inno Setup 6 (winget).
#   .\build.ps1             full build
#   .\build.ps1 -SomenteExe stop after the PyInstaller exes and their --verificar
param([switch]$SomenteExe)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$raiz = $PSScriptRoot

function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

$versao = (Select-String -Path "$raiz\version.py" -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "SysMonitor $versao"

# 1. venv + PyInstaller
$venv = Join-Path $raiz '.venv-build'
$py = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $py)) { & py -3.12 -m venv $venv; Check 'venv' }
& $py -m pip install --disable-pip-version-check -q -r "$raiz\requirements-build.txt"; Check 'pip install'
& $py -c "import comtypes.client as c; c.GetModule('UIAutomationCore.dll')"; Check 'comtypes UIA'
& $py -m PyInstaller --noconfirm --clean --distpath "$raiz\build\pyinstaller\dist" `
    --workpath "$raiz\build\pyinstaller\work" "$raiz\SysMonitor.spec"; Check 'PyInstaller'

# 2. --verificar on both exes
$dist = "$raiz\build\pyinstaller\dist\SysMonitor"
foreach ($exe in 'SysMonitor.exe', 'SysMonitor-Bandeja.exe') {
    $saida = & "$dist\$exe" --verificar 2>&1 | Out-String
    Write-Host $saida
    if ($LASTEXITCODE -ne 0 -or $saida -notmatch "SysMonitor $([regex]::Escape($versao))") {
        throw "$exe --verificar failed"
    }
}
if ($SomenteExe) { return }
