Atualizado em 2026-10-07 (commit 7400f35)

# Sensores e coleta
## Contrato (`sensors.py`)
- `SensorReader.read()` retorna `cpu_temp`, `gpu_temp`, `gpu_usage`, `cpu_temp_error`, `gpu_error`.
- Temperaturas em °C; usos em percentual; indisponível é `None`, não zero.
- Captura exceções separadamente por fonte, evitando que um sensor interrompa o Collector.

## GPU / NVML
- `NvmlReader` carrega `nvml.dll` do driver NVIDIA com `ctypes.WinDLL`.
- Inicializa com `nvmlInit_v2` e seleciona somente GPU de índice 0.
- Consulta temperatura e utilização; retorno diferente de `NVML_SUCCESS` invalida aquela leitura.
- Quando ambas as consultas falham, registra erro e faz `_reset()`/shutdown; próximo tick reinicializa.
- Falha parcial retorna `None` só para o campo afetado, mas não define `last_error`: aviso pode não aparecer.
- Sem biblioteca, driver ou GPU NVIDIA, retorna ausência e mensagem de erro; não há backend AMD/Intel GPU.

## CPU / LibreHardwareMonitor
- `LHM_URL`: `http://127.0.0.1:8085/data.json`; timeout de 0,5 s.
- LHM roda elevado para ler via PawnIO; SysMonitor continua sem elevação, consultando HTTP local.
- `_walk()` percorre `Children`; filtra `SensorId` com `/temperature/` e `cpu/`.
- Preferência: `Core (Tctl/Tdie)`, `Core (Tctl)`, `CPU Package`, `Core Average`.
- Nomes duplicados preservam o primeiro valor encontrado (`setdefault`).
- `_parse_value()` remove unidade pelo primeiro espaço e troca vírgula decimal por ponto.
- HTTP/JSON inválido ou sensor ausente → `None` + erro; exceções inesperadas também são isoladas.

## psutil / Collector
- Fontes: `net_io_counters()`, `cpu_percent(interval=None)`, `virtual_memory().percent`.
- Rede é agregada, sem seleção de interface: delta de bytes enviados/recebidos dividido por tempo.
- Tempo usa `time.time()` e denominador mínimo de `1e-6`; não há tratamento de reset de contadores.
- `run()` faz uma leitura inicial de CPU para preparar o contador interno.
- Intervalo do widget vem de `update_interval_ms`; bandeja fixa 1,0 s.
- Pausa ocorre após coleta, portanto duração do I/O soma-se ao intervalo configurado.
- `stop()` sinaliza Event; thread é daemon e não há join no encerramento das entradas.
- Falhas de psutil não têm proteção equivalente à dos sensores e podem encerrar a thread.
- Formatação de rede converte bytes/s em bits/s decimais (Kbps/Mbps), não KiB/s.

## Diagnóstico
- `python3 sensors.py` imprime GPU (temperatura, uso) e temperatura CPU com mensagens de erro.
- Conferir LHM → Options → Remote Web Server → Run (porta 8085).
- Não reinstalar HWiNFO para restaurar a coleta: veja [armadilhas.md](armadilhas.md).
