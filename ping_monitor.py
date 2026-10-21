"""
ping_monitor.py — real-time internet packet-loss monitor (ICMP echo).

Sends one ICMP echo per cycle to each IP in the IPv4 and IPv6 groups.
Each IP has its own sliding loss window (default 60 cycles). Automatic
family selection preserves history; only failure of ALL IPs is an outage.

Design constraints (see docs/agentes/armadilhas.md):
  - No elevation, HVCI-safe: uses iphlpapi!IcmpSendEcho (no raw sockets,
    no driver, no admin) via ctypes, with explicit argtypes/restype.
  - All blocking I/O lives in this background thread, never in the GUI.
  - Notifications are Windows toasts through a short-lived hidden
    powershell.exe (no extra Python dependency).

The monitor writes an ordered tuple of (ip, loss, rtt, ok) into Metrics.ping.
"""
import ctypes
import os
import ipaddress
import struct
import subprocess
import threading
import time
from collections import deque
from xml.sax.saxutils import escape as _xml_escape

DEFAULT_TARGETS = ("8.8.8.8", "1.1.1.1")
DEFAULT_TARGETS_V6 = ("2001:4860:4860::8888", "2606:4700:4700::1111")


def ping_marker(family, auto):
    return ("v6" if family == "ipv6" else "v4") + ("·A" if auto else "")


def initial_ping_family(mode: str, preferred: str, groups) -> str:
    """Choose the initial layout/monitor family, including empty-group fallback."""
    family = preferred if mode == "auto" else mode
    return family if groups[family] else ("ipv6" if family == "ipv4" else "ipv4")


def ping_column_width(measure, active_targets, timeout_ms=1000):
    reserve_ms = max(1000, int(timeout_ms))
    return measure("v6·A ") + max(
        (measure(f"{ip} 100% {reserve_ms}ms") for ip in active_targets), default=0)


def fmt_loss(value) -> str:
    if value is None:
        return "--"
    if value <= 0:
        return "0%"
    return f"{value:.1f}%" if value < 10 else f"{value:.0f}%"


def fmt_ping_line(ip, loss, rtt, ok) -> str:
    if loss is None:
        return f"{ip} --"
    latency = f"{rtt:.0f}" if ok and rtt is not None else "--"
    return f"{ip} {fmt_loss(loss)} {latency}ms"


def ping_has_problem(loss, ok) -> bool:
    return (loss is not None and loss > 0) or ok is False


# ---------------------------------------------------------------------------
# ICMP via iphlpapi (Windows)
# ---------------------------------------------------------------------------
class _IP_OPTION_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Ttl", ctypes.c_ubyte),
        ("Tos", ctypes.c_ubyte),
        ("Flags", ctypes.c_ubyte),
        ("OptionsSize", ctypes.c_ubyte),
        ("OptionsData", ctypes.c_void_p),
    ]


class _ICMP_ECHO_REPLY(ctypes.Structure):
    _fields_ = [
        ("Address", ctypes.c_uint32),
        ("Status", ctypes.c_uint32),
        ("RoundTripTime", ctypes.c_uint32),
        ("DataSize", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort),
        ("Data", ctypes.c_void_p),
        ("Options", _IP_OPTION_INFORMATION),
    ]


class _SOCKADDR_IN6(ctypes.Structure):
    _fields_ = [("sin6_family", ctypes.c_ushort), ("sin6_port", ctypes.c_ushort),
                ("sin6_flowinfo", ctypes.c_uint32), ("sin6_addr", ctypes.c_ubyte * 16),
                ("sin6_scope_id", ctypes.c_uint32)]


class _IPV6_ADDRESS_EX(ctypes.Structure):
    _fields_ = [("sin6_port", ctypes.c_ushort), ("sin6_flowinfo", ctypes.c_uint32),
                ("sin6_addr", ctypes.c_ushort * 8), ("sin6_scope_id", ctypes.c_uint32)]


class _ICMPV6_ECHO_REPLY(ctypes.Structure):
    _fields_ = [("Address", _IPV6_ADDRESS_EX), ("Status", ctypes.c_uint32),
                ("RoundTripTime", ctypes.c_uint32)]


IP_SUCCESS = 0


class IcmpPinger:
    """IPv4/IPv6 ICMP wrapper. Handles are owned by the probing thread."""

    def __init__(self, dll=None, on_event=None):
        dll = dll if dll is not None else ctypes.WinDLL("iphlpapi", use_last_error=True)
        self.on_event = on_event or (lambda msg: None)
        self._h6 = None
        self._ipv6_attempted = False
        dll.Icmp6CreateFile.restype = ctypes.c_void_p
        dll.Icmp6CreateFile.argtypes = []
        dll.Icmp6SendEcho2.restype = ctypes.c_uint32
        dll.Icmp6SendEcho2.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(_SOCKADDR_IN6), ctypes.POINTER(_SOCKADDR_IN6),
            ctypes.c_char_p, ctypes.c_ushort, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32,
        ]
        dll.IcmpCreateFile.restype = ctypes.c_void_p
        dll.IcmpCreateFile.argtypes = []
        dll.IcmpCloseHandle.restype = ctypes.c_int
        dll.IcmpCloseHandle.argtypes = [ctypes.c_void_p]
        dll.IcmpSendEcho.restype = ctypes.c_uint32
        dll.IcmpSendEcho.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_ushort,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
        ]
        self._dll = dll
        h = dll.IcmpCreateFile()
        if not h or h == ctypes.c_void_p(-1).value:
            raise OSError(f"IcmpCreateFile failed (err={ctypes.get_last_error()})")
        self._h = h
        self._payload = b"SysMonitor"
        self._buf = ctypes.create_string_buffer(256)

    def ping(self, ip: str, timeout_ms: int):
        """Round-trip time in ms (float) on success, None on loss/error."""
        address = ipaddress.ip_address(ip)
        if address.version == 6:
            if not self._ipv6_attempted:
                self._ipv6_attempted = True
                h = self._dll.Icmp6CreateFile()
                if not h or h == ctypes.c_void_p(-1).value:
                    self.on_event(f"ping: IPv6 ICMP unavailable (err={ctypes.get_last_error()})")
                else:
                    self._h6 = h
            if self._h6 is None:
                return None
            source = _SOCKADDR_IN6(sin6_family=23)
            destination = _SOCKADDR_IN6(sin6_family=23)
            destination.sin6_addr[:] = address.packed
            n = self._dll.Icmp6SendEcho2(
                self._h6, None, None, None, ctypes.byref(source), ctypes.byref(destination),
                self._payload, len(self._payload), None, self._buf,
                ctypes.sizeof(self._buf), int(timeout_ms))
            reply_type = _ICMPV6_ECHO_REPLY
        else:
            addr = struct.unpack("<L", address.packed)[0]
            n = self._dll.IcmpSendEcho(self._h, addr, self._payload, len(self._payload),
                                       None, self._buf, ctypes.sizeof(self._buf), int(timeout_ms))
            reply_type = _ICMP_ECHO_REPLY
        if n == 0:
            return None
        reply = reply_type.from_buffer(self._buf)
        if reply.Status != IP_SUCCESS:
            return None
        return float(reply.RoundTripTime)

    def close(self):
        if self._h6:
            self._dll.IcmpCloseHandle(self._h6)
            self._h6 = None
        if self._h:
            self._dll.IcmpCloseHandle(self._h)
            self._h = None


# ---------------------------------------------------------------------------
# Windows toast notification (no extra dependencies, no elevation)
# ---------------------------------------------------------------------------
_PS_APPID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def show_toast(title: str, message: str):
    """Fire-and-forget Windows toast. Runs in its own thread; never raises."""
    def _run():
        try:
            xml = ('<toast><visual><binding template="ToastGeneric">'
                   f'<text>{_xml_escape(title)}</text><text>{_xml_escape(message)}</text>'
                   '</binding></visual></toast>').replace("'", "''")
            script = (
                "$ErrorActionPreference='Stop';"
                "[void][Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime];"
                "[void][Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime];"
                "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
                f"$x.LoadXml('{xml}');"
                "$t=New-Object Windows.UI.Notifications.ToastNotification $x;"
                f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_PS_APPID}').Show($t)"
            )
            flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-Command", script],
                creationflags=flags, timeout=20,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# Monitor thread
# ---------------------------------------------------------------------------
def _parse_target(value):
    value = value.strip()
    if "%" in value:
        raise ValueError("IPv6 com zona (%) não é permitido.")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        raise ValueError(f"Destino inválido: {value}. Informe um IPv4 ou IPv6 literal.") from None


def parse_ping_targets(values) -> tuple[str, ...]:
    targets = tuple(_parse_target(value) for value in values if value.strip())
    if not 1 <= len(targets) <= 2:
        raise ValueError("Informe um ou dois destinos de ping.")
    if len(set(targets)) != len(targets):
        raise ValueError("Os destinos de ping não podem ser repetidos.")
    return targets


def parse_ping_groups(values, preferred):
    """Validate the four editor fields, preserving their family and position."""
    if len(values) != 4:
        raise ValueError("Informe os quatro campos de destinos.")
    groups = [[], []]
    for index, value in enumerate(values):
        if not value.strip():
            continue
        family = 4 if index < 2 else 6
        title = f"IPv{family} {index % 2 + 1}"
        try:
            target = _parse_target(value)
        except ValueError as exc:
            raise ValueError(f"{title}: {exc}") from None
        if ipaddress.ip_address(target).version != family:
            raise ValueError(f'{title}: "{value}" não é IPv{family}.')
        group = groups[index // 2]
        if target in group:
            raise ValueError("Os destinos não podem ser repetidos.")
        group.append(target)
    if not any(groups):
        raise ValueError("Informe pelo menos 1 IP no total.")
    if preferred not in ("ipv4", "ipv6") or not groups[preferred == "ipv6"]:
        raise ValueError("O grupo preferido não pode estar vazio.")
    return tuple(groups[0]), tuple(groups[1])


def _valid_group(values, family):
    ok = []
    for value in values:
        try:
            target = _parse_target(value)
            if ipaddress.ip_address(target).version == family and target not in ok:
                ok.append(target)
        except ValueError:
            pass
    return tuple(ok[:2])


def ping_settings(section):
    """Read strict family groups, including the legacy mixed targets key."""
    if "targets_v4" not in section and "targets_v6" not in section and "targets" in section:
        legacy = section.get("targets", "").split(",")
        v4, v6 = _valid_group(legacy, 4), _valid_group(legacy, 6)
    else:
        v4 = _valid_group(section.get("targets_v4", ",".join(DEFAULT_TARGETS)).split(","), 4)
        v6 = _valid_group(section.get("targets_v6", ",".join(DEFAULT_TARGETS_V6)).split(","), 6)
    if not v4 and not v6:
        v4, v6 = DEFAULT_TARGETS, DEFAULT_TARGETS_V6
    mode = section.get("mode", "auto")
    preferred = section.get("preferred", "ipv4")
    return dict(targets_v4=v4, targets_v6=v6,
                mode=mode if mode in ("auto", "ipv4", "ipv6") else "auto",
                preferred=preferred if preferred in ("ipv4", "ipv6") else "ipv4")


class _ProbeResults(tuple):
    """Carry the configuration generation across blocking network I/O."""
    generation: int

    def __new__(cls, values, generation):
        result = super().__new__(cls, values)
        result.generation = generation
        return result


class PingMonitor(threading.Thread):
    def __init__(self, metrics, targets_v4=DEFAULT_TARGETS, targets_v6=DEFAULT_TARGETS_V6,
                 mode="auto", preferred="ipv4", return_clean_cycles=60,
                 interval_s=1.0, timeout_ms=1000, window=60, notify=True,
                 alert_after=1, recover_after=5, cooldown_s=60.0,
                 on_event=None, pinger_factory=IcmpPinger, notifier=show_toast,
                 mute_after_alerts=5, mute_window_s=120, unmute_after_s=1800):
        super().__init__(daemon=True, name="PingMonitor")
        self._lock = threading.RLock()
        self._generation = 0
        self.metrics = metrics
        self.groups = {"ipv4": _valid_group(targets_v4, 4), "ipv6": _valid_group(targets_v6, 6)}
        if not any(self.groups.values()):
            self.groups = {"ipv4": DEFAULT_TARGETS, "ipv6": DEFAULT_TARGETS_V6}
        self.mode = mode if mode in ("auto", "ipv4", "ipv6") else "auto"
        self.preferred = preferred if preferred in self.groups else "ipv4"
        if self.mode != "auto" and not self.groups[self.mode]:
            self.mode = self._other(self.mode)
        self.active = self._initial_family()
        self.return_clean_cycles = max(1, int(return_clean_cycles))
        self._clean = {"ipv4": 0, "ipv6": 0}
        self._results = {}
        self.interval_s = max(0.2, interval_s)
        self.timeout_ms = int(timeout_ms)
        self.notify = notify
        self.alert_after = max(1, alert_after)
        self.recover_after = max(1, recover_after)
        self.cooldown_s = cooldown_s
        self.on_event = on_event or (lambda msg: None)
        self._pinger_factory = pinger_factory
        self._notifier = notifier
        self.mute_after_alerts = max(0, int(mute_after_alerts))
        self.mute_window_s = max(0.0, float(mute_window_s))
        self.unmute_after_s = max(0.0, float(unmute_after_s))
        self._alert_times = {}
        self._muted = set()
        self._last_failure = {}
        self._samples = [deque(maxlen=max(1, window)) for _ in self.targets]
        self._outage_samples = deque(maxlen=max(1, window))
        # NB: not "_stop" — that would shadow threading.Thread's internals.
        self._stop_evt = threading.Event()
        self._consec_lost = 0
        self._consec_ok = 0
        self._alert = False
        self._alert_notified = False
        self._alert_start = 0.0
        self._alert_lost = 0
        self._last_notify = -1e9
        self._publish()

    @property
    def targets(self):
        return self.groups["ipv4"] + self.groups["ipv6"]

    def _initial_family(self):
        return initial_ping_family(self.mode, self.preferred, self.groups)

    @staticmethod
    def _other(family):
        return "ipv6" if family == "ipv4" else "ipv4"

    def _publish(self):
        def results(family):
            return tuple(self._results.get(ip, (ip, None, None, None)) for ip in self.groups[family])
        with self.metrics.lock:
            self.metrics.ping = results(self.active)
            self.metrics.ping_other = results(self._other(self.active))
            self.metrics.ping_family = self.active
            self.metrics.ping_auto = self.mode == "auto"

    @classmethod
    def from_config(cls, section, metrics, on_event=None):
        """Build from a configparser [ping] section; None if disabled."""
        if not section.getboolean("enabled", fallback=True):
            return None
        return cls(
            metrics,
            **ping_settings(section),
            return_clean_cycles=section.getint("return_clean_cycles", fallback=60),
            interval_s=section.getint("interval_ms", fallback=1000) / 1000.0,
            timeout_ms=section.getint("timeout_ms", fallback=1000),
            window=section.getint("window", fallback=60),
            notify=section.getboolean("notify", fallback=True),
            alert_after=section.getint("alert_after", fallback=1),
            cooldown_s=section.getfloat("cooldown_s", fallback=60.0),
            mute_after_alerts=section.getint("mute_after_alerts", fallback=5),
            mute_window_s=section.getfloat("mute_window_s", fallback=120),
            unmute_after_s=section.getfloat("unmute_after_s", fallback=1800),
            on_event=on_event,
        )

    def set_mode(self, mode):
        with self._lock:
            if mode not in ("auto", "ipv4", "ipv6"):
                raise ValueError("Modo de ping inválido.")
            if mode != "auto" and not self.groups[mode]:
                raise ValueError("O grupo escolhido está vazio.")
            self.mode = mode
            self.active = self._initial_family()
            self._generation += 1
            self._publish()

    def set_groups(self, v4, v6, preferred):
        fields = list(v4) + [""] * (2 - len(v4)) + list(v6) + [""] * (2 - len(v6))
        if len(v4) > 2 or len(v6) > 2:
            raise ValueError("No máximo dois IPs por grupo.")
        v4, v6 = parse_ping_groups(fields, preferred)
        with self._lock:
            self.groups = {"ipv4": v4, "ipv6": v6}
            self.preferred = preferred
            if self.mode != "auto" and not self.groups[self.mode]:
                self.mode = self._other(self.mode)
            self.active = self._initial_family()
            self._generation += 1
            self._results = {}
            self._clean = {"ipv4": 0, "ipv6": 0}
            self._samples = [deque(maxlen=self._outage_samples.maxlen) for _ in self.targets]
            self._outage_samples.clear()
            self._consec_lost = self._consec_ok = 0
            self._alert = self._alert_notified = False
            self._alert_start = 0.0
            self._alert_lost = 0
            self._last_notify = -1e9
            self._alert_times.clear()
            self._muted.clear()
            self._last_failure.clear()
            self._publish()

    def stop(self):
        self._stop_evt.set()

    # -- core ---------------------------------------------------------------
    def probe(self, pinger):
        """One cycle: sequential RTTs for all targets, without fallback."""
        with self._lock:
            targets, generation = self.targets, self._generation
        return _ProbeResults((pinger.ping(ip, self.timeout_ms) for ip in targets), generation)

    def record(self, rtts, now=None):
        """Feed a complete cycle; publish independent per-target windows."""
        with self._lock:
            if getattr(rtts, "generation", self._generation) != self._generation:
                return None
            return self._record(rtts, now)

    def _record(self, rtts, now):
        now = time.monotonic() if now is None else now
        if len(rtts) != len(self.targets):
            raise ValueError("one RTT is required for each target")
        results = []
        for ip, samples, rtt in zip(self.targets, self._samples, rtts):
            ok = rtt is not None
            samples.append(ok)
            loss = 100.0 * sum(not sample for sample in samples) / len(samples)
            results.append((ip, loss, rtt, ok))
        results = tuple(results)
        self._results = {result[0]: result for result in results}
        self._update_mutes(results, now)
        for family, targets in self.groups.items():
            clean = bool(targets) and all(self._results[ip][3] for ip in targets)
            self._clean[family] = self._clean[family] + 1 if clean else 0
        if self.mode == "auto":
            other = self._other(self.active)
            # Show current loss first, even when the return timer also expires.
            if (self.groups[other] and self._clean[self.active] > 0
                    and any(not self._results[ip][3] for ip in self.groups[other])):
                self._switch(other, now=now)
            elif (self.active != self.preferred and self.groups[self.preferred]
                  and self._clean[self.active] >= self.return_clean_cycles):
                self._switch(self.preferred, returning=True, now=now)
        self._publish()
        ok = any(result[3] for result in results)
        self._outage_samples.append(ok)
        loss = 100.0 * sum(not sample for sample in self._outage_samples) / len(self._outage_samples)
        self._update_alert(ok, now, loss, results)
        return results

    def _update_mutes(self, results, now):
        """Every failed probe restarts that IP's quiet period, even off-screen."""
        if not self.mute_after_alerts:
            return
        for ip, _, _, ok in results:
            if not ok:
                self._last_failure[ip] = now
            elif ip in self._muted and now - self._last_failure[ip] >= self.unmute_after_s:
                self._muted.remove(ip)
                self._alert_times.pop(ip, None)
                self.on_event(f"ping: alertas reativados para {ip} após "
                              f"{self.unmute_after_s:g}s sem queda")

    def _notify_loss(self, title, message, targets, now):
        """Count loss-toast subjects before filtering, including omitted toasts."""
        if not self.notify:
            return False
        if self.mute_after_alerts:
            for ip in targets:
                history = self._alert_times.setdefault(ip, deque(maxlen=self.mute_after_alerts))
                while history and now - history[0] > self.mute_window_s:
                    history.popleft()
                history.append(now)
                if ip not in self._muted and len(history) >= self.mute_after_alerts:
                    self._muted.add(ip)
                    self.on_event(f"ping: alertas silenciados para {ip}: "
                                  f"{self.mute_after_alerts} alertas em {self.mute_window_s:g}s")
                    self._notifier("Alertas silenciados",
                        f"{ip} instável: {self.mute_after_alerts} alertas em "
                        f"{self.mute_window_s / 60:g} min. Avisos dele voltam após "
                        f"{self.unmute_after_s / 60:g} min sem queda.")
            if all(ip in self._muted for ip in targets):
                return False
        self._notifier(title, message)
        return True

    def _switch(self, family, returning=False, now=None):
        now = time.monotonic() if now is None else now
        previous_targets = self.groups[self.active]
        previous = "IPv4" if self.active == "ipv4" else "IPv6"
        name = "IPv4" if family == "ipv4" else "IPv6"
        self.active = family
        if returning:
            title = f"Ping: de volta ao {name}"
            seconds = self.return_clean_cycles * self.interval_s
            duration = f"{seconds / 60:g} min" if seconds >= 60 and seconds % 60 == 0 else f"{seconds:g} s"
            message = f"{previous} sem perda há {duration}."
        else:
            title = f"Ping: perda no {name}"
            failed = [ip for ip in self.groups[family] if not self._results[ip][3]]
            message = f"Sem resposta de {' e '.join(failed)}; exibindo {name}."
        self.on_event(f"{title}: {message}")
        if returning:
            if self.notify and not any(ip in self._muted for ip in previous_targets):
                self._notifier(title, message)
        else:
            self._notify_loss(title, message, failed, now)

    def _update_alert(self, ok, now, loss, results):
        if ok:
            self._consec_ok += 1
            self._consec_lost = 0
            if self._alert and self._consec_ok >= self.recover_after:
                dur = now - self._alert_start
                self.on_event(f"ping: connection recovered after {dur:.0f}s "
                              f"({self._alert_lost} lost probes)")
                if self.notify and self._alert_notified:
                    self._notifier("Conexão restabelecida",
                                   f"Instável por {dur:.0f}s · {self._alert_lost} pacote(s) perdido(s).")
                self._alert = False
            return
        self._consec_lost += 1
        self._consec_ok = 0
        if self._alert:
            self._alert_lost += 1
        if not self._alert and self._consec_lost >= self.alert_after:
            self._alert = True
            self._alert_start = now
            self._alert_lost = self._consec_lost
            self._alert_notified = False
            self.on_event(f"ping: packet loss detected (window loss {loss:.1f}%, "
                          f"targets {','.join(self.targets)})")
            if self.notify and now - self._last_notify >= self.cooldown_s:
                self._last_notify = now
                self._alert_notified = self._notify_loss(
                    "Perda de pacotes detectada",
                    f"Sem resposta de {' e '.join(self.targets)}. " +
                    " · ".join(f"{ip} {fmt_loss(target_loss)}"
                               for ip, target_loss, _, _ in results), self.targets, now)

    def run(self):
        try:
            pinger = self._pinger_factory()
            if isinstance(pinger, IcmpPinger):
                pinger.on_event = self.on_event
        except Exception as e:  # no iphlpapi / handle failure: widget keeps "--"
            self.on_event(f"ping: ICMP unavailable ({e}); monitor disabled")
            return
        try:
            while not self._stop_evt.is_set():
                t0 = time.monotonic()
                try:
                    self.record(self.probe(pinger))
                except Exception as e:
                    self.on_event(f"ping: cycle error {e!r}")
                self._stop_evt.wait(max(0.05, self.interval_s - (time.monotonic() - t0)))
        finally:
            try:
                pinger.close()
            except Exception:
                pass


