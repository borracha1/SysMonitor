"""One threshold editor per hidden Tk root; shared by widget and tray."""
import configparser
import tkinter as tk
from tkinter import ttk, colorchooser
from usage_limits import (load_preferences, validate_preferences, save_limits, limit_settings,
                          LEVELS, DEFAULT_COLORS, color_text_color)


def open_limits_editor(master, cfg, path, on_saved=None):
    editor = getattr(master, '_usage_limits_editor', None)
    if editor is not None and editor.window.winfo_exists():
        editor.window.lift()
        editor.window.focus_force()
        return editor
    editor = LimitsEditor(master, cfg, path, on_saved)
    master._usage_limits_editor = editor
    return editor


class TrayLimitsPreferences:
    """Tk lives on the Win32 message thread, never the refresh worker."""
    def __init__(self, cfg, path):
        self.cfg, self.path = cfg, path
        self.limits = load_preferences(cfg)
        self.root = None
        self._showing = False

    def _saved(self, values):
        self.limits = values  # Publish a new complete snapshot; worker only reads it.

    def show(self):
        if self.root is None:
            self.root = tk.Tk()
            self.root.withdraw()
        editor = open_limits_editor(self.root, self.cfg, self.path, self._saved)
        if self._showing:
            return
        self._showing = True
        try:
            self.root.wait_window(editor.window)
        finally:
            self._showing = False

    def close(self):
        if self.root is not None:
            self.root.destroy()
            self.root = None


class LimitsEditor:
    def __init__(self, master, cfg, path, on_saved):
        self.master, self.cfg, self.path, self.on_saved = master, cfg, path, on_saved
        self.window = tk.Toplevel(master)
        self.window.title('Limites de uso e temperatura — SysMonitor')
        self.window.resizable(False, False)
        self.window.attributes('-topmost', True)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill='both', expand=True)
        values = load_preferences(cfg)
        self.colors = dict(zip(LEVELS, values['colors']))
        self.color_boxes = {}
        for column, level in enumerate(LEVELS, 1):
            box = tk.Label(frame, text=level.title(), bg=self.colors[level], fg=color_text_color(self.colors[level]),
                           padx=10, pady=4, cursor='hand2', width=8)
            box.grid(row=0, column=column, padx=5)
            box.bind('<Button-1>', lambda event, level=level: self.choose_color(level))
            self.color_boxes[level] = box
        for row, title in ((1, 'Uso (%)'), (5, 'Temperatura (°C)')):
            ttk.Label(frame, text=title, font=('Segoe UI', 11, 'bold')).grid(
                row=row, column=0, columnspan=4, sticky='w', pady=(10, 4))
        self.entries = {}
        for row, metric in ((2, 'cpu'), (3, 'gpu'), (4, 'mem'), (6, 'cpu_temp'), (7, 'gpu_temp')):
            numbers = values[metric]
            ttk.Label(frame, text={'cpu': 'CPU', 'gpu': 'GPU', 'mem': 'MEMÓRIA'}[metric.split('_')[0]]).grid(row=row, column=0, sticky='w', padx=(0, 15))
            self.entries[metric] = []
            for column, value in enumerate(numbers, 1):
                entry = ttk.Entry(frame, width=10)
                entry.insert(0, f'{value:g}')
                entry.grid(row=row, column=column, padx=5, pady=5)
                self.entries[metric].append(entry)
        ttk.Label(frame, text='0 ≤ Low < Warning < High (decimais com ponto).\n'
                  'Uso: 0–100%. Temperatura: 0–120 °C.\n'
                  'Abaixo de Low: cor normal. Vale a cor do maior limite atingido.\n'
                  'Clique nas caixas acima para escolher as cores globais.').grid(
                      row=8, column=0, columnspan=4, sticky='w', pady=(12, 4))
        self.error = ttk.Label(frame, text='', foreground='#b00020', wraplength=440)
        self.error.grid(row=9, column=0, columnspan=4, sticky='w')
        buttons = ttk.Frame(frame)
        buttons.grid(row=10, column=0, columnspan=4, sticky='ew', pady=(12, 0))
        ttk.Button(buttons, text='Restaurar cores padrão', command=self.restore_colors).pack(side='left', padx=(0, 20))
        ttk.Button(buttons, text='Salvar', command=self.save).pack(side='left', padx=5)
        ttk.Button(buttons, text='Cancelar', command=self.close).pack(side='left')
        self.window.bind('<Return>', lambda event: self.save())
        self.window.bind('<Escape>', lambda event: self.close())
        self.window.update_idletasks()
        w, h = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        self.window.geometry(f'+{(self.window.winfo_screenwidth()-w)//2}+{(self.window.winfo_screenheight()-h)//2}')
        self.entries['cpu'][0].focus_set()

    def choose_color(self, level):
        _, color = colorchooser.askcolor(color=self.colors[level], parent=self.window)
        if color is not None:
            self.colors[level] = color
            self.color_boxes[level].configure(bg=color, fg=color_text_color(color))

    def restore_colors(self):
        for level, color in zip(LEVELS, DEFAULT_COLORS):
            self.colors[level] = color
            self.color_boxes[level].configure(bg=color, fg=color_text_color(color))

    def save(self):
        try:
            values = validate_preferences(dict(
                {metric: [e.get() for e in entries] for metric, entries in self.entries.items()},
                colors=tuple(self.colors[level] for level in LEVELS)))
            save_limits(self.path, values)
        except (ValueError, OSError, configparser.Error) as exc:
            self.error.configure(text=f'Não foi possível salvar: {exc}')
            return
        # Publish only after the atomic replace succeeds. All widgets share cfg.
        if not self.cfg.has_section('usage_limits'):
            self.cfg.add_section('usage_limits')
        self.cfg['usage_limits'].update(limit_settings(values))
        if self.on_saved is not None:
            self.on_saved(values)
        self.close()

    def close(self):
        self.master._usage_limits_editor = None
        self.window.destroy()
