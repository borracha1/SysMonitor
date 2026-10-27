# PyInstaller spec: one folder, two console exes (the code hides its own
# console; a windowed exe behaves like pythonw, which fails to paint the
# layered Tk window — see sys_monitor.py hide_console_window).
# build.ps1 pre-generates comtypes.gen.UIAutomationClient in the venv so it
# can be bundled instead of generated at runtime.
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules('comtypes.gen') + ['comtypes.client', 'usage_limits_ui',
                                                'lhm_launcher', 'screen_side', 'tkinter.messagebox',
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
