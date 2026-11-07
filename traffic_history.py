"""Last 4 h of estimated per-family traffic: buckets, CSV storage and chart data.

No Tk here. All file I/O runs on the TrafficRecorder thread, so a slow disk
never delays the widget's collection or its interface.
"""
from collections import deque, namedtuple
import os
from pathlib import Path
import tempfile
import threading
import time

BUCKET_S = 5
KEEP_S = 4 * 3600
MAX_POINTS = KEEP_S // BUCKET_S
FUTURE_TOLERANCE_S = 60

Point = namedtuple('Point', 'epoch v4_down v4_up v6_down v6_up v4_mark v6_mark')
FamilyPoint = namedtuple('FamilyPoint', 'epoch down up mark')


def _parse_line(line):
    fields = line.strip().split(',')
    if len(fields) != 7:
        return None
    try:
        epoch = int(fields[0])
        speeds = [int(value) if value else None for value in fields[1:5]]
        marks = [int(fields[5]), int(fields[6])]
    except ValueError:
        return None
    if any(value is not None and value < 0 for value in speeds) or any(m not in (0, 1, 2) for m in marks):
        return None
    return Point(epoch, *speeds, *marks)


def _format_line(point):
    return ','.join('' if value is None else str(value) for value in point) + '\n'


class TrafficHistory:
    def __init__(self, path, log, clock=time.time):
        self.path = Path(path)
        self.log = log
        self.clock = clock
        self._lock = threading.Lock()
        self._points = deque(maxlen=MAX_POINTS)
        self._pending = []
        self._bucket = None
        self._samples = []
        self._marks = {'ipv4': 0, 'ipv6': 0}
        # Always rewrite first: a line cut by a power loss would otherwise
        # glue itself to the next append and damage both lines.
        self._needs_rewrite = True
        self._error_logged = False

    def add_sample(self, rates, marks):
        """rates: ((up_v4, up_v6), (down_v4, down_v6)) or None; marks: per-family worst."""
        epoch = int(self.clock()) // BUCKET_S * BUCKET_S
        with self._lock:
            if self._bucket is not None and epoch != self._bucket:
                self._close_bucket()
            self._bucket = epoch
            if rates is not None:
                self._samples.append(rates)
            for family, mark in marks.items():
                self._marks[family] = max(self._marks[family], mark)

    def finish_bucket(self):
        with self._lock:
            if self._bucket is not None:
                self._close_bucket()

    def _close_bucket(self):
        def average(direction, family):
            if not self._samples:
                return None
            return round(sum(sample[direction][family] for sample in self._samples) / len(self._samples))
        point = Point(self._bucket, average(1, 0), average(0, 0), average(1, 1), average(0, 1),
                      self._marks['ipv4'], self._marks['ipv6'])
        self._points.append(point)
        self._pending.append(point)
        del self._pending[:-MAX_POINTS]
        self._bucket = None
        self._samples = []
        self._marks = {'ipv4': 0, 'ipv6': 0}

    def points(self, family, period_s):
        now = self.clock()
        with self._lock:
            visible = [p for p in self._points if now - period_s <= p.epoch <= now]
        visible.sort(key=lambda p: p.epoch)
        if family == 'ipv4':
            return [FamilyPoint(p.epoch, p.v4_down, p.v4_up, p.v4_mark) for p in visible]
        return [FamilyPoint(p.epoch, p.v6_down, p.v6_up, p.v6_mark) for p in visible]

    def load(self):
        lines = []
        try:
            with open(self.path, encoding='ascii', errors='replace') as stream:
                lines = stream.readlines()
        except FileNotFoundError:
            pass
        except OSError as exc:
            self._report(exc)
        now = self.clock()
        loaded = [point for point in map(_parse_line, lines)
                  if point and now - KEEP_S <= point.epoch <= now + FUTURE_TOLERANCE_S]
        loaded.sort(key=lambda point: point.epoch)
        with self._lock:
            self._points.extend(loaded)
        self.rewrite()

    def flush(self):
        if self._needs_rewrite:
            return self.rewrite()
        with self._lock:
            pending = list(self._pending)
        if not pending:
            return True
        try:
            with open(self.path, 'a', encoding='ascii', newline='\n') as stream:
                stream.writelines(map(_format_line, pending))
        except OSError as exc:
            self._needs_rewrite = True  # A partial append may have cut a line.
            self._report(exc)
            return False
        with self._lock:
            del self._pending[:len(pending)]
        self._error_logged = False
        return True

    def rewrite(self):
        now = self.clock()
        with self._lock:
            kept = sorted((p for p in self._points
                           if now - KEEP_S <= p.epoch <= now + FUTURE_TOLERANCE_S),
                          key=lambda p: p.epoch)
            self._points = deque(kept, maxlen=MAX_POINTS)
            written = len(self._pending)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='ascii', newline='\n', dir=self.path.parent,
                                             prefix=self.path.name + '.', suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                stream.writelines(map(_format_line, kept))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            self._needs_rewrite = True
            self._report(exc)
            return False
        finally:
            if temporary is not None and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
        with self._lock:
            del self._pending[:written]
        self._needs_rewrite = False
        self._error_logged = False
        return True

    def _report(self, exc):
        if not self._error_logged:
            self._error_logged = True
            self.log(f'traffic history: write failed: {exc}')


class TrafficRecorder(threading.Thread):
    def __init__(self, history, metrics, ping_monitor=None, log=lambda message: None,
                 interval_s=1.0, flush_s=60.0, rewrite_s=3600.0, clock=time.monotonic):
        super().__init__(daemon=True, name='TrafficRecorder')
        self.history = history
        self.metrics = metrics
        self.ping_monitor = ping_monitor
        self.log = log
        self.interval_s = interval_s
        self.flush_s = flush_s
        self.rewrite_s = rewrite_s
        self.clock = clock
        self._stop_evt = threading.Event()
        self._failed_logged = False
        self._next_flush = clock() + flush_s
        self._next_rewrite = clock() + rewrite_s

    def stop(self):
        self._stop_evt.set()

    def tick(self):
        with self.metrics.lock:
            rates = self.metrics.net_rates
        marks = self.ping_monitor.take_loss_marks() if self.ping_monitor is not None else {}
        self.history.add_sample(rates, marks)
        now = self.clock()
        if now >= self._next_rewrite:
            self.history.rewrite()
            self._next_rewrite = now + self.rewrite_s
            self._next_flush = now + self.flush_s
        elif now >= self._next_flush:
            self.history.flush()
            self._next_flush = now + self.flush_s

    def _safely(self, action):
        try:
            action()
        except Exception as exc:  # The history must never affect the widget.
            if not self._failed_logged:
                self._failed_logged = True
                self.log(f'traffic history: recorder failed: {exc}')

    def run(self):
        self._safely(self.history.load)
        while not self._stop_evt.wait(self.interval_s):
            self._safely(self.tick)
        self._safely(self.history.finish_bucket)
        self._safely(self.history.flush)
