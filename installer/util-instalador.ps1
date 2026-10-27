# Helper for SysMonitor's Inno Setup installer (runs elevated).
#   -Acao CriarTarefa : registers the "SysMonitor LHM" logon task from tarefa-lhm.xml
#                       (-SomenteGerar <file> only writes the XML, for tests)
#   -Acao PararLhm    : stops LibreHardwareMonitor.exe only if it runs from -LhmDir
param(
    [Parameter(Mandatory = $true)][ValidateSet('CriarTarefa', 'PararLhm')][string]$Acao,
    [Parameter(Mandatory = $true)][string]$LhmDir,
    [string]$UserId,
    [string]$SomenteGerar
)
$ErrorActionPreference = 'Stop'
$NomeTarefa = 'SysMonitor LHM'
$LhmDir = $LhmDir.TrimEnd('\')
$exe = Join-Path $LhmDir 'LibreHardwareMonitor.exe'

if ($Acao -eq 'CriarTarefa') {
    if (-not $UserId) { $UserId = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value }
    $modelo = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'tarefa-lhm.xml'), [Text.Encoding]::UTF8)
    $xml = $modelo.Replace('{{USER_ID}}', [Security.SecurityElement]::Escape($UserId))
    $xml = $xml.Replace('{{LHM_EXE}}', [Security.SecurityElement]::Escape($exe))
    $xml = $xml.Replace('{{LHM_DIR}}', [Security.SecurityElement]::Escape($LhmDir))
    if ($SomenteGerar) {
        [IO.File]::WriteAllText($SomenteGerar, $xml, (New-Object Text.UTF8Encoding $false))
        exit 0
    }
    Register-ScheduledTask -TaskName $NomeTarefa -Xml $xml -Force | Out-Null
    exit 0
}

if ($Acao -eq 'PararLhm') {
    Get-Process -Name 'LibreHardwareMonitor' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and ($_.Path -ieq $exe) } |
        Stop-Process -Force
    exit 0
}
