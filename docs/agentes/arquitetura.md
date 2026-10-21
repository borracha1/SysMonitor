Atualizado em 2026-10-20 (branch main; grupos IPv4/IPv6 e seleção automática; commit "perda de pacotes por grupo IPv4/IPv6")

# Arquitetura e dados
## Módulos
| Caminho | Responsabilidade |
|---|---|
| `sys_monitor.py` | Entrada do widget; Win32, Tkinter, configuração, coleta própria e recuperação da janela |
| `tray_monitor.py` | Entrada alternativa; janela Win32 oculta, mensagens, GDI e Shell_NotifyIcon |
| `ping_monitor.py` | Grupos ICMP IPv4/IPv6 em thread própria, histórico por IP, seleção manual/automática, validação pura e toasts |
| `ping_config.py` | Persistência atômica seletiva em `[ping]`, preserva demais chaves e remove `targets` antiga |
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
- Widget mantém I/O nos coletores; Tk e reconstrução da janela ficam na thread principal.
- Ping publica sob lock `ping` (grupo ativo), `ping_other` (inativo), `ping_family` e `ping_auto` nas DUAS classes Metrics/snapshot. Placeholders são publicados ao construir o monitor e ao editar grupos.
- `set_mode`/`set_groups` usam RLock e geração: ciclo captura destinos/geração, faz I/O fora do lock e descarta resultados antigos. Modo preserva histórico; grupos zeram janelas/alertas. Famílias seguem sequenciais, com handle/buffer exclusivos da thread de coleta.
- Contadores de ciclos limpos por família independem do tamanho da janela de perda, permitindo thresholds maiores que `window`. Failover/retorno não zeram histórico.
- Bandeja atualiza ícones numa segunda thread daemon, a cada segundo.
- Apesar do comentário de `metrics_collector.py`, o widget NÃO importa esse módulo: mantém classes duplicadas em `sys_monitor.py`.
- Alterações no contrato de coleta exigem revisar as duas implementações.

## Armazenamento e fronteiras
- Não há banco de dados, conta, API remota autenticada ou histórico de métricas.
- Configuração, `crash.log` e `sysmon.log` ficam junto aos scripts, não no diretório corrente.
- `sysmon.log` registra ciclo de vida do widget e é apagado ao ultrapassar 256.000 bytes antes da próxima escrita.
- `crash.log` recebe exceções de thread principal/background; widget também captura callbacks Tk.
- Bandeja usa `crash.log`, lê `[ping]` de `config.ini` na inicialização e não grava `sysmon.log`.
- Cada edição tem mutex próprio: `Global\SysMonitor_SingleInstance` e `Global\SysMonitorTray_SingleInstance`.
- O mutex não impede executar as duas edições simultaneamente.
- Código é específico de Windows: imports acessam APIs Win32; não importar as entradas para testes portáveis.
