"""
hwinfo_reader.py
Reads HWiNFO64 Shared Memory (HWiNFO_SENS_SM2) sensors via ctypes.
Requires HWiNFO64 running with "Shared Memory Support" enabled
(Settings -> General -> Shared Memory Support, or HWiNFO64.INI: SensorsSM=1).

Struct layout reference: HWiNFO SDK (element sizes are minimums; the real
stride always comes from the header's SizeOfElement fields, since HWiNFO
may append fields in newer versions).
"""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional


FILE_MAP_READ = 0x0004

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
kernel32.OpenFileMappingW.restype = wintypes.HANDLE
kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
kernel32.UnmapViewOfFile.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

SHARED_MEM_NAME = "Global\\HWiNFO_SENS_SM2"

READING_TYPE_TEMP = 1
READING_TYPE_VOLT = 2
READING_TYPE_FAN = 3
READING_TYPE_CURRENT = 4
READING_TYPE_POWER = 5
READING_TYPE_CLOCK = 6
READING_TYPE_USAGE = 7
READING_TYPE_OTHER = 8


class _Header(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("dwSignature", ctypes.c_uint32),
        ("dwVersion", ctypes.c_uint32),
        ("dwRevision", ctypes.c_uint32),
        ("poll_time", ctypes.c_int64),
        ("dwOffsetOfSensorSection", ctypes.c_uint32),
        ("dwSizeOfSensorElement", ctypes.c_uint32),
        ("dwNumSensorElements", ctypes.c_uint32),
        ("dwOffsetOfReadingSection", ctypes.c_uint32),
        ("dwSizeOfReadingElement", ctypes.c_uint32),
        ("dwNumReadingElements", ctypes.c_uint32),
    ]


class _ReadingElement(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("tReading", ctypes.c_uint32),
        ("dwSensorIndex", ctypes.c_uint32),
        ("dwReadingID", ctypes.c_uint32),
        ("szLabelOrig", ctypes.c_char * 128),
        ("szLabelUser", ctypes.c_char * 128),
        ("szUnit", ctypes.c_char * 16),
        ("Value", ctypes.c_double),
        ("ValueMin", ctypes.c_double),
        ("ValueMax", ctypes.c_double),
        ("ValueAvg", ctypes.c_double),
    ]


@dataclass
class Reading:
    reading_type: int
    label: str
    unit: str
    value: float


class HWiNFOReader:
    """
    Connects to HWiNFO's shared memory and reads sensor values.
    Safe to call .read() repeatedly (opens/closes the mapping each time,
    which is cheap and avoids stale-handle issues if HWiNFO restarts).
    """

    def __init__(self):
        self._last_error: Optional[str] = None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def read(self) -> list[Reading]:
        self._last_error = None
        h = kernel32.OpenFileMappingW(FILE_MAP_READ, False, SHARED_MEM_NAME)
        if not h:
            self._last_error = (
                f"HWiNFO shared memory not found (error {ctypes.get_last_error()}). "
                "Is HWiNFO64 running with Shared Memory Support enabled?"
            )
            return []
        try:
            addr = kernel32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, 0)
            if not addr:
                self._last_error = f"MapViewOfFile failed (error {ctypes.get_last_error()})"
                return []
            try:
                header = _Header.from_address(addr)
                if header.dwSignature != 0x53695748:  # 'HWiS'
                    self._last_error = "Unexpected shared memory signature"
                    return []
                readings: list[Reading] = []
                base = addr + header.dwOffsetOfReadingSection
                stride = header.dwSizeOfReadingElement
                for i in range(header.dwNumReadingElements):
                    elem = _ReadingElement.from_address(base + i * stride)
                    label = (
                        elem.szLabelUser.decode('mbcs', errors='replace').strip('\x00')
                        or elem.szLabelOrig.decode('mbcs', errors='replace').strip('\x00')
                    )
                    unit = elem.szUnit.decode('mbcs', errors='replace').strip('\x00')
                    readings.append(Reading(elem.tReading, label, unit, elem.Value))
                return readings
            finally:
                kernel32.UnmapViewOfFile(ctypes.c_void_p(addr))
        finally:
            kernel32.CloseHandle(h)

    def find(self, readings: list[Reading], *substrings: str, reading_type: Optional[int] = None) -> Optional[Reading]:
        """Find the first reading whose label contains all given substrings (case-insensitive)."""
        for r in readings:
            low = r.label.lower()
            if reading_type is not None and r.reading_type != reading_type:
                continue
            if all(s.lower() in low for s in substrings):
                return r
        return None


if __name__ == "__main__":
    reader = HWiNFOReader()
    data = reader.read()
    if reader.last_error:
        print("ERROR:", reader.last_error)
    else:
        print(f"{len(data)} readings")
        cpu_temp = reader.find(data, "tctl", reading_type=READING_TYPE_TEMP) or reader.find(data, "cpu", reading_type=READING_TYPE_TEMP)
        gpu_temp = reader.find(data, "gpu", reading_type=READING_TYPE_TEMP)
        print("CPU temp:", cpu_temp)
        print("GPU temp:", gpu_temp)
