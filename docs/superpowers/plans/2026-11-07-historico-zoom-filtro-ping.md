# Histórico: períodos curtos, zoom, seleção, filtro e ping · plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** na janela do histórico, ter períodos de 5 e 15 min, zoom, seleção com o mouse e resumo, filtro por medida e uma linha nova de ping em ms.

**Architecture:** o monitor de ping passa a entregar o pior tempo de resposta; `traffic_history.py` grava esse dado em duas colunas novas do CSV (lendo também o formato antigo) e ganha funções puras de trecho, zoom, seleção e resumo; `traffic_history_ui.py` só guarda o estado da tela e chama essas funções.

**Tech Stack:** Python 3.12, Tkinter `Canvas`, `unittest`. Sem dependência nova.

**Spec:** `docs/superpowers/specs/2026-11-06-historico-zoom-filtro-ping-design.md`

## Global Constraints

- Branch `versao-1.1`. Versão continua `1.1.0`. Commits locais por tarefa, sem push, tag ou release.
- Nunca alterar nem adicionar `config.ini`, e nunca usar `git add -A` nem `git add .`.
- Não matar nem reiniciar o widget em execução. Não rodar `build.ps1`: o Claude gera o instalador depois da revisão.
- O histórico real do Mateus (`%APPDATA%\SysMonitor\trafego-historico.csv`) não é lido nem alterado em testes: pasta temporária e relógio falso.
- Testes: `py -3.12 -m unittest discover -s tests`; um arquivo: `py -3.12 -m unittest discover -s tests -p "test_x.py"`. O `python` do PATH não serve. Base atual: 273 OK.
- Texto para o usuário em português do Brasil.
- 0 ms é resposta válida: nunca testar tempo de resposta com `if valor:`.
- Pare só em falha de testes que não souber resolver; tropeço de edição, refaça e siga.

## Review Focus

- **Soltar o mouse fora da janela:** a seleção vai até a borda do gráfico, sem erro. Teste na Tarefa 4.
- **Atualização de 5 s ou tempo passando durante o arraste:** a faixa continua na tela, e o trecho escolhido é o que estava desenhado quando o arraste começou. Teste na Tarefa 4.
- **Arrastar da direita para a esquerda:** dá o mesmo trecho. Testes nas Tarefas 3 e 4.
- **Zoom num trecho parado que envelheceu além de 4 h:** o trecho volta para dentro do que está guardado. Testes nas Tarefas 3 e 4.
- **Filtro só de ping em dados antigos, sem ping:** gráfico vazio, sem eixo e sem erro. Teste na Tarefa 4.

---

### Task 1: Pior tempo de resposta por família

**Files:**
- Modify: `ping_monitor.py` (`__init__`, `_record`, `set_groups`, novo `take_worst_rtts`)
- Test: `tests/test_ping_worst_rtts.py`

**Interfaces:**
- Produces: `PingMonitor.take_worst_rtts() -> {"ipv4": float | None, "ipv6": float | None}`. Maior tempo desde a última chamada; `None` se nenhum IP respondeu. Zera ao ler.

- [ ] **Step 1: Escrever os testes**

```python
"""Worst response time per family for the traffic history; no real toasts."""
import unittest

import ping_monitor as pm
from metrics_collector import Metrics


class WorstRttTests(unittest.TestCase):
    def monitor(self, **kwargs):
        options = dict(targets_v4=('1.1.1.1', '8.8.8.8'), targets_v6=('::1',),
                       notifier=lambda *args: None)
        options.update(kwargs)
        return pm.PingMonitor(Metrics(), **options)

    def test_worst_answer_of_each_family(self):
        monitor = self.monitor()
        monitor.record((12, 30, 7), now=0)
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': 30, 'ipv6': 7})

    def test_keeps_the_worst_between_reads_and_clears_on_read(self):
        monitor = self.monitor()
        monitor.record((50, 12, 7), now=0)
        monitor.record((12, 12, 90), now=1)
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': 50, 'ipv6': 90})
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': None, 'ipv6': None})

    def test_ignores_who_did_not_answer(self):
        monitor = self.monitor()
        monitor.record((None, 12, None), now=0)
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': 12, 'ipv6': None})

    def test_zero_ms_is_a_valid_answer(self):
        monitor = self.monitor()
        monitor.record((0, 0, 0), now=0)
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': 0, 'ipv6': 0})

    def test_does_not_depend_on_notification_settings(self):
        monitor = self.monitor(notify=False, notify_ipv4=False, notify_ipv6=False)
        monitor.record((12, 30, 7), now=0)
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': 30, 'ipv6': 7})

    def test_replacing_groups_clears_the_values(self):
        monitor = self.monitor()
        monitor.record((12, 30, 7), now=0)
        monitor.set_groups(('9.9.9.9',), ('::2',), 'ipv4')
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': None, 'ipv6': None})

    def test_empty_family_stays_empty(self):
        monitor = self.monitor(targets_v6=())
        monitor.record((12, 30), now=0)
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': 30, 'ipv6': None})


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -3.12 -m unittest discover -s tests -p "test_ping_worst_rtts.py"`
Expected: ERROR com `AttributeError: 'PingMonitor' object has no attribute 'take_worst_rtts'`

- [ ] **Step 3: Implementar**

Em `__init__`, logo depois de `self._loss_marks = {"ipv4": 0, "ipv6": 0}`:

```python
        self._worst_rtts = {"ipv4": None, "ipv6": None}
```

Em `_record`, dentro do `if targets:` que calcula a marca, depois da linha `self._loss_marks[family] = ...`:

```python
                answered = [self._results[ip][2] for ip in targets if self._results[ip][3]]
                if answered:
                    worst = self._worst_rtts[family]
                    self._worst_rtts[family] = max(answered) if worst is None else max(worst, *answered)
```

Em `set_groups`, logo depois de `self._loss_marks = {"ipv4": 0, "ipv6": 0}`:

```python
            self._worst_rtts = {"ipv4": None, "ipv6": None}
```

Novo método, logo depois de `take_loss_marks`:

```python
    def take_worst_rtts(self):
        """Largest answered response time per family since the last read, or None."""
        with self._lock:
            rtts, self._worst_rtts = self._worst_rtts, {"ipv4": None, "ipv6": None}
            return rtts
```

- [ ] **Step 4: Rodar a suíte de ping**

Run: `py -3.12 -m unittest discover -s tests -p "test_ping*.py"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add ping_monitor.py tests/test_ping_worst_rtts.py
git commit -m "feat(ping): expõe o pior tempo de resposta por família"
```

---

### Task 2: Ping no ponto e no CSV, lendo o formato antigo

**Files:**
- Modify: `traffic_history.py`
- Modify: `tests/test_traffic_history.py` (3 expectativas que mudam de propósito)
- Test: `tests/test_traffic_ping_storage.py`

**Interfaces:**
- Consumes: `PingMonitor.take_worst_rtts()`.
- Produces:
  - `FamilyPoint(epoch, down, up, mark, ping=None)`.
  - `TrafficHistory.add_sample(rates, marks, rtts=None)`.
  - `TrafficHistory.points_between(family, start, end) -> list[FamilyPoint]`, em ordem de horário.
  - `points(family, period_s)` continua existindo.

- [ ] **Step 1: Escrever os testes novos**

```python
"""Ping in points and CSV, including files written by the first 1.1.0 build."""
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import traffic_history as th


def rates(up4=0, up6=0, down4=0, down6=0):
    return ((up4, up6), (down4, down6))


class Clock:
    def __init__(self, now=100000.0):
        self.now = now

    def __call__(self):
        return self.now


class PingPointTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'h.csv'
        self.clock = Clock()

    def history(self):
        return th.TrafficHistory(self.path, Mock(), clock=self.clock)

    def test_point_keeps_the_worst_rounded_ping_of_each_family(self):
        history = self.history()
        history.add_sample(rates(), {}, {'ipv4': 12.4, 'ipv6': None})
        self.clock.now += 1
        history.add_sample(rates(), {}, {'ipv4': 30.6, 'ipv6': 7.0})
        history.finish_bucket()
        self.assertEqual(history.points('ipv4', 3600)[0].ping, 31)
        self.assertEqual(history.points('ipv6', 3600)[0].ping, 7)

    def test_interval_without_answer_has_empty_ping(self):
        history = self.history()
        history.add_sample(rates(), {}, {'ipv4': None, 'ipv6': None})
        history.finish_bucket()
        self.assertIsNone(history.points('ipv4', 3600)[0].ping)

    def test_samples_without_ping_information_still_work(self):
        history = self.history()
        history.add_sample(rates(down4=5), {})
        history.finish_bucket()
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(100000, 5, 0, 0, None)])

    def test_next_point_starts_without_the_previous_ping(self):
        history = self.history()
        history.add_sample(rates(), {}, {'ipv4': 90})
        self.clock.now += th.BUCKET_S
        history.add_sample(rates(), {}, {})
        history.finish_bucket()
        self.assertEqual([p.ping for p in history.points('ipv4', 3600)], [90, None])

    def test_points_between_uses_the_given_range_in_time_order(self):
        history = self.history()
        for epoch in (100010.0, 100000.0, 100005.0):
            self.clock.now = epoch
            history.add_sample(rates(), {})
            history.finish_bucket()
        self.clock.now = 100100.0
        self.assertEqual([p.epoch for p in history.points_between('ipv4', 100000, 100005)], [100000, 100005])


class PingFileTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'h.csv'
        self.clock = Clock()
        self.now = int(self.clock.now)

    def history(self):
        history = th.TrafficHistory(self.path, Mock(), clock=self.clock)
        history.load()
        return history

    def test_file_from_the_first_build_is_read_and_converted(self):
        self.path.write_text(f'{self.now - 60},1,2,3,4,0,1\n', encoding='ascii')
        history = self.history()
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(self.now - 60, 1, 2, 0, None)])
        self.assertEqual(history.points('ipv6', 3600), [th.FamilyPoint(self.now - 60, 3, 4, 1, None)])
        self.assertEqual(self.path.read_text(encoding='ascii'), f'{self.now - 60},1,2,3,4,0,1,,\n')

    def test_round_trip_with_ping_including_zero_and_empty(self):
        first = self.history()
        first.add_sample(rates(), {}, {'ipv4': 0, 'ipv6': None})
        first.finish_bucket()
        self.assertTrue(first.flush())
        self.clock.now += th.BUCKET_S
        second = self.history()
        self.assertEqual(second.points('ipv4', 3600)[0].ping, 0)
        self.assertIsNone(second.points('ipv6', 3600)[0].ping)

    def test_wrong_column_count_and_negative_ping_are_ignored(self):
        self.path.write_text(f'{self.now - 60},1,2,3,4,0,1,5\n'
                             f'{self.now - 55},1,2,3,4,0,1,-5,7\n'
                             f'{self.now - 50},1,2,3,4,0,1,5,x\n'
                             f'{self.now - 45},1,2,3,4,0,1,5,7,9\n'
                             f'{self.now - 40},1,2,3,4,0,1,5,7\n', encoding='ascii')
        history = self.history()
        self.assertEqual([p.epoch for p in history.points('ipv4', 3600)], [self.now - 40])

    def test_old_and_new_lines_can_live_in_the_same_file(self):
        self.path.write_text(f'{self.now - 60},1,2,3,4,0,1\n{self.now - 55},1,2,3,4,0,1,5,7\n', encoding='ascii')
        history = self.history()
        self.assertEqual([p.ping for p in history.points('ipv4', 3600)], [None, 5])


class RecorderPingTests(unittest.TestCase):
    def test_tick_feeds_the_worst_response_times(self):
        history, ping = Mock(), Mock()
        ping.take_loss_marks.return_value = {'ipv4': 1, 'ipv6': 0}
        ping.take_worst_rtts.return_value = {'ipv4': 12.0, 'ipv6': None}
        metrics = SimpleNamespace(lock=threading.Lock(), net_rates=rates(1, 2, 3, 4))
        th.TrafficRecorder(history, metrics, ping, Mock(), clock=lambda: 0.0).tick()
        history.add_sample.assert_called_once_with(rates(1, 2, 3, 4), {'ipv4': 1, 'ipv6': 0},
                                                   {'ipv4': 12.0, 'ipv6': None})


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Ajustar as 3 expectativas antigas em `tests/test_traffic_history.py`**

O formato do arquivo e a chamada de `add_sample` mudam de propósito. Só estes pontos:

```python
        # 1. Em test_load_ignores_bad_lines_and_times_out_of_range, troque a última linha por:
        self.assertEqual(self.path.read_text(encoding='ascii'), good.replace('\n', ',,\n'))

        # 2. Em test_tick_feeds_rates_and_marks, depois de ping.take_loss_marks.return_value = ...:
        ping.take_worst_rtts.return_value = {'ipv4': 12.0, 'ipv6': None}
        # e troque a verificação por:
        self.history.add_sample.assert_called_once_with(rates(1, 2, 3, 4), {'ipv4': 1, 'ipv6': 0},
                                                        {'ipv4': 12.0, 'ipv6': None})

        # 3. Em test_tick_without_ping_has_no_marks, troque a verificação por:
        self.history.add_sample.assert_called_once_with(rates(1, 2, 3, 4), {}, {})
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `py -3.12 -m unittest discover -s tests -p "test_traffic_ping_storage.py"`
Expected: FAILED com erros `TypeError: TrafficHistory.add_sample() takes 3 positional arguments but 4 were given` e falhas no formato do arquivo

- [ ] **Step 4: Implementar em `traffic_history.py`**

Troque as duas definições de namedtuple:

```python
Point = namedtuple('Point', 'epoch v4_down v4_up v6_down v6_up v4_mark v6_mark v4_ping v6_ping',
                   defaults=(None, None))
FamilyPoint = namedtuple('FamilyPoint', 'epoch down up mark ping', defaults=(None,))
```

Troque `_parse_line` inteira:

```python
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
```

Em `TrafficHistory.__init__`, logo depois de `self._marks = {'ipv4': 0, 'ipv6': 0}`:

```python
        self._rtts = {'ipv4': None, 'ipv6': None}
```

Troque `add_sample` inteira:

```python
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
```

Em `_close_bucket`, troque a criação do ponto e acrescente o `_rtts` à limpeza:

```python
        def worst(family):
            value = self._rtts[family]
            return None if value is None else round(value)
        point = Point(self._bucket, average(1, 0), average(0, 0), average(1, 1), average(0, 1),
                      self._marks['ipv4'], self._marks['ipv6'], worst('ipv4'), worst('ipv6'))
```

```python
        self._rtts = {'ipv4': None, 'ipv6': None}
```

Troque `points` inteira por:

```python
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
```

Em `TrafficRecorder.tick`, troque as duas linhas de marcas e amostra por:

```python
        ping = self.ping_monitor
        marks = ping.take_loss_marks() if ping is not None else {}
        rtts = ping.take_worst_rtts() if ping is not None else {}
        self.history.add_sample(rates, marks, rtts)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `py -3.12 -m unittest discover -s tests -p "test_traffic*.py"`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add traffic_history.py tests/test_traffic_history.py tests/test_traffic_ping_storage.py
git commit -m "feat(trafego): guarda o ping no ponto e no CSV, lendo o formato antigo"
```

---

### Task 3: Gráfico com filtro e ping; zoom, seleção e resumo puros

**Files:**
- Modify: `traffic_history.py` (`build_chart` e funções novas)
- Test: `tests/test_traffic_view.py`

**Interfaces:**
- Consumes: `FamilyPoint`, `KEEP_S`.
- Produces:
  - `ALL_SERIES = frozenset({'down', 'up', 'ping', 'loss'})`, `MIN_VIEW_S = 60`, `ZOOM_STEP = 0.75`.
  - `build_chart(points, width, height, end, span_s, series=ALL_SERIES, fmt_time=None) -> Chart | None`. `Chart` ganha `ping` (trechos) e `ping_ticks` (`(y, ms)`).
  - `zoom_view(start, end, factor, anchor, now) -> (start, end)`.
  - `selection_view(first, second, now) -> (start, end)`.
  - `x_to_time(x, plot, start, end) -> float`, limitando `x` à área do gráfico.
  - `summarize(points, start, end, series, fmt_speed, fmt_time=local_hhmm) -> str`.

- [ ] **Step 1: Escrever os testes**

```python
"""Pure view logic: filter, ping axis, zoom, selection and summary."""
import unittest

from traffic_history import (ALL_SERIES, FamilyPoint as P, build_chart, selection_view, summarize,
                             x_to_time, zoom_view)

NOW = 1_000_000
HOUR = 3600
FOUR = 4 * 3600


def chart(points, series=ALL_SERIES, now=NOW, span=HOUR):
    return build_chart(points, 800, 360, now, span, series, fmt_time=str)


class FilterTests(unittest.TestCase):
    POINTS = [P(NOW - 20, 100, 50, 1, 10), P(NOW - 10, 200, 40, 2, 20)]

    def test_everything_is_visible_by_default(self):
        result = chart(self.POINTS)
        self.assertTrue(result.down and result.up and result.ping and result.bands)

    def test_only_download(self):
        result = chart(self.POINTS, {'down'})
        self.assertTrue(result.down)
        self.assertEqual((result.up, result.ping, result.bands, result.ping_ticks), ([], [], [], []))

    def test_scale_follows_only_what_is_visible(self):
        points = [P(NOW - 10, 1000, 50, 0)]
        _, y0, _, _ = chart(points).plot
        result = chart(points, {'up'})
        self.assertEqual(result.up[0][0][1], y0)
        self.assertEqual(result.y_ticks[-1], (y0, 50))

    def test_only_ping_hides_the_left_axis(self):
        result = chart(self.POINTS, {'ping'})
        self.assertTrue(result.ping)
        self.assertEqual(result.y_ticks, [])
        self.assertEqual((result.down, result.up, result.bands), ([], [], []))

    def test_only_loss_hides_both_value_axes_and_keeps_time(self):
        result = chart(self.POINTS, {'loss'})
        self.assertEqual([band[2] for band in result.bands], [1, 2])
        self.assertEqual((result.y_ticks, result.ping_ticks, result.down, result.ping), ([], [], [], []))
        self.assertTrue(result.x_ticks)


class PingAxisTests(unittest.TestCase):
    def test_ping_has_its_own_scale(self):
        result = chart([P(NOW - 10, 1000, 1000, 0, 100)])
        _, y0, _, y1 = result.plot
        self.assertEqual(result.ping[0][0][1], y0)
        self.assertEqual(result.ping_ticks, [(y1, 0), ((y0 + y1) / 2, 50), (y0, 100)])
        self.assertEqual(result.y_ticks[-1], (y0, 1000))

    def test_ping_of_zero_ms_stays_on_the_base(self):
        result = chart([P(NOW - 10, 1, 1, 0, 0)])
        _, _, _, y1 = result.plot
        self.assertEqual(result.ping[0][0][1], y1)
        self.assertEqual(result.ping_ticks, [(y1, 0)])

    def test_old_points_have_no_ping_line_and_no_axis(self):
        result = chart([P(NOW - 10, 1, 1, 0)])
        self.assertEqual((result.ping, result.ping_ticks), ([], []))

    def test_missing_ping_breaks_the_line(self):
        result = chart([P(NOW - 100, 1, 1, 0, 5), P(NOW - 95, 1, 1, 0, None), P(NOW - 90, 1, 1, 0, 5)])
        self.assertEqual(len(result.ping), 2)

    def test_short_ping_peak_survives_reduction(self):
        points = [P(NOW - FOUR + i * 5, 1, 1, 0, 10) for i in range(2880)]
        points[1000] = points[1000]._replace(ping=900)
        result = chart(points, span=FOUR)
        self.assertEqual(result.ping_ticks[-1][1], 900)


class TimeAxisTests(unittest.TestCase):
    def ticks(self, span, now=36000, fmt_time=str):
        return [text for _, text in build_chart([], 800, 360, now, span, ALL_SERIES, fmt_time).x_ticks]

    def test_steps_of_each_period(self):
        self.assertEqual(self.ticks(300), [str(35700 + i * 60) for i in range(6)])
        self.assertEqual(self.ticks(900), [str(35100 + i * 300) for i in range(4)])
        self.assertEqual(self.ticks(3600), [str(32400 + i * 900) for i in range(5)])
        self.assertEqual(self.ticks(14400), [str(21600 + i * 3600) for i in range(5)])
        self.assertEqual(self.ticks(60), [str(35940 + i * 15) for i in range(5)])

    def test_labels_include_seconds_only_with_steps_under_one_minute(self):
        self.assertEqual(self.ticks(60, fmt_time=None)[0].count(':'), 2)
        self.assertEqual(self.ticks(300, fmt_time=None)[0].count(':'), 1)


class ZoomTests(unittest.TestCase):
    def test_zoom_in_cuts_25_percent_keeping_the_anchor_in_place(self):
        self.assertEqual(zoom_view(NOW - 3600, NOW, 0.75, NOW - 1800, NOW), (NOW - 3150, NOW - 450))
        start, end = zoom_view(NOW - 3600, NOW, 0.75, NOW - 2700, NOW)
        self.assertAlmostEqual((NOW - 2700 - start) / (end - start), 0.25)

    def test_never_shorter_than_one_minute(self):
        self.assertEqual(zoom_view(NOW - 60, NOW, 0.75, NOW - 30, NOW), (NOW - 60, NOW))
        start, end = zoom_view(NOW - 70, NOW - 10, 0.75, NOW - 40, NOW)
        self.assertEqual(end - start, 60)

    def test_never_longer_than_four_hours(self):
        self.assertEqual(zoom_view(NOW - FOUR, NOW, 1 / 0.75, NOW - 1000, NOW), (NOW - FOUR, NOW))

    def test_slides_back_when_passing_the_present(self):
        self.assertEqual(zoom_view(NOW - 3600, NOW, 1 / 0.75, NOW - 1800, NOW), (NOW - 4800, NOW))

    def test_slides_forward_when_passing_what_is_stored(self):
        start, end = zoom_view(NOW - FOUR, NOW - 12000, 1 / 0.75, NOW - 12000, NOW)
        self.assertEqual(start, NOW - FOUR)
        self.assertAlmostEqual(end - start, 3200)

    def test_view_that_aged_beyond_four_hours_comes_back(self):
        start, end = zoom_view(NOW - 20000, NOW - 19000, 0.75, NOW - 19500, NOW)
        self.assertEqual(start, NOW - FOUR)
        self.assertEqual(end - start, 750)


class SelectionTests(unittest.TestCase):
    def test_either_direction_gives_the_same_range(self):
        self.assertEqual(selection_view(NOW - 500, NOW - 100, NOW), (NOW - 500, NOW - 100))
        self.assertEqual(selection_view(NOW - 100, NOW - 500, NOW), (NOW - 500, NOW - 100))

    def test_short_selection_becomes_one_minute_around_its_center(self):
        self.assertEqual(selection_view(NOW - 100, NOW - 90, NOW), (NOW - 125, NOW - 65))

    def test_short_selection_at_the_present_slides_back(self):
        self.assertEqual(selection_view(NOW - 10, NOW, NOW), (NOW - 60, NOW))


class XToTimeTests(unittest.TestCase):
    PLOT = (100, 0, 300, 50)

    def test_converts_inside_the_plot(self):
        self.assertEqual(x_to_time(200, self.PLOT, 0, 200), 100)

    def test_limits_to_the_edges(self):
        self.assertEqual(x_to_time(50, self.PLOT, 0, 200), 0)
        self.assertEqual(x_to_time(999, self.PLOT, 0, 200), 200)


class SummaryTests(unittest.TestCase):
    POINTS = [P(1, 100, 10, 0, 20), P(2, 300, None, 1, None), P(3, None, 30, 2, 40)]

    def text(self, points=None, series=ALL_SERIES):
        return summarize(self.POINTS if points is None else points, 1, 3, series,
                         lambda v: f'{v}B', fmt_time=str)

    def test_peaks_averages_and_failures_skip_empty_values(self):
        self.assertEqual(self.text(), '1 – 3 · ↓ pico 300B, média 200.0B · ↑ pico 30B, média 20.0B'
                                      ' · ping pico 40 ms, média 30 ms · 2 intervalos com falha')

    def test_only_the_visible_measure_enters(self):
        self.assertEqual(self.text(series={'up'}), '1 – 3 · ↑ pico 30B, média 20.0B')
        self.assertEqual(self.text(series={'loss'}), '1 – 3 · 2 intervalos com falha')

    def test_measure_without_data_says_so(self):
        points = [P(1, None, None, 0, None)]
        self.assertEqual(self.text(points), '1 – 3 · ↓ sem dados · ↑ sem dados · ping sem dados · 0 intervalos com falha')

    def test_singular_failure(self):
        self.assertTrue(self.text([P(1, 1, 1, 2, 1)]).endswith('· 1 intervalo com falha'))

    def test_zero_ms_counts_as_data(self):
        self.assertIn('ping pico 0 ms, média 0 ms', self.text([P(1, 1, 1, 0, 0)]))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -3.12 -m unittest discover -s tests -p "test_traffic_view.py"`
Expected: ERROR com `ImportError: cannot import name 'ALL_SERIES'`

- [ ] **Step 3: Implementar em `traffic_history.py`**

Troque do bloco `GAP_S = 15` até o fim do arquivo por:

```python
GAP_S = 15
MARGIN_LEFT, MARGIN_TOP, MARGIN_RIGHT, MARGIN_BOTTOM = 76, 12, 56, 26
TICK_STEPS = (15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200)
ALL_SERIES = frozenset({'down', 'up', 'ping', 'loss'})
MIN_VIEW_S = 60
ZOOM_STEP = 0.75

Chart = namedtuple('Chart', 'plot down up bands x_ticks y_ticks ping ping_ticks')


def local_hhmm(epoch):
    return time.strftime('%H:%M', time.localtime(epoch))


def local_hhmmss(epoch):
    return time.strftime('%H:%M:%S', time.localtime(epoch))


def _larger(first, second):
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def build_chart(points, width, height, end, span_s, series=ALL_SERIES, fmt_time=None):
    """Geometry only. Each pixel keeps its largest values and worst mark, so short
    peaks and failures survive when there are more points than pixels."""
    x0, y0 = MARGIN_LEFT, MARGIN_TOP
    x1, y1 = width - MARGIN_RIGHT, height - MARGIN_BOTTOM
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    pixels = x1 - x0
    start = end - span_s
    groups = {}
    for point in sorted(points, key=lambda p: p.epoch):
        if not start <= point.epoch <= end:
            continue
        x = x0 + int((point.epoch - start) / span_s * pixels)
        group = groups.get(x)
        if group is None:
            groups[x] = dict(first=point.epoch, last=point.epoch, down=point.down, up=point.up,
                             ping=point.ping, mark=point.mark)
        else:
            group['last'] = point.epoch
            for name in ('down', 'up', 'ping'):
                group[name] = _larger(group[name], getattr(point, name))
            group['mark'] = max(group['mark'], point.mark)
    ordered = [(x, groups[x]) for x in sorted(groups)]

    def peak_of(*names):
        return max((group[name] for _, group in ordered for name in names if group[name] is not None),
                   default=None)

    def segments(name, top):
        result, current, previous = [], [], None
        for x, group in ordered:
            value = group[name]
            if current and (value is None or group['first'] - previous > GAP_S):
                result.append(current)
                current = []
            if value is not None:
                current.append((x, y1 - (value / top) * (y1 - y0)))
            previous = group['last']
        if current:
            result.append(current)
        return result

    speeds = [name for name in ('down', 'up') if name in series]
    speed_peak = peak_of(*speeds) if speeds else None
    speed_top = speed_peak or 1
    down = segments('down', speed_top) if 'down' in series else []
    up = segments('up', speed_top) if 'up' in series else []
    if not speeds:
        y_ticks = []
    elif not speed_peak:
        y_ticks = [(y1, 0)]
    else:
        y_ticks = [(y1, 0), ((y0 + y1) / 2, speed_top / 2), (y0, speed_top)]

    ping_peak = peak_of('ping') if 'ping' in series else None
    ping = segments('ping', ping_peak or 1) if 'ping' in series else []
    if ping_peak is None:
        ping_ticks = []
    elif not ping_peak:
        ping_ticks = [(y1, 0)]
    else:
        ping_ticks = [(y1, 0), ((y0 + y1) / 2, round(ping_peak / 2)), (y0, ping_peak)]

    band_width = max(1, round(BUCKET_S / span_s * pixels))
    bands = []
    if 'loss' in series:
        bands = sorted(((x, min(x + band_width, x1), group['mark']) for x, group in ordered if group['mark']),
                       key=lambda band: band[2])

    step = next((step for step in TICK_STEPS if span_s / step <= 5), TICK_STEPS[-1])
    formatter = fmt_time or (local_hhmm if step >= 60 else local_hhmmss)
    tick = (int(start) + step - 1) // step * step
    x_ticks = []
    while tick <= end:
        x_ticks.append((x0 + (tick - start) / span_s * pixels, formatter(tick)))
        tick += step
    return Chart((x0, y0, x1, y1), down, up, bands, x_ticks, y_ticks, ping, ping_ticks)


def _slide(start, span, now):
    """Keep the span, moving the range inside what is stored and before the present."""
    start = max(min(start, now - span), now - KEEP_S)
    return start, start + span


def _limited_span(span):
    return min(KEEP_S, max(MIN_VIEW_S, span))


def zoom_view(start, end, factor, anchor, now):
    """The anchor stays at the same place on screen unless a limit moves the range."""
    span = end - start
    new_span = _limited_span(span * factor)
    return _slide(anchor - (anchor - start) * new_span / span, new_span, now)


def selection_view(first, second, now):
    start, end = sorted((first, second))
    span = _limited_span(end - start)
    return _slide((start + end) / 2 - span / 2, span, now)


def x_to_time(x, plot, start, end):
    x0, _, x1, _ = plot
    return start + (min(x1, max(x0, x)) - x0) / (x1 - x0) * (end - start)


def summarize(points, start, end, series, fmt_speed, fmt_time=local_hhmm):
    parts = [f'{fmt_time(start)} – {fmt_time(end)}']
    for name, label, fmt in (('down', '↓', fmt_speed), ('up', '↑', fmt_speed),
                             ('ping', 'ping', lambda value: f'{round(value)} ms')):
        if name not in series:
            continue
        values = [getattr(point, name) for point in points if getattr(point, name) is not None]
        if values:
            parts.append(f'{label} pico {fmt(max(values))}, média {fmt(sum(values) / len(values))}')
        else:
            parts.append(f'{label} sem dados')
    if 'loss' in series:
        failures = sum(point.mark > 0 for point in points)
        parts.append(f'{failures} intervalo{"" if failures == 1 else "s"} com falha')
    return ' · '.join(parts)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -3.12 -m unittest discover -s tests -p "test_traffic*.py"`
Expected: OK. Os testes antigos de `test_traffic_chart.py` não mudam: `build_chart` mantém a ordem dos primeiros argumentos.

- [ ] **Step 5: Commit**

```bash
git add traffic_history.py tests/test_traffic_view.py
git commit -m "feat(trafego): filtro e ping no gráfico; zoom, seleção e resumo puros"
```

---

### Task 4: Janela com períodos, zoom, seleção, filtro e resumo

**Files:**
- Modify: `traffic_history_ui.py` (substituir o arquivo inteiro)
- Modify: `tests/test_traffic_window.py` (a janela passa a ler por `points_between`)
- Modify: `docs/agentes/interface.md`, `build-e-uso.md`, `estado.md`, `INDICE.md`
- Test: `tests/test_traffic_window_zoom.py`

**Interfaces:**
- Consumes: `build_chart`, `zoom_view`, `selection_view`, `x_to_time`, `summarize`, `ALL_SERIES`, `ZOOM_STEP`; `history.points_between` e `history.clock`.
- Produces: `TrafficHistoryWindow` com a mesma assinatura e os mesmos `show` e `close`. `sys_monitor.py` não muda.

- [ ] **Step 1: Escrever os testes novos**

```python
"""Live and frozen views, drag, zoom and filter with a fake Tk: nothing on screen."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import traffic_history as th
import traffic_history_ui as ui
from traffic_history import FamilyPoint as P

NOW = 1_000_000


def event(x=400, y=100, delta=0):
    return SimpleNamespace(x=x, y=y, delta=delta)


class WindowCase(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(ui, 'tk')
        self.tk = patcher.start()
        self.addCleanup(patcher.stop)
        self.tk.TclError = RuntimeError
        self.tk.Button.side_effect = lambda *args, **kwargs: Mock()
        self.tk.Label.side_effect = lambda *args, **kwargs: Mock()
        self.master = Mock()
        self.history = Mock()
        self.history.clock.return_value = NOW
        self.history.points_between.return_value = []
        self.top = self.tk.Toplevel.return_value
        self.top.winfo_exists.return_value = True
        self.canvas = self.tk.Canvas.return_value
        self.canvas.winfo_width.return_value = 800
        self.canvas.winfo_height.return_value = 360
        self.window = ui.TrafficHistoryWindow(self.master, self.history, lambda v: f'{v}B', '#111', '#222',
                                              work_area=lambda: (0, 0, 1920, 1040))
        self.window.show('ipv4')
        self.plot = self.window._chart.plot

    def range_shown(self):
        return self.history.points_between.call_args.args[1:]

    def selected(self, key):
        return self.window._buttons[key].config.call_args.kwargs['relief'] == 'sunken'


class PeriodTests(WindowCase):
    def test_four_period_buttons(self):
        self.assertEqual([key for key in self.window._buttons if key not in ('ipv4', 'ipv6')],
                         [300, 900, 3600, 14400])

    def test_each_period_is_live_and_highlighted(self):
        for period in (300, 900, 3600, 14400):
            with self.subTest(period=period):
                self.window._select_period(period)
                self.assertEqual(self.range_shown(), (NOW - period, NOW))
                self.assertTrue(self.selected(period))

    def test_live_view_follows_the_clock_and_a_frozen_one_does_not(self):
        self.history.clock.return_value = NOW + 5
        self.window._refresh()
        self.assertEqual(self.range_shown(), (NOW + 5 - 3600, NOW + 5))
        self.window._zoom(th.ZOOM_STEP)
        frozen = self.range_shown()
        self.history.clock.return_value = NOW + 10
        self.window._refresh()
        self.assertEqual(self.range_shown(), frozen)


class ZoomTests(WindowCase):
    def test_wheel_up_zooms_in_keeping_the_time_under_the_mouse(self):
        x = 244
        before = th.x_to_time(x, self.plot, NOW - 3600, NOW)
        self.window._on_wheel(event(x=x, delta=120))
        start, end = self.range_shown()
        self.assertAlmostEqual(end - start, 2700)
        self.assertAlmostEqual(th.x_to_time(x, self.plot, start, end), before)

    def test_wheel_down_zooms_out(self):
        self.window._on_wheel(event(delta=-120))
        start, end = self.range_shown()
        self.assertAlmostEqual(end - start, 4800)
        self.assertEqual(end, NOW)

    def test_wheel_outside_the_plot_uses_the_center(self):
        self.window._on_wheel(event(x=10, delta=120))
        self.assertEqual(self.range_shown(), (NOW - 3150, NOW - 450))

    def test_plus_and_minus_buttons_use_the_center(self):
        commands = {call.kwargs['text']: call.kwargs['command'] for call in self.tk.Button.call_args_list}
        commands['+']()
        self.assertEqual(self.range_shown(), (NOW - 3150, NOW - 450))
        commands['−']()
        start, end = self.range_shown()
        self.assertAlmostEqual(end - start, 3600)

    def test_keyboard(self):
        handlers = {call.args[0]: call.args[1] for call in self.top.bind.call_args_list}
        for key in ('<plus>', '<equal>', '<KP_Add>'):
            with self.subTest(key=key):
                self.window._select_period(3600)
                handlers[key](None)
                self.assertAlmostEqual(self.range_shown()[1] - self.range_shown()[0], 2700)
        for key in ('<minus>', '<KP_Subtract>'):
            with self.subTest(key=key):
                self.window._select_period(3600)
                handlers[key](None)
                self.assertAlmostEqual(self.range_shown()[1] - self.range_shown()[0], 4800)

    def test_frozen_view_turns_off_the_period_highlight_and_a_period_goes_back_to_live(self):
        self.window._zoom(th.ZOOM_STEP)
        self.assertFalse(self.selected(3600))
        self.window._select_period(900)
        self.assertTrue(self.selected(900))
        self.assertEqual(self.range_shown(), (NOW - 900, NOW))

    def test_changing_family_keeps_the_frozen_range(self):
        self.window._zoom(th.ZOOM_STEP)
        frozen = self.range_shown()
        self.window._select_family('ipv6')
        self.assertEqual(self.history.points_between.call_args.args, ('ipv6', *frozen))
        self.window.show('ipv4')
        self.assertEqual(self.history.points_between.call_args.args, ('ipv4', *frozen))

    def test_closing_drops_the_frozen_range_and_keeps_the_last_period(self):
        self.window._select_period(900)
        self.window._zoom(th.ZOOM_STEP)
        self.window.close()
        self.window.show()
        self.assertEqual(self.range_shown(), (NOW - 900, NOW))
        self.assertTrue(self.selected(900))

    def test_zoom_on_a_range_older_than_four_hours_comes_back(self):
        self.window.view = (NOW - 20000, NOW - 19000)
        self.window._zoom(th.ZOOM_STEP)
        self.assertEqual(self.range_shown()[0], NOW - th.KEEP_S)


class DragTests(WindowCase):
    def drag(self, first, last):
        self.window._drag_start(event(x=first))
        self.window._drag_move(event(x=last))
        self.window._drag_end(event(x=last))

    def expected(self, first, last):
        return th.selection_view(th.x_to_time(first, self.plot, NOW - 3600, NOW),
                                 th.x_to_time(last, self.plot, NOW - 3600, NOW), NOW)

    def test_dragging_freezes_the_selected_range(self):
        self.drag(176, 576)
        self.assertEqual(self.range_shown(), self.expected(176, 576))

    def test_either_direction_gives_the_same_range(self):
        self.drag(576, 176)
        self.assertEqual(self.range_shown(), self.expected(176, 576))

    def test_band_follows_the_mouse_inside_the_plot(self):
        self.window._drag_start(event(x=176))
        self.window._drag_move(event(x=5000))
        item = self.canvas.create_rectangle.return_value
        self.canvas.coords.assert_called_with(item, 176, self.plot[1], self.plot[2], self.plot[3])

    def test_releasing_outside_the_window_stops_at_the_edge(self):
        self.drag(176, 5000)
        self.assertEqual(self.range_shown(), self.expected(176, self.plot[2]))
        self.assertAlmostEqual(self.range_shown()[1], NOW)

    def test_movement_under_4_px_is_not_a_selection(self):
        self.drag(176, 179)
        self.assertIsNone(self.window.view)
        self.assertTrue(self.selected(3600))

    def test_movement_of_4_px_selects_at_least_one_minute(self):
        self.drag(176, 180)
        start, end = self.range_shown()
        self.assertEqual(end - start, 60)

    def test_press_outside_the_plot_is_ignored(self):
        self.drag(10, 400)
        self.assertIsNone(self.window.view)
        self.window._drag_start(event(x=176, y=self.plot[3] + 5))
        self.assertIsNone(self.window._drag)

    def test_refresh_during_the_drag_keeps_the_band(self):
        self.window._drag_start(event(x=176))
        deletes = self.canvas.delete.call_count
        self.window._refresh()
        self.assertEqual(self.canvas.delete.call_count, deletes)
        self.assertIsNotNone(self.window._drag)

    def test_range_comes_from_what_was_on_screen_when_the_drag_started(self):
        expected = self.expected(176, 576)
        self.window._drag_start(event(x=176))
        self.history.clock.return_value = NOW + 30
        self.window._drag_end(event(x=576))
        self.assertEqual(self.window.view, expected)

    def test_escape_cancels_the_drag_and_keeps_the_window(self):
        handlers = {call.args[0]: call.args[1] for call in self.top.bind.call_args_list}
        self.window._drag_start(event(x=176))
        handlers['<Escape>'](None)
        self.assertIsNone(self.window._drag)
        self.assertIsNone(self.window.view)
        self.top.destroy.assert_not_called()
        self.window._drag_end(event(x=576))
        self.assertIsNone(self.window.view)

    def test_escape_without_a_drag_closes(self):
        handlers = {call.args[0]: call.args[1] for call in self.top.bind.call_args_list}
        handlers['<Escape>'](None)
        self.top.destroy.assert_called_once()

    def test_canvas_binds_drag_and_wheel(self):
        events = {call.args[0] for call in self.canvas.bind.call_args_list}
        self.assertLessEqual({'<ButtonPress-1>', '<B1-Motion>', '<ButtonRelease-1>', '<MouseWheel>'}, events)


class SummaryLineTests(WindowCase):
    def test_hidden_when_live_and_shown_when_frozen(self):
        self.window._summary.pack.assert_not_called()
        self.history.points_between.return_value = [P(NOW - 100, 100, 10, 2, 30)]
        self.window._zoom(th.ZOOM_STEP)
        self.window._summary.pack.assert_called_once()
        text = self.window._summary.config.call_args.kwargs['text']
        self.assertIn('↓ pico 100B', text)
        self.assertIn('ping pico 30 ms', text)
        self.assertIn('1 intervalo com falha', text)
        self.window._select_period(300)
        self.window._summary.pack_forget.assert_called_once()

    def test_summary_follows_the_filter(self):
        self.history.points_between.return_value = [P(NOW - 100, 100, 10, 2, 30)]
        self.window._zoom(th.ZOOM_STEP)
        self.window._select_series('up')
        text = self.window._summary.config.call_args.kwargs['text']
        self.assertIn('↑ pico 10B', text)
        self.assertNotIn('↓', text)

    def test_frozen_range_without_data_says_so(self):
        self.window._zoom(th.ZOOM_STEP)
        texts = [call.kwargs.get('text') for call in self.canvas.create_text.call_args_list]
        self.assertIn('Sem dados neste trecho', texts)


class FilterTests(WindowCase):
    def series(self):
        with patch.object(ui, 'build_chart', wraps=ui.build_chart) as spy:
            self.window.redraw()
        return spy.call_args.args[5]

    def test_click_shows_only_that_item_another_swaps_and_again_shows_all(self):
        self.assertEqual(self.series(), th.ALL_SERIES)
        self.window._select_series('down')
        self.assertEqual(self.series(), {'down'})
        self.window._select_series('ping')
        self.assertEqual(self.series(), {'ping'})
        self.window._select_series('ping')
        self.assertEqual(self.series(), th.ALL_SERIES)

    def test_every_label_of_an_item_is_clickable(self):
        for name in ('down', 'up', 'ping', 'loss'):
            for label in self.window._legend[name]:
                with self.subTest(name=name):
                    self.window.series_filter = None
                    handler = label.bind.call_args.args[1]
                    self.assertEqual(label.bind.call_args.args[0], '<Button-1>')
                    handler(None)
                    self.assertEqual(self.window.series_filter, name)

    def test_active_item_is_highlighted(self):
        self.window._select_series('ping')
        self.assertEqual(self.window._legend['ping'][0].config.call_args.kwargs['bg'], ui.LEGEND_ACTIVE_BG)
        self.assertEqual(self.window._legend['down'][0].config.call_args.kwargs['bg'], ui.BG)

    def test_filter_survives_closing_the_window(self):
        self.window._select_series('up')
        self.window.close()
        self.window.show()
        self.assertEqual(self.series(), {'up'})

    def test_ping_draws_its_line_and_axis_in_ms(self):
        self.history.points_between.return_value = [P(NOW - 100, 100, 10, 0, 30)]
        self.window.redraw()
        texts = [call.kwargs.get('text') for call in self.canvas.create_text.call_args_list]
        self.assertIn('30 ms', texts)
        colors = [call.kwargs.get('fill') for call in self.canvas.create_line.call_args_list]
        self.assertIn(ui.PING_COLOR, colors)

    def test_only_ping_on_old_data_is_empty_without_failing(self):
        self.history.points_between.return_value = [P(NOW - 100, 100, 10, 0)]
        self.canvas.create_text.reset_mock()
        self.window._select_series('ping')
        texts = [call.kwargs.get('text') for call in self.canvas.create_text.call_args_list]
        self.assertFalse([text for text in texts if text and text.endswith(' ms')])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Ajustar `tests/test_traffic_window.py`**

A janela passa a pedir um trecho, não um período. Troque todas as ocorrências de `self.history.points` por `self.history.points_between` e estas três verificações:

```python
        # Em test_default_family_is_ipv4_and_period_is_one_hour:
        self.assertEqual(self.history.points_between.call_args.args, ('ipv4', 1_000_000 - 3600, 1_000_000))

        # Em test_chosen_period_lasts_until_the_program_closes, a primeira verificação:
        self.assertEqual(self.history.points_between.call_args.args, ('ipv4', 1_000_000 - 14400, 1_000_000))
        # e a última:
        self.assertEqual(self.history.points_between.call_args.args[1], 1_000_000 - 14400)
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `py -3.12 -m unittest discover -s tests -p "test_traffic_window*.py"`
Expected: FAILED/ERROR, porque a janela ainda chama `history.points` e não tem `_chart`, `_zoom` nem `_select_series`

- [ ] **Step 4: Substituir `traffic_history_ui.py` inteiro**

```python
"""History window: keeps the screen state and draws what traffic_history computes.

A Toplevel of the hidden root, never of the widget embedded in Explorer, so it
survives the widget being rebuilt when Explorer restarts.
"""
import ctypes
from ctypes import wintypes
import tkinter as tk

from traffic_history import (ALL_SERIES, ZOOM_STEP, build_chart, selection_view, summarize,
                             x_to_time, zoom_view)

BG = '#15171a'
FG = '#e6e6e6'
SELECTED_BG = '#2f6fb0'
SELECTED_FG = '#ffffff'
NORMAL_BG = 'SystemButtonFace'
NORMAL_FG = 'SystemButtonText'
LEGEND_ACTIVE_BG = '#3a3f46'
GRID = '#33373d'
PING_COLOR = '#c9a0ff'
SELECTION_COLOR = '#ffffff'
MARK_COLORS = {1: '#6b2a2a', 2: '#d83a3a'}
WIDTH, HEIGHT = 800, 400
REFRESH_MS = 5000
DRAG_MIN_PX = 4
PERIODS = ((300, '5 min'), (900, '15 min'), (3600, '1 h'), (14400, '4 h'))


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
        self.period_s = 3600
        self.series_filter = None
        self.view = None  # (start, end) while frozen by zoom or selection; None is live.
        self.window = None
        self.canvas = None
        self._buttons = {}
        self._legend = {}
        self._summary = None
        self._summary_shown = False
        self._chart = None
        self._drag = None
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
        self._legend = {}
        self._summary = None
        self._summary_shown = False
        self._chart = None
        self._drag = None
        self.view = None
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
        window.minsize(620, 280)
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.bind('<Escape>', self._on_escape)
        for key in ('<plus>', '<equal>', '<KP_Add>'):
            window.bind(key, lambda event: self._zoom(ZOOM_STEP))
        for key in ('<minus>', '<KP_Subtract>'):
            window.bind(key, lambda event: self._zoom(1 / ZOOM_STEP))
        self._build_buttons(window)
        self._build_legend(window)
        self._summary = tk.Label(window, text='', fg=FG, bg=BG, anchor='w', justify='left',
                                 wraplength=WIDTH - 16)
        self.canvas = tk.Canvas(window, bg=BG, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda event: self.redraw())
        self.canvas.bind('<ButtonPress-1>', self._drag_start)
        self.canvas.bind('<B1-Motion>', self._drag_move)
        self.canvas.bind('<ButtonRelease-1>', self._drag_end)
        self.canvas.bind('<MouseWheel>', self._on_wheel)
        window.focus_force()
        self._after_id = window.after(REFRESH_MS, self._refresh)

    def _build_buttons(self, window):
        row = tk.Frame(window, bg=BG)
        row.pack(fill='x', padx=8, pady=(6, 2))
        self._buttons = {}
        for family, text in (('ipv4', 'IPv4'), ('ipv6', 'IPv6')):
            button = tk.Button(row, text=text, width=6, command=lambda value=family: self._select_family(value))
            button.pack(side='left', padx=2)
            self._buttons[family] = button
        for index, (period, text) in enumerate(PERIODS):
            button = tk.Button(row, text=text, width=6, command=lambda value=period: self._select_period(value))
            button.pack(side='left', padx=(14 if index == 0 else 2, 2))
            self._buttons[period] = button
        for index, (text, factor) in enumerate((('+', ZOOM_STEP), ('−', 1 / ZOOM_STEP))):
            button = tk.Button(row, text=text, width=3, command=lambda value=factor: self._zoom(value))
            button.pack(side='left', padx=(14 if index == 0 else 2, 2))

    def _build_legend(self, window):
        row = tk.Frame(window, bg=BG)
        row.pack(fill='x', padx=8, pady=(0, 2))
        self._legend = {}
        for name, items in (('down', (('↓ download', self.accent_down),)),
                            ('up', (('↑ upload', self.accent_up),)),
                            ('ping', (('ping', PING_COLOR),)),
                            ('loss', (('perda:', FG), ('▌', MARK_COLORS[1]), ('um IP sem resposta', FG),
                                      ('▌', MARK_COLORS[2]), ('todos sem resposta', FG)))):
            labels = []
            for index, (text, color) in enumerate(items):
                label = tk.Label(row, text=text, fg=color, bg=BG, cursor='hand2')
                label.pack(side='left', padx=(10 if index == 0 else 0, 2))
                label.bind('<Button-1>', lambda event, value=name: self._select_series(value))
                labels.append(label)
            self._legend[name] = labels

    def _select_family(self, family):
        self.family = family
        self._update_buttons()
        self.redraw()

    def _select_period(self, period_s):
        self.period_s = period_s
        self.view = None
        self._update_buttons()
        self.redraw()

    def _select_series(self, name):
        self.series_filter = None if self.series_filter == name else name
        self._update_buttons()
        self.redraw()

    def _visible_series(self):
        return ALL_SERIES if self.series_filter is None else {self.series_filter}

    def _update_buttons(self):
        current = (self.family,) if self.view is not None else (self.family, self.period_s)
        for key, button in self._buttons.items():
            selected = key in current
            button.config(relief='sunken' if selected else 'raised',
                          bg=SELECTED_BG if selected else NORMAL_BG,
                          fg=SELECTED_FG if selected else NORMAL_FG)
        for name, labels in self._legend.items():
            for label in labels:
                label.config(bg=LEGEND_ACTIVE_BG if name == self.series_filter else BG)

    def _current_range(self):
        if self.view is not None:
            return self.view
        now = self.history.clock()
        return now - self.period_s, now

    def _refresh(self):
        self.redraw()
        if self.window is not None:
            self._after_id = self.window.after(REFRESH_MS, self._refresh)

    def _zoom(self, factor, x=None):
        start, end = self._current_range()
        anchor = (start + end) / 2
        chart = self._chart
        if x is not None and chart is not None and chart.plot[0] <= x <= chart.plot[2]:
            anchor = x_to_time(x, chart.plot, start, end)
        self.view = zoom_view(start, end, factor, anchor, self.history.clock())
        self._update_buttons()
        self.redraw()

    def _on_wheel(self, event):
        self._zoom(ZOOM_STEP if event.delta > 0 else 1 / ZOOM_STEP, event.x)

    def _drag_start(self, event):
        chart = self._chart
        if chart is None:
            return
        x0, y0, x1, y1 = chart.plot
        if not (x0 <= event.x <= x1 and y0 <= event.y <= y1):
            return
        item = self.canvas.create_rectangle(event.x, y0, event.x, y1, fill=SELECTION_COLOR,
                                            stipple='gray25', outline=SELECTION_COLOR)
        # The range on screen now: the clock and the window may change during the drag.
        self._drag = dict(x=event.x, item=item, plot=chart.plot, range=self._current_range())

    def _drag_move(self, event):
        drag = self._drag
        if drag is None:
            return
        x0, y0, x1, y1 = drag['plot']
        self.canvas.coords(drag['item'], drag['x'], y0, min(x1, max(x0, event.x)), y1)

    def _drag_end(self, event):
        drag, self._drag = self._drag, None
        if drag is None:
            return
        self.canvas.delete(drag['item'])
        x0, _, x1, _ = drag['plot']
        x = min(x1, max(x0, event.x))
        if abs(x - drag['x']) >= DRAG_MIN_PX:
            start, end = drag['range']
            self.view = selection_view(x_to_time(drag['x'], drag['plot'], start, end),
                                       x_to_time(x, drag['plot'], start, end), self.history.clock())
            self._update_buttons()
        self.redraw()

    def _on_escape(self, event):
        drag, self._drag = self._drag, None
        if drag is None:
            self.close()
            return
        self.canvas.delete(drag['item'])
        self.redraw()

    def _update_summary(self, points, start, end, series):
        if self.view is None:
            if self._summary_shown:
                self._summary.pack_forget()
                self._summary_shown = False
            return
        self._summary.config(text=summarize(points, start, end, series, self.fmt_speed),
                             wraplength=max(200, self.canvas.winfo_width() - 16))
        if not self._summary_shown:
            self._summary.pack(fill='x', padx=8, pady=(0, 2), before=self.canvas)
            self._summary_shown = True

    def redraw(self):
        canvas = self.canvas
        if canvas is None or self._drag is not None:
            return  # Redrawing during a drag would erase the selection band.
        canvas.delete('all')
        start, end = self._current_range()
        series = self._visible_series()
        points = self.history.points_between(self.family, start, end)
        self._update_summary(points, start, end, series)
        chart = self._chart = build_chart(points, canvas.winfo_width(), canvas.winfo_height(),
                                          end, end - start, series)
        if chart is None:
            return
        x0, y0, x1, y1 = chart.plot
        for left, right, mark in chart.bands:
            canvas.create_rectangle(left, y0, right, y1, fill=MARK_COLORS[mark], width=0)
        for y, value in chart.y_ticks:
            canvas.create_line(x0, y, x1, y, fill=GRID)
            canvas.create_text(x0 - 6, y, text=self.fmt_speed(value), fill=FG, anchor='e')
        for y, value in chart.ping_ticks:
            canvas.create_text(x1 + 6, y, text=f'{value} ms', fill=PING_COLOR, anchor='w')
        for x, text in chart.x_ticks:
            canvas.create_line(x, y1, x, y1 + 4, fill=FG)
            canvas.create_text(x, y1 + 6, text=text, fill=FG, anchor='n')
        for segments, color in ((chart.up, self.accent_up), (chart.down, self.accent_down),
                                (chart.ping, PING_COLOR)):
            for segment in segments:
                coordinates = [value for point in segment for value in point]
                if len(segment) == 1:  # create_line needs two points.
                    coordinates += [segment[0][0] + 1, segment[0][1]]
                canvas.create_line(*coordinates, fill=color, width=1)
        if not points:
            message = 'Coletando dados…' if self.view is None else 'Sem dados neste trecho'
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=message, fill=FG)
```

- [ ] **Step 5: Rodar a suíte completa**

Run: `py -3.12 -m unittest discover -s tests`
Expected: OK. Se outro teste quebrar, ajuste só o que for necessário e liste no relatório cada teste alterado e o motivo.

Run: `py -3.12 sys_monitor.py --verificar`
Expected: `SysMonitor 1.1.0 (widget)` e código 0.

- [ ] **Step 6: Conferência com Tk real, sem salvar nada no repositório**

Adapte `D:/dev/temp/sysmonitor-1.1/ver_janela.py`, com os dados de exemplo incluindo ping (com um pico) e pontos antigos sem ping, gravando só em `D:/dev/temp/sysmonitor-1.1/`. Capture com System.Drawing, com tempo curto:
- `janela-ao-vivo.png`: tudo visível, período de 1 h.
- `janela-parada.png`: depois de chamar `_drag_start`, `_drag_move` e `_drag_end` num trecho de 4 h, com a linha de resumo.
- `janela-filtro.png`: mesmo trecho, com `_select_series('ping')`.

Confira: rótulos dos dois eixos sem sobrepor, todos os botões e a legenda visíveis a 800 px, resumo sem cobrir o gráfico, item ativo da legenda destacado. Encerre o script e processos filhos antes de responder. Não toque na barra real nem no widget em execução.

- [ ] **Step 7: Documentação**

Atualizar com cabeçalho de data 2026-11-07, sem colar a spec, apontando para ela:
- `docs/agentes/interface.md`: períodos, ao vivo e parado, zoom, seleção, resumo e filtro.
- `docs/agentes/build-e-uso.md`: as 9 colunas do CSV e a leitura do formato de 7 colunas.
- `docs/agentes/estado.md`: marco com TDD por tarefa e suíte final; o teste do Mateus de 2026-11-06 na primeira etapa passou nos 6 itens.
- `docs/agentes/INDICE.md`: estado. Não invente SHA do instalador.

- [ ] **Step 8: Commit**

```bash
git add traffic_history_ui.py tests/test_traffic_window.py tests/test_traffic_window_zoom.py docs/agentes/interface.md docs/agentes/build-e-uso.md docs/agentes/estado.md docs/agentes/INDICE.md
git commit -m "feat(trafego): períodos curtos, zoom, seleção com resumo, filtro e ping na janela"
```

Se o Step 5 tiver exigido ajuste em outros testes, adicione esses arquivos pelo nome. Confira com `git status` que `config.ini` continua fora do commit.

## Relatório final (em português)
Falha vista em cada tarefa (RED), resultado exato da suíte completa, testes antigos alterados com o motivo, caminho das capturas, desvios deste plano e `git log --oneline` da branch. Confirme que `config.ini` não entrou em nenhum commit. Se precisar desviar do plano, faça o menor desvio possível e relate.
