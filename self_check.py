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
