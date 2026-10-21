"""Tk-thread taskbar coordination; no collectors, UIA or Windows calls here."""


class TaskbarSession:
    def __init__(self, master, cfg, metrics, ping_monitor, space_monitor,
                 window_factory, enumerate_secondary, primary_handle, on_event):
        self.master = master
        self.cfg = cfg
        self.metrics = metrics
        self.ping_monitor = ping_monitor
        self.space_monitor = space_monitor
        self.window_factory = window_factory
        self.enumerate_secondary = enumerate_secondary
        self.primary_handle = primary_handle
        self.on_event = on_event
        self.primary = None
        self.secondary = {}
        self.exit_requested = False
        self._editor_owner = None
        self._after_id = None
        self._running = False
        self._polling = False
        self._ready = False

    def attach_primary(self, window):
        self.primary = window
        self._ready = True

    def start(self):
        if not self._running:
            self._running = True
            self._after_id = self.master.after(0, self._tick)

    def _tick(self):
        self._after_id = None
        try:
            self.poll()
        finally:
            if self._running and not self.exit_requested:
                self._after_id = self.master.after(2000, self._tick)

    def drop_secondary(self, hwnd):
        window = self.secondary.pop(hwnd, None)
        if window is not None:
            try:
                window._destroy()
            except Exception as exc:
                self.on_event(f'secondary taskbar cleanup failed ({hwnd}): {exc}')

    def poll(self):
        # update()/menus can enter Tk recursively during widget construction.
        if self.exit_requested or self._polling:
            return
        self._polling = True
        try:
            handles = set(self.enumerate_secondary())
            primary = self.primary_handle()
            handles.discard(primary)
            self.space_monitor.set_targets(handles | ({primary} if primary else set()))
            for hwnd in set(self.secondary) - handles:
                self.drop_secondary(hwnd)
            for hwnd in handles:
                snapshot = self.space_monitor.snapshot(hwnd)
                window = self.secondary.get(hwnd)
                if snapshot is None or (window is not None and window._closing):
                    self.drop_secondary(hwnd)
                    continue
                if window is not None or not self._ready:
                    continue
                window = None
                try:
                    window = self.window_factory(
                        self.master, self.cfg, self.metrics, 'taskbar',
                        ping_monitor=self.ping_monitor, space_monitor=self.space_monitor,
                        taskbar_hwnd=hwnd, session=self)
                    if window.embed_failed or window._closing or self.exit_requested or not self._ready:
                        window._destroy()
                    else:
                        self.secondary[hwnd] = window
                except Exception as exc:
                    if window is not None:
                        window._destroy()
                    self.on_event(f'secondary taskbar creation failed ({hwnd}): {exc}')
        except Exception as exc:
            self.on_event(f'secondary taskbar enumeration failed: {exc}')
        finally:
            self._polling = False

    def sync_settings(self):
        split = str(self.cfg['window'].get('net_split', 'false')).lower() in ('1', 'true', 'yes', 'on')
        windows = ([self.primary] if self.primary is not None else []) + list(self.secondary.values())
        for window in windows:
            if window._closing:
                continue
            try:
                window.net_split = split
                window._net_mode_var.set(split)
                if self.ping_monitor is not None and hasattr(window, '_ping_mode_var'):
                    window._ping_mode_var.set(self.ping_monitor.mode)
                window._update_labels()
                window._maintain_position()
            except Exception as exc:
                if window is self.primary:
                    raise
                self.on_event(f'secondary taskbar settings failed: {exc}')
                for hwnd, candidate in list(self.secondary.items()):
                    if candidate is window:
                        self.drop_secondary(hwnd)

    def claim_editor(self, window):
        owner = self._editor_owner
        editor = owner._ping_editor if owner is not None else None
        if editor is not None:
            try:
                if editor.winfo_exists():
                    editor.lift()
                    editor.focus_force()
                    return False
            except Exception:
                pass
        self._editor_owner = window
        return True

    def release_editor(self, window):
        if self._editor_owner is window:
            self._editor_owner = None

    def reconfigure(self):
        self._ready = False
        for hwnd in list(self.secondary):
            self.drop_secondary(hwnd)
        primary, self.primary = self.primary, None
        if primary is not None:
            primary.reconfigure_requested = True
            primary._destroy()

    def wait(self, milliseconds):
        # Keep secondary updates/menus alive while the primary waits for Explorer.
        timer = self.master.after(milliseconds, self.master.quit)
        try:
            self.master.mainloop()
        finally:
            self.master.after_cancel(timer)

    def close(self):
        self.primary = None  # Break window <-> session cycles on the Tk thread.
        self._ready = False
        self._running = False
        if self._after_id is not None:
            self.master.after_cancel(self._after_id)
            self._after_id = None
        for hwnd in list(self.secondary):
            self.drop_secondary(hwnd)

    def quit(self):
        if self.exit_requested:
            return
        self.exit_requested = True
        primary = self.primary
        self.close()
        if primary is not None:
            primary.exit_requested = True
            primary._destroy()
        self.master.quit()
