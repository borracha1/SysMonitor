Atualizado em 2026-10-07 (commit 7400f35)

# Arquitetura e dados
## Módulos
| Caminho | Responsabilidade |
|---|---|
| `sys_monitor.py` | Entrada do widget; Win32, Tkinter, configuração, coleta própria e recuperação da janela |
| `tray_monitor.py` | Entrada alternativa; janela Win32 oculta, mensagens, GDI e Shell_NotifyIcon |
| `metrics_collector.py` | `Metrics` e `Collector` usados pela edição de bandeja |
| `sensors.py` | NVML por ctypes e temperatura da CPU por HTTP/JSON do LHM |
| `create_shortcut.py` | Atalhos do usuário no Menu Iniciar e Startup para o widget |
| `config.ini` | Configuração persistida do widget, já rastreada pelo Git |
| `.gitignore` | Ignora cache Python, arquivos .pyc, .log e backup/ |

## Fluxo e concorrência
- `main()` do widget → configuração → `Metrics` → `Collector` daemon → raiz Tk oculta → `MonitorWindow`.
- `run()` da bandeja → `Metrics`/`Collector` importados → janela oculta → três `TrayIconSlot` → loop Win32.
- Collector → psutil e `SensorReader.read()` → atualização sob lock → `snapshot()` → renderização.
- `Metrics.snapshot()` devolve uma cópia coerente: velocidades, uso CPU/memória, temperaturas, uso GPU e dois erros.
- Widget mantém I/O no Collector; Tk e reconstrução da janela ficam na thread principal.
- Bandeja atualiza ícones numa segunda thread daemon, a cada segundo.
- Apesar do comentário de `metrics_collector.py`, o widget NÃO importa esse módulo: mantém classes duplicadas em `sys_monitor.py`.
- Alterações no contrato de coleta exigem revisar as duas implementações.

## Armazenamento e fronteiras
- Não há banco de dados, conta, API remota autenticada ou histórico de métricas.
- Configuração, `crash.log` e `sysmon.log` ficam junto aos scripts, não no diretório corrente.
- `sysmon.log` registra ciclo de vida do widget e é apagado ao ultrapassar 256.000 bytes antes da próxima escrita.
- `crash.log` recebe exceções de thread principal/background; widget também captura callbacks Tk.
- Bandeja usa `crash.log`, não lê `config.ini` e não grava `sysmon.log`.
- Cada edição tem mutex próprio: `Global\SysMonitor_SingleInstance` e `Global\SysMonitorTray_SingleInstance`.
- O mutex não impede executar as duas edições simultaneamente.
- Código é específico de Windows: imports acessam APIs Win32; não importar as entradas para testes portáveis.
