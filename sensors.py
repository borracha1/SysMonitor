"""
sensors.py
CPU temperature and GPU usage/temperature, without HWiNFO.

  - GPU: NVIDIA's NVML (nvml.dll, ships with the driver) via ctypes. Signed
    driver, works with Memory Integrity/HVCI ON, no time limit.
  - CPU temp: LibreHardwareMonitor's local web server
    (http://127.0.0.1:8085/data.json). LHM reads the Ryzen sensor through the
    PawnIO driver (signed, HVCI-compatible) and has to run elevated; reading
    it over HTTP keeps this app unprivileged.

Why not HWiNFO anymore: HWiNFO64 Free switches its Shared Memory off after
12 hours, which left the widget showing "--" and the warning icon.
"""
import ctypes
import json
import urllib.request
from ctypes import wintypes
from typing import Optional


LHM_URL = "http://127.0.0.1:8085/data.json"
LHM_TIMEOUT_S = 0.5

NVML_SUCCESS = 0
NVML_TEMPERATURE_GPU = 0


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class NvmlReader:
    """First NVIDIA GPU via NVML. Re-initializes after any failure, so a
    driver update/restart only costs a few missed readings."""

    def __init__(self):
        self._lib = None
        self._handle = None
        self._last_error: Optional[str] = None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def _ensure_open(self) -> bool:
        if self._handle is not None:
            return True
        if self._lib is None:
            try:
                self._lib = ctypes.WinDLL("nvml.dll")
            except OSError as e:
                self._last_error = f"nvml.dll not found ({e})"
                return False
        rc = self._lib.nvmlInit_v2()
        if rc != NVML_SUCCESS:
            self._last_error = f"nvmlInit failed (rc={rc})"
            return False
        handle = ctypes.c_void_p()
        rc = self._lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle))
        if rc != NVML_SUCCESS:
            self._last_error = f"no NVIDIA GPU (rc={rc})"
            self._lib.nvmlShutdown()
            return False
        self._handle = handle
        return True

    def _reset(self):
        if self._handle is not None:
            self._lib.nvmlShutdown()
        self._handle = None

    def read(self) -> tuple[Optional[float], Optional[float]]:
        """Returns (temperature °C, usage %); (None, None) on failure."""
        self._last_error = None
        if not self._ensure_open():
            return None, None
        temp = wintypes.UINT()
        util = _NvmlUtilization()
        rc_t = self._lib.nvmlDeviceGetTemperature(self._handle, NVML_TEMPERATURE_GPU, ctypes.byref(temp))
        rc_u = self._lib.nvmlDeviceGetUtilizationRates(self._handle, ctypes.byref(util))
        if rc_t != NVML_SUCCESS and rc_u != NVML_SUCCESS:
            self._last_error = f"NVML read failed (rc={rc_t}/{rc_u})"
            self._reset()
            return None, None
        return (
            float(temp.value) if rc_t == NVML_SUCCESS else None,
            float(util.gpu) if rc_u == NVML_SUCCESS else None,
        )


def _parse_value(text: str) -> Optional[float]:
    # LHM formats values with the system locale and a unit ("52,3 °C").
    num = text.split(" ")[0].replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def _walk(node):
    yield node
    for child in node.get("Children", []):
        yield from _walk(child)


class LhmReader:
    """CPU temperature from LibreHardwareMonitor's web server."""

    # Preferred sensor names, in order (AMD first, then Intel).
    CPU_TEMP_NAMES = ("Core (Tctl/Tdie)", "Core (Tctl)", "CPU Package", "Core Average")

    def __init__(self, url: str = LHM_URL):
        self._url = url
        self._last_error: Optional[str] = None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def read_cpu_temp(self) -> Optional[float]:
        self._last_error = None
        try:
            with urllib.request.urlopen(self._url, timeout=LHM_TIMEOUT_S) as resp:
                tree = json.load(resp)
        except Exception as e:
            self._last_error = (
                f"LibreHardwareMonitor not reachable ({e}). "
                "Is it running with Options -> Remote Web Server -> Run?"
            )
            return None
        temps = {}
        for node in _walk(tree):
            sid = node.get("SensorId", "")
            if "/temperature/" in sid and "cpu/" in sid:
                temps.setdefault(node.get("Text", ""), node.get("Value", ""))
        for name in self.CPU_TEMP_NAMES:
            if name in temps:
                value = _parse_value(temps[name])
                if value is not None:
                    return value
        self._last_error = f"no CPU temperature sensor in LibreHardwareMonitor (saw: {sorted(temps)})"
        return None


class SensorReader:
    """What the collectors use: one call per tick, never raises."""

    def __init__(self):
        self._nvml = NvmlReader()
        self._lhm = LhmReader()

    def read(self) -> dict:
        try:
            gpu_temp, gpu_usage = self._nvml.read()
            gpu_error = self._nvml.last_error
        except Exception as e:  # never let a sensor hiccup kill the collector thread
            gpu_temp = gpu_usage = None
            gpu_error = f"unexpected error: {e}"
        try:
            cpu_temp = self._lhm.read_cpu_temp()
            cpu_temp_error = self._lhm.last_error
        except Exception as e:
            cpu_temp = None
            cpu_temp_error = f"unexpected error: {e}"
        return dict(
            cpu_temp=cpu_temp,
            gpu_temp=gpu_temp,
            gpu_usage=gpu_usage,
            cpu_temp_error=cpu_temp_error,
            gpu_error=gpu_error,
        )


if __name__ == "__main__":
    nv = NvmlReader()
    print("GPU (temp, usage):", nv.read(), nv.last_error or "")
    lhm = LhmReader()
    print("CPU temp:", lhm.read_cpu_temp(), lhm.last_error or "")
