# SysMonitor 1.0.0: exe e instalador · Plano de implementação

> **Para agentes executores:** SUB-SKILL OBRIGATÓRIA: superpowers:executing-plans (ou
> superpowers:subagent-driven-development), tarefa por tarefa. Passos com `- [ ]`.

**Objetivo:** gerar `dist/SysMonitor-Setup-1.0.0.exe`, que instala o SysMonitor (exe PyInstaller,
sem elevação), o PawnIO (baixado do release oficial) e o LibreHardwareMonitor 0.9.6 portátil com
tarefa elevada no logon, pedindo admin uma única vez.

**Arquitetura:** o código Python ganha `app_paths.data_dir()` (config/logs em `%APPDATA%\SysMonitor`
quando congelado), `--verificar` nas duas entradas e um aviso de LHM fora do ar no menu do widget.
O `build.ps1` monta o exe (PyInstaller, modo pasta, 2 EXE), baixa o LHM com SHA-256 fixado e chama
o Inno Setup. O instalador usa um script PowerShell auxiliar (ASCII) para criar a tarefa do LHM e
parar o LHM próprio.

**Stack:** Python 3.12 (`py -3.12`, Tk 8.6), PyInstaller 6.22.3, Inno Setup 6.7.x (winget),
PowerShell 5.1, unittest da stdlib.

**Spec:** `docs/superpowers/specs/2026-10-26-exe-instalador-design.md` (ler junto com este plano).

## Restrições globais

- Branch `versao-1.0` (já é a atual). Commits só nela. **Sem** merge na main, push, tag ou release.
- Nunca commitar `config.ini` (é a config local do Mateus, tem mudanças não commitadas de propósito)
  nem `docs/agentes/estado.md` (tem mudança pendente; o Claude atualiza no fim). Use sempre
  `git add <arquivos>` explícitos, nunca `git add -A` / `git add .`.
- Testes: `py -3.12 -m unittest discover -s tests -v` a partir da raiz. Hoje: 117 testes, todos OK.
- Python do build: venv `.venv-build` criado com `py -3.12`. Não usar `C:\Python314` (Tk 9.0).
- Versões fixadas: `pyinstaller==6.22.3`, `pyinstaller-hooks-contrib==2026.9`, `psutil==7.2.2`,
  `comtypes==1.4.17`; LHM **0.9.6** `LibreHardwareMonitor.zip` (build .NET Framework 4.7.2, já vem
  no Windows), SHA-256 `086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001`;
  PawnIO **2.2.0** `PawnIO_setup.exe`, SHA-256
  `1f519a22e47187f70a1379a48ca604981c4fcf694f4e65b734aaa74a9fba3032`.
- URLs oficiais:
  `https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.6/LibreHardwareMonitor.zip`
  e `https://github.com/namazso/PawnIO.Setup/releases/download/2.2.0/PawnIO_setup.exe`.
- Nomes fixos: tarefa `SysMonitor LHM`; registro `HKLM\Software\SysMonitor` (`Version`,
  `InstalledPawnIO`, `InstalledLHM`, `CreatedTask`); `AppId` do Inno
  `{B9BAAD01-C950-4857-A03B-47BD6FA9B2F1}`; atalho de inicialização do widget `SysMonitor.lnk`.
- O app nunca pede elevação; só o instalador. Manter compatibilidade com HVCI.
- Rodar pelo `.py` continua idêntico: mesmos caminhos de config e logs (raiz do projeto).
- Arquivos `.ps1` deste plano: **somente ASCII** (o PowerShell 5.1 lê .ps1 sem BOM como ANSI).
  Mensagens neles sem acento. Arquivos do Inno (`.iss`, `LEIA-ME.txt`): UTF-8 **com BOM**.
- Não editar `CLAUDE.md` nem `AGENTS.md`.

## Confirmado pelo Claude em 2026-10-26 (não precisa refazer)

- `PawnIO_setup.exe` 2.2.0 aceita `-install`, `-uninstall`, `-silent` (texto de ajuda dentro do
  binário). Desinstalação silenciosa registrada no PC do Mateus:
  `"C:\Program Files\PawnIO\uninstall.exe" -uninstall -silent`; chave
  `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO`; serviço de driver `PawnIO`.
  Códigos de saída do setup **não** estão documentados: o plano trata 0 = ok, 3010/1641 = reiniciar,
  outro = erro; o teste no Windows Sandbox confirma.
- Usuário **não elevado** consegue disparar a tarefa elevada `\LibreHardwareMonitor` com
  `schtasks /run` (código 0). O zip do LHM é plano (exe na raiz) e não traz `LibreHardwareMonitor.config`.
- Desvio consciente da spec: a tarefa é registrada com `Register-ScheduledTask -Xml` (PowerShell),
  não `schtasks /create /xml`, para não depender de arquivo UTF-16; o gatilho de logon fica sem
  `UserId` (igual à tarefa do LHM que já funciona no PC do Mateus) e o vínculo ao usuário vem do
  `Principal`.

## Foco de revisão

1. Atualização por cima com o LHM **do próprio SysMonitor** rodando: o LHM responde na 8085, mas
   o instalador tem de tratá-lo como seu (copiar por cima, recriar tarefa, manter `InstalledLHM=1`,
   `InstalledPawnIO` e `CreatedTask`), senão o desinstalador deixa lixo. Coberto no Teste real
   (Sandbox, passo "instalar duas vezes"), porque a lógica está no Pascal do Inno.
2. `SysMonitor.exe --verificar` (ou `py sys_monitor.py --verificar`) rodado num terminal **não pode
   esconder o terminal**: hoje `hide_console_window()` roda na importação. Teste na Tarefa 2.
3. `%APPDATA%\SysMonitor` inexistente ou variável `APPDATA` ausente: `data_dir()` cria a pasta /
   cai em `~\AppData\Roaming`. Teste na Tarefa 1.
4. Menu aberto várias vezes enquanto o LHM cai e volta: o aviso nunca duplica e some quando volta.
   Teste na Tarefa 4.
5. Caminho com espaço, `&` e acento (ex.: `C:\Program Files\Sys & Mon\Ação`) na tarefa do LHM: XML
   válido com o caminho exato. Teste na Tarefa 5.

---

## Parte A: código Python (lote 1 do Hermes)

### Tarefa 1: `app_paths.py`, `version.py` e caminhos de config/logs

**Arquivos:**
- Criar: `app_paths.py`, `version.py`, `tests/test_app_paths.py`
- Modificar: `sys_monitor.py:53-55`, `tray_monitor.py:37`, `tray_monitor.py:412`, `tray_monitor.py:420`, `.gitignore`

**Interfaces:**
- Produz: `app_paths.data_dir() -> pathlib.Path`; `version.__version__ == "1.0.0"`;
  `tray_monitor.CONFIG_PATH`.

- [ ] **Passo 1: teste que falha** — `tests/test_app_paths.py`:

```python
"""data_dir(): source mode keeps the project root; frozen mode uses %APPDATA%\\SysMonitor."""
import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_paths

ROOT = Path(__file__).resolve().parents[1]


class DataDirTests(unittest.TestCase):
    def test_source_mode_is_project_root(self):
        self.assertFalse(getattr(sys, 'frozen', False))
        self.assertEqual(app_paths.data_dir().resolve(), ROOT)

    def test_frozen_mode_creates_appdata_folder(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(sys, 'frozen', True, create=True), \
                patch.dict(os.environ, {'APPDATA': tmp}):
            folder = app_paths.data_dir()
            self.assertEqual(folder, Path(tmp) / 'SysMonitor')
            self.assertTrue(folder.is_dir())

    def test_frozen_mode_without_appdata_falls_back_to_roaming(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(sys, 'frozen', True, create=True), \
                patch.dict(os.environ, {}, clear=True), \
                patch.object(Path, 'home', return_value=Path(tmp)):
            folder = app_paths.data_dir()
            self.assertEqual(folder, Path(tmp) / 'AppData' / 'Roaming' / 'SysMonitor')
            self.assertTrue(folder.is_dir())


class EntryPointPathsTests(unittest.TestCase):
    def assignments(self, filename):
        tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
        return {node.targets[0].id: ast.unparse(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}

    def test_widget_paths_come_from_data_dir(self):
        values = self.assignments('sys_monitor.py')
        self.assertEqual(values['CONFIG_PATH'], "data_dir() / 'config.ini'")
        self.assertEqual(values['CRASH_LOG_PATH'], "data_dir() / 'crash.log'")
        self.assertEqual(values['EVENT_LOG_PATH'], "data_dir() / 'sysmon.log'")

    def test_tray_paths_come_from_data_dir(self):
        values = self.assignments('tray_monitor.py')
        self.assertEqual(values['CONFIG_PATH'], "data_dir() / 'config.ini'")
        self.assertEqual(values['CRASH_LOG_PATH'], "data_dir() / 'crash.log'")

    def test_entry_points_no_longer_use_dunder_file(self):
        for filename in ('sys_monitor.py', 'tray_monitor.py'):
            with self.subTest(filename=filename):
                self.assertNotIn('__file__', (ROOT / filename).read_text(encoding='utf-8'))

    def test_version(self):
        import version
        self.assertEqual(version.__version__, '1.0.0')
```

- [ ] **Passo 2:** `py -3.12 -m unittest tests.test_app_paths -v` → falha com `ModuleNotFoundError: app_paths`.

- [ ] **Passo 3: implementação mínima**

`app_paths.py`:
```python
"""
app_paths.py — where SysMonitor keeps config.ini and its logs.

Running from source (python sys_monitor.py) keeps everything next to the
scripts, exactly as before. The PyInstaller build lives in Program Files,
which a normal user can't write to, so there it uses %APPDATA%\\SysMonitor.
"""
import os
import sys
from pathlib import Path

APP_DIR_NAME = "SysMonitor"


def data_dir() -> Path:
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        folder = base / APP_DIR_NAME
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    return Path(__file__).parent
```

`version.py`:
```python
__version__ = "1.0.0"
```

`sys_monitor.py`: adicionar `from app_paths import data_dir` junto dos outros imports locais e
trocar as linhas 53–55 por:
```python
CONFIG_PATH = data_dir() / "config.ini"
CRASH_LOG_PATH = data_dir() / "crash.log"
EVENT_LOG_PATH = data_dir() / "sysmon.log"
```

`tray_monitor.py`: adicionar `from app_paths import data_dir`; linha 37 vira
```python
CONFIG_PATH = data_dir() / "config.ini"
CRASH_LOG_PATH = data_dir() / "crash.log"
```
e, em `run()`, `cfg.read(CONFIG_PATH, encoding="utf-8")` e
`TrayLimitsPreferences(cfg, CONFIG_PATH)`. Se `Path` deixar de ser usado em algum dos dois
arquivos, remover o import.

`.gitignore`: acrescentar
```
.venv-build/
build/
dist/
```

- [ ] **Passo 4:** `py -3.12 -m unittest tests.test_app_paths -v` → OK; depois a suíte inteira → OK.
- [ ] **Passo 5: commit**
```bash
git add app_paths.py version.py tests/test_app_paths.py sys_monitor.py tray_monitor.py .gitignore
git commit -m "Config e logs em %APPDATA% quando empacotado (app_paths)"
```

### Tarefa 2: `--verificar` nas duas entradas

**Arquivos:**
- Criar: `self_check.py`, `tests/test_self_check.py`
- Modificar: `sys_monitor.py:125` e bloco `if __name__ == "__main__"` (fim do arquivo);
  `tray_monitor.py:81` e bloco `__main__`

**Interfaces:**
- Consome: `app_paths.data_dir()`, `version.__version__`.
- Produz: `self_check.SELF_CHECK_FLAG = "--verificar"`;
  `self_check.is_self_check(argv: list[str]) -> bool`;
  `self_check.run_self_check(entry: str, modules: tuple[str, ...], uia: bool, out=print) -> int`.
  O `build.ps1` (Tarefa 6) depende de: sai 0, imprime uma linha que contém `SysMonitor 1.0.0`.

- [ ] **Passo 1: teste que falha** — `tests/test_self_check.py`:

```python
"""--verificar: imports what the entry point needs, prints version/paths, exits 0, opens nothing."""
import ast
import subprocess
import sys
import unittest
from pathlib import Path

import self_check

ROOT = Path(__file__).resolve().parents[1]


class RunSelfCheckTests(unittest.TestCase):
    def test_ok_prints_version_data_dir_and_frozen(self):
        lines = []
        rc = self_check.run_self_check('widget', ('json',), uia=False, out=lines.append)
        self.assertEqual(rc, 0)
        text = '\n'.join(lines)
        self.assertIn('SysMonitor 1.0.0 (widget)', text)
        self.assertIn('dados: ', text)
        self.assertIn('congelado: False', text)

    def test_missing_module_returns_nonzero(self):
        lines = []
        rc = self_check.run_self_check('widget', ('modulo_que_nao_existe_123',), uia=False,
                                       out=lines.append)
        self.assertNotEqual(rc, 0)
        self.assertTrue(lines[-1].startswith('ERRO'), lines)

    def test_flag_detection(self):
        self.assertTrue(self_check.is_self_check(['--verificar']))
        self.assertFalse(self_check.is_self_check([]))


class EntryPointTests(unittest.TestCase):
    def run_entry(self, script):
        return subprocess.run([sys.executable, script, '--verificar'], cwd=ROOT,
                              capture_output=True, text=True, timeout=120)

    def test_widget_entry(self):
        result = self.run_entry('sys_monitor.py')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SysMonitor 1.0.0 (widget)', result.stdout)

    def test_tray_entry(self):
        result = self.run_entry('tray_monitor.py')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SysMonitor 1.0.0 (bandeja)', result.stdout)

    def test_console_is_not_hidden_when_self_checking(self):
        # Foco de revisão 2: hiding the console on import would hide the
        # terminal that ran --verificar. The module-level call must be guarded.
        for filename in ('sys_monitor.py', 'tray_monitor.py'):
            tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
            bare = [n for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                    and getattr(n.value.func, 'id', None) == 'hide_console_window']
            guarded = [n for n in tree.body if isinstance(n, ast.If)
                       and 'is_self_check' in ast.unparse(n.test)
                       and 'hide_console_window()' in ast.unparse(n)]
            with self.subTest(filename=filename):
                self.assertEqual(bare, [])
                self.assertEqual(len(guarded), 1)
```

- [ ] **Passo 2:** `py -3.12 -m unittest tests.test_self_check -v` → falha (`ModuleNotFoundError: self_check`).

- [ ] **Passo 3: implementação mínima**

`self_check.py`:
```python
"""
self_check.py — `--verificar` for both entry points.

Used by build.ps1 to prove a PyInstaller build is complete: imports every
module the entry point loads lazily, regenerates/loads the UI Automation
wrapper (taskbar_space.py needs it), prints version and data folder, and
exits without opening a window, taking the single-instance mutex or
writing config.
"""
import importlib
import sys

from app_paths import data_dir
from version import __version__

SELF_CHECK_FLAG = "--verificar"


def is_self_check(argv) -> bool:
    """argv without the program name, i.e. sys.argv[1:]."""
    return SELF_CHECK_FLAG in argv


def run_self_check(entry: str, modules: tuple[str, ...], uia: bool, out=print) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    try:
        for name in modules:
            importlib.import_module(name)
        import tkinter
        tcl = tkinter.Tcl().eval("info patchlevel")
        if uia:
            import comtypes.client
            comtypes.client.GetModule("UIAutomationCore.dll")
    except Exception as exc:
        out(f"ERRO: {exc!r}")
        return 1
    out(f"SysMonitor {__version__} ({entry})")
    out(f"dados: {data_dir()}")
    out(f"congelado: {bool(getattr(sys, 'frozen', False))}")
    out(f"tcl: {tcl}")
    return 0
```
`sys_monitor.py`: importar `from self_check import is_self_check, run_self_check`; trocar a linha
125 `hide_console_window()` por
```python
if not is_self_check(sys.argv[1:]):
    hide_console_window()
```
e o fim do arquivo por
```python
if __name__ == "__main__":
    if is_self_check(sys.argv[1:]):
        sys.exit(run_self_check("widget", ("usage_limits_ui", "lhm_launcher", "tkinter.messagebox"),
                                uia=True))
    main()
```
Atenção: `lhm_launcher` só existe depois da Tarefa 4. Nesta tarefa use
`("usage_limits_ui", "tkinter.messagebox")` e a Tarefa 4 acrescenta `"lhm_launcher"`.

`tray_monitor.py`: mesmo padrão; linha 81 guardada com `if not is_self_check(sys.argv[1:]):` e
```python
if __name__ == "__main__":
    if is_self_check(sys.argv[1:]):
        sys.exit(run_self_check("bandeja", ("usage_limits_ui", "usage_limits"), uia=False))
    run()
```

- [ ] **Passo 4:** teste focado → OK; suíte inteira → OK. Conferir à mão
  `py -3.12 sys_monitor.py --verificar` num terminal: imprime 4 linhas, sai 0, o terminal **continua
  visível**, nenhum widget novo aparece.
- [ ] **Passo 5: commit**
```bash
git add self_check.py tests/test_self_check.py sys_monitor.py tray_monitor.py
git commit -m "--verificar nas entradas do widget e da bandeja"
```

### Tarefa 3: `LhmReader.reachable` e `lhm_reachable` nas métricas

**Arquivos:**
- Modificar: `sensors.py` (`LhmReader`, `SensorReader.read`), `sys_monitor.py` (`Metrics`,
  por volta das linhas 583–620), `metrics_collector.py` (`Metrics`)
- Criar: `tests/test_lhm_reachable.py`

**Interfaces:**
- Produz: `LhmReader.reachable: bool | None` (None antes da 1ª leitura); `SensorReader.read()`
  devolve também `lhm_reachable`; `Metrics.lhm_reachable` (inicial `None`) e
  `snapshot()["lhm_reachable"]` nas **duas** classes `Metrics`.

- [ ] **Passo 1: teste que falha** — `tests/test_lhm_reachable.py`:

```python
"""LHM reachability: down only when the HTTP call fails, not when the CPU sensor is missing."""
import io
import json
import unittest
from unittest.mock import patch

import sensors
from metrics_collector import Metrics
import test_ping_views as views


def fake_response(tree):
    # BytesIO is already a context manager, and json.load only needs .read().
    return io.BytesIO(json.dumps(tree).encode('utf-8'))


class LhmReachableTests(unittest.TestCase):
    def test_unknown_before_first_read(self):
        self.assertIsNone(sensors.LhmReader().reachable)

    def test_unreachable_when_urlopen_fails(self):
        reader = sensors.LhmReader()
        with patch('sensors.urllib.request.urlopen', side_effect=OSError('refused')):
            self.assertIsNone(reader.read_cpu_temp())
        self.assertIs(reader.reachable, False)

    def test_reachable_without_cpu_sensor(self):
        reader = sensors.LhmReader()
        tree = {'Text': 'Sensor', 'Children': [{'Text': 'GPU', 'SensorId': '/gpu/0/temperature/0',
                                                 'Value': '50,0 °C', 'Children': []}]}
        with patch('sensors.urllib.request.urlopen', return_value=fake_response(tree)):
            self.assertIsNone(reader.read_cpu_temp())
        self.assertIs(reader.reachable, True)
        self.assertIn('no CPU temperature sensor', reader.last_error)

    def test_sensor_reader_exposes_reachability(self):
        reader = sensors.SensorReader()
        with patch('sensors.urllib.request.urlopen', side_effect=OSError('refused')), \
                patch.object(sensors.NvmlReader, 'read', return_value=(None, None)):
            data = reader.read()
        self.assertIs(data['lhm_reachable'], False)

    def test_both_metrics_classes_carry_the_flag(self):
        widget_ns = views.PingViewTests().widget_namespace()
        for cls in (Metrics, widget_ns['Metrics']):
            with self.subTest(cls=cls.__module__):
                metrics = cls()
                self.assertIsNone(metrics.lhm_reachable)
                self.assertIn('lhm_reachable', metrics.snapshot())
```
- [ ] **Passo 2:** `py -3.12 -m unittest tests.test_lhm_reachable -v` → falha (`AttributeError: reachable`).

- [ ] **Passo 3: implementação mínima**

`sensors.py`, em `LhmReader`:
```python
    def __init__(self, url: str = LHM_URL):
        self._url = url
        self._last_error: Optional[str] = None
        self._reachable: Optional[bool] = None

    @property
    def reachable(self) -> Optional[bool]:
        """False when the web server didn't answer; True when it answered,
        even without a CPU sensor; None before the first read."""
        return self._reachable
```
Em `read_cpu_temp`, no `except` do `urlopen`: `self._reachable = False` antes do `return None`;
logo depois do `with ... json.load(resp)` ter dado certo: `self._reachable = True`.

`SensorReader.read()`: acrescentar `lhm_reachable=self._lhm.reachable` ao dict de retorno (também
quando cai no `except Exception` da CPU).

Nas duas classes `Metrics` (`sys_monitor.py` e `metrics_collector.py`): `self.lhm_reachable = None`
no `__init__` e `lhm_reachable=self.lhm_reachable,` no `snapshot()`. Os coletores já copiam todas as
chaves de `sensors` com `setattr`, não mexer neles.

- [ ] **Passo 4:** teste focado → OK; suíte inteira → OK.
- [ ] **Passo 5: commit**
```bash
git add sensors.py sys_monitor.py metrics_collector.py tests/test_lhm_reachable.py
git commit -m "Sensores: estado de alcance do LibreHardwareMonitor"
```

### Tarefa 4: `lhm_launcher.py` e aviso no menu do widget

**Arquivos:**
- Criar: `lhm_launcher.py`, `tests/test_lhm_launcher.py`
- Modificar: `sys_monitor.py` (`_bind_menu`, por volta das linhas 1060–1095; novo método
  `_open_lhm`; tupla do `--verificar` no fim do arquivo)

**Interfaces:**
- Consome: `snapshot()["lhm_reachable"]` (Tarefa 3).
- Produz:
  - `WARNING_LABEL = "⚠ LibreHardwareMonitor fora do ar"`, `OPEN_LABEL = "Abrir LibreHardwareMonitor"`
  - `TASK_NAMES = ("SysMonitor LHM", "LibreHardwareMonitor")`
  - `sync_menu(menu, reachable: bool | None, shown: int, on_open) -> int` — remove as `shown`
    primeiras entradas que ele mesmo pôs; se `reachable is False`, insere no topo aviso desabilitado,
    item de abrir e separador e devolve 3; senão devolve 0.
  - `default_lhm_exe() -> Path` — `<ProgramW6432 ou ProgramFiles>\SysMonitor\LibreHardwareMonitor\LibreHardwareMonitor.exe`
  - `open_lhm(log, run_task=run_task, runas=runas, exe=None, exists=None) -> bool`
  - `run_task(name: str) -> bool` (subprocess `schtasks /run /tn <name>`, sem janela, código 0 = True)
  - `runas(exe: Path) -> bool` (`ShellExecuteW(None, "runas", exe, None, exe.parent, 1) > 32`)

- [ ] **Passo 1: teste que falha** — `tests/test_lhm_launcher.py`:

```python
"""LHM-down warning: menu entries follow the state, launch tries tasks then runas."""
import tkinter as tk
import unittest
from pathlib import Path

import lhm_launcher as L


class SyncMenuTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label='Configurar limites de uso…')
        self.menu.add_command(label='Fechar')

    def tearDown(self):
        self.root.destroy()

    def labels(self):
        end = self.menu.index('end')
        return [self.menu.type(i) == 'separator' and '---' or self.menu.entrycget(i, 'label')
                for i in range(end + 1)]

    def test_reachable_or_unknown_adds_nothing(self):
        for state in (True, None):
            with self.subTest(state=state):
                self.assertEqual(L.sync_menu(self.menu, state, 0, lambda: None), 0)
                self.assertEqual(self.labels(), ['Configurar limites de uso…', 'Fechar'])

    def test_down_adds_disabled_warning_open_item_and_separator(self):
        shown = L.sync_menu(self.menu, False, 0, lambda: None)
        self.assertEqual(shown, 3)
        self.assertEqual(self.labels(), [L.WARNING_LABEL, L.OPEN_LABEL, '---',
                                         'Configurar limites de uso…', 'Fechar'])
        self.assertEqual(self.menu.entrycget(0, 'state'), 'disabled')
        self.assertEqual(self.menu.entrycget(1, 'state'), 'normal')

    def test_flipping_state_never_duplicates(self):
        # Foco de revisão 4.
        shown = 0
        for state in (False, False, True, False, None, False, True):
            shown = L.sync_menu(self.menu, state, shown, lambda: None)
        self.assertEqual(shown, 0)
        self.assertEqual(self.labels(), ['Configurar limites de uso…', 'Fechar'])
        shown = L.sync_menu(self.menu, False, shown, lambda: None)
        self.assertEqual(self.labels().count(L.WARNING_LABEL), 1)


class OpenLhmTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.logs = [], []
        self.exe = Path(r'C:\Program Files\SysMonitor\LibreHardwareMonitor\LibreHardwareMonitor.exe')

    def task(self, ok_names):
        def run(name):
            self.calls.append(('task', name))
            return name in ok_names
        return run

    def runas(self, ok):
        def run(exe):
            self.calls.append(('runas', exe))
            return ok
        return run

    def test_stops_at_first_task_that_works(self):
        ok = L.open_lhm(self.logs.append, run_task=self.task({'SysMonitor LHM'}),
                        runas=self.runas(True), exe=self.exe, exists=lambda p: True)
        self.assertTrue(ok)
        self.assertEqual(self.calls, [('task', 'SysMonitor LHM')])

    def test_falls_back_to_mateus_task_then_runas(self):
        ok = L.open_lhm(self.logs.append, run_task=self.task({'LibreHardwareMonitor'}),
                        runas=self.runas(True), exe=self.exe, exists=lambda p: True)
        self.assertTrue(ok)
        self.assertEqual(self.calls, [('task', 'SysMonitor LHM'), ('task', 'LibreHardwareMonitor')])
        self.calls.clear()
        ok = L.open_lhm(self.logs.append, run_task=self.task(set()),
                        runas=self.runas(True), exe=self.exe, exists=lambda p: True)
        self.assertTrue(ok)
        self.assertEqual(self.calls[-1], ('runas', self.exe))

    def test_skips_runas_when_exe_missing_and_logs_total_failure(self):
        ok = L.open_lhm(self.logs.append, run_task=self.task(set()),
                        runas=self.runas(True), exe=self.exe, exists=lambda p: False)
        self.assertFalse(ok)
        self.assertNotIn('runas', [c[0] for c in self.calls])
        self.assertEqual(len(self.logs), 1)
        self.assertIn('LibreHardwareMonitor', self.logs[0])

    def test_default_exe_path(self):
        self.assertEqual(L.default_lhm_exe().parts[-3:],
                         ('SysMonitor', 'LibreHardwareMonitor', 'LibreHardwareMonitor.exe'))
```

- [ ] **Passo 2:** `py -3.12 -m unittest tests.test_lhm_launcher -v` → falha (`ModuleNotFoundError`).

- [ ] **Passo 3: implementação mínima** — `lhm_launcher.py`:

```python
"""
lhm_launcher.py — "LibreHardwareMonitor fora do ar" in the widget menu.

The CPU temperature comes from LHM, which has to run elevated. When its web
server stops answering, the widget menu offers to start it again, trying in
order: the installer's task, the task LHM itself creates (Mateus' PC), and
finally the bundled exe through UAC. Pure logic here; Tk/Win32 are injected.
"""
import ctypes
import os
import subprocess
from pathlib import Path

WARNING_LABEL = "⚠ LibreHardwareMonitor fora do ar"
OPEN_LABEL = "Abrir LibreHardwareMonitor"
TASK_NAMES = ("SysMonitor LHM", "LibreHardwareMonitor")
_CREATE_NO_WINDOW = 0x08000000


def sync_menu(menu, reachable, shown: int, on_open) -> int:
    if shown:
        menu.delete(0, shown - 1)
    if reachable is not False:
        return 0
    menu.insert_command(0, label=WARNING_LABEL, state="disabled")
    menu.insert_command(1, label=OPEN_LABEL, command=on_open)
    menu.insert_separator(2)
    return 3


def default_lhm_exe() -> Path:
    program_files = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"
    return Path(program_files) / "SysMonitor" / "LibreHardwareMonitor" / "LibreHardwareMonitor.exe"


def run_task(name: str) -> bool:
    try:
        result = subprocess.run(["schtasks", "/run", "/tn", name], capture_output=True,
                                timeout=10, creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def runas(exe: Path) -> bool:
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", str(exe), None, str(exe.parent), 1) > 32


def open_lhm(log, run_task=run_task, runas=runas, exe=None, exists=None) -> bool:
    for name in TASK_NAMES:
        if run_task(name):
            return True
    exe = exe or default_lhm_exe()
    exists = exists or Path.exists
    if exists(exe) and runas(exe):
        return True
    log(f"lhm: could not start LibreHardwareMonitor (tasks {TASK_NAMES}, exe {exe})")
    return False
```

`sys_monitor.py`, em `_bind_menu`: depois de montar o menu, guardar `self._lhm_menu_shown = 0` e,
em `show_menu`, antes do `menu.tk_popup(x, y)`:
```python
            from lhm_launcher import sync_menu
            self._lhm_menu_shown = sync_menu(menu, self.metrics.snapshot().get("lhm_reachable"),
                                             self._lhm_menu_shown, self._open_lhm)
```
Novo método em `MonitorWindow`, ao lado de `_edit_usage_limits`:
```python
    def _open_lhm(self):
        from lhm_launcher import open_lhm
        if not open_lhm(_log_event):
            from tkinter import messagebox
            messagebox.showwarning(APP_NAME, "Não consegui abrir o LibreHardwareMonitor.",
                                   parent=self.master)
```
No fim do arquivo, a tupla do `--verificar` passa a ser
`("usage_limits_ui", "lhm_launcher", "tkinter.messagebox")`.

- [ ] **Passo 4:** teste focado → OK; suíte inteira → OK; `py -3.12 sys_monitor.py --verificar` → 0.
- [ ] **Passo 5: commit**
```bash
git add lhm_launcher.py tests/test_lhm_launcher.py sys_monitor.py
git commit -m "Widget: aviso de LibreHardwareMonitor fora do ar com atalho para abrir"
```

**Fim do lote 1.** Pare aqui e reporte (o Claude revisa antes da Parte B).

---

## Parte B: build e instalador (lote 2 do Hermes)

### Tarefa 5: arquivos de apoio do instalador

**Arquivos:**
- Criar: `installer/tarefa-lhm.xml`, `installer/LibreHardwareMonitor.config`,
  `installer/util-instalador.ps1`, `installer/LEIA-ME.txt`, `tests/test_installer_files.py`

**Interfaces:**
- Produz: `util-instalador.ps1 -Acao CriarTarefa -LhmDir <pasta> [-UserId <sid>] [-SomenteGerar <arquivo>]`
  (lê `tarefa-lhm.xml` da **mesma pasta do script**; registra `SysMonitor LHM`; sai 0) e
  `util-instalador.ps1 -Acao PararLhm -LhmDir <pasta>` (encerra só o `LibreHardwareMonitor.exe`
  dessa pasta; sai 0 mesmo sem processo). O `.iss` (Tarefa 7) chama exatamente assim.

- [ ] **Passo 1: teste que falha** — `tests/test_installer_files.py`:

```python
"""Installer data files: LHM task XML, LHM config, PowerShell helper."""
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / 'installer'
NS = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}


def run_helper(*args):
    return subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                           str(INSTALLER / 'util-instalador.ps1'), *args],
                          capture_output=True, text=True, timeout=60)


class TaskXmlTests(unittest.TestCase):
    def generate(self, lhm_dir, user='S-1-5-21-1-2-3-1001'):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'tarefa.xml'
            result = run_helper('-Acao', 'CriarTarefa', '-LhmDir', lhm_dir, '-UserId', user,
                                '-SomenteGerar', str(out))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return ET.fromstring(out.read_text(encoding='utf-8'))

    def test_values_from_spec(self):
        task = self.generate(r'C:\Program Files\SysMonitor\LibreHardwareMonitor')
        get = lambda path: task.find(path, NS).text
        self.assertEqual(get('t:Principals/t:Principal/t:UserId'), 'S-1-5-21-1-2-3-1001')
        self.assertEqual(get('t:Principals/t:Principal/t:LogonType'), 'InteractiveToken')
        self.assertEqual(get('t:Principals/t:Principal/t:RunLevel'), 'HighestAvailable')
        self.assertIsNotNone(task.find('t:Triggers/t:LogonTrigger', NS))
        self.assertEqual(get('t:Settings/t:DisallowStartIfOnBatteries'), 'false')
        self.assertEqual(get('t:Settings/t:StopIfGoingOnBatteries'), 'false')
        self.assertEqual(get('t:Settings/t:ExecutionTimeLimit'), 'PT0S')
        self.assertEqual(get('t:Settings/t:MultipleInstancesPolicy'), 'IgnoreNew')
        self.assertEqual(get('t:Actions/t:Exec/t:Command'),
                         r'C:\Program Files\SysMonitor\LibreHardwareMonitor\LibreHardwareMonitor.exe')
        self.assertEqual(get('t:Actions/t:Exec/t:WorkingDirectory'),
                         r'C:\Program Files\SysMonitor\LibreHardwareMonitor')

    def test_path_with_ampersand_and_accents(self):
        # Foco de revisão 5.
        folder = r'C:\Program Files\Sys & Mon\Ação'
        task = self.generate(folder)
        self.assertEqual(task.find('t:Actions/t:Exec/t:Command', NS).text,
                         folder + r'\LibreHardwareMonitor.exe')

    def test_stop_lhm_without_process_is_noop(self):
        result = run_helper('-Acao', 'PararLhm', '-LhmDir', r'C:\nao\existe')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_powershell_files_are_ascii(self):
        for name in ('util-instalador.ps1',):
            with self.subTest(name=name):
                (INSTALLER / name).read_bytes().decode('ascii')


class LhmConfigTests(unittest.TestCase):
    def test_web_server_settings(self):
        tree = ET.parse(INSTALLER / 'LibreHardwareMonitor.config')
        values = {node.get('key'): node.get('value') for node in tree.iter('add')}
        self.assertEqual(values['runWebServerMenuItem'], 'true')
        self.assertEqual(values['listenerIp'], '127.0.0.1')
        self.assertEqual(values['listenerPort'], '8085')
        self.assertEqual(values['authenticationEnabled'], 'false')
        for key in ('startMinMenuItem', 'minTrayMenuItem', 'minCloseMenuItem'):
            self.assertEqual(values[key], 'true', key)
        self.assertNotIn('startupMenuItem', values)  # LHM's own autostart stays off
```

- [ ] **Passo 2:** `py -3.12 -m unittest tests.test_installer_files -v` → falha (arquivos não existem).

- [ ] **Passo 3: implementação mínima**

`installer/tarefa-lhm.xml` (UTF-8 sem BOM, **sem** declaração `<?xml ...?>`, só ASCII):
```xml
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Starts LibreHardwareMonitor elevated so SysMonitor can read the CPU temperature.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{{USER_ID}}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{{LHM_EXE}}</Command>
      <WorkingDirectory>{{LHM_DIR}}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
```

`installer/LibreHardwareMonitor.config`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <appSettings>
    <add key="runWebServerMenuItem" value="true" />
    <add key="listenerIp" value="127.0.0.1" />
    <add key="listenerPort" value="8085" />
    <add key="authenticationEnabled" value="false" />
    <add key="startMinMenuItem" value="true" />
    <add key="minTrayMenuItem" value="true" />
    <add key="minCloseMenuItem" value="true" />
  </appSettings>
</configuration>
```

`installer/util-instalador.ps1` (somente ASCII):
```powershell
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
```

`installer/LEIA-ME.txt` (UTF-8 com BOM; aparece antes da instalação):
```text
SysMonitor 1.0.0

Monitor de rede, CPU, GPU e memória que fica na barra de tarefas.

Antes de instalar:
- Instale pela sua própria conta do Windows. Se você usa uma conta sem
  administrador e digitar a senha de outra conta, os atalhos e a tarefa
  podem ir para a outra conta.
- O instalador não tem assinatura digital. Se o Windows mostrar
  "O Windows protegeu o computador" (SmartScreen), clique em
  "Mais informações" e depois em "Executar assim mesmo".

O que o instalador faz (pede administrador uma vez):
- Instala o PawnIO (driver assinado que o LibreHardwareMonitor usa para
  ler a temperatura da CPU), baixado do site oficial, se ainda não houver.
- Copia o LibreHardwareMonitor 0.9.6 (licença MPL-2.0, código em
  https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) e cria a
  tarefa "SysMonitor LHM", que o abre no logon, se ainda não houver.
- Instala o SysMonitor, que roda sem administrador.

Configurações ficam em %APPDATA%\SysMonitor.
Para desinstalar: Configurações > Aplicativos > SysMonitor.
```

- [ ] **Passo 4:** teste focado → OK; suíte inteira → OK.
- [ ] **Passo 5: commit**
```bash
git add installer/tarefa-lhm.xml installer/LibreHardwareMonitor.config installer/util-instalador.ps1 installer/LEIA-ME.txt tests/test_installer_files.py
git commit -m "Instalador: tarefa do LHM, config do LHM, script auxiliar e LEIA-ME"
```

### Tarefa 6: exe com PyInstaller (`build.ps1` etapa 1)

**Arquivos:**
- Criar: `requirements-build.txt`, `SysMonitor.spec`, `build.ps1`

**Interfaces:**
- Consome: `--verificar` (Tarefa 2), que imprime `SysMonitor 1.0.0 (...)` e sai 0.
- Produz: `build/pyinstaller/dist/SysMonitor/{SysMonitor.exe,SysMonitor-Bandeja.exe,_internal/}`;
  `build.ps1 [-SomenteExe]`.

- [ ] **Passo 1:** `requirements-build.txt`:
```text
pyinstaller==6.22.3
pyinstaller-hooks-contrib==2026.9
psutil==7.2.2
comtypes==1.4.17
```

- [ ] **Passo 2:** `SysMonitor.spec`:
```python
# PyInstaller spec: one folder, two console exes (the code hides its own
# console; a windowed exe behaves like pythonw, which fails to paint the
# layered Tk window — see sys_monitor.py hide_console_window).
# build.ps1 pre-generates comtypes.gen.UIAutomationClient in the venv so it
# can be bundled instead of generated at runtime.
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules('comtypes.gen') + ['comtypes.client', 'usage_limits_ui',
                                                'lhm_launcher', 'tkinter.messagebox',
                                                'tkinter.colorchooser']
common = dict(pathex=[SPECPATH], hiddenimports=hidden, excludes=['tests', 'backup'])

a_widget = Analysis(['sys_monitor.py'], **common)
a_tray = Analysis(['tray_monitor.py'], **common)

exe_widget = EXE(PYZ(a_widget.pure), a_widget.scripts, [], exclude_binaries=True,
                 name='SysMonitor', console=True)
exe_tray = EXE(PYZ(a_tray.pure), a_tray.scripts, [], exclude_binaries=True,
               name='SysMonitor-Bandeja', console=True)

coll = COLLECT(exe_widget, a_widget.binaries, a_widget.datas,
               exe_tray, a_tray.binaries, a_tray.datas,
               name='SysMonitor')
```

- [ ] **Passo 3:** `build.ps1` (somente ASCII), primeira versão:
```powershell
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
```

- [ ] **Passo 4:** rodar `powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1 -SomenteExe`.
  Esperado: os dois `--verificar` imprimem `SysMonitor 1.0.0 (widget)` / `(bandeja)`,
  `congelado: True` e `dados: C:\Users\<usuário>\AppData\Roaming\SysMonitor`; script sai 0.
  Falhou o `--verificar` por módulo faltando → acrescentar o módulo em `hidden` no `.spec` e rodar
  de novo. **Não** abrir o `SysMonitor.exe` sem `--verificar` (o widget do Mateus está rodando).
- [ ] **Passo 5:** a suíte inteira continua OK (o `.venv-build`/`build/` não entram no discover).
- [ ] **Passo 6: commit**
```bash
git add requirements-build.txt SysMonitor.spec build.ps1
git commit -m "Build: exe do widget e da bandeja com PyInstaller e --verificar"
```

### Tarefa 7: instalador Inno Setup e build completo

**Arquivos:**
- Criar: `installer/SysMonitor.iss`
- Modificar: `build.ps1` (etapas 3 e 4, depois do `if ($SomenteExe) { return }`)

**Interfaces:**
- Consome: `build/pyinstaller/dist/SysMonitor/` (Tarefa 6), `build/lhm/` (esta tarefa),
  `installer/util-instalador.ps1` e `installer/tarefa-lhm.xml` (Tarefa 5).
- Produz: `dist/SysMonitor-Setup-1.0.0.exe`.

- [ ] **Passo 1: Inno Setup.** Se não houver `ISCC.exe` em
  `%LOCALAPPDATA%\Programs\Inno Setup 6\` nem em `%ProgramFiles(x86)%\Inno Setup 6\`, rodar
  `winget install -e --id JRSoftware.InnoSetup --scope user --silent --accept-package-agreements --accept-source-agreements`.
  Se pedir UAC ou falhar, **pare e reporte** (o Mateus instala).

- [ ] **Passo 2:** acrescentar ao fim do `build.ps1`:
```powershell
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
```

- [ ] **Passo 3:** `installer/SysMonitor.iss` (UTF-8 **com BOM**):
```pascal
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
```
Se o ISCC reclamar de alguma assinatura (ex.: `CreateDownloadPage` com `nil`), conferir na ajuda
do Inno 6.7 instalada (`ISetup.chm`) e ajustar o mínimo; anotar o ajuste no relatório.

- [ ] **Passo 4:** rodar `powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1` (completo).
  Esperado: `OK: ...\dist\SysMonitor-Setup-1.0.0.exe`, sem erros no ISCC. **Não executar o setup**
  (pede admin e mexe no PC do Mateus; o teste é dele, no Sandbox).
- [ ] **Passo 5:** suíte inteira OK; `git status` não mostra `build/`, `dist/` nem `.venv-build/`.
- [ ] **Passo 6: commit**
```bash
git add installer/SysMonitor.iss build.ps1
git commit -m "Instalador Inno Setup com PawnIO, LHM e desinstalador completo"
```

**Fim do lote 2.** Reportar: hashes conferidos, saída dos dois `--verificar`, tamanho do setup,
ajustes feitos no `.iss`, e `git log --oneline` da branch.

---

## Parte C: fechamento (Claude)

### Tarefa 8: documentação

- Atualizar `docs/agentes/build-e-uso.md` (seção nova "Build e instalador": `build.ps1`,
  `-SomenteExe`, `.venv-build`, Inno via winget, onde ficam config/logs no modo exe),
  `docs/agentes/INDICE.md` (comando de build, specs/planos existem) e `docs/agentes/estado.md`
  (marco 1.0.0, preservando a mudança pendente) e o registro em
  `D:/dev/memoria-compartilhada/pedidos/2026-10-26-claude-sysmonitor-exe-instalador.md`.
- Commit só dos docs, na `versao-1.0`.

### Teste real (Mateus, nesta ordem; spec, seção Testes)

1. **Windows Sandbox** (habilitar: `Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM`
   como admin + reiniciar). Copiar `dist/SysMonitor-Setup-1.0.0.exe` para dentro.
   - Instalar: UAC uma vez; widget na barra; `schtasks /query /tn "SysMonitor LHM"`;
     `reg query HKLM\Software\SysMonitor`; atalhos no Menu Iniciar e no Inicializar.
     PawnIO pode não carregar no Sandbox → temperatura vazia e aviso no menu são o esperado.
     Anotar o código de saída do PawnIO no log do Setup (`%TEMP%\Setup Log *.txt`).
   - **Instalar de novo por cima** (Foco de revisão 1): registro continua `InstalledLHM=1`,
     `CreatedTask=1`; uma só tarefa; atalhos não duplicam; config mantida.
   - Menu do widget com o LHM fechado: aviso aparece; "Abrir LibreHardwareMonitor" abre.
   - Desinstalar sem marcar nada; depois reinstalar e desinstalar marcando as duas remoções.
2. **PC do Mateus**: fechar o widget `.py` antes; instalar; o instalador deve usar o PawnIO e o LHM
   existentes (`InstalledLHM=0`, `CreatedTask=0`); copiar `config.ini` para `%APPDATA%\SysMonitor`;
   apagar o atalho antigo `SysMonitor.lnk` do Menu Iniciar do usuário (o do `create_shortcut.py`).
   Voltar ao modo `.py`: `py -3.12 create_shortcut.py`.
3. **PC de um amigo**.

Merge na main, push e release só depois disso e com aprovação do Mateus.
