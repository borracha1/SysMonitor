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
