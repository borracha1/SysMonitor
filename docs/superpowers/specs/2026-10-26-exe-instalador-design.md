# SysMonitor 1.0.0: exe e instalador único com LibreHardwareMonitor e PawnIO

Data: 2026-10-26 · Status: desenho aprovado em conversa, aguardando revisão desta spec
Registro do pedido: `D:/dev/memoria-compartilhada/pedidos/2026-10-26-claude-sysmonitor-exe-instalador.md`

## Objetivo

Um `SysMonitor-Setup-1.0.0.exe` que o Mateus passa para amigos e conhecidos. Num Windows sem
Python, LHM ou PawnIO, ele deixa o widget funcionando com temperatura da CPU, pedindo admin
uma única vez (na instalação). O SysMonitor continua rodando sem elevação.

Público: amigos e conhecidos (não é distribuição pública). Por isso o LHM vai embutido (MPL-2.0)
e o PawnIO é baixado do GitHub oficial durante a instalação, porque a licença de redistribuição
do instalador dele não está documentada.

Fora do escopo: leitura de GPU AMD/Intel pelo LHM, assinatura digital, atualização automática,
mudanças no modo `.py` que o Mateus usa hoje.

## Critérios de sucesso

1. Num Windows limpo, instalar o setup, confirmar o UAC uma vez e ver o widget na barra com rede,
   CPU, MEM e temperatura da CPU (quando o PawnIO carrega). Funciona sem reiniciar, exceto se o
   PawnIO pedir reinicialização.
2. Após reiniciar o Windows, o widget e o LHM voltam sozinhos; o LHM sem UAC.
3. Instalar por cima (atualização) mantém as configurações e não duplica tarefa nem atalhos.
4. Desinstalar não deixa tarefa, atalho nem pasta em Program Files; configurações e PawnIO só
   saem se o usuário marcar.
5. No PC que já tem LHM/PawnIO (o do Mateus), o instalador usa os existentes.
6. Rodar pelo `.py` continua idêntico ao de hoje (mesmos caminhos de config e logs).

## Parte 1: código e build

### Mudanças no código

- **`app_paths.py`** (novo): `data_dir() -> Path`.
  - Congelado (`getattr(sys, "frozen", False)`): `%APPDATA%\SysMonitor`, criado se faltar.
  - Fonte: pasta do próprio `app_paths.py` (raiz do projeto), igual ao comportamento atual.
- **`sys_monitor.py`**: `CONFIG_PATH`, `CRASH_LOG_PATH` e `EVENT_LOG_PATH` (linhas 53–55) passam a
  usar `data_dir()`.
- **`tray_monitor.py`**: `CRASH_LOG_PATH` (linha 37) e os dois `Path(__file__).with_name("config.ini")`
  (linhas 412 e 420) passam a usar `data_dir()`.
- **`version.py`** (novo): `__version__ = "1.0.0"`. Usado pelo `--verificar` e pelo instalador.
- **`--verificar`** nas duas entradas: importa tudo que a entrada usa (inclusive `comtypes` e a
  geração UIA), imprime versão, `data_dir()` e se está congelado, e sai com código 0 sem abrir
  janela nem gravar config. Erro de importação → mensagem e código diferente de 0.
- O `config.ini` rastreado no git **não** vai para o instalador; `load_config()` já cria o arquivo
  com os padrões quando falta.

### Executáveis

- PyInstaller em modo pasta (`--onedir`), um único `.spec` com **dois EXE** num só COLLECT:
  `SysMonitor.exe` (entrada `sys_monitor.py`) e `SysMonitor-Bandeja.exe` (entrada `tray_monitor.py`).
- **Com console** (`console=True`): o código já esconde o console; o modo sem console equivale ao
  `pythonw`, que tem falha de pintura na janela em camadas (`sys_monitor.py:107`).
- Ícone: padrão do PyInstaller nesta versão (`assets/` está vazio; arte própria fica para depois).
- Python do build: venv `.venv-build` na raiz do projeto (gitignored) criado com `py -3.12`, o mesmo
  Python 3.12 / Tk 8.6 em que o widget roda hoje, com `psutil`, `comtypes` e `pyinstaller` em
  versões fixadas. Não usar o `C:\Python314`: ele traz Tk 9.0, e o widget depende de
  comportamentos de janela (camadas, alpha, `SetParent`) validados só em Tk 8.6. (Correção de
  2026-10-26, feita ao escrever o plano.)

### `build.ps1` (na raiz, versionado)

1. Cria/atualiza `.venv-build` e roda o PyInstaller → `build/pyinstaller/dist/SysMonitor/`.
2. Roda `SysMonitor.exe --verificar` e `SysMonitor-Bandeja.exe --verificar`; falha se algum sair ≠ 0.
3. Baixa o zip oficial do LHM **0.9.6** do GitHub para `build/cache/`, confere SHA-256 fixado no
   script e extrai. Hash diferente → para. Nunca copia o LHM instalado no PC do Mateus.
4. Chama o `ISCC.exe` (Inno Setup 6, instalado via winget) → `dist/SysMonitor-Setup-1.0.0.exe`.
- `.gitignore` ganha `.venv-build/`, `build/`, `dist/`.
- Ferramentas de build são só da máquina do Mateus: Inno Setup (winget) e PyInstaller (venv).

## Parte 2: instalador (Inno Setup)

Arquivos versionados em `installer/`: `SysMonitor.iss`, `LibreHardwareMonitor.config`
(predefinido), `tarefa-lhm.xml` (modelo da tarefa) e `LEIA-ME.txt`.

- Idioma português do Brasil; `PrivilegesRequired=admin`; `AppId` fixo (atualização por cima).
- Destino: `{commonpf64}\SysMonitor\app` (SysMonitor) e `{commonpf64}\SysMonitor\LibreHardwareMonitor`.
- Opções (tarefas do Inno): ☑ iniciar o widget com o Windows; ☐ iniciar a bandeja com o Windows;
  ☐ atalho na área de trabalho. Fim: ☑ "Abrir o SysMonitor agora".

### Passos

1. **Fechar instâncias**: encerra `SysMonitor.exe` e `SysMonitor-Bandeja.exe` antes de copiar.
2. **PawnIO**
   - Já instalado (chave de desinstalação do PawnIO no registro ou serviço de driver `PawnIO`) → pula.
   - Faltando → baixa `PawnIO_setup.exe` **2.2.0** do release oficial `namazso/PawnIO.Setup` pela
     página de download do Inno, com SHA-256 fixado (hash diferente → não executa). Roda
     `-install -silent` e trata o código de saída: sucesso, reinício necessário (pede reinício no
     fim) ou erro (avisa e segue).
   - Download falhou → segue a instalação e avisa no fim que a temperatura da CPU ficará vazia
     até instalar o PawnIO (com o link oficial).
   - Os switches `-install -silent` e os códigos de saída vêm de fontes de terceiros: o plano deve
     confirmá-los rodando o instalador real antes de depender deles.
3. **LHM**
   - Considera "LHM existente" se `http://127.0.0.1:8085/data.json` responde **ou** a tarefa
     `\LibreHardwareMonitor` existe → não copia LHM nem cria tarefa; anota no registro.
   - Senão, copia o LHM 0.9.6 e o `LibreHardwareMonitor.config` predefinido: servidor web ligado,
     `listenerIp=127.0.0.1`, `listenerPort=8085`, `authenticationEnabled=false`, iniciar minimizado,
     minimizar para a bandeja e ao fechar. Não liga o "Run On Windows Startup" do próprio LHM.
4. **Tarefa `SysMonitor LHM`** (só quando o LHM foi copiado)
   - Criada com `schtasks /create /xml` a partir de `tarefa-lhm.xml`: gatilho no logon do usuário
     que instalou, `RunLevel=HighestAvailable`, `DisallowStartIfOnBatteries=false`,
     `StopIfGoingOnBatteries=false`, `ExecutionTimeLimit=PT0S`, `MultipleInstancesPolicy=IgnoreNew`.
   - Disparada no fim da instalação (`schtasks /run`) para funcionar sem reiniciar.
5. **SysMonitor**: copia a pasta do PyInstaller; atalhos no Menu Iniciar ("SysMonitor" e
   "SysMonitor (bandeja)"); na pasta Inicializar, `SysMonitor.lnk` (widget) e/ou
   `SysMonitor Bandeja.lnk`, conforme marcado. O nome `SysMonitor.lnk` é o mesmo do atalho atual do
   modo `.py`, de propósito: substitui o antigo em vez de abrir dois widgets.
6. **Abrir agora**: `[Run]` com `runasoriginaluser` (widget sem elevação).

### Registro do que o instalador fez

`HKLM\Software\SysMonitor`: `Version`, `InstalledPawnIO` (0/1), `InstalledLHM` (0/1),
`CreatedTask` (0/1). É a fonte do desinstalador para saber o que pode remover.

### Limitação conhecida

Se o usuário estiver numa conta sem admin e digitar a senha de outra conta, atalhos e tarefa
podem ir para a outra conta (comportamento de instaladores elevados). O `LEIA-ME.txt` orienta a
instalar pela própria conta e explica o aviso do SmartScreen ("Mais informações" → "Executar
assim mesmo"), já que o exe não tem assinatura digital.

## Parte 3: desinstalador e aviso do LHM

### Desinstalador

- Fecha `SysMonitor.exe` e `SysMonitor-Bandeja.exe`; fecha o LHM **só se** `InstalledLHM=1` e o
  processo for o exe dentro de `{commonpf64}\SysMonitor\LibreHardwareMonitor`.
- Remove a tarefa `SysMonitor LHM` só se `CreatedTask=1`. Remove `{commonpf64}\SysMonitor`,
  atalhos e `HKLM\Software\SysMonitor`.
- Pergunta (ambas desmarcadas): "Remover também as configurações?" (`%APPDATA%\SysMonitor`) e,
  só se `InstalledPawnIO=1`, "Remover também o PawnIO?" (desinstalador do próprio PawnIO, modo
  silencioso a confirmar no plano).

### Aviso de LHM fora do ar no widget

- Fonte do estado: `LhmReader` ganha o atributo `reachable` (False quando o `urlopen` falha; True
  quando responde, mesmo sem sensor de CPU). A coleta expõe esse valor ao lado de `cpu_temp_error`
  (hoje em `sys_monitor.py:595` e `metrics_collector.py:27`). O aviso usa só `reachable`: LHM no ar
  sem sensor de CPU não mostra "fora do ar".
- Com o LHM inacessível, o menu de contexto (`sys_monitor.py`, montado por volta da linha 1062)
  ganha no topo uma linha desabilitada "⚠ LibreHardwareMonitor fora do ar" e o item
  "Abrir LibreHardwareMonitor", seguidos de separador. Com o LHM respondendo, não aparecem.
- "Abrir LibreHardwareMonitor" tenta, em ordem, parando na primeira que der certo:
  1. `schtasks /run /tn "SysMonitor LHM"`;
  2. `schtasks /run /tn "LibreHardwareMonitor"` (a tarefa do PC do Mateus);
  3. `ShellExecute "runas"` no exe do LHM em `{commonpf64}\SysMonitor\LibreHardwareMonitor`, se
     existir (abre o UAC).
  Nenhuma funcionou → registra no log e mostra uma mensagem curta.
- Lógica de decisão (itens do menu e ordem de tentativas) em módulo puro e testável
  (`lhm_launcher.py`), sem Tk nem Win32 no teste.
- O plano deve confirmar na prática que um usuário não elevado consegue disparar com
  `schtasks /run` uma tarefa elevada criada para ele; se não conseguir, o passo 3 cobre.
- A bandeja não muda (já avisa no tooltip).

## Testes

### Automáticos (TDD; stdlib unittest, `py -3.12 -m unittest discover -s tests -v`)

- `app_paths.data_dir()`: congelado → `%APPDATA%\SysMonitor` (com `APPDATA` simulado em pasta
  temporária, criada se faltar); fonte → raiz do projeto.
- `sys_monitor` e `tray_monitor` derivam config e logs de `data_dir()` (verificação por AST ou
  mock, sem abrir o widget, no padrão dos testes existentes).
- `LhmReader.reachable`: falso com `urlopen` falhando, verdadeiro com resposta sem sensor de CPU.
- `lhm_launcher`: menu com/sem aviso conforme o estado; ordem das tentativas; parada na primeira
  que funciona; falha total registrada (subprocess e ShellExecute simulados).
- `installer/tarefa-lhm.xml`: XML válido com os valores da Parte 2, item 4.
- `installer/LibreHardwareMonitor.config`: servidor ligado, 127.0.0.1, 8085, sem autenticação,
  minimizar para bandeja.
- A suíte existente (117 testes) continua passando; `py_compile` das fontes.

### Build

`build.ps1` completo gera o setup, e os dois `--verificar` saem com 0.

### Teste real (Mateus, nesta ordem)

1. **Windows Sandbox** (habilitar o recurso exige admin e reinício, comando rodado pelo Mateus):
   instalar, conferir atalhos, tarefa, registro e widget; desinstalar com e sem as duas
   remoções. O driver do PawnIO pode não carregar no Sandbox; nesse caso, o aviso de LHM/
   temperatura vazia é o comportamento esperado.
2. **PC do Mateus**: o instalador detecta PawnIO e LHM e os usa; `SysMonitor.lnk` passa a apontar
   para o exe. Configurações não migram sozinhas: copiar `config.ini` para `%APPDATA%\SysMonitor`.
   Voltar ao modo `.py`: `create_shortcut.py`.
3. **PC de um amigo**.

## Git

Trabalho na branch `versao-1.0`. Sem commit na main, push, tag ou release antes do teste real e
da aprovação do Mateus. `config.ini` local e mudanças já pendentes em `docs/agentes/estado.md`
ficam preservados.
