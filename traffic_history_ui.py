"""History window: only draws what traffic_history.build_chart returns.

A Toplevel of the hidden root, never of the widget embedded in Explorer, so it
survives the widget being rebuilt when Explorer restarts.
"""
import ctypes
from ctypes import wintypes
import tkinter as tk

from traffic_history import build_chart

BG = '#15171a'
FG = '#e6e6e6'
GRID = '#33373d'
MARK_COLORS = {1: '#6b2a2a', 2: '#d83a3a'}
WIDTH, HEIGHT = 800, 360
REFRESH_MS = 5000
HOUR = 3600
FOUR_HOURS = 4 * HOUR


class _MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]


def pointer_work_area():
    """Work area (left, top, right, bottom) of the screen under the mouse, or None."""
    try:
        user32 = ctypes.WinDLL('user32')  # Private instance: argtypes stay local.
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(user32.MonitorFromPoint(point, 2), ctypes.byref(info)):
            return None
        work = info.rcWork
        return work.left, work.top, work.right, work.bottom
    except (OSError, AttributeError):
        return None


def centered_geometry(work, width, height):
    left, top, right, bottom = work
    x = left + max(0, (right - left - width) // 2)
    y = top + max(0, (bottom - top - height) // 2)
    return f'{width}x{height}+{x}+{y}'


class TrafficHistoryWindow:
    def __init__(self, master, history, fmt_speed, accent_up, accent_down, work_area=None):
        self.master = master
        self.history = history
        self.fmt_speed = fmt_speed
        self.accent_up = accent_up
        self.accent_down = accent_down
        self.work_area = work_area or pointer_work_area
        self.family = 'ipv4'
        self.period_s = HOUR
        self.window = None
        self.canvas = None
        self._buttons = {}
        self._after_id = None

    def show(self, family=None):
        if family is not None:
            self.family = family
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
        else:
            self._build()
        self._update_buttons()
        self.redraw()

    def close(self):
        window, self.window = self.window, None
        self.canvas = None
        self._buttons = {}
        after_id, self._after_id = self._after_id, None
        if window is None:
            return
        try:
            if after_id is not None:
                window.after_cancel(after_id)
            window.destroy()
        except tk.TclError:
            pass  # Tk is already gone while the program closes.

    def _build(self):
        window = self.window = tk.Toplevel(self.master)
        window.title('SysMonitor · Histórico de tráfego (estimado)')
        window.configure(bg=BG)
        work = self.work_area()
        if work is None:
            work = (0, 0, self.master.winfo_screenwidth(), self.master.winfo_screenheight())
        window.geometry(centered_geometry(work, WIDTH, HEIGHT))
        window.minsize(420, 240)
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.bind('<Escape>', lambda event: self.close())
        header = tk.Frame(window, bg=BG)
        header.pack(fill='x', padx=8, pady=6)
        self._buttons = {}
        for key, text, command in (
                ('ipv4', 'IPv4', lambda: self._select_family('ipv4')),
                ('ipv6', 'IPv6', lambda: self._select_family('ipv6')),
                (HOUR, '1 h', lambda: self._select_period(HOUR)),
                (FOUR_HOURS, '4 h', lambda: self._select_period(FOUR_HOURS))):
            button = tk.Button(header, text=text, width=5, command=command)
            button.pack(side='left', padx=(12 if key == HOUR else 2, 2))
            self._buttons[key] = button
        for text, color in (('↓ download', self.accent_down), ('↑ upload', self.accent_up),
                            ('▌ um IP sem resposta', MARK_COLORS[1]),
                            ('▌ todos sem resposta', MARK_COLORS[2])):
            tk.Label(header, text=text, fg=color, bg=BG).pack(side='right', padx=4)
        self.canvas = tk.Canvas(window, bg=BG, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda event: self.redraw())
        self._after_id = window.after(REFRESH_MS, self._refresh)

    def _select_family(self, family):
        self.family = family
        self._update_buttons()
        self.redraw()

    def _select_period(self, period_s):
        self.period_s = period_s
        self._update_buttons()
        self.redraw()

    def _update_buttons(self):
        for key, button in self._buttons.items():
            selected = key in (self.family, self.period_s)
            button.config(relief='sunken' if selected else 'raised')

    def _refresh(self):
        self.redraw()
        if self.window is not None:
            self._after_id = self.window.after(REFRESH_MS, self._refresh)

    def redraw(self):
        canvas = self.canvas
        if canvas is None:
            return
        canvas.delete('all')
        points = self.history.points(self.family, self.period_s)
        chart = build_chart(points, canvas.winfo_width(), canvas.winfo_height(),
                            self.history.clock(), self.period_s)
        if chart is None:
            return
        x0, y0, x1, y1 = chart.plot
        for left, right, mark in chart.bands:
            canvas.create_rectangle(left, y0, right, y1, fill=MARK_COLORS[mark], width=0)
        for y, value in chart.y_ticks:
            canvas.create_line(x0, y, x1, y, fill=GRID)
            canvas.create_text(x0 - 6, y, text=self.fmt_speed(value), fill=FG, anchor='e')
        for x, text in chart.x_ticks:
            canvas.create_line(x, y1, x, y1 + 4, fill=FG)
            canvas.create_text(x, y1 + 6, text=text, fill=FG, anchor='n')
        for segments, color in ((chart.up, self.accent_up), (chart.down, self.accent_down)):
            for segment in segments:
                coordinates = [value for point in segment for value in point]
                if len(segment) == 1:  # create_line needs two points.
                    coordinates += [segment[0][0] + 1, segment[0][1]]
                canvas.create_line(*coordinates, fill=color, width=1)
        if not points:
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text='Coletando dados…', fill=FG)
