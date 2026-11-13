"""Hover tooltip with the top 3 programs, for the CPU and MEM labels of the widget.

Tk thread only. The data comes from a TopProcessesMonitor thread (snapshot() never
blocks), which samples only while some tooltip is shown. The cursor is read from
Windows by the caller's `hit_test`: in taskbar mode the text window is colour-keyed,
so Tk's own Enter/Leave only fire on the letter strokes and cannot be trusted.
"""
import ctypes
import tkinter as tk

from top_processes import tooltip_origin, widget_text

POLL_MS = 250  # While shown: follows the cursor away and picks up each new 2 s sample.


def virtual_screen():
    """(left, top, right, bottom) of all monitors together."""
    user32 = ctypes.WinDLL('user32')  # Private instance: argtypes stay local.
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    return left, top, left + user32.GetSystemMetrics(78), top + user32.GetSystemMetrics(79)


class HoverTooltip:
    """hit_test() -> (kind, (left, top, right, bottom)) of the label under the cursor, or None."""

    def __init__(self, master, monitor, owner, hit_test, bg, fg, font, screen=virtual_screen):
        self.master = master
        self.monitor = monitor
        self.owner = owner
        self.hit_test = hit_test
        self.bg, self.fg, self.font = bg, fg, font
        self.screen = screen
        self.kind = None
        self.window = None
        self._label = None
        self._text = None
        self._rect = None
        self._after_id = None

    @property
    def visible(self):
        return self.window is not None

    def pointer_moved(self):
        """Call on every Enter/Motion/Leave of the widget."""
        try:
            hit = self.hit_test()
        except Exception:  # A failed hit test is "not over a label".
            hit = None
        self._follow(hit)

    def _follow(self, hit):
        if hit is None:
            self.hide()
            return
        kind, rect = hit
        if kind != self.kind or self.window is None:
            self._show(kind, rect)
        else:
            self._rect = rect
            self._refresh()
        if self._after_id is None:
            self._after_id = self.master.after(POLL_MS, self._poll)

    def _poll(self):
        self._after_id = None
        if self.window is None:
            return
        self.pointer_moved()

    def _show(self, kind, rect):
        self._drop_window()
        self.kind, self._rect = kind, rect
        self.monitor.set_active(self.owner, True)
        window = tk.Toplevel(self.master)
        window.overrideredirect(True)
        window.attributes('-topmost', True)
        window.configure(bg=self.bg, highlightthickness=1, highlightbackground=self.fg)
        self._label = tk.Label(window, text='', fg=self.fg, bg=self.bg, font=self.font, justify='left',
                               anchor='w', padx=6, pady=3)
        self._label.pack()
        self.window = window
        self._text = None
        self._refresh()

    def _refresh(self):
        text = widget_text(self.kind, self.monitor.snapshot())
        if text != self._text:
            self._text = text
            self._label.config(text=text)
        self._place()

    def _place(self):
        window = self.window
        window.update_idletasks()
        size = (window.winfo_reqwidth(), window.winfo_reqheight())
        x, y = tooltip_origin(self._rect, size, self.screen())
        window.geometry(f'+{x}+{y}')

    def _drop_window(self):
        window, self.window, self._label = self.window, None, None
        if window is not None:
            try:
                window.destroy()
            except tk.TclError:
                pass

    def hide(self):
        was_shown = self.kind is not None
        if self._after_id is not None:
            try:
                self.master.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self._drop_window()
        self.kind = self._text = self._rect = None
        if was_shown:
            self.monitor.set_active(self.owner, False)

    close = hide
