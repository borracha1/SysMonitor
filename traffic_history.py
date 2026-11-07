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

Point = namedtuple('Point', 'epoch v4_down v4_up v6_down v6_up v4_mark v6_mark v4_ping v6_ping',
                   defaults=(None, None))
FamilyPoint = namedtuple('FamilyPoint', 'epoch down up mark ping', defaults=(None,))


def _parse_line(line):
    fields = line.strip().split(',')
    if len(fields) not in (7, 9):  # 7: first 1.1.0 build, without ping.
        return None
    try:
        epoch = int(fields[0])
        speeds = [int(value) if value else None for value in fields[1:5]]
        marks = [int(fields[5]), int(fields[6])]
        pings = [int(value) if value else None for value in fields[7:9]]
    except ValueError:
        return None
    if (any(value is not None and value < 0 for value in speeds + pings)
            or any(m not in (0, 1, 2) for m in marks)):
        return None
    return Point(epoch, *speeds, *marks, *pings)


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
        self._rtts = {'ipv4': None, 'ipv6': None}
        # Always rewrite first: a line cut by a power loss would otherwise
        # glue itself to the next append and damage both lines.
        self._needs_rewrite = True
        self._error_logged = False

    def add_sample(self, rates, marks, rtts=None):
        """rates: ((up_v4, up_v6), (down_v4, down_v6)) or None; marks and rtts: per family."""
        epoch = int(self.clock()) // BUCKET_S * BUCKET_S
        with self._lock:
            if self._bucket is not None and epoch != self._bucket:
                self._close_bucket()
            self._bucket = epoch
            if rates is not None:
                self._samples.append(rates)
            for family, mark in marks.items():
                self._marks[family] = max(self._marks[family], mark)
            for family, rtt in (rtts or {}).items():
                if rtt is not None:
                    current = self._rtts[family]
                    self._rtts[family] = rtt if current is None else max(current, rtt)

    def finish_bucket(self):
        with self._lock:
            if self._bucket is not None:
                self._close_bucket()

    def _close_bucket(self):
        def average(direction, family):
            if not self._samples:
                return None
            return round(sum(sample[direction][family] for sample in self._samples) / len(self._samples))
        def worst(family):
            value = self._rtts[family]
            return None if value is None else round(value)
        point = Point(self._bucket, average(1, 0), average(0, 0), average(1, 1), average(0, 1),
                      self._marks['ipv4'], self._marks['ipv6'], worst('ipv4'), worst('ipv6'))
        self._points.append(point)
        self._pending.append(point)
        del self._pending[:-MAX_POINTS]
        self._bucket = None
        self._samples = []
        self._marks = {'ipv4': 0, 'ipv6': 0}
        self._rtts = {'ipv4': None, 'ipv6': None}

    def points(self, family, period_s):
        now = self.clock()
        return self.points_between(family, now - period_s, now)

    def points_between(self, family, start, end):
        with self._lock:
            visible = [p for p in self._points if start <= p.epoch <= end]
        visible.sort(key=lambda p: p.epoch)
        if family == 'ipv4':
            return [FamilyPoint(p.epoch, p.v4_down, p.v4_up, p.v4_mark, p.v4_ping) for p in visible]
        return [FamilyPoint(p.epoch, p.v6_down, p.v6_up, p.v6_mark, p.v6_ping) for p in visible]

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
        ping = self.ping_monitor
        marks = ping.take_loss_marks() if ping is not None else {}
        rtts = ping.take_worst_rtts() if ping is not None else {}
        self.history.add_sample(rates, marks, rtts)
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


GAP_S = 15
MARGIN_LEFT, MARGIN_TOP, MARGIN_RIGHT, MARGIN_BOTTOM = 76, 12, 12, 26
TICK_STEP_S = {3600: 900, 4 * 3600: 3600}

Chart = namedtuple('Chart', 'plot down up bands x_ticks y_ticks')


def local_hhmm(epoch):
    return time.strftime('%H:%M', time.localtime(epoch))


def _larger(first, second):
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def build_chart(points, width, height, now, period_s, fmt_time=local_hhmm):
    """Geometry only. Each pixel keeps its largest rates and worst mark, so short
    peaks and failures survive when there are more points than pixels."""
    x0, y0 = MARGIN_LEFT, MARGIN_TOP
    x1, y1 = width - MARGIN_RIGHT, height - MARGIN_BOTTOM
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    span = x1 - x0
    start = now - period_s
    groups = {}
    for point in sorted(points, key=lambda p: p.epoch):
        if not start <= point.epoch <= now:
            continue
        x = x0 + int((point.epoch - start) / period_s * span)
        group = groups.get(x)
        if group is None:
            groups[x] = dict(first=point.epoch, last=point.epoch, down=point.down,
                             up=point.up, mark=point.mark)
        else:
            group['last'] = point.epoch
            group['down'] = _larger(group['down'], point.down)
            group['up'] = _larger(group['up'], point.up)
            group['mark'] = max(group['mark'], point.mark)
    ordered = [(x, groups[x]) for x in sorted(groups)]
    peak = max((value for _, group in ordered for value in (group['down'], group['up'])
                if value is not None), default=0)
    top = peak or 1

    def y_of(value):
        return y1 - (value / top) * (y1 - y0)

    def segments(name):
        result, current, previous = [], [], None
        for x, group in ordered:
            value = group[name]
            if current and (value is None or group['first'] - previous > GAP_S):
                result.append(current)
                current = []
            if value is not None:
                current.append((x, y_of(value)))
            previous = group['last']
        if current:
            result.append(current)
        return result

    band_width = max(1, round(BUCKET_S / period_s * span))
    bands = sorted(((x, min(x + band_width, x1), group['mark']) for x, group in ordered if group['mark']),
                   key=lambda band: band[2])
    step = TICK_STEP_S.get(period_s, period_s / 4)
    tick = (int(start) + step - 1) // step * step
    x_ticks = []
    while tick <= now:
        x_ticks.append((x0 + (tick - start) / period_s * span, fmt_time(tick)))
        tick += step
    y_ticks = [(y1, 0)] if not peak else [(y1, 0), (y_of(top / 2), top / 2), (y0, top)]
    return Chart((x0, y0, x1, y1), segments('down'), segments('up'), bands, x_ticks, y_ticks)
