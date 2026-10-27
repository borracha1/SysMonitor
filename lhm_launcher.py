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
