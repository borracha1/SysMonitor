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

# 3. LibreHardwareMonitor 0.9.6 (official release, pinned SHA-256)
$LhmUrl = 'https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.6/LibreHardwareMonitor.zip'
$LhmSha256 = '086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001'
$lhmZip = "$raiz\build\cache\LibreHardwareMonitor-0.9.6.zip"
if (-not (Test-Path $lhmZip)) {
    New-Item -ItemType Directory -Force (Split-Path $lhmZip) | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $LhmUrl -OutFile $lhmZip
}
$hash = (Get-FileHash $lhmZip -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $LhmSha256) { Remove-Item $lhmZip; throw "LHM SHA-256 mismatch: $hash" }
$lhmDir = "$raiz\build\lhm"
if (Test-Path $lhmDir) { Remove-Item -Recurse -Force $lhmDir }
Expand-Archive -Path $lhmZip -DestinationPath $lhmDir
if (-not (Test-Path "$lhmDir\LibreHardwareMonitor.exe")) { throw 'LibreHardwareMonitor.exe missing from zip' }

# 4. Inno Setup
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 not found: winget install -e --id JRSoftware.InnoSetup' }
& $iscc "/DAppVersion=$versao" "$raiz\installer\SysMonitor.iss"; Check 'ISCC'
Write-Host "OK: $raiz\dist\SysMonitor-Setup-$versao.exe"
