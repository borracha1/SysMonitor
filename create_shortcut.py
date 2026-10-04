"""
create_shortcut.py — creates a Start Menu shortcut for SysMonitor and
optionally registers it to run at Windows startup (current user only).
"""
import os
import sys
import winshell
from win32com.client import Dispatch

APP_DIR = os.path.dirname(os.path.abspath(__file__))
# Intentionally uses the regular python.exe (not pythonw.exe): on this
# machine pythonw's layered/alpha Tkinter window fails to paint. The script
# itself hides its own console window on startup (see hide_console_window()
# in sys_monitor.py), so no black window is shown either way.
PYTHONW = sys.executable
SCRIPT = os.path.join(APP_DIR, "sys_monitor.py")


def create_shortcut(path: str, target: str, args: str, workdir: str, icon: str | None = None):
    shell = Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(path)
    shortcut.Targetpath = target
    shortcut.Arguments = args
    shortcut.WorkingDirectory = workdir
    shortcut.WindowStyle = 7  # 7 = start minimized (console flashes minimized, then hides itself)
    if icon:
        shortcut.IconLocation = icon
    shortcut.save()


def main():
    print(f"Using interpreter: {PYTHONW}")
    start_menu = winshell.start_menu()
    lnk_path = os.path.join(start_menu, "Programs", "SysMonitor.lnk")
    create_shortcut(lnk_path, PYTHONW, f'"{SCRIPT}"', APP_DIR)
    print(f"Start Menu shortcut created: {lnk_path}")

    startup_dir = winshell.startup()
    startup_lnk = os.path.join(startup_dir, "SysMonitor.lnk")
    create_shortcut(startup_lnk, PYTHONW, f'"{SCRIPT}"', APP_DIR)
    print(f"Startup shortcut created: {startup_lnk}")
    print("SysMonitor will now start automatically when you log in.")


if __name__ == "__main__":
    main()
