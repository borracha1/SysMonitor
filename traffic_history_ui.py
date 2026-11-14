"""History window: keeps the screen state and draws what traffic_history computes.

A Toplevel of the hidden root, never of the widget embedded in Explorer, so it
survives the widget being rebuilt when Explorer restarts.
"""
import ctypes
from ctypes import wintypes
import tkinter as tk

from traffic_history import (KIND_SERIES, ZOOM_STEP, build_chart, selection_view, summarize,
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
PING2_COLOR = '#5fd7c0'
PING_WORST_COLOR = '#9aa0a6'
PING_WORST_DASH = (4, 3)
DIM_FG = '#8a8f96'
SELECTION_OUTLINE = '#7fb3e6'
MARK_COLORS = {1: '#6b2a2a', 2: '#d83a3a'}
WIDTH, HEIGHT = 800, 420
MIN_WIDTH, MIN_HEIGHT = 640, 340
CASCADE_PX = 36  # The latency window opens a little off the traffic one, not exactly over it.
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


class HistoryWindow:
    """Base of the two history windows: buttons, periods, zoom, selection and refresh. A subclass
    sets `kind` ('traffic' or 'latency'), the title and what its legend and panel draw."""
    kind = None
    title = ''
    offset = 0

    def __init__(self, master, history, fmt_speed, accent_up, accent_down, work_area=None,
                 ping_targets=None):
        self.master = master
        self.history = history
        self.fmt_speed = fmt_speed
        self.accent_up = accent_up
        self.accent_down = accent_down
        self.work_area = work_area or pointer_work_area
        self.ping_targets = ping_targets or (lambda: {})  # family -> (ip1, ip2) now configured
        self.family = 'ipv4'
        self.period_s = 3600
        self.series_filter = None
        self.view = None  # (start, end) while frozen by zoom or selection; None is live.
        self.window = None
        self.canvas = None
        self._buttons = {}
        self._legend = {}
        self._legend_frames = {}
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
        self._legend_frames = {}
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
        window.title(self.title)
        window.configure(bg=BG)
        work = self.work_area()
        if work is None:
            work = (0, 0, self.master.winfo_screenwidth(), self.master.winfo_screenheight())
        window.geometry(centered_geometry((work[0] + self.offset, work[1] + self.offset, work[2], work[3]),
                                          WIDTH, HEIGHT))
        window.minsize(MIN_WIDTH, MIN_HEIGHT)
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.bind('<Escape>', self._on_escape)
        for key in ('<plus>', '<equal>', '<KP_Add>'):
            window.bind(key, lambda event: self._zoom(ZOOM_STEP))
        for key in ('<minus>', '<KP_Subtract>'):
            window.bind(key, lambda event: self._zoom(1 / ZOOM_STEP))
        self._build_buttons(window)
        self.canvas = tk.Canvas(window, bg=BG, highlightthickness=0)
        self._build_legend(self.canvas)
        self._summary = tk.Label(window, text='', fg=FG, bg=BG, anchor='w', justify='left',
                                 wraplength=WIDTH - 16)
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

    def _legend_groups(self):
        """[(frame key, title, [(series, sample text, sample colour, name text)])] of this kind."""
        raise NotImplementedError

    def _build_legend(self, canvas):
        """One legend placed over the canvas above the panel; the loss one goes under the chart."""
        self._legend = {}
        self._legend_frames = {}
        for key, title, entries in self._legend_groups():
            frame = tk.Frame(canvas, bg=BG)
            self._legend_frames[key] = frame
            if title:
                tk.Label(frame, text=title, fg=FG, bg=BG, font=('Segoe UI', 9, 'bold')).pack(side='left')
            for name, sample, color, text in entries:
                self._legend[name] = self._legend_item(frame, name, [(sample, color), (text, FG)])
        if 'loss' in self._legend_frames:
            self._legend['loss'] = self._legend_item(
                self._legend_frames['loss'], 'loss',
                [('perda:', FG), ('▌', MARK_COLORS[1]), ('um IP sem resposta', FG), ('▌', MARK_COLORS[2]),
                 ('todos sem resposta', FG)])

    def _legend_item(self, frame, name, parts):
        """Clickable labels of one legend entry. A series entry is [colour sample, name] on screen
        and returned as [name, sample], so labels[0] is the text the code rewrites."""
        labels = []
        for index, (text, color) in enumerate(parts):
            label = tk.Label(frame, text=text, fg=color, bg=BG, cursor='hand2')
            label.pack(side='left', padx=((12 if name != 'loss' else 6) if index == 0 else 0, 3))
            label.bind('<Button-1>', lambda event, value=name: self._select_series(value))
            labels.append(label)
        return labels if name == 'loss' else labels[::-1]

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
        return KIND_SERIES[self.kind] if self.series_filter is None else {self.series_filter}

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
        item = self.canvas.create_rectangle(event.x, y0, event.x, y1, fill=SELECTED_BG,
                                            stipple='gray25', outline=SELECTION_OUTLINE)
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

    def _series_labels(self, points, legend=False):
        """Text of the series whose name depends on the data; {} when the kind has none."""
        return {}

    @staticmethod
    def _sample_text(name):
        return '╌╌' if name == 'pingw' else '━'

    def _update_legend_text(self, labels):
        for name, labels_of in self._legend.items():
            background = LEGEND_ACTIVE_BG if name == self.series_filter else BG
            text = labels.get(name)
            for index, label in enumerate(labels_of):
                if text is None:  # Fixed text: only the highlight changes.
                    label.config(bg=background)
                    continue
                # labels_of[1] is the colour sample: it disappears together with its name.
                label.config(text=text if index == 0 else (self._sample_text(name) if text else ''),
                             bg=background)

    def _update_summary(self, points, start, end, series, labels=None):
        if self.view is None:
            if self._summary_shown:
                self._summary.pack_forget()
                self._summary_shown = False
            return
        self._summary.config(text=summarize(points, start, end, series, self.fmt_speed, ping_labels=labels),
                             wraplength=max(200, self.canvas.winfo_width() - 16))
        if not self._summary_shown:
            self._summary.pack(fill='x', padx=8, pady=(0, 2), before=self.canvas)
            self._summary_shown = True

    def _place_legends(self, chart):
        x0, y0, _, y1 = chart.plot
        for key, frame in self._legend_frames.items():
            y, anchor = (y1 + 24, 'nw') if key == 'loss' else (y0 - 4, 'sw')
            self.canvas.create_window(x0 - 4, y, window=frame, anchor=anchor)

    def _panel(self, chart, series):
        """(axis ticks, their formatter, message over the panel) of this kind."""
        raise NotImplementedError

    def _draw_panel(self, panel, ticks, fmt, message):
        canvas = self.canvas
        x0, y0, x1, y1 = panel
        canvas.create_line(x0, y1, x1, y1, fill=FG)
        for y, value in ticks:
            canvas.create_line(x0, y, x1, y, fill=GRID)
            canvas.create_text(x0 - 6, y, text=fmt(value), fill=FG, anchor='e')
        if message:
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=message, fill=DIM_FG)

    def _lines(self, chart):
        """[(segments, colour, dash)] in drawing order (the last one stays on top)."""
        raise NotImplementedError

    def redraw(self):
        canvas = self.canvas
        if canvas is None or self._drag is not None:
            return  # Redrawing during a drag would erase the selection band.
        canvas.delete('all')
        start, end = self._current_range()
        series = self._visible_series()
        points = self.history.points_between(self.family, start, end)
        self._update_legend_text(self._series_labels(points, legend=True))
        self._update_summary(points, start, end, series,
                             {name: text for name, text in self._series_labels(points).items() if text})
        chart = self._chart = build_chart(points, canvas.winfo_width(), canvas.winfo_height(),
                                          end, end - start, series, kind=self.kind)
        if chart is None:
            return
        x0, y0, x1, y1 = chart.plot
        self._place_legends(chart)
        for left, right, mark in chart.bands:  # Loss marks sit at the back (latency only).
            canvas.create_rectangle(left, y0, right, y1, fill=MARK_COLORS[mark], width=0)
        self._draw_panel(chart.plot, *self._panel(chart, series))
        for x, text in chart.x_ticks:
            canvas.create_line(x, y1, x, y1 + 4, fill=FG)
            canvas.create_text(x, y1 + 6, text=text, fill=FG, anchor='n')
        for segments, color, dash in self._lines(chart):
            for segment in segments:
                coordinates = [value for point in segment for value in point]
                if len(segment) == 1:  # create_line needs two points.
                    coordinates += [segment[0][0] + 1, segment[0][1]]
                options = {'dash': dash} if dash else {}
                canvas.create_line(*coordinates, fill=color, width=1, **options)
        if not points:
            message = 'Coletando dados…' if self.view is None else 'Sem dados neste trecho'
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=message, fill=FG)


class TrafficHistoryWindow(HistoryWindow):
    """Download and upload only: one panel, Mbps at the left."""
    kind = 'traffic'
    title = 'SysMonitor · Tráfego (estimado)'

    def _legend_groups(self):
        return (('traffic', 'Tráfego', (('down', '━', self.accent_down, '↓ download'),
                                        ('up', '━', self.accent_up, '↑ upload'))),)

    def _panel(self, chart, series):
        return chart.y_ticks, self.fmt_speed, None

    def _lines(self, chart):
        return ((chart.up, self.accent_up, None), (chart.down, self.accent_down, None))


class LatencyHistoryWindow(HistoryWindow):
    """One ms line per IP and the loss bands behind them: one panel, ms at the left."""
    kind = 'latency'
    title = 'SysMonitor · Latência e perda'
    offset = CASCADE_PX

    def _legend_groups(self):
        return (('latency', 'Latência', (('ping', '━', PING_COLOR, ''), ('ping2', '━', PING2_COLOR, ''),
                                         ('pingw', '╌╌', PING_WORST_COLOR, ''))),
                ('loss', None, ()))

    def _series_labels(self, points, legend=False):
        """Text of each ping series; '' hides one that has no IP nor data. The summary says
        'ping <ip>'; the legend sits under the title and says just the IP."""
        try:
            targets = tuple(self.ping_targets().get(self.family, ()))
        except Exception:  # The legend must never stop the chart.
            targets = ()
        labels = {}
        for position, (name, field) in enumerate((('ping', 'ping'), ('ping2', 'ping2'))):
            ip = targets[position] if position < len(targets) else ''
            if ip:
                labels[name] = ip if legend else f'ping {ip}'
            elif any(getattr(point, field) is not None for point in points):
                labels[name] = 'ping' if position == 0 else 'ping 2'
            else:
                labels[name] = ''
        has_worst = any(point.worst is not None for point in points)
        labels['pingw'] = ('pior dos dois' if legend else 'ping (pior dos dois)') if has_worst else ''
        return labels

    def _panel(self, chart, series):
        message = None
        if series & {'ping', 'ping2', 'pingw'} and not (chart.ping or chart.ping2 or chart.ping_worst):
            message = 'sem dados de ping'
        return chart.ping_ticks, lambda value: f'{value} ms', message

    def _lines(self, chart):
        return ((chart.ping_worst, PING_WORST_COLOR, PING_WORST_DASH), (chart.ping2, PING2_COLOR, None),
                (chart.ping, PING_COLOR, None))
