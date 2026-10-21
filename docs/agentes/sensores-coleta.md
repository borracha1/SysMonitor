Atualizado em 2026-10-21 (branch main; automático mostra grupo com perda; commit "perda de pacotes por grupo IPv4/IPv6")

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

## Perda de pacotes (`ping_monitor.py`)
- `PingMonitor` (thread daemon) usa `iphlpapi` via ctypes com assinaturas explícitas: IPv4 por `IcmpSendEcho`; IPv6 por `Icmp6CreateFile`/`Icmp6SendEcho2`, origem AF_INET6 qualquer, destino empacotado de 16 bytes e buffer de 256 bytes. Sem admin, sem driver, compatível com HVCI. O handle IPv6 é criado só no primeiro alvo IPv6; falha registra um evento e não impede IPv4.
- A cada ciclo, pinga TODOS os IPs dos dois grupos, inclusive em modo manual, sequencialmente com o mesmo `IcmpPinger`. Padrões IPv4: `8.8.8.8,1.1.1.1`; IPv6: `2001:4860:4860::8888,2606:4700:4700::1111`. Queda total pode levar ~4 s com timeout de 1000 ms; paralelismo não foi adicionado.
- Janela deslizante independente por IP (`window`, padrão 60): perda % = falhas / amostras. Nas duas classes `Metrics`, `ping` contém `(ip, loss, rtt, ok)` do grupo ativo; `ping_other` contém inativo ou `()`, `ping_family` é `ipv4`/`ipv6`, `ping_auto` é booleano. `ping` é `None` antes de construir monitor; construção/edição publica placeholders `(ip, None, None, None)`. RTT é `None` se a última tentativa falhou.
- `auto` inicia no preferido (ou outro se vazio) e serve para MOSTRAR a perda, não fazer failover para o grupo limpo. Após cada ciclo, se algum IP do outro grupo falhou e nenhum IP do exibido falhou, exibe o outro imediatamente. Perda nos dois mantém o grupo exibido. Essa regra tem prioridade sobre o retorno: se o exibido não é o preferido e completou `return_clean_cycles` (60) ciclos consecutivos sem nenhuma falha, volta ao preferido, desde que ele não esteja vazio. Contador é do grupo exibido, inclui o ciclo atual, zera com qualquer falha e independe de `window`; grupo vazio nunca conta nem é exibido.
- Cada troca automática registra evento e, com `notify`, toast `Ping: perda no IPv6` / `Sem resposta de 2606:4700:4700::1111; exibindo IPv6.` (lista todos os IPs que falharam naquele ciclo), ou `Ping: de volta ao IPv4` / `IPv6 sem perda há 1 min.` (famílias conforme a troca). Tempo deriva de ciclos × intervalo configurado. Histórico não é zerado ao trocar. `ipv4`/`ipv6` fixam manualmente a família, mas continuam medindo ambas.
- Alerta e log só consideram perdido um ciclo em que TODOS os alvos falham. Mantidos `alert_after`, cooldown de 60 s e recuperação após 5 ciclos com alguma resposta. Toast de perda informa a perda de cada IP; eventos do widget vão para `sysmon.log`.
- Config opcional em `[ping]`: enabled, targets_v4, targets_v6, mode, preferred, return_clean_cycles, interval_ms, timeout_ms, window, notify, alert_after, cooldown_s. `enabled=false` esconde indicadores. `targets` antiga é separada por família quando não existem as duas chaves novas. Cada grupo aceita 0–2 IPs, inválidos/família errada são descartados; ambos vazios usam padrões. mode/preferred inválidos viram auto/ipv4. Grupo vazio não é selecionável; modo manual indisponível acompanha a família existente.
- Não usar nome `_stop` na thread (colide com Thread); só IPs literais, sem DNS. Testes sem thread e sem Tk: `py -3.12 -m unittest discover -s tests -v`.
- `fmt_loss`, `fmt_ping_line` e `ping_has_problem` são helpers sem Tkinter. Exemplo: `8.8.8.8 0% 14ms`; sem dados: `8.8.8.8 --`; última falha: `8.8.8.8 25% --ms`.
- Todos os modos mostram duas linhas do grupo ativo com marcador separado e largura medida pelo pior IP do grupo ativo e relayout ao mudar de família; segunda linha vazia se não houver segundo IP. Cor vermelha individual e alinhamento em pixels preservados na troca sem reconstruir.
- Tooltip de rede da bandeja mostra marcador e grupo ativo, depois inativo, limitado a 127 caracteres. Inativo é cortado primeiro; resumo de velocidade cede espaço ao ativo se necessário.

## Troca de destinos em tempo real
- `parse_ping_groups(values, preferred)` valida quatro campos por posição/família usando `ipaddress`: remove espaços/vazios, canonicaliza, rejeita duplicados/zonas, exige pelo menos um IP e preferido não vazio; mensagens identificam campo e família. `ping_settings(section)` faz leitura tolerante e migração legada, sem DNS e sem gravar. Widget resolve migração antes de preencher DEFAULTS para não mascarar `targets` antiga.
- `ping_config.save_ping_settings(path, **settings)` lê ConfigParser novo sem defaults do aplicativo, altera apenas chaves pedidas em `[ping]`, remove `targets` obsoleta e preserva demais seções/chaves. Temporário na mesma pasta, flush/fsync e `os.replace`; falha preserva original e limpa temporário. Comentários/formatação não são preservados. Ao mudar modo sobre config legada, GUI também envia grupos migrados para não perder destinos.
- GUI: gravação → fechar editor → atualizar cfg → `set_groups` → log → reconstrução imediata. Falha de validação/gravação mantém editor e monitor inalterados. Se a edição esvaziar grupo manual atual, modo muda/persiste para o grupo restante.
- `set_groups(v4, v6, preferred)` usa lock, zera janelas/alertas sem toast e publica placeholders. `set_mode(mode)` muda família imediatamente, recalcula auto a partir do preferido e preserva histórico/alertas. Ambos incrementam geração; probe captura destinos/geração sob lock, faz I/O fora dele e descarta ciclos antigos ao publicar.
- Bandeja lê grupos/modo/preferido e demais parâmetros do config apenas na inicialização, sem menu de edição nem gravação.

## Diagnóstico
- `python3 sensors.py` imprime GPU (temperatura, uso) e temperatura CPU com mensagens de erro.
- Conferir LHM → Options → Remote Web Server → Run (porta 8085).
- Não reinstalar HWiNFO para restaurar a coleta: veja [armadilhas.md](armadilhas.md).
