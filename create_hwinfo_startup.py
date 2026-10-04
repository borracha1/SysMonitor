"""
Creates a Startup shortcut for HWiNFO64 that launches it minimized
(so the Sensor Status window doesn't pop up on every login), keeping
Shared Memory Support enabled via HWiNFO64.INI (SensorsSM=1).
"""
import os
import winshell
from win32com.client import Dispatch

HWINFO_EXE = r"C:\Program Files\HWiNFO64\HWiNFO64.EXE"


def main():
    if not os.path.exists(HWINFO_EXE):
        print(f"HWiNFO64.EXE not found at {HWINFO_EXE}")
        return
    shell = Dispatch("WScript.Shell")
    startup_dir = winshell.startup()
    lnk_path = os.path.join(startup_dir, "HWiNFO64.lnk")
    shortcut = shell.CreateShortCut(lnk_path)
    shortcut.Targetpath = HWINFO_EXE
    shortcut.WorkingDirectory = os.path.dirname(HWINFO_EXE)
    shortcut.WindowStyle = 7  # 7 = minimized
    shortcut.save()
    print(f"Startup shortcut created: {lnk_path}")
    print("HWiNFO64 will launch minimized on next login.")


if __name__ == "__main__":
    main()
