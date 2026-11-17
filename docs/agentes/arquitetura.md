Atualizado em 2026-11-16 (1.2.0 local: discos)

# Arquitetura e dados
## Módulos
| Caminho | Responsabilidade |
|---|---|
| `sys_monitor.py` | Entrada do widget; Win32, Tkinter, configuração, coleta própria e recuperação da janela |
| `tray_monitor.py` | Entrada alternativa; janela Win32 oculta, mensagens, GDI e Shell_NotifyIcon |
| `ping_monitor.py` | Grupos ICMP IPv4/IPv6 em thread própria, histórico por IP, seleção manual/automática, validação pura e toasts |
| `ping_config.py` | Persistência atômica seletiva compartilhada em `[ping]`/`[window]`; só a gravação de ping remove `targets` antiga |
| `taskbar_space.py` | Política pura de layout/regiões e daemon UIA de múltiplos HWNDs, sem Tk |
| `taskbar_session.py` | Gerente Tk das secundárias, sincronização de ações/editor e fechamento global, sem coleta/UIA |
| `net_split.py` | GetIpStatisticsEx sem admin, deltas DWORD, divisão pura de velocidades e medida da coluna |
| `traffic_history.py` | Pontos de 5 s, CSV das últimas 4 h, gravador daemon e geometria pura do gráfico |
| `traffic_history_ui.py` | Janelas Tk do histórico (tráfego e latência/perda, base comum), sem I/O em disco |
| `top_processes.py` | Puro: soma por nome, top 3 de CPU/memória, formatação, corte do tooltip da bandeja; leitura em massa por NtQuerySystemInformation e thread `TopProcessesMonitor` |
| `hover_tooltip.py` | Tooltip Tk do widget (Toplevel do root oculto) para os rótulos CPU/MEM, guiado pelo cursor do Windows |
| `disk_monitor.py` | Puro: retrato por disco, alerta, formatação, visão da janela; Win32: contadores PDH, volumes, modelo/extents, fallback psutil, thread `DiskMonitor` |
| `disk_ui.py` | Janela Tk `SysMonitor · Discos`; só desenha `disk_view()` |
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
- `main()` cria um único `TaskbarSpaceMonitor` daemon para a sessão taskbar, reutilizado nas reconstruções. `TaskbarSession` fornece o conjunto principal + secundárias por `set_targets`; snapshot imutável/timestamp e geração são separados por HWND. Remover alvo descarta seus dados; resultado em voo só publica se HWND/geração ainda coincidirem. Falha numa varredura invalida apenas aquela barra e as demais continuam.
- Inicialização COM MTA, cliente e todas as chamadas UIA permanecem na única worker, varrendo o conjunto ~2 s. Tk só publica alvos/lê snapshots sob lock curto, nunca espera varredura nem faz join. Um provider nativo permanentemente preso pode impedir novas amostras de todas as barras nessa worker única; dados expiram e secundárias ficam ocultas.
- UIA tenta ConnectionTimeout/TransactionTimeout de 1000 ms quando IUIAutomation2 existe. Provider travado afeta só a daemon; snapshot expira em 6 s e não são criadas workers substitutas. Erro/ausência de comtypes invalida snapshot e registra uma vez; varredura seguinte pode recuperar. Mudança de alvo invalida imediatamente e resultado de alvo antigo é descartado.
- Embedder escolhe layout em coordenadas de tela e converte para o pai; callback Tk troca nível e refaz layout no lugar. Reentrância de reposition durante relayout é evitada; callback reutiliza métricas já renderizadas, sem obter um segundo grupo de ping após medir larguras.
- `TaskbarSession` nasce fora do loop de reconstrução principal, enumera barras secundárias na thread Tk via after (~2 s), mantém dicionário HWND→MonitorWindow, editor único e ações globais. Widgets compartilham configuração/Metrics/PingMonitor, mas têm nível/lado próprios. Nenhum Collector/PingMonitor adicional.
- Secundárias usam HWND explícito no embedder; healthy não consulta a barra principal. Erros/criação/remoção são locais e não saem do mainloop. Reconstrução principal simples apenas reanexa a nova referência; reconfiguração de grupos fecha todas as secundárias e aguarda attach_primary antes de recriá-las. Fechamento cancela after e quebra a referência principal↔sessão na thread Tk.
- `wait_for_taskbar` aceita espera/cancelamento; em taskbar, `TaskbarSession.wait` processa mainloop com timer durante esperas do principal. Assim o gerente e os menus sobrevivem à recuperação; em docked/floating preserva o caminho anterior e não cria gerente.
- Widget mantém I/O nos coletores; Tk e reconstrução da janela ficam na thread principal.
- Collector do widget lê `GetIpStatisticsEx` (AF_INET=2/AF_INET6=23) exclusivamente na thread de coleta. `dwOutRequests` reparte subida e `dwInReceives` descida: velocidade real psutil × proporção de pacotes no intervalo, não bytes reais por família. Zero pacotes produz zero; wrap DWORD próximo da borda é modular, demais recuos tratados como reset (delta zero).
- Snapshot acrescenta `net_rates=((up_v4,up_v6),(down_v4,down_v6))` ou None (sem baseline/falha); Tk só formata. Falha da API registra log uma vez, invalida baseline e retorna à exibição total; recuperação exige duas amostras válidas consecutivas. A classe Metrics da bandeja mantém o campo para compatibilidade, mas a bandeja continua coletando/exibindo somente totais, sem chamar esta API.
- Ping publica sob lock `ping` (grupo ativo), `ping_other` (inativo), `ping_family` e `ping_auto` nas DUAS classes Metrics/snapshot. Placeholders são publicados ao construir o monitor e ao editar grupos.
- `set_mode`/`set_groups` usam RLock e geração: ciclo captura destinos/geração, faz I/O fora do lock e descarta resultados antigos. Modo preserva histórico; grupos zeram janelas/alertas. Famílias seguem sequenciais, com handle/buffer exclusivos da thread de coleta.
- Contadores de ciclos limpos por família independem do tamanho da janela de perda, permitindo thresholds maiores que `window`. Failover/retorno não zeram histórico.
- Bandeja atualiza ícones numa segunda thread daemon, a cada segundo.
- Apesar do comentário de `metrics_collector.py`, o widget NÃO importa esse módulo: mantém classes duplicadas em `sys_monitor.py`.
- Alterações no contrato de coleta exigem revisar as duas implementações.

## Armazenamento e fronteiras
- Não há banco de dados, conta ou API remota autenticada. O widget mantém histórico local estimado de tráfego por família (a bandeja não grava histórico).
- `TrafficRecorder` único lê `metrics.net_rates` sob lock a cada 1 s e consome `PingMonitor.take_loss_marks()` e `take_worst_rtts()` (pior RTT por família e posição do destino, `[ip1, ip2]`) (pior perda exata por família desde a leitura, zerada ao ler e ao trocar grupos). Independente de notificações.
- `TrafficHistory` acumula médias de 5 s e pior marca; até 2.880 pontos sob lock. A thread própria carrega/limpa o CSV ao iniciar, acrescenta a cada 60 s, reescreve atomicamente a cada hora e finaliza/grava ao sair (join limitado a 2 s). Erro de disco fica no log uma vez e permite nova tentativa, sem atrasar Tk/coleta.
- Arquivo `data_dir()/trafego-historico.csv`, sem IPs, sites ou programas. Geometria pura ordena pontos, preserva picos por pixel e interrompe buracos; Tk apenas desenha. Ver [spec](../superpowers/specs/2026-11-06-historico-trafego-design.md).
- Top 3 de programas: `TopProcessesMonitor` (thread daemon, evento interno `_stop_evt`) amostra a cada 2 s só com algum dono ativo (tooltip aberto; a bandeja fica sempre ativa) e publica `snapshot()` sob lock curto; Tk/Win32 só leem. Sem gravação em disco.
- Discos: `DiskMonitor` (thread daemon, evento `_stop_evt`) coleta a cada 1 s e publica o último retrato sob lock; Tk (coluna do widget, tooltip, `DiskWindow`) só chama `snapshot()`. Espaço dos volumes relido a cada 5 ciclos, modelo só quando muda o conjunto de instâncias. Falha de coleta: log uma vez e segue; sem gravação em disco. O top 3 por E/S usa o mesmo `TopProcessesMonitor` (lista `io`).
- Configuração, `crash.log` e `sysmon.log` ficam junto aos scripts, não no diretório corrente.
- `sysmon.log` registra ciclo de vida do widget e é apagado ao ultrapassar 256.000 bytes antes da próxima escrita.
- `crash.log` recebe exceções de thread principal/background; widget também captura callbacks Tk.
- Bandeja usa `crash.log`, lê `[ping]` de `config.ini` na inicialização e não grava `sysmon.log`.
- Cada edição tem mutex próprio: `Global\SysMonitor_SingleInstance` e `Global\SysMonitorTray_SingleInstance`.
- O mutex não impede executar as duas edições simultaneamente.
- Código é específico de Windows: imports acessam APIs Win32; não importar as entradas para testes portáveis.
