; SysMonitor installer. Build with build.ps1 (passes /DAppVersion).
; Asks for admin once: installs PawnIO (downloaded, pinned SHA-256) when missing,
; copies the portable LibreHardwareMonitor + logon task when no LHM is present,
; and installs SysMonitor, which itself runs without elevation.
#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z (build.ps1 does it)
#endif
#define PawnIOUrl "https://github.com/namazso/PawnIO.Setup/releases/download/2.2.0/PawnIO_setup.exe"
#define PawnIOSha256 "1f519a22e47187f70a1379a48ca604981c4fcf694f4e65b734aaa74a9fba3032"

[Setup]
AppId={{B9BAAD01-C950-4857-A03B-47BD6FA9B2F1}
AppName=SysMonitor
AppVersion={#AppVersion}
AppVerName=SysMonitor {#AppVersion}
AppPublisher=Mateus
DefaultDirName={commonpf64}\SysMonitor
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=SysMonitor-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
InfoBeforeFile=LEIA-ME.txt
UninstallDisplayName=SysMonitor
UninstallDisplayIcon={app}\app\SysMonitor.exe
UsedUserAreasWarning=no
CloseApplications=no

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "iniciarwidget"; Description: "Iniciar o widget com o Windows"; GroupDescription: "Inicialização:"
Name: "iniciarbandeja"; Description: "Iniciar a bandeja com o Windows"; GroupDescription: "Inicialização:"; Flags: unchecked
Name: "atalhodesktop"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[InstallDelete]
; Startup shortcuts follow the current choice on every install/update.
Type: files; Name: "{userstartup}\SysMonitor.lnk"
Type: files; Name: "{userstartup}\SysMonitor Bandeja.lnk"

[Files]
Source: "..\build\pyinstaller\dist\SysMonitor\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\build\lhm\*"; DestDir: "{app}\LibreHardwareMonitor"; Flags: recursesubdirs createallsubdirs ignoreversion; Check: DeveCopiarLhm
Source: "LibreHardwareMonitor.config"; DestDir: "{app}\LibreHardwareMonitor"; Flags: onlyifdoesntexist; Check: DeveCopiarLhm
Source: "util-instalador.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "tarefa-lhm.xml"; DestDir: "{app}"; Flags: ignoreversion
Source: "LEIA-ME.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\SysMonitor"; Filename: "{app}\app\SysMonitor.exe"; WorkingDir: "{app}\app"; Flags: runminimized
Name: "{autoprograms}\SysMonitor (bandeja)"; Filename: "{app}\app\SysMonitor-Bandeja.exe"; WorkingDir: "{app}\app"; Flags: runminimized
Name: "{autodesktop}\SysMonitor"; Filename: "{app}\app\SysMonitor.exe"; WorkingDir: "{app}\app"; Flags: runminimized; Tasks: atalhodesktop
Name: "{userstartup}\SysMonitor"; Filename: "{app}\app\SysMonitor.exe"; WorkingDir: "{app}\app"; Flags: runminimized; Tasks: iniciarwidget
Name: "{userstartup}\SysMonitor Bandeja"; Filename: "{app}\app\SysMonitor-Bandeja.exe"; WorkingDir: "{app}\app"; Flags: runminimized; Tasks: iniciarbandeja

[Run]
Filename: "{app}\app\SysMonitor.exe"; WorkingDir: "{app}\app"; Description: "Abrir o SysMonitor agora"; Flags: postinstall nowait runasoriginaluser runminimized skipifsilent

[Code]
const
  RegKey = 'Software\SysMonitor';
  LhmTask = 'SysMonitor LHM';
  PawnIOReleases = 'https://github.com/namazso/PawnIO.Setup/releases';

var
  DownloadPage: TDownloadWizardPage;
  PrevInstalledLhm, PrevInstalledPawnIO: Boolean;
  PawnIOExistente, CopiarLhm: Boolean;
  PawnIOBaixado, PawnIOInstalado, PawnIOReiniciar: Boolean;
  RemoverConfig, RemoverPawnIO, UninstLhm, UninstTarefa: Boolean;
  Avisos: String;

function LerFlag(Nome: String): Boolean;
var
  V: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM64, RegKey, Nome, V) and (V = 1);
end;

function BoolDW(B: Boolean): Cardinal;
begin
  if B then Result := 1 else Result := 0;
end;

procedure Avisar(Texto: String);
begin
  Log('Aviso: ' + Texto);
  Avisos := Avisos + #13#10#13#10 + Texto;
end;

function Sys(Exe: String): String;
begin
  Result := ExpandConstant('{sys}\') + Exe;
end;

function RodarOculto(Exe, Params: String): Integer;
var
  Rc: Integer;
begin
  if not Exec(Exe, Params, '', SW_HIDE, ewWaitUntilTerminated, Rc) then
    Rc := -1;
  Log(Format('%s %s -> %d', [Exe, Params, Rc]));
  Result := Rc;
end;

function RodarUtil(Pasta, Args: String): Integer;
begin
  Result := RodarOculto(Sys('WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + Pasta + '\util-instalador.ps1" ' + Args);
end;

function TarefaExiste(Nome: String): Boolean;
begin
  Result := RodarOculto(Sys('schtasks.exe'), '/query /tn "' + Nome + '"') = 0;
end;

function LhmRespondendo: Boolean;
var
  Http: Variant;
begin
  Result := False;
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.SetTimeouts(1000, 1000, 1000, 1000);
    Http.Open('GET', 'http://127.0.0.1:8085/data.json', False);
    Http.Send('');
    Result := Http.Status = 200;
  except
    Result := False;
  end;
end;

function PawnIOJaInstalado: Boolean;
begin
  Result := RegKeyExists(HKLM64, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO')
    or RegKeyExists(HKLM64, 'SYSTEM\CurrentControlSet\Services\PawnIO');
end;

function InitializeSetup: Boolean;
begin
  PrevInstalledLhm := LerFlag('InstalledLHM');
  PrevInstalledPawnIO := LerFlag('InstalledPawnIO');
  PawnIOExistente := PawnIOJaInstalado;
  { An LHM we installed earlier is ours to update even though it answers on 8085. }
  if PrevInstalledLhm then
    CopiarLhm := True
  else
    CopiarLhm := not (LhmRespondendo or TarefaExiste('\LibreHardwareMonitor'));
  Log(Format('PawnIO existente=%d, copiar LHM=%d', [BoolDW(PawnIOExistente), BoolDW(CopiarLhm)]));
  Result := True;
end;

function DeveCopiarLhm: Boolean;
begin
  Result := CopiarLhm;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing),
    'Baixando o PawnIO (driver usado para ler a temperatura da CPU)...', nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and (not PawnIOExistente) then begin
    DownloadPage.Clear;
    DownloadPage.Add('{#PawnIOUrl}', 'PawnIO_setup.exe', '{#PawnIOSha256}');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
        PawnIOBaixado := True;
      except
        PawnIOBaixado := False;
        Log('PawnIO: download falhou: ' + GetExceptionMessage);
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

procedure InstalarPawnIO;
var
  Rc: Integer;
begin
  if PawnIOExistente then exit;
  if not PawnIOBaixado then begin
    Avisar('Não consegui baixar o PawnIO. A temperatura da CPU ficará vazia até você instalá-lo: ' + PawnIOReleases);
    exit;
  end;
  WizardForm.StatusLabel.Caption := 'Instalando o PawnIO...';
  Rc := RodarOculto(ExpandConstant('{tmp}\PawnIO_setup.exe'), '-install -silent');
  if Rc = 0 then
    PawnIOInstalado := True
  else if (Rc = 3010) or (Rc = 1641) then begin
    PawnIOInstalado := True;
    PawnIOReiniciar := True;
  end else
    Avisar(Format('A instalação do PawnIO falhou (código %d). A temperatura da CPU ficará vazia até instalá-lo: %s', [Rc, PawnIOReleases]));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  CriouTarefa: Boolean;
begin
  if CurStep = ssInstall then begin
    RodarOculto(Sys('taskkill.exe'), '/F /IM SysMonitor.exe');
    RodarOculto(Sys('taskkill.exe'), '/F /IM SysMonitor-Bandeja.exe');
    if PrevInstalledLhm then begin
      ExtractTemporaryFile('util-instalador.ps1');
      RodarUtil(ExpandConstant('{tmp}'), '-Acao PararLhm -LhmDir "' + ExpandConstant('{app}\LibreHardwareMonitor') + '"');
    end;
    InstalarPawnIO;
  end;
  if CurStep = ssPostInstall then begin
    CriouTarefa := False;
    if CopiarLhm then begin
      if RodarUtil(ExpandConstant('{app}'), '-Acao CriarTarefa -LhmDir "' + ExpandConstant('{app}\LibreHardwareMonitor') + '"') = 0 then begin
        CriouTarefa := True;
        RodarOculto(Sys('schtasks.exe'), '/run /tn "' + LhmTask + '"');
      end else
        Avisar('Não consegui criar a tarefa que abre o LibreHardwareMonitor no logon. Use "Abrir LibreHardwareMonitor" no menu do widget.');
    end;
    RegWriteStringValue(HKLM64, RegKey, 'Version', '{#AppVersion}');
    RegWriteDWordValue(HKLM64, RegKey, 'InstalledLHM', BoolDW(CopiarLhm));
    RegWriteDWordValue(HKLM64, RegKey, 'InstalledPawnIO', BoolDW(PrevInstalledPawnIO or PawnIOInstalado));
    RegWriteDWordValue(HKLM64, RegKey, 'CreatedTask', BoolDW(CopiarLhm and (CriouTarefa or TarefaExiste(LhmTask))));
  end;
end;

function NeedRestart: Boolean;
begin
  Result := PawnIOReiniciar;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and (Avisos <> '') then
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + Avisos;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  App: String;
begin
  App := ExpandConstant('{app}');
  if CurUninstallStep = usUninstall then begin
    UninstLhm := LerFlag('InstalledLHM');
    UninstTarefa := LerFlag('CreatedTask');
    RodarOculto(Sys('taskkill.exe'), '/F /IM SysMonitor.exe');
    RodarOculto(Sys('taskkill.exe'), '/F /IM SysMonitor-Bandeja.exe');
    if UninstLhm then
      RodarUtil(App, '-Acao PararLhm -LhmDir "' + App + '\LibreHardwareMonitor"');
    if UninstTarefa then
      RodarOculto(Sys('schtasks.exe'), '/delete /tn "' + LhmTask + '" /f');
    RemoverConfig := SuppressibleMsgBox('Remover também as configurações do SysMonitor (%APPDATA%\SysMonitor)?',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
    if LerFlag('InstalledPawnIO') then
      RemoverPawnIO := SuppressibleMsgBox('Remover também o PawnIO (driver da temperatura da CPU)? Outros programas, como o LibreHardwareMonitor, podem usá-lo.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
  end;
  if CurUninstallStep = usPostUninstall then begin
    if RemoverConfig then
      DelTree(ExpandConstant('{userappdata}\SysMonitor'), True, True, True);
    if RemoverPawnIO then
      RodarOculto(ExpandConstant('{commonpf64}\PawnIO\uninstall.exe'), '-uninstall -silent');
    { LHM writes its own files (config, logs) that Inno did not install. }
    if CompareText(ExtractFileName(App), 'SysMonitor') = 0 then
      DelTree(App, True, True, True);
    RegDeleteKeyIncludingSubkeys(HKLM64, RegKey);
  end;
end;
