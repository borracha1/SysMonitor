"""
metrics_collector.py — shared system-metrics collection, used by both
sys_monitor.py (floating window, legacy) and tray_monitor.py (tray icons).

Extracted verbatim from sys_monitor.py so both front-ends stay in sync
without duplicating the psutil/HWiNFO reading logic.
"""
import time
import threading

import psutil

from hwinfo_reader import HWiNFOReader, READING_TYPE_TEMP, READING_TYPE_USAGE


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.up_speed = 0.0
        self.down_speed = 0.0
        self.cpu_percent = 0.0
        self.mem_percent = 0.0
        self.cpu_temp = None
        self.gpu_temp = None
        self.gpu_usage = None
        self.hwinfo_ok = False
        self.hwinfo_error = None

    def snapshot(self):
        with self.lock:
            return dict(
                up_speed=self.up_speed,
                down_speed=self.down_speed,
                cpu_percent=self.cpu_percent,
                mem_percent=self.mem_percent,
                cpu_temp=self.cpu_temp,
                gpu_temp=self.gpu_temp,
                gpu_usage=self.gpu_usage,
                hwinfo_ok=self.hwinfo_ok,
                hwinfo_error=self.hwinfo_error,
            )


class Collector(threading.Thread):
    def __init__(self, metrics: Metrics, interval_s: float = 1.0):
        super().__init__(daemon=True)
        self.metrics = metrics
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._hwinfo = HWiNFOReader()
        self._last_net = psutil.net_io_counters()
        self._last_net_time = time.time()

    def stop(self):
        self._stop.set()

    def run(self):
        # Prime psutil's internal CPU counter (first call after interval=None is always 0.0)
        psutil.cpu_percent(interval=None)
        while not self._stop.is_set():
            self._collect_once()
            self._stop.wait(self.interval_s)

    def _collect_once(self):
        now = time.time()
        net = psutil.net_io_counters()
        dt = max(now - self._last_net_time, 1e-6)
        up = (net.bytes_sent - self._last_net.bytes_sent) / dt
        down = (net.bytes_recv - self._last_net.bytes_recv) / dt
        self._last_net = net
        self._last_net_time = now

        cpu_percent = psutil.cpu_percent(interval=None)
        mem_percent = psutil.virtual_memory().percent

        cpu_temp = gpu_temp = gpu_usage = None
        hwinfo_ok = False
        hwinfo_error = None
        try:
            readings = self._hwinfo.read()
            if self._hwinfo.last_error:
                hwinfo_error = self._hwinfo.last_error
            elif readings:
                hwinfo_ok = True
                r_cpu = (
                    self._hwinfo.find(readings, "tctl", reading_type=READING_TYPE_TEMP)
                    or self._hwinfo.find(readings, "cpu package", reading_type=READING_TYPE_TEMP)
                    or self._hwinfo.find(readings, "cpu (", reading_type=READING_TYPE_TEMP)
                )
                r_gpu_t = self._hwinfo.find(readings, "gpu", reading_type=READING_TYPE_TEMP)
                r_gpu_u = (
                    self._hwinfo.find(readings, "núcleo da gpu", reading_type=READING_TYPE_USAGE)
                    or self._hwinfo.find(readings, "gpu", "core", reading_type=READING_TYPE_USAGE)
                    or self._hwinfo.find(readings, "gpu", "utilization", reading_type=READING_TYPE_USAGE)
                    or self._hwinfo.find(readings, "gpu", "utilização", reading_type=READING_TYPE_USAGE)
                )
                cpu_temp = r_cpu.value if r_cpu else None
                gpu_temp = r_gpu_t.value if r_gpu_t else None
                gpu_usage = r_gpu_u.value if r_gpu_u else None
        except Exception as e:  # never let a sensor hiccup kill the collector thread
            hwinfo_error = f"unexpected error: {e}"

        with self.metrics.lock:
            self.metrics.up_speed = up
            self.metrics.down_speed = down
            self.metrics.cpu_percent = cpu_percent
            self.metrics.mem_percent = mem_percent
            self.metrics.cpu_temp = cpu_temp
            self.metrics.gpu_temp = gpu_temp
            self.metrics.gpu_usage = gpu_usage
            self.metrics.hwinfo_ok = hwinfo_ok
            self.metrics.hwinfo_error = hwinfo_error
