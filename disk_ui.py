"""The disks window: one block per physical disk, a row per volume. Draws disk_view() only."""
import os
import tkinter as tk

from disk_monitor import disk_view
from traffic_history_ui import BG, FG, centered_geometry, pointer_work_area

REFRESH_MS = 1000
BAR_WIDTH, BAR_HEIGHT = 160, 10
TROUGH = '#33373d'
DIM_FG = '#8a8f96'


def _open_in_explorer(letter):
    os.startfile(f'{letter}:\\')


class DiskWindow:
    title = 'SysMonitor · Discos'

    def __init__(self, master, monitor, prefs, open_volume=None, work_area=None):
        self.master = master
        self.monitor = monitor
        self.prefs = prefs
        self.open_volume = open_volume or _open_in_explorer
        self.work_area = work_area or pointer_work_area
        self.window = None
        self.body = None
        self.empty = None
        self.blocks = []
        self._keys = None
        self._after_id = None

    def show(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
            self.refresh()
            return
        window = self.window = tk.Toplevel(self.master)
        window.title(self.title)
        window.configure(bg=BG)
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.bind('<Escape>', lambda event: self.close())
        self.body = tk.Frame(window, bg=BG, padx=14, pady=10)
        self.body.pack(fill='both', expand=True)
        self.empty = tk.Label(self.body, text='', fg=DIM_FG, bg=BG, font=('Segoe UI', 10))
        self._keys = None
        self.refresh()
        window.update_idletasks()
        work = self.work_area() or (0, 0, self.master.winfo_screenwidth(), self.master.winfo_screenheight())
        window.geometry(centered_geometry(work, max(460, window.winfo_reqwidth()), window.winfo_reqheight()))

    def close(self):
        window, self.window = self.window, None
        after_id, self._after_id = self._after_id, None
        self.blocks, self._keys, self.body, self.empty = [], None, None, None
        if window is None:
            return
        try:
            if after_id is not None:
                window.after_cancel(after_id)
            window.destroy()
        except tk.TclError:
            pass  # Tk is already gone while the program closes.

    def refresh(self):
        if self.window is None:
            return
        if self._after_id is not None:
            try:
                self.window.after_cancel(self._after_id)
            except tk.TclError:
                pass
        view = disk_view(self.monitor.snapshot(), self.prefs(), FG)
        keys = [disk['key'] for disk in view]
        if keys != self._keys:
            self._rebuild(view)
            self._keys = keys
        for block, disk in zip(self.blocks, view):
            self._fill(block, disk)
        self._after_id = self.window.after(REFRESH_MS, self.refresh)

    def _rebuild(self, view):
        for child in self.body.winfo_children():
            if child is not self.empty:
                child.destroy()
        self.blocks = []
        if not view:
            self.empty.config(text='Nenhum disco encontrado')
            self.empty.pack(anchor='w')
            return
        self.empty.pack_forget()
        for index, disk in enumerate(view):
            frame = tk.Frame(self.body, bg=BG)
            frame.pack(fill='x', anchor='w', pady=(0 if index == 0 else 12, 0))
            head = tk.Frame(frame, bg=BG)
            head.pack(fill='x')
            title = tk.Label(head, fg=FG, bg=BG, font=('Segoe UI', 10, 'bold'), anchor='w')
            title.pack(side='left')
            activity = tk.Label(head, bg=BG, font=('Segoe UI', 10), anchor='e')
            activity.pack(side='right', padx=(16, 0))
            rates = tk.Label(frame, fg=FG, bg=BG, font=('Segoe UI', 9), anchor='w')
            rates.pack(fill='x', padx=(12, 0))
            rows = []
            for volume in disk['volumes']:
                row = tk.Frame(frame, bg=BG)
                row.pack(fill='x', padx=(12, 0), pady=(3, 0))
                name = tk.Label(row, fg=FG, bg=BG, font=('Segoe UI', 9), anchor='w', width=14, cursor='hand2')
                name.pack(side='left')
                bar = tk.Canvas(row, width=BAR_WIDTH, height=BAR_HEIGHT, bg=TROUGH, highlightthickness=0,
                                cursor='hand2')
                bar.pack(side='left', padx=(0, 10))
                space = tk.Label(row, fg=FG, bg=BG, font=('Segoe UI', 9), anchor='w', cursor='hand2')
                space.pack(side='left')
                free = tk.Label(row, fg=DIM_FG, bg=BG, font=('Segoe UI', 9), anchor='w', cursor='hand2')
                free.pack(side='left', padx=(10, 0))
                for widget in (row, name, bar, space, free):
                    widget.bind('<Double-Button-1>',
                                lambda event, letter=volume['letter']: self.open_volume(letter))
                rows.append({'name': name, 'bar': bar, 'space': space, 'free': free})
            self.blocks.append({'title': title, 'activity': activity, 'rates': rates, 'volumes': rows})

    @staticmethod
    def _fill(block, disk):
        block['title'].config(text=disk['title'])
        block['activity'].config(text=disk['activity'], fg=disk['activity_color'])
        block['rates'].config(text=disk['rates'])
        for row, volume in zip(block['volumes'], disk['volumes']):
            row['name'].config(text=volume['name'])
            row['space'].config(text=volume['space'])
            row['free'].config(text=volume['free'])
            bar = row['bar']
            bar.delete('all')
            if volume['fraction'] is not None:
                bar.create_rectangle(0, 0, int(BAR_WIDTH * volume['fraction']), BAR_HEIGHT,
                                     fill=volume['bar_color'], width=0)
