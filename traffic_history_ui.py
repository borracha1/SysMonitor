"""History window: keeps the screen state and draws what traffic_history computes.

A Toplevel of the hidden root, never of the widget embedded in Explorer, so it
survives the widget being rebuilt when Explorer restarts.
"""
import ctypes
from ctypes import wintypes
import tkinter as tk

from traffic_history import (ALL_SERIES, ZOOM_STEP, build_chart, selection_view, summarize,
                             x_to_time, zoom_view)

BG = '#15171a'
FG = '#e6e6e6'
SELECTED_BG = '#2f6fb0'
SELECTED_FG = '#ffffff'
NORMAL_BG = 'SystemButtonFace'
NORMAL_FG = 'SystemButtonText'
LEGEND_ACTIVE_BG = '#3a3f46'
GRID = '#33373d'
PING_COLOR = '#c9a0ff'
SELECTION_COLOR = '#ffffff'
MARK_COLORS = {1: '#6b2a2a', 2: '#d83a3a'}
WIDTH, HEIGHT = 800, 400
REFRESH_MS = 5000
DRAG_MIN_PX = 4
PERIODS = ((300, '5 min'), (900, '15 min'), (3600, '1 h'), (14400, '4 h'))


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
        self.period_s = 3600
        self.series_filter = None
        self.view = None  # (start, end) while frozen by zoom or selection; None is live.
        self.window = None
        self.canvas = None
        self._buttons = {}
        self._legend = {}
        self._summary = None
        self._summary_shown = False
        self._chart = None
        self._drag = None
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
        self._legend = {}
        self._summary = None
        self._summary_shown = False
        self._chart = None
        self._drag = None
        self.view = None
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
        window.minsize(620, 280)
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.bind('<Escape>', self._on_escape)
        for key in ('<plus>', '<equal>', '<KP_Add>'):
            window.bind(key, lambda event: self._zoom(ZOOM_STEP))
        for key in ('<minus>', '<KP_Subtract>'):
            window.bind(key, lambda event: self._zoom(1 / ZOOM_STEP))
        self._build_buttons(window)
        self._build_legend(window)
        self._summary = tk.Label(window, text='', fg=FG, bg=BG, anchor='w', justify='left',
                                 wraplength=WIDTH - 16)
        self.canvas = tk.Canvas(window, bg=BG, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda event: self.redraw())
        self.canvas.bind('<ButtonPress-1>', self._drag_start)
        self.canvas.bind('<B1-Motion>', self._drag_move)
        self.canvas.bind('<ButtonRelease-1>', self._drag_end)
        self.canvas.bind('<MouseWheel>', self._on_wheel)
        window.focus_force()
        self._after_id = window.after(REFRESH_MS, self._refresh)

    def _build_buttons(self, window):
        row = tk.Frame(window, bg=BG)
        row.pack(fill='x', padx=8, pady=(6, 2))
        self._buttons = {}
        for family, text in (('ipv4', 'IPv4'), ('ipv6', 'IPv6')):
            button = tk.Button(row, text=text, width=6, command=lambda value=family: self._select_family(value))
            button.pack(side='left', padx=2)
            self._buttons[family] = button
        for index, (period, text) in enumerate(PERIODS):
            button = tk.Button(row, text=text, width=6, command=lambda value=period: self._select_period(value))
            button.pack(side='left', padx=(14 if index == 0 else 2, 2))
            self._buttons[period] = button
        for index, (text, factor) in enumerate((('+', ZOOM_STEP), ('−', 1 / ZOOM_STEP))):
            button = tk.Button(row, text=text, width=3, command=lambda value=factor: self._zoom(value))
            button.pack(side='left', padx=(14 if index == 0 else 2, 2))

    def _build_legend(self, window):
        row = tk.Frame(window, bg=BG)
        row.pack(fill='x', padx=8, pady=(0, 2))
        self._legend = {}
        for name, items in (('down', (('↓ download', self.accent_down),)),
                            ('up', (('↑ upload', self.accent_up),)),
                            ('ping', (('ping', PING_COLOR),)),
                            ('loss', (('perda:', FG), ('▌', MARK_COLORS[1]), ('um IP sem resposta', FG),
                                      ('▌', MARK_COLORS[2]), ('todos sem resposta', FG)))):
            labels = []
            for index, (text, color) in enumerate(items):
                label = tk.Label(row, text=text, fg=color, bg=BG, cursor='hand2')
                label.pack(side='left', padx=(10 if index == 0 else 0, 2))
                label.bind('<Button-1>', lambda event, value=name: self._select_series(value))
                labels.append(label)
            self._legend[name] = labels

    def _select_family(self, family):
        self.family = family
        self._update_buttons()
        self.redraw()

    def _select_period(self, period_s):
        self.period_s = period_s
        self.view = None
        self._update_buttons()
        self.redraw()

    def _select_series(self, name):
        self.series_filter = None if self.series_filter == name else name
        self._update_buttons()
        self.redraw()

    def _visible_series(self):
        return ALL_SERIES if self.series_filter is None else {self.series_filter}

    def _update_buttons(self):
        current = (self.family,) if self.view is not None else (self.family, self.period_s)
        for key, button in self._buttons.items():
            selected = key in current
            button.config(relief='sunken' if selected else 'raised',
                          bg=SELECTED_BG if selected else NORMAL_BG,
                          fg=SELECTED_FG if selected else NORMAL_FG)
        for name, labels in self._legend.items():
            for label in labels:
                label.config(bg=LEGEND_ACTIVE_BG if name == self.series_filter else BG)

    def _current_range(self):
        if self.view is not None:
            return self.view
        now = self.history.clock()
        return now - self.period_s, now

    def _refresh(self):
        self.redraw()
        if self.window is not None:
            self._after_id = self.window.after(REFRESH_MS, self._refresh)

    def _zoom(self, factor, x=None):
        start, end = self._current_range()
        anchor = (start + end) / 2
        chart = self._chart
        if x is not None and chart is not None and chart.plot[0] <= x <= chart.plot[2]:
            anchor = x_to_time(x, chart.plot, start, end)
        self.view = zoom_view(start, end, factor, anchor, self.history.clock())
        self._update_buttons()
        self.redraw()

    def _on_wheel(self, event):
        self._zoom(ZOOM_STEP if event.delta > 0 else 1 / ZOOM_STEP, event.x)

    def _drag_start(self, event):
        chart = self._chart
        if chart is None:
            return
        x0, y0, x1, y1 = chart.plot
        if not (x0 <= event.x <= x1 and y0 <= event.y <= y1):
            return
        item = self.canvas.create_rectangle(event.x, y0, event.x, y1, fill=SELECTION_COLOR,
                                            stipple='gray25', outline=SELECTION_COLOR)
        # The range on screen now: the clock and the window may change during the drag.
        self._drag = dict(x=event.x, item=item, plot=chart.plot, range=self._current_range())

    def _drag_move(self, event):
        drag = self._drag
        if drag is None:
            return
        x0, y0, x1, y1 = drag['plot']
        self.canvas.coords(drag['item'], drag['x'], y0, min(x1, max(x0, event.x)), y1)

    def _drag_end(self, event):
        drag, self._drag = self._drag, None
        if drag is None:
            return
        self.canvas.delete(drag['item'])
        x0, _, x1, _ = drag['plot']
        x = min(x1, max(x0, event.x))
        if abs(x - drag['x']) >= DRAG_MIN_PX:
            start, end = drag['range']
            self.view = selection_view(x_to_time(drag['x'], drag['plot'], start, end),
                                       x_to_time(x, drag['plot'], start, end), self.history.clock())
            self._update_buttons()
        self.redraw()

    def _on_escape(self, event):
        drag, self._drag = self._drag, None
        if drag is None:
            self.close()
            return
        self.canvas.delete(drag['item'])
        self.redraw()

    def _update_summary(self, points, start, end, series):
        if self.view is None:
            if self._summary_shown:
                self._summary.pack_forget()
                self._summary_shown = False
            return
        self._summary.config(text=summarize(points, start, end, series, self.fmt_speed),
                             wraplength=max(200, self.canvas.winfo_width() - 16))
        if not self._summary_shown:
            self._summary.pack(fill='x', padx=8, pady=(0, 2), before=self.canvas)
            self._summary_shown = True

    def redraw(self):
        canvas = self.canvas
        if canvas is None or self._drag is not None:
            return  # Redrawing during a drag would erase the selection band.
        canvas.delete('all')
        start, end = self._current_range()
        series = self._visible_series()
        points = self.history.points_between(self.family, start, end)
        self._update_summary(points, start, end, series)
        chart = self._chart = build_chart(points, canvas.winfo_width(), canvas.winfo_height(),
                                          end, end - start, series)
        if chart is None:
            return
        x0, y0, x1, y1 = chart.plot
        for left, right, mark in chart.bands:
            canvas.create_rectangle(left, y0, right, y1, fill=MARK_COLORS[mark], width=0)
        for y, value in chart.y_ticks:
            canvas.create_line(x0, y, x1, y, fill=GRID)
            canvas.create_text(x0 - 6, y, text=self.fmt_speed(value), fill=FG, anchor='e')
        for y, value in chart.ping_ticks:
            canvas.create_text(x1 + 6, y, text=f'{value} ms', fill=PING_COLOR, anchor='w')
        for x, text in chart.x_ticks:
            canvas.create_line(x, y1, x, y1 + 4, fill=FG)
            canvas.create_text(x, y1 + 6, text=text, fill=FG, anchor='n')
        for segments, color in ((chart.up, self.accent_up), (chart.down, self.accent_down),
                                (chart.ping, PING_COLOR)):
            for segment in segments:
                coordinates = [value for point in segment for value in point]
                if len(segment) == 1:  # create_line needs two points.
                    coordinates += [segment[0][0] + 1, segment[0][1]]
                canvas.create_line(*coordinates, fill=color, width=1)
        if not points:
            message = 'Coletando dados…' if self.view is None else 'Sem dados neste trecho'
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=message, fill=FG)
