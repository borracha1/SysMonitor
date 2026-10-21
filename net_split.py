"""Unprivileged IP packet counters and approximate byte-rate attribution."""
import ctypes
from ctypes import wintypes


class MIB_IPSTATS(ctypes.Structure):
    _fields_ = [(name, wintypes.DWORD) for name in (
        'dwForwarding', 'dwDefaultTTL', 'dwInReceives', 'dwInHdrErrors',
        'dwInAddrErrors', 'dwForwDatagrams', 'dwInUnknownProtos', 'dwInDiscards',
        'dwInDelivers', 'dwOutRequests', 'dwRoutingDiscards', 'dwOutDiscards',
        'dwOutNoRoutes', 'dwReasmTimeout', 'dwReasmReqds', 'dwReasmOks',
        'dwReasmFails', 'dwFragOks', 'dwFragFails', 'dwFragCreates',
        'dwNumIf', 'dwNumAddr', 'dwNumRoutes')]


def packet_delta(current, previous):
    """DWORD wrap near its boundary; other backwards jumps are resets."""
    if current >= previous:
        return current - previous
    if previous >= 0xF0000000 and current < 0x10000000:
        return (current - previous) & 0xFFFFFFFF
    return 0


def split_rates(up, down, previous, current):
    """Counters are ((v4_in, v4_out), (v6_in, v6_out)); None means unavailable."""
    if previous is None or current is None:
        return None
    deltas = [[packet_delta(current[f][d], previous[f][d]) for d in (0, 1)]
              for f in (0, 1)]
    def divide(total, direction):
        count = deltas[0][direction] + deltas[1][direction]
        return tuple(max(0.0, total) * family[direction] / count if count else 0.0
                     for family in deltas)
    return divide(up, 1), divide(down, 0)


class PacketCounters:
    """Lazy Win32 setup/read: called only from Collector, logs failure once."""
    def __init__(self, log):
        self.log = log
        self.failed_logged = False
        self.api = None

    def read(self):
        try:
            if self.api is None:
                self.api = ctypes.WinDLL('iphlpapi').GetIpStatisticsEx
                self.api.argtypes = [ctypes.POINTER(MIB_IPSTATS), wintypes.ULONG]
                self.api.restype = wintypes.ULONG
            values = []
            for family in (2, 23):
                stats = MIB_IPSTATS()
                status = self.api(ctypes.byref(stats), family)
                if status:
                    raise OSError(status, 'GetIpStatisticsEx')
                values.append((stats.dwInReceives, stats.dwOutRequests))
            return tuple(values)
        except (OSError, AttributeError) as exc:
            if not self.failed_logged:
                self.log(f'net split: packet counters unavailable: {exc}')
                self.failed_logged = True
            return None


def net_column_width(measure, split):
    if not split:
        return measure('↓1000.0 Mbps')
    prefix = max(measure('↑ v4 '), measure('↓ v4 '))
    return prefix + measure('1000.0 Mbps') + measure(' v6 ') + measure('1000.0 Mbps')
