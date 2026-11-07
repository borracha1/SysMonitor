# Histórico de tráfego por família: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** clicar na parte v4 ou v6 da rede abre uma janela com o gráfico de 1 h ou 4 h do tráfego daquela família, com as falhas de ping marcadas, e o histórico sobrevive ao reinício.

**Architecture:** `traffic_history.py` (sem Tk) acumula pontos de 5 s, grava o CSV e monta o gráfico como dados puros, numa thread própria. `traffic_history_ui.py` só desenha. `ping_monitor.py` entrega as marcas exatas, e `sys_monitor.py` liga o clique, o menu e o início/fim.

**Tech Stack:** Python 3.12, Tkinter `Canvas`, ctypes/Win32, `unittest`. Sem dependência nova.

**Spec:** `docs/superpowers/specs/2026-11-06-historico-trafego-design.md`

## Global Constraints

- Branch `versao-1.1`. Commits locais por tarefa, sem push, tag ou release.
- Nunca alterar nem adicionar `config.ini`, e nunca usar `git add -A`: tem mudanças locais do Mateus.
- Não matar nem reiniciar o widget. Não rodar `build.ps1`: o Claude gera o instalador depois da revisão.
- Sem privilégio elevado, driver, rede nova ou dependência nova; continuar compatível com HVCI.
- Testes: `py -3.12 -m unittest discover -s tests`; um arquivo: `py -3.12 -m unittest discover -s tests -p "test_x.py"`. O `python` do PATH não serve. Base atual: 207 OK.
- Testes nunca tocam no `config.ini` nem no CSV reais: pasta temporária e relógio falso.
- Texto para o usuário em português do Brasil.
- `net_rates` é `((up_v4, up_v6), (down_v4, down_v6))`: o índice 0 é upload.
- Não usar o nome `_stop` em subclasse de `threading.Thread`: conflita com a classe base.
- Pare só em falha de testes que não souber resolver; tropeço de edição, refaça e siga.

## Review Focus

- **PC dormiu ou hibernou:** os pontos continuam de onde estavam e o gráfico mostra um buraco, sem ligar os dois lados. Teste na Tarefa 3.
- **Relógio do Windows voltou para trás:** pontos fora de ordem não quebram nem embaralham o gráfico. Testes nas Tarefas 2 e 3.
- **Família sem tráfego (tudo zero):** não há divisão por zero; a linha fica na base e o eixo mostra só o zero. Teste na Tarefa 3.
- **Janela muito pequena ou ainda sem tamanho:** `build_chart` devolve `None` e nada quebra (o `Canvas` nasce com 1x1). Testes nas Tarefas 3 e 4.
- **Explorer reinicia com a janela aberta:** a janela é filha da raiz oculta, não do widget, e continua viva; o widget novo volta a aceitar clique. Testes nas Tarefas 4 e 5.

---

### Task 1: Marcas de perda no monitor de ping

**Files:**
- Modify: `ping_monitor.py` (`__init__`, `_record`, `set_groups`, novo `take_loss_marks`)
- Test: `tests/test_ping_loss_marks.py`

**Interfaces:**
- Produces: `PingMonitor.take_loss_marks() -> {"ipv4": 0|1|2, "ipv6": 0|1|2}`. Pior marca desde a última chamada: 0 nenhuma falha, 1 algum IP da família sem resposta, 2 todos. Zera ao ler.

- [ ] **Step 1: Escrever os testes**

```python
"""Exact per-family loss marks for the traffic history; no real toasts."""
import unittest

import ping_monitor as pm
from metrics_collector import Metrics


class LossMarkTests(unittest.TestCase):
    def monitor(self, **kwargs):
        options = dict(targets_v4=('1.1.1.1', '8.8.8.8'), targets_v6=('::1',),
                       notifier=lambda *args: None)
        options.update(kwargs)
        return pm.PingMonitor(Metrics(), **options)

    def test_marks_none_partial_and_total_per_family(self):
        monitor = self.monitor()
        monitor.record((12, 12, 12), now=0)
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 0, 'ipv6': 0})
        monitor.record((None, 12, 12), now=1)
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 1, 'ipv6': 0})
        monitor.record((None, None, None), now=2)
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 2, 'ipv6': 2})

    def test_reading_clears_the_marks(self):
        monitor = self.monitor()
        monitor.record((None, None, 12), now=0)
        monitor.take_loss_marks()
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 0, 'ipv6': 0})

    def test_keeps_the_worst_mark_between_reads(self):
        monitor = self.monitor()
        monitor.record((None, None, 12), now=0)
        monitor.record((None, 12, 12), now=1)
        monitor.record((12, 12, 12), now=2)
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 2, 'ipv6': 0})

    def test_marks_do_not_depend_on_notification_settings(self):
        for options in ({'notify': False}, {'notify_ipv4': False, 'notify_ipv6': False}):
            with self.subTest(options=options):
                monitor = self.monitor(**options)
                monitor.record((None, 12, None), now=0)
                self.assertEqual(monitor.take_loss_marks(), {'ipv4': 1, 'ipv6': 2})

    def test_replacing_groups_clears_the_marks(self):
        monitor = self.monitor()
        monitor.record((None, None, None), now=0)
        monitor.set_groups(('9.9.9.9',), ('::2',), 'ipv4')
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 0, 'ipv6': 0})

    def test_empty_family_stays_at_zero(self):
        monitor = self.monitor(targets_v6=())
        monitor.record((None, None), now=0)
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 2, 'ipv6': 0})


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -3.12 -m unittest discover -s tests -p "test_ping_loss_marks.py"`
Expected: ERROR com `AttributeError: 'PingMonitor' object has no attribute 'take_loss_marks'`

- [ ] **Step 3: Implementar**

Em `__init__`, junto de `self._family_clean`:

```python
        self._loss_marks = {"ipv4": 0, "ipv6": 0}
```

Em `_record`, dentro do `for family, targets in self.groups.items():`, depois da linha do `self._clean[family]`:

```python
            if targets:
                failed = sum(not self._results[ip][3] for ip in targets)
                mark = 2 if failed == len(targets) else 1 if failed else 0
                self._loss_marks[family] = max(self._loss_marks[family], mark)
```

Em `set_groups`, junto de `self._family_clean = ...`:

```python
            self._loss_marks = {"ipv4": 0, "ipv6": 0}
```

Novo método, logo depois de `set_family_notify`:

```python
    def take_loss_marks(self):
        """Worst mark per family since the last read: 0 none, 1 some IPs, 2 all."""
        with self._lock:
            marks, self._loss_marks = self._loss_marks, {"ipv4": 0, "ipv6": 0}
            return marks
```

- [ ] **Step 4: Rodar a suíte de ping**

Run: `py -3.12 -m unittest discover -s tests -p "test_ping*.py"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add ping_monitor.py tests/test_ping_loss_marks.py
git commit -m "feat(ping): expõe marcas exatas de perda por família"
```

---

### Task 2: Pontos, CSV e gravador

**Files:**
- Create: `traffic_history.py`
- Test: `tests/test_traffic_history.py`

**Interfaces:**
- Consumes: `PingMonitor.take_loss_marks()`; `metrics.lock` e `metrics.net_rates`.
- Produces:
  - `FamilyPoint(epoch, down, up, mark)` (namedtuple; `down` e `up` podem ser `None`).
  - `TrafficHistory(path, log, clock=time.time)`, com `.clock`, `add_sample(rates, marks)`, `finish_bucket()`, `points(family, period_s) -> list[FamilyPoint]` em ordem de horário, `load()`, `flush() -> bool` e `rewrite() -> bool`.
  - `TrafficRecorder(history, metrics, ping_monitor=None, log=..., interval_s=1.0, flush_s=60.0, rewrite_s=3600.0, clock=time.monotonic)`, com `start()`, `stop()`, `join(timeout)` e `tick()`.

- [ ] **Step 1: Escrever os testes**

```python
"""Traffic buckets and CSV storage with a fake clock and temporary folders."""
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import traffic_history as th


def rates(up4=0, up6=0, down4=0, down6=0):
    return ((up4, up6), (down4, down6))


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class BucketTests(unittest.TestCase):
    def history(self, clock):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return th.TrafficHistory(Path(directory.name) / 'h.csv', Mock(), clock=clock)

    def test_point_has_average_rates_worst_mark_and_aligned_time(self):
        clock = Clock(1001.0)
        history = self.history(clock)
        history.add_sample(rates(up4=10, down4=100), {'ipv4': 1, 'ipv6': 0})
        clock.now = 1003.0
        history.add_sample(rates(up4=30, down4=300), {'ipv4': 2, 'ipv6': 0})
        clock.now = 1005.0
        history.add_sample(rates(), {})
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(1000, 200, 20, 2)])

    def test_each_family_reads_its_own_columns(self):
        clock = Clock()
        history = self.history(clock)
        history.add_sample(rates(1, 2, 3, 4), {'ipv4': 0, 'ipv6': 1})
        history.finish_bucket()
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(1000, 3, 1, 0)])
        self.assertEqual(history.points('ipv6', 3600), [th.FamilyPoint(1000, 4, 2, 1)])

    def test_interval_without_measurement_keeps_empty_rates_and_the_mark(self):
        clock = Clock()
        history = self.history(clock)
        history.add_sample(None, {'ipv4': 2})
        history.finish_bucket()
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(1000, None, None, 2)])

    def test_points_respect_the_period(self):
        clock = Clock()
        history = self.history(clock)
        history.add_sample(rates(), {})
        history.finish_bucket()
        clock.now = 1000.0 + 3601
        self.assertEqual(history.points('ipv4', 3600), [])
        self.assertEqual(len(history.points('ipv4', 14400)), 1)

    def test_clock_going_back_keeps_points_in_time_order(self):
        clock = Clock(2000.0)
        history = self.history(clock)
        history.add_sample(rates(down4=1), {})
        clock.now = 1000.0
        history.add_sample(rates(down4=2), {})
        history.finish_bucket()
        clock.now = 2001.0
        self.assertEqual([p.epoch for p in history.points('ipv4', 3600)], [1000, 2000])


class StorageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'h.csv'
        self.log = Mock()
        self.clock = Clock(100000.0)

    def history(self):
        return th.TrafficHistory(self.path, self.log, clock=self.clock)

    def add_point(self, history, down4=100):
        history.add_sample(rates(1, 2, down4, 4), {'ipv4': 1, 'ipv6': 2})
        history.finish_bucket()
        self.clock.now += th.BUCKET_S

    def test_round_trip_survives_a_restart(self):
        first = self.history()
        first.load()
        self.add_point(first)
        self.assertTrue(first.flush())
        second = self.history()
        second.load()
        self.assertEqual(second.points('ipv4', 3600), [th.FamilyPoint(100000, 100, 1, 1)])
        self.assertEqual(second.points('ipv6', 3600), [th.FamilyPoint(100000, 4, 2, 2)])

    def test_flush_appends_only_new_points(self):
        history = self.history()
        history.load()
        self.add_point(history)
        history.flush()
        self.add_point(history)
        history.flush()
        history.flush()
        self.assertEqual(len(self.path.read_text(encoding='ascii').splitlines()), 2)

    def test_load_ignores_bad_lines_and_times_out_of_range(self):
        now = int(self.clock.now)
        good = f'{now - 60},1,2,3,4,0,1\n'
        self.path.write_text(
            'lixo\n' + f'{now - 90},1,2\n' + f'{now - 80},1,2,3,4,0,9\n' + f'{now - 70},-1,2,3,4,0,0\n'
            + f'{now - th.KEEP_S - 5},1,2,3,4,0,0\n' + f'{now + th.FUTURE_TOLERANCE_S + 5},1,2,3,4,0,0\n'
            + good + f'{now - 50},1,2,3', encoding='ascii')
        history = self.history()
        history.load()
        self.assertEqual([p.epoch for p in history.points('ipv4', th.KEEP_S)], [now - 60])
        self.assertEqual(self.path.read_text(encoding='ascii'), good)

    def test_cut_line_from_power_loss_does_not_damage_the_next_write(self):
        now = int(self.clock.now)
        self.path.write_text(f'{now - 60},1,2,3,4,0,1\n{now - 50},1,2', encoding='ascii')
        history = self.history()
        history.load()
        self.add_point(history)
        history.flush()
        second = self.history()
        second.load()
        self.assertEqual(len(second.points('ipv4', 3600)), 2)

    def test_rewrite_drops_points_older_than_four_hours(self):
        history = self.history()
        history.load()
        self.add_point(history)
        history.flush()
        self.clock.now += th.KEEP_S + 1
        self.add_point(history)
        self.assertTrue(history.rewrite())
        self.assertEqual(len(self.path.read_text(encoding='ascii').splitlines()), 1)

    def test_write_failure_logs_once_keeps_points_and_retries(self):
        history = self.history()
        history.load()
        self.add_point(history)
        with patch('builtins.open', side_effect=OSError('denied')), \
                patch('traffic_history.tempfile.NamedTemporaryFile', side_effect=OSError('denied')):
            self.assertFalse(history.flush())
            self.assertFalse(history.flush())
        self.assertEqual(self.log.call_count, 1)
        self.assertEqual(len(history.points('ipv4', 3600)), 1)
        self.assertTrue(history.flush())
        self.assertEqual(len(self.path.read_text(encoding='ascii').splitlines()), 1)

    def test_memory_stays_limited_to_four_hours_of_points(self):
        history = self.history()
        for _ in range(th.MAX_POINTS + 10):
            self.add_point(history)
        self.assertEqual(len(history.points('ipv4', th.KEEP_S * 2)), th.MAX_POINTS)


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.metrics = SimpleNamespace(lock=threading.Lock(), net_rates=rates(1, 2, 3, 4))
        self.history = Mock()
        self.clock = Clock(0.0)

    def recorder(self, ping=None, log=None):
        return th.TrafficRecorder(self.history, self.metrics, ping, log or Mock(),
                                  flush_s=60, rewrite_s=3600, clock=self.clock)

    def test_tick_feeds_rates_and_marks(self):
        ping = Mock()
        ping.take_loss_marks.return_value = {'ipv4': 1, 'ipv6': 0}
        self.recorder(ping).tick()
        self.history.add_sample.assert_called_once_with(rates(1, 2, 3, 4), {'ipv4': 1, 'ipv6': 0})

    def test_tick_without_ping_has_no_marks(self):
        self.recorder().tick()
        self.history.add_sample.assert_called_once_with(rates(1, 2, 3, 4), {})

    def test_flush_every_minute_and_rewrite_every_hour(self):
        recorder = self.recorder()
        self.clock.now = 59.0
        recorder.tick()
        self.history.flush.assert_not_called()
        self.clock.now = 60.0
        recorder.tick()
        self.history.flush.assert_called_once()
        self.clock.now = 3600.0
        recorder.tick()
        self.history.rewrite.assert_called_once()

    def test_stop_finishes_the_open_point_and_writes(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'h.csv'
        history = th.TrafficHistory(path, Mock())
        recorder = th.TrafficRecorder(history, self.metrics, None, Mock(), interval_s=0.01)
        recorder.start()
        while not history._bucket:
            pass
        recorder.stop()
        recorder.join(2)
        self.assertFalse(recorder.is_alive())
        self.assertTrue(path.read_text(encoding='ascii'))

    def test_failure_is_logged_once_and_never_ends_the_thread(self):
        log = Mock()
        self.history.add_sample.side_effect = ValueError('boom')
        recorder = th.TrafficRecorder(self.history, self.metrics, None, log, interval_s=0.01)
        recorder.start()
        while self.history.add_sample.call_count < 3:
            pass
        self.assertTrue(recorder.is_alive())
        recorder.stop()
        recorder.join(2)
        self.assertEqual(log.call_count, 1)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -3.12 -m unittest discover -s tests -p "test_traffic_history.py"`
Expected: ERROR com `ModuleNotFoundError: No module named 'traffic_history'`

- [ ] **Step 3: Implementar `traffic_history.py`**

```python
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -3.12 -m unittest discover -s tests -p "test_traffic_history.py"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add traffic_history.py tests/test_traffic_history.py
git commit -m "feat(trafego): pontos de 5 s, CSV de 4 h e gravador em thread própria"
```

---

### Task 3: Dados do gráfico

**Files:**
- Modify: `traffic_history.py` (acrescentar `build_chart` ao fim)
- Test: `tests/test_traffic_chart.py`

**Interfaces:**
- Consumes: `FamilyPoint`, `BUCKET_S`.
- Produces: `build_chart(points, width, height, now, period_s, fmt_time=local_hhmm) -> Chart | None`. `None` quando a área de desenho é pequena demais.
  - `Chart(plot, down, up, bands, x_ticks, y_ticks)`
  - `plot`: `(x0, y0, x1, y1)`.
  - `down` e `up`: listas de trechos, cada trecho uma lista de `(x, y)`.
  - `bands`: `(x_left, x_right, mark)`, marca 1 antes da 2, para a forte ficar por cima.
  - `x_ticks`: `(x, texto)`. `y_ticks`: `(y, bytes_por_segundo)`.

- [ ] **Step 1: Escrever os testes**

```python
"""Pure chart geometry: every number here is what the window will draw."""
import unittest

from traffic_history import FamilyPoint as P, build_chart

NOW = 1_000_000
HOUR = 3600
FOUR = 4 * 3600


def chart(points, width=800, height=360, now=NOW, period=HOUR):
    return build_chart(points, width, height, now, period, fmt_time=str)


class ChartTests(unittest.TestCase):
    def test_peak_touches_the_top_and_zero_the_base(self):
        result = chart([P(NOW - 20, 0, 0, 0), P(NOW - 10, 100, 50, 0)])
        _, y0, _, y1 = result.plot
        self.assertEqual(result.down[0][0][1], y1)
        self.assertEqual(result.down[0][1][1], y0)
        self.assertEqual(result.up[0][1][1], (y0 + y1) / 2)

    def test_time_runs_left_to_right(self):
        result = chart([P(NOW - HOUR, 1, 1, 0), P(NOW, 1, 1, 0)])
        x0, _, x1, _ = result.plot
        self.assertEqual([point[0] for segment in result.down for point in segment], [x0, x1])

    def test_short_peak_survives_when_there_are_more_points_than_pixels(self):
        points = [P(NOW - FOUR + i * 5, 100, 100, 0) for i in range(2880)]
        points[1000] = P(points[1000].epoch, 9000, 100, 0)
        result = chart(points, width=400, period=FOUR)
        _, y0, _, _ = result.plot
        self.assertIn(y0, [y for _, y in result.down[0]])

    def test_interval_above_15_s_breaks_the_line(self):
        result = chart([P(NOW - 100, 1, 1, 0), P(NOW - 95, 1, 1, 0), P(NOW - 79, 1, 1, 0)])
        self.assertEqual([len(segment) for segment in result.down], [2, 1])

    def test_interval_of_exactly_15_s_keeps_the_line(self):
        result = chart([P(NOW - 100, 1, 1, 0), P(NOW - 85, 1, 1, 0)])
        self.assertEqual([len(segment) for segment in result.down], [2])

    def test_pc_asleep_for_an_hour_shows_a_hole(self):
        result = chart([P(NOW - FOUR + 10, 1, 1, 0), P(NOW - 10, 1, 1, 0)], period=FOUR)
        self.assertEqual(len(result.down), 2)

    def test_missing_measurement_breaks_the_line_but_keeps_the_mark(self):
        result = chart([P(NOW - 100, 1, 1, 0), P(NOW - 95, None, None, 2), P(NOW - 90, 1, 1, 0)])
        self.assertEqual(len(result.down), 2)
        self.assertEqual([band[2] for band in result.bands], [2])

    def test_points_out_of_order_are_drawn_in_time_order(self):
        result = chart([P(NOW, 1, 1, 0), P(NOW - HOUR, 1, 1, 0)])
        xs = [point[0] for segment in result.down for point in segment]
        self.assertEqual(xs, sorted(xs))

    def test_family_without_traffic_stays_on_the_base_with_only_zero_on_the_axis(self):
        result = chart([P(NOW - 10, 0, 0, 0), P(NOW - 5, 0, 0, 0)])
        _, _, _, y1 = result.plot
        self.assertEqual({y for _, y in result.down[0]}, {y1})
        self.assertEqual(result.y_ticks, [(y1, 0)])

    def test_axis_shows_zero_middle_and_peak(self):
        result = chart([P(NOW - 10, 100, 0, 0)])
        _, y0, _, y1 = result.plot
        self.assertEqual(result.y_ticks, [(y1, 0), ((y0 + y1) / 2, 50), (y0, 100)])

    def test_strong_marks_are_drawn_after_light_ones_and_clean_points_have_none(self):
        result = chart([P(NOW - 100, 1, 1, 2), P(NOW - 50, 1, 1, 0), P(NOW - 10, 1, 1, 1)])
        self.assertEqual([band[2] for band in result.bands], [1, 2])

    def test_mark_band_is_at_least_one_pixel_and_stays_inside_the_plot(self):
        result = chart([P(NOW, 1, 1, 2)], period=FOUR)
        left, right, _ = result.bands[0]
        _, _, x1, _ = result.plot
        self.assertLessEqual(right, x1)
        self.assertGreaterEqual(right - left, 0)
        result = chart([P(NOW - 100, 1, 1, 2)], period=FOUR)
        self.assertGreaterEqual(result.bands[0][1] - result.bands[0][0], 1)

    def test_time_marks_every_15_min_in_one_hour_and_every_hour_in_four(self):
        now = 36000
        one = build_chart([], 800, 360, now, HOUR, fmt_time=str)
        self.assertEqual([text for _, text in one.x_ticks], [str(32400 + i * 900) for i in range(5)])
        four = build_chart([], 800, 360, now, FOUR, fmt_time=str)
        self.assertEqual([text for _, text in four.x_ticks], [str(21600 + i * 3600) for i in range(5)])

    def test_points_outside_the_period_are_ignored(self):
        result = chart([P(NOW - HOUR - 1, 9000, 9000, 2), P(NOW - 10, 100, 0, 0)])
        self.assertEqual(result.y_ticks[-1][1], 100)
        self.assertEqual(result.bands, [])

    def test_area_too_small_returns_none(self):
        for width, height in ((1, 1), (50, 200), (800, 20)):
            with self.subTest(width=width, height=height):
                self.assertIsNone(build_chart([P(NOW, 1, 1, 0)], width, height, NOW, HOUR))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -3.12 -m unittest discover -s tests -p "test_traffic_chart.py"`
Expected: ERROR com `ImportError: cannot import name 'build_chart'`

- [ ] **Step 3: Implementar, ao fim de `traffic_history.py`**

```python
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -3.12 -m unittest discover -s tests -p "test_traffic*.py"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add traffic_history.py tests/test_traffic_chart.py
git commit -m "feat(trafego): monta os dados do gráfico sem depender do Tk"
```

---

### Task 4: Janela do histórico

**Files:**
- Create: `traffic_history_ui.py`
- Test: `tests/test_traffic_window.py`

**Interfaces:**
- Consumes: `build_chart`, `Chart`; `history.points(family, period_s)` e `history.clock()`.
- Produces: `TrafficHistoryWindow(master, history, fmt_speed, accent_up, accent_down, work_area=None)`, com `show(family=None)`, `close()` e `redraw()`. `family` é `'ipv4'` ou `'ipv6'`; `None` mantém a última vista. Também `centered_geometry(work, width, height) -> str`.

- [ ] **Step 1: Escrever os testes**

```python
"""History window logic with a fake Tk: nothing is shown on screen."""
import unittest
from unittest.mock import Mock, patch

import traffic_history_ui as ui
from traffic_history import FamilyPoint


class WindowTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(ui, 'tk')
        self.tk = patcher.start()
        self.addCleanup(patcher.stop)
        self.tk.TclError = RuntimeError
        self.tk.Button.side_effect = lambda *args, **kwargs: Mock()
        self.master = Mock()
        self.history = Mock()
        self.history.clock.return_value = 1_000_000
        self.history.points.return_value = []
        self.top = self.tk.Toplevel.return_value
        self.top.winfo_exists.return_value = True
        self.canvas = self.tk.Canvas.return_value
        self.canvas.winfo_width.return_value = 800
        self.canvas.winfo_height.return_value = 360
        self.window = ui.TrafficHistoryWindow(self.master, self.history, lambda v: f'{v}B', '#111', '#222',
                                              work_area=lambda: (0, 0, 1920, 1040))

    def shown_family(self):
        return self.history.points.call_args.args[0]

    def test_window_is_a_child_of_the_hidden_root_so_it_survives_explorer_restart(self):
        self.window.show('ipv4')
        self.tk.Toplevel.assert_called_once_with(self.master)

    def test_opens_on_the_clicked_family(self):
        self.window.show('ipv6')
        self.assertEqual(self.shown_family(), 'ipv6')

    def test_default_family_is_ipv4_and_period_is_one_hour(self):
        self.window.show()
        self.assertEqual(self.history.points.call_args.args, ('ipv4', 3600))

    def test_second_click_reuses_the_window_and_changes_family(self):
        self.window.show('ipv4')
        self.window.show('ipv6')
        self.tk.Toplevel.assert_called_once()
        self.top.lift.assert_called()
        self.assertEqual(self.shown_family(), 'ipv6')

    def test_menu_opens_the_last_family_seen(self):
        self.window.show('ipv6')
        self.window.close()
        self.window.show()
        self.assertEqual(self.shown_family(), 'ipv6')

    def test_chosen_period_lasts_until_the_program_closes(self):
        self.window.show('ipv4')
        self.window._select_period(14400)
        self.assertEqual(self.history.points.call_args.args, ('ipv4', 14400))
        self.window.close()
        self.window.show()
        self.assertEqual(self.history.points.call_args.args[1], 14400)

    def test_selected_buttons_are_highlighted(self):
        self.window.show('ipv6')
        self.assertEqual(self.window._buttons['ipv6'].config.call_args.kwargs['relief'], 'sunken')
        self.assertEqual(self.window._buttons['ipv4'].config.call_args.kwargs['relief'], 'raised')

    def test_refreshes_every_5_s_and_close_cancels_it(self):
        self.window.show('ipv4')
        self.top.after.assert_called_with(5000, self.window._refresh)
        self.top.after.return_value = 'job'
        self.window._refresh()
        self.window.close()
        self.top.after_cancel.assert_called_with('job')
        self.top.destroy.assert_called_once()
        calls = self.history.points.call_count
        self.window.redraw()
        self.assertEqual(self.history.points.call_count, calls)

    def test_window_closed_by_the_system_is_recreated(self):
        self.window.show('ipv4')
        self.top.winfo_exists.return_value = False
        self.window.show('ipv4')
        self.assertEqual(self.tk.Toplevel.call_count, 2)

    def test_canvas_not_measured_yet_draws_nothing_and_does_not_fail(self):
        self.canvas.winfo_width.return_value = 1
        self.canvas.winfo_height.return_value = 1
        self.window.show('ipv4')
        self.canvas.create_line.assert_not_called()

    def test_no_data_shows_collecting_message(self):
        self.window.show('ipv4')
        texts = [call.kwargs.get('text') for call in self.canvas.create_text.call_args_list]
        self.assertIn('Coletando dados…', texts)

    def test_single_point_segment_is_still_drawn(self):
        self.history.points.return_value = [FamilyPoint(1_000_000 - 10, 100, None, 0)]
        self.window.show('ipv4')
        self.assertTrue(self.canvas.create_line.called)

    def test_close_without_a_window_and_after_tk_is_gone_is_harmless(self):
        self.window.close()
        self.window.show('ipv4')
        self.top.destroy.side_effect = RuntimeError('gone')
        self.window.close()

    def test_title_says_the_values_are_estimated(self):
        self.window.show('ipv4')
        self.top.title.assert_called_once_with('SysMonitor · Histórico de tráfego (estimado)')


class GeometryTests(unittest.TestCase):
    def test_centers_inside_the_work_area_of_the_clicked_screen(self):
        self.assertEqual(ui.centered_geometry((0, 0, 1920, 1040), 800, 360), '800x360+560+340')
        self.assertEqual(ui.centered_geometry((-1920, 100, 0, 1180), 800, 360), '800x360+-1360+460')

    def test_never_starts_above_or_left_of_a_small_screen(self):
        self.assertEqual(ui.centered_geometry((0, 0, 640, 300), 800, 360), '800x360+0+0')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -3.12 -m unittest discover -s tests -p "test_traffic_window.py"`
Expected: ERROR com `ModuleNotFoundError: No module named 'traffic_history_ui'`

- [ ] **Step 3: Implementar `traffic_history_ui.py`**

```python
"""History window: only draws what traffic_history.build_chart returns.

A Toplevel of the hidden root, never of the widget embedded in Explorer, so it
survives the widget being rebuilt when Explorer restarts.
"""
import ctypes
from ctypes import wintypes
import tkinter as tk

from traffic_history import build_chart

BG = '#15171a'
FG = '#e6e6e6'
GRID = '#33373d'
MARK_COLORS = {1: '#6b2a2a', 2: '#d83a3a'}
WIDTH, HEIGHT = 800, 360
REFRESH_MS = 5000
HOUR = 3600
FOUR_HOURS = 4 * HOUR


class _MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]


def pointer_work_area():
    """Work area (left, top, right, bottom) of the screen under the mouse, or None."""
    try:
        user32 = ctypes.WinDLL('user32')  # Private instance: argtypes stay local.
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(user32.MonitorFromPoint(point, 2), ctypes.byref(info)):
            return None
        work = info.rcWork
        return work.left, work.top, work.right, work.bottom
    except (OSError, AttributeError):
        return None


def centered_geometry(work, width, height):
    left, top, right, bottom = work
    x = left + max(0, (right - left - width) // 2)
    y = top + max(0, (bottom - top - height) // 2)
    return f'{width}x{height}+{x}+{y}'


class TrafficHistoryWindow:
    def __init__(self, master, history, fmt_speed, accent_up, accent_down, work_area=None):
        self.master = master
        self.history = history
        self.fmt_speed = fmt_speed
        self.accent_up = accent_up
        self.accent_down = accent_down
        self.work_area = work_area or pointer_work_area
        self.family = 'ipv4'
        self.period_s = HOUR
        self.window = None
        self.canvas = None
        self._buttons = {}
        self._after_id = None

    def show(self, family=None):
        if family is not None:
            self.family = family
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
        else:
            self._build()
        self._update_buttons()
        self.redraw()

    def close(self):
        window, self.window = self.window, None
        self.canvas = None
        self._buttons = {}
        after_id, self._after_id = self._after_id, None
        if window is None:
            return
        try:
            if after_id is not None:
                window.after_cancel(after_id)
            window.destroy()
        except tk.TclError:
            pass  # Tk is already gone while the program closes.

    def _build(self):
        window = self.window = tk.Toplevel(self.master)
        window.title('SysMonitor · Histórico de tráfego (estimado)')
        window.configure(bg=BG)
        work = self.work_area()
        if work is None:
            work = (0, 0, self.master.winfo_screenwidth(), self.master.winfo_screenheight())
        window.geometry(centered_geometry(work, WIDTH, HEIGHT))
        window.minsize(420, 240)
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.bind('<Escape>', lambda event: self.close())
        header = tk.Frame(window, bg=BG)
        header.pack(fill='x', padx=8, pady=6)
        self._buttons = {}
        for key, text, command in (
                ('ipv4', 'IPv4', lambda: self._select_family('ipv4')),
                ('ipv6', 'IPv6', lambda: self._select_family('ipv6')),
                (HOUR, '1 h', lambda: self._select_period(HOUR)),
                (FOUR_HOURS, '4 h', lambda: self._select_period(FOUR_HOURS))):
            button = tk.Button(header, text=text, width=5, command=command)
            button.pack(side='left', padx=(12 if key == HOUR else 2, 2))
            self._buttons[key] = button
        for text, color in (('↓ download', self.accent_down), ('↑ upload', self.accent_up),
                            ('▌ um IP sem resposta', MARK_COLORS[1]),
                            ('▌ todos sem resposta', MARK_COLORS[2])):
            tk.Label(header, text=text, fg=color, bg=BG).pack(side='right', padx=4)
        self.canvas = tk.Canvas(window, bg=BG, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda event: self.redraw())
        self._after_id = window.after(REFRESH_MS, self._refresh)

    def _select_family(self, family):
        self.family = family
        self._update_buttons()
        self.redraw()

    def _select_period(self, period_s):
        self.period_s = period_s
        self._update_buttons()
        self.redraw()

    def _update_buttons(self):
        for key, button in self._buttons.items():
            selected = key in (self.family, self.period_s)
            button.config(relief='sunken' if selected else 'raised')

    def _refresh(self):
        self.redraw()
        if self.window is not None:
            self._after_id = self.window.after(REFRESH_MS, self._refresh)

    def redraw(self):
        canvas = self.canvas
        if canvas is None:
            return
        canvas.delete('all')
        points = self.history.points(self.family, self.period_s)
        chart = build_chart(points, canvas.winfo_width(), canvas.winfo_height(),
                            self.history.clock(), self.period_s)
        if chart is None:
            return
        x0, y0, x1, y1 = chart.plot
        for left, right, mark in chart.bands:
            canvas.create_rectangle(left, y0, right, y1, fill=MARK_COLORS[mark], width=0)
        for y, value in chart.y_ticks:
            canvas.create_line(x0, y, x1, y, fill=GRID)
            canvas.create_text(x0 - 6, y, text=self.fmt_speed(value), fill=FG, anchor='e')
        for x, text in chart.x_ticks:
            canvas.create_line(x, y1, x, y1 + 4, fill=FG)
            canvas.create_text(x, y1 + 6, text=text, fill=FG, anchor='n')
        for segments, color in ((chart.up, self.accent_up), (chart.down, self.accent_down)):
            for segment in segments:
                coordinates = [value for point in segment for value in point]
                if len(segment) == 1:  # create_line needs two points.
                    coordinates += [segment[0][0] + 1, segment[0][1]]
                canvas.create_line(*coordinates, fill=color, width=1)
        if not points:
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text='Coletando dados…', fill=FG)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -3.12 -m unittest discover -s tests -p "test_traffic*.py"`
Expected: OK

- [ ] **Step 5: Conferência com Tk real, sem salvar nada no repositório**

Grave um script temporário em `D:/dev/temp/sysmonitor-1.1/ver_janela.py` que crie `tk.Tk()` oculta, um `TrafficHistory` em `D:/dev/temp/sysmonitor-1.1/h.csv`, preencha 4 h de pontos (com picos, buraco e as duas marcas), abra a janela, capture a tela da janela com PowerShell/System.Drawing em `D:/dev/temp/sysmonitor-1.1/janela.png` e feche. Confira na imagem: rótulos sem sobrepor, linhas nas cores certas e marcas nas duas intensidades. Não toque na barra real nem no widget em execução.

- [ ] **Step 6: Commit**

```bash
git add traffic_history_ui.py tests/test_traffic_window.py
git commit -m "feat(trafego): janela com gráfico por família e período"
```

---

### Task 5: Clique, menu, início e fim do programa

**Files:**
- Modify: `net_split.py` (`net_family_at`, `is_click`)
- Modify: `sys_monitor.py` (imports, `TRAFFIC_HISTORY_UI`, `_cursor_pos`, `MonitorWindow`, `main`)
- Modify: `version.py`, `.gitignore`, `tests/test_app_paths.py`, `tests/test_self_check.py`, `tests/test_ping_targets.py`
- Modify: `docs/agentes/interface.md`, `arquitetura.md`, `build-e-uso.md`, `estado.md`, `INDICE.md`
- Test: `tests/test_traffic_click.py`

**Interfaces:**
- Consumes: `TrafficHistory`, `TrafficRecorder`, `TrafficHistoryWindow.show(family=None)` e `close()`.
- Produces:
  - `net_family_at(x, left, widths) -> 'ipv4' | 'ipv6' | None`, com `widths = (prefixo, valor_v4, " v6 ", valor_v6)`.
  - `is_click(press, release, tolerance=3) -> bool`.
  - `MonitorWindow._on_net_click()` e `MonitorWindow._open_traffic_history(family=None)`.

- [ ] **Step 1: Escrever os testes**

```python
"""Left click on the network column; Win32 and Tk are replaced by fakes."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock
from ctypes import wintypes

from net_split import is_click, net_family_at
import test_ping_group_views as views


class PureClickTests(unittest.TestCase):
    WIDTHS = (30, 70, 25, 75)  # v4 half: 100 px; v6 half: 100 px.

    def test_each_half_opens_its_family_including_the_boundaries(self):
        self.assertEqual(net_family_at(500, 500, self.WIDTHS), 'ipv4')
        self.assertEqual(net_family_at(599, 500, self.WIDTHS), 'ipv4')
        self.assertEqual(net_family_at(600, 500, self.WIDTHS), 'ipv6')
        self.assertEqual(net_family_at(699, 500, self.WIDTHS), 'ipv6')

    def test_outside_the_column_is_nothing(self):
        self.assertIsNone(net_family_at(499, 500, self.WIDTHS))
        self.assertIsNone(net_family_at(700, 500, self.WIDTHS))

    def test_release_without_moving_is_a_click_and_a_drag_is_not(self):
        self.assertTrue(is_click((10, 10), (10, 10)))
        self.assertTrue(is_click((10, 10), (13, 7)))
        self.assertFalse(is_click((10, 10), (14, 10)))
        self.assertFalse(is_click((10, 10), (10, 6)))
        self.assertFalse(is_click(None, (10, 10)))


def rect(left, top, right, bottom):
    return wintypes.RECT(left, top, right, bottom)


class WindowClickTests(unittest.TestCase):
    def window(self, cursor, active=True):
        helper = views.GroupViewTests()
        ns = helper.namespace()
        window = helper.window(ns)
        ui = Mock()
        rects = {1: rect(500, 0, 700, 20), 2: rect(500, 20, 700, 40)}
        ns.update(TRAFFIC_HISTORY_UI=ui, net_family_at=net_family_at, is_click=is_click,
                  _cursor_pos=Mock(return_value=cursor), _win_rect=lambda hwnd: rects.get(hwnd))
        window.lbl_up = Mock(winfo_id=Mock(return_value=1))
        window.lbl_down = Mock(winfo_id=Mock(return_value=2))
        window._closing = False
        window._net_active = active
        window._net_font = Mock(measure=Mock(side_effect=lambda text: {
            '↑ v4 ': 30, '↓ v4 ': 30, '1000.0 Mbps': 70, ' v6 ': 60}[text]))
        return ns, window, ui

    def test_click_on_each_half_opens_that_family(self):
        for cursor, family in (((510, 10), 'ipv4'), ((510, 30), 'ipv4'),
                               ((690, 10), 'ipv6'), ((690, 30), 'ipv6')):
            with self.subTest(cursor=cursor):
                _, window, ui = self.window(cursor)
                window._on_net_click()
                ui.show.assert_called_once_with(family)

    def test_click_outside_the_network_column_does_nothing(self):
        for cursor in ((499, 10), (700, 10), (510, 40), (510, -1)):
            with self.subTest(cursor=cursor):
                _, window, ui = self.window(cursor)
                window._on_net_click()
                ui.show.assert_not_called()

    def test_without_split_on_screen_opens_the_last_family_seen(self):
        _, window, ui = self.window((510, 10), active=False)
        window._on_net_click()
        ui.show.assert_called_once_with(None)

    def test_refused_window_handle_or_closing_widget_does_nothing(self):
        ns, window, ui = self.window((510, 10))
        ns['_win_rect'] = lambda hwnd: None
        window._on_net_click()
        ui.show.assert_not_called()
        ns, window, ui = self.window((510, 10))
        window._closing = True
        window._on_net_click()
        ui.show.assert_not_called()

    def test_program_without_history_window_ignores_the_click(self):
        ns, window, _ = self.window((510, 10))
        ns['TRAFFIC_HISTORY_UI'] = None
        window._on_net_click()

    def test_taskbar_binds_left_click_on_text_and_catcher(self):
        _, window, _ = self.window((510, 10))
        window.mode, window.click_catcher = 'taskbar', Mock()
        window._bind_traffic_click()
        window.root.bind.assert_called_once()
        self.assertEqual(window.root.bind.call_args.args[0], '<Button-1>')
        window.click_catcher.bind.assert_called_once()
        self.assertEqual(window.click_catcher.bind.call_args.args[0], '<Button-1>')

    def test_rebuilt_widget_binds_the_click_again_after_explorer_restart(self):
        source = Path('sys_monitor.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MonitorWindow')
        init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
        self.assertIn('self._bind_traffic_click()', ast.get_source_segment(source, init))

    def test_floating_mode_leaves_left_button_to_drag(self):
        _, window, _ = self.window((510, 10))
        window.mode, window.click_catcher = 'floating', None
        window._bind_traffic_click()
        window.root.bind.assert_not_called()

    def test_menu_item_comes_before_limits_and_opens_last_family(self):
        ns, window, ui = self.window((510, 10))
        window._bind_menu()
        calls = [c for c in ns['tk'].Menu.return_value.method_calls if c[0] == 'add_command']
        labels = [c.kwargs['label'] for c in calls]
        index = labels.index('Histórico de tráfego…')
        self.assertEqual(labels[index + 1], 'Configurar limites de uso…')
        calls[index].kwargs['command']()
        ui.show.assert_called_once_with(None)


if __name__ == '__main__':
    unittest.main()
```

Em `tests/test_ping_targets.py`, `LifecycleTests.test_main_executes_reconfigurations_without_delay_or_fallback` executa `main()` num ambiente falso, que precisa conhecer as peças novas. É também o teste do início e do fim do gravador. Altere três pontos:

```python
        # 1. Troque a linha cfg.read_dict por:
        cfg.read_dict({'window': {'display_mode': 'taskbar', 'update_interval_ms': '1000',
                                  'accent_up': '#111', 'accent_down': '#222'}, 'ping': {}})

        # 2. Acrescente antes de ns = load_definitions(...):
        recorder, history_ui = Mock(), Mock()

        # 3. Acrescente ao dicionário de load_definitions, depois de '_log_event': logs:
            'TrafficHistory': Mock(), 'TrafficRecorder': Mock(return_value=recorder),
            'TrafficHistoryWindow': Mock(return_value=history_ui), 'fmt_speed': Mock(),
            'data_dir': lambda: Path('.')})

        # 4. Acrescente ao fim do teste:
        recorder.start.assert_called_once()
        recorder.stop.assert_called_once()
        recorder.join.assert_called_once_with(timeout=2)
        history_ui.close.assert_called_once()
```

Confira se `Path` já está importado nesse arquivo; se não, acrescente `from pathlib import Path`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -3.12 -m unittest discover -s tests -p "test_traffic_click.py"`
Expected: ERROR com `ImportError: cannot import name 'is_click'`

Run: `py -3.12 -m unittest discover -s tests -p "test_ping_targets.py"`
Expected: FAIL em `recorder.start.assert_called_once()`, porque `main()` ainda não cria o gravador

- [ ] **Step 3: Funções puras em `net_split.py`, ao fim**

```python
def net_family_at(x, left, widths):
    """Family under x in the split network column: v4 half, then v6 half."""
    prefix, v4_value, v6_prefix, v6_value = widths
    if x < left or x >= left + prefix + v4_value + v6_prefix + v6_value:
        return None
    return 'ipv4' if x < left + prefix + v4_value else 'ipv6'


def is_click(press, release, tolerance=3):
    """A press released without really moving, as opposed to a drag."""
    if press is None:
        return False
    return abs(release[0] - press[0]) <= tolerance and abs(release[1] - press[1]) <= tolerance
```

- [ ] **Step 4: Ligar em `sys_monitor.py`**

Imports:

```python
from net_split import PacketCounters, split_rates, net_column_width, net_family_at, is_click
from traffic_history import TrafficHistory, TrafficRecorder
from traffic_history_ui import TrafficHistoryWindow
```

Junto das demais funções de módulo, logo depois de `_win_rect`:

```python
TRAFFIC_HISTORY_UI = None  # One process-wide window; set by main().


def _cursor_pos():
    point = wintypes.POINT()
    _u32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y
```

Em `MonitorWindow.__init__`, logo depois de `self._bind_menu()`:

```python
            self._bind_traffic_click()
```

Em `_bind_drag`, no modo flutuante, troque `start` e `release` para distinguir clique de arraste. Mantenha o que já existe:

```python
        def start(e):
            self._drag["x"], self._drag["y"] = e.x, e.y
            self._drag_press = (e.x_root, e.y_root)
```

e, ao fim de `release`, depois de gravar o config:

```python
            if is_click(getattr(self, "_drag_press", None), (e.x_root, e.y_root)):
                self._on_net_click()
```

Em `_bind_menu`, logo antes de `Configurar limites de uso…`:

```python
        menu.add_command(label="Histórico de tráfego…", command=self._open_traffic_history)
```

Em `_update_net_split`, troque as duas linhas de `widths = (...)` por `widths = self._net_cell_widths()`. Depois, novos métodos, logo depois de `_update_net_split`:

```python
    def _net_cell_widths(self):
        measure = self._net_font.measure
        return (max(measure("↑ v4 "), measure("↓ v4 ")), measure("1000.0 Mbps"),
                measure(" v6 "), measure("1000.0 Mbps"))

    def _bind_traffic_click(self):
        if self.mode == "floating":
            return  # The left button drags here; _bind_drag detects a plain click.
        # Bound on the Toplevel for the same reason as the right-click menu.
        self.root.bind("<Button-1>", lambda event: self._on_net_click())
        if getattr(self, "click_catcher", None) is not None:
            self.click_catcher.bind("<Button-1>", lambda event: self._on_net_click())

    def _on_net_click(self):
        if getattr(self, "_closing", False):
            return
        # Windows coordinates in every mode: Tk's are unreliable for a child
        # of another process's window (same reason as show_menu).
        x, y = _cursor_pos()
        rects = [_win_rect(label.winfo_id()) for label in (self.lbl_up, self.lbl_down)]
        if None in rects:
            return
        left = min(rect.left for rect in rects)
        if not (left <= x < max(rect.right for rect in rects)
                and min(rect.top for rect in rects) <= y < max(rect.bottom for rect in rects)):
            return
        family = net_family_at(x, left, self._net_cell_widths()) if self._net_active else None
        self._open_traffic_history(family)

    def _open_traffic_history(self, family=None):
        if TRAFFIC_HISTORY_UI is not None:
            TRAFFIC_HISTORY_UI.show(family)
```

Em `main()`, logo depois do bloco `if ping: ping.start()`:

```python
    traffic_history = TrafficHistory(data_dir() / "trafego-historico.csv", _log_event)
    recorder = TrafficRecorder(traffic_history, metrics, ping, _log_event)
    recorder.start()
```

Logo depois de `app_root.report_callback_exception = ...`:

```python
    global TRAFFIC_HISTORY_UI
    TRAFFIC_HISTORY_UI = TrafficHistoryWindow(app_root, traffic_history, fmt_speed,
                                              cfg["window"]["accent_up"], cfg["window"]["accent_down"])
```

No `finally`, antes de `collector.stop()`:

```python
        TRAFFIC_HISTORY_UI.close()
        recorder.stop()
        recorder.join(timeout=2)  # Final write; never hold the exit on a blocked disk.
```

- [ ] **Step 5: Versão e `.gitignore`**

- `version.py`: `__version__ = "1.1.0"`.
- `tests/test_app_paths.py` e os três pontos de `tests/test_self_check.py`: trocar `1.0.3` por `1.1.0`.
- `.gitignore`: acrescentar a linha `trafego-historico.csv*`.

- [ ] **Step 6: Rodar a suíte completa**

Run: `py -3.12 -m unittest discover -s tests`
Expected: OK. Se um teste existente de menu ou de interface quebrar por causa do item novo ou de uma variável que falta num objeto falso, ajuste só o que for necessário e liste no relatório cada teste alterado e o motivo.

- [ ] **Step 7: Conferir que o programa inicia com os módulos novos**

Run: `py -3.12 sys_monitor.py --verificar`
Expected: saída com `SysMonitor 1.1.0 (widget)` e código 0.

- [ ] **Step 8: Documentação**

Atualizar com cabeçalho de data 2026-11-06, sem colar a spec, apontando para ela:
- `docs/agentes/interface.md`: clique esquerdo, item de menu e janela.
- `docs/agentes/arquitetura.md`: módulos novos, thread do gravador e arquivo.
- `docs/agentes/build-e-uso.md`: `trafego-historico.csv`, local e conteúdo.
- `docs/agentes/estado.md`: marco 1.1.0 com TDD por tarefa e suíte final; a linha "Sem histórico/gráficos" de "Limitações" sai.
- `docs/agentes/INDICE.md`: estado e cabeçalho. Não invente SHA do instalador.

- [ ] **Step 9: Commit**

```bash
git add net_split.py sys_monitor.py version.py .gitignore tests/test_traffic_click.py tests/test_app_paths.py tests/test_self_check.py tests/test_ping_targets.py docs/agentes/interface.md docs/agentes/arquitetura.md docs/agentes/build-e-uso.md docs/agentes/estado.md docs/agentes/INDICE.md
git commit -m "feat(trafego): clique em v4/v6 e menu abrem o histórico (1.1.0)"
```

Se o Step 6 tiver exigido ajuste em outros testes, adicione esses arquivos pelo nome. Confira com `git status` que `config.ini` continua fora do commit.

## Relatório final (em português)
Falha vista em cada tarefa (RED), resultado exato da suíte completa, testes antigos alterados com o motivo, caminho da captura da janela, desvios deste plano e `git log --oneline` da branch. Confirme que `config.ini` não entrou em nenhum commit. Se precisar desviar do plano, faça o menor desvio possível e relate.
