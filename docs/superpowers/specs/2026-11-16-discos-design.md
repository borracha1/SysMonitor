# Discos: coluna no widget e janela de discos (SysMonitor 1.2.0)

Data: 2026-11-16. Registro: `D:/dev/memoria-compartilhada/pedidos/2026-11-16-claude-sysmonitor-discos.md`.
Branch: `versao-1.2`, criada a partir da `versao-1.1.1` (a 1.2.0 inclui a 1.1.1, ainda fora da main).

## Objetivo
Ver de relance se algum disco está trabalhando muito e, com um clique, ver todos os discos com a leitura e a
escrita atuais e o espaço total, usado e livre.

Pedido original: "queria uma outra telinha, onde eu vou clicar e vai aparecer a listagem de todos os discos do meu
sistema, e nela vai mostrar a taxa de leitura e escrita atual, e o tamanho total, usado e disponível em cada disco,
o acesso a essa telinha pode ficar ao lado da memória, com algum ícone relacionado a armazenamento. E quando houver
algum disco em alta utilização esse ícone iria mudar de cor e mostrar um resumo de hd em uso igual é mostrado na
memória/cpu atualmente".

## Decisões do Mateus
- "Alta utilização" = atividade do disco físico, o mesmo % da coluna "Disco" do Gerenciador de Tarefas
  (100 − `% Idle Time`), com limites Low/Warning/High como CPU/MEM.
- Coluna de largura fixa à direita de MEM. Em repouso só o ícone; quando algum disco atinge Low, ícone e texto
  ficam na cor do limite e aparece o disco mais ativo: `🖴 D: 87%`. Nada na barra se mexe ao entrar ou sair do alerta.
- Hover no ícone: tooltip com o top 3 de programas por E/S, igual ao de CPU/MEM.
- Janela agrupada por disco físico, barra de espaço colorida por volume e duplo clique no volume abre no Explorer.
- Só discos internos fixos. Coleta pelos contadores PDH (alternativa A).

## Fora desta versão
Ícone de disco na bandeja, histórico ou gráfico de disco, alerta/toast de espaço cheio, unidades USB/removíveis e
de rede, discos sem letra (aparecem só se tiverem volume com letra), escolha de quais discos monitorar.

## Limitações conhecidas
- O top 3 usa `ReadTransferCount`/`WriteTransferCount` de cada processo. O Windows soma ali toda E/S do processo
  (arquivos, rede, dispositivos), não só disco. O Gerenciador de Tarefas usa ETW, que pede mais. Por isso o título
  do tooltip é `Maiores em E/S (aprox.)`.
- Volume que ocupa mais de um disco físico (span/RAID do Windows) aparece sob o primeiro disco listado pelo contador.

## Comportamento

### Coluna no widget (taskbar, docked, floating)
- Posição: à direita de MEM, com o mesmo espaçamento de 10 px entre colunas na barra.
- Ícone: glifo de HD da fonte `Segoe Fluent Icons` (U+EDA2); se a fonte não existir, `🖴` em `Segoe UI Symbol`.
  A escolha é feita uma vez ao montar o widget, por `tkinter.font.families()`.
- Largura reservada = ícone + espaço + pior texto `Z: 100%` na fonte atual, medida como as outras colunas. A largura
  não muda entre repouso e alerta.
- Repouso (nenhum disco ≥ Low, ou sem dados): só o ícone, na cor normal do texto.
- Alerta: disco físico com maior atividade ≥ Low. Texto `<letra>: <n>%`, onde a letra é a do primeiro volume do
  disco em ordem alfabética (disco sem volume com letra não é exibido). Ícone e texto na cor de `usage_color`
  com os limites `disk`. Empate: menor índice de disco.
- Níveis de espaço da barra: nível 0 e 1 mostram a coluna; nível 2 a oculta junto com MEM. As larguras dos níveis
  passam a contar a coluna nova.
- Clique esquerdo na coluna abre a janela de discos (ou traz para a frente). Usa o mesmo esquema de retângulos com
  `_cursor_pos`/`_win_rect` do clique na rede; floating respeita a tolerância de arraste de 3 px.
- Menu direito: item `Discos…` logo abaixo de `Latência e perda…` (ou de `Histórico de tráfego…` sem ping).
- Hover: tooltip `Maiores em E/S (aprox.)` com 3 linhas `chrome.exe  12,4 MB/s` (leitura + escrita somadas), mesma
  mecânica do top 3 de CPU/MEM (detecção pelo cursor do Windows, poll de 250 ms, amostra a cada 2 s só com o tooltip
  aberto). Primeira amostra ainda sem diferença: `medindo…`. Programa com 0 B/s não entra; lista vazia: `sem E/S`.

### Janela `SysMonitor · Discos`
- `Toplevel` da raiz oculta, instância única, sobrevive à reconstrução do widget e é compartilhada por todas as
  barras. Tamanho inicial pelo conteúdo, redimensionável, centrada na tela do clique. Esc fecha.
- Atualiza a cada 1 s lendo o último retrato do monitor; não coleta nada na thread do Tk.
- Um bloco por disco físico, em ordem de índice:
  - Cabeçalho: `Disco N · <modelo>` e, à direita, `atividade NN%` na cor do limite `disk`.
  - Linha: `leitura <taxa>   escrita <taxa>`.
  - Uma linha por volume com letra, em ordem alfabética: `C:  <rótulo>`, barra de usado/total colorida pelos
    limites `disk_space` (abaixo de 80%: cor Low; 80–89%: Warning; ≥ 90%: High; sem leitura: cor normal), `<usado> / <total>` e `<livre> livre`.
- Duplo clique numa linha de volume abre `C:\` no Explorer (`os.startfile`).
- Sem disco algum: `Nenhum disco encontrado`. Valor indisponível: `--` só naquele campo.
- Formatos: taxas em `B/s`, `KB/s`, `MB/s`, `GB/s` com vírgula decimal (1 casa abaixo de 100); espaço em `GB` até
  999 GB e `TB` acima, com 1 casa. Base 1024, como o Explorer.

### Limites (editor existente)
- Duas linhas novas no grupo Uso (%): `DISCO (atividade)` padrão 50/75/90 e `ESPAÇO DO VOLUME` padrão 80/90, só 2 campos (Warning e High; `abaixo` na coluna Low).
- Chaves em `[usage_limits]`: `disk_low`, `disk_warning`, `disk_high`, `disk_space_warning`,
  `disk_space_high` (`disk_space_low` é ignorada). Validação `0 ≤ Low < Warning < High ≤ 100`, e `0 ≤ Warning < High ≤ 100` para espaço e as 3 cores globais. Chave ausente ou
  inválida usa o padrão só daquela métrica, como hoje.

## Componentes

### `disk_monitor.py` (novo)
- Funções puras, sem ctypes nem Tk:
  - `parse_instance("0 C: F:") -> (0, ('C', 'F'))`; ignora `_Total`.
  - `build_snapshot(counters, volumes, models) -> DiskSnapshot`: discos com índice, modelo, atividade (0–100,
    limitada), leitura e escrita em B/s, e volumes (letra, rótulo, total, usado, livre).
  - `alert_disk(snapshot, limits) -> (letra, pct) | None`.
  - `fmt_rate(bps)`, `fmt_size(bytes)`.
- `PdhReader`: abre uma consulta PDH com `PdhAddEnglishCounterW` para `\PhysicalDisk(*)\% Idle Time`,
  `\PhysicalDisk(*)\Disk Read Bytes/sec` e `\PhysicalDisk(*)\Disk Write Bytes/sec`, lê com
  `PdhGetFormattedCounterArrayW`. Instância privada de `pdh.dll` com `argtypes`/`restype` explícitos
  (ver armadilhas.md). Não pede admin.
- Espaço e rótulo: `GetDiskFreeSpaceExW` e `GetVolumeInformationW` só para letras com `GetDriveTypeW == DRIVE_FIXED`,
  relidos a cada 5 s.
- Modelo: `IOCTL_STORAGE_QUERY_PROPERTY` em `\\.\PhysicalDriveN` aberto com acesso 0 (sem admin), lido uma vez por
  índice e de novo quando o conjunto de instâncias muda. Falha: `Disco N` sem modelo.
- `DiskMonitor(threading.Thread)`, daemon: a cada 1 s coleta e publica o retrato sob lock; `snapshot()` devolve o
  último. Uma exceção num ciclo vai uma vez para o `sysmon.log` (e de novo só após recuperar) e não mata a thread.
- Fallback: se o PDH não abrir, taxas pela diferença de `psutil.disk_io_counters(perdisk=True)` (`PhysicalDriveN`)
  e atividade `None` (`--` na janela; sem alerta). Mapeamento volume→disco nesse caso por
  `IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS` em `\\.\C:` com acesso 0.
- Criado em `main()` uma vez por processo e encerrado no `finally`, como os outros monitores; uma só coleta para
  todas as barras.

### `disk_ui.py` (novo)
`DiskWindow`: desenha o retrato com Labels/Canvas; não tem lógica de coleta nem de formatação própria.

### Alterações
- `top_processes.py`: `parse_process_buffer` passa a ler também `ReadTransferCount` e `WriteTransferCount` do
  `SYSTEM_PROCESS_INFORMATION` (x64), ampliando `_SPI_MIN_SIZE` conforme. `top_lists` ganha a lista `io` pela
  diferença entre duas amostras (B/s), casando processos por (pid, hora de criação). Fallback psutil:
  `io_counters()`; processo sem acesso fica de fora.
- `usage_limits.py` / `usage_limits_ui.py`: métricas `disk` e `disk_space`.
- `sys_monitor.py`: coluna, clique, hover, item de menu, larguras dos níveis.
- `taskbar_space.py`: só se as larguras por nível precisarem da coluna nova (a política não muda).
- `version.py`: 1.2.0. `SysMonitor.spec`/`build.ps1`: incluir os módulos novos se não forem achados sozinhos.

## Erros
- Disco sem contador, volume sem resposta ou modelo ilegível: `--` só no campo afetado.
- Volume que some: sai da lista no próximo ciclo; janela aberta não quebra.
- PDH falhando no meio: um log, fallback para psutil no ciclo seguinte; volta ao PDH ao reiniciar o programa.
- Fonte de ícone ausente: fallback de glifo, sem log.

## Testes
- Unidade (dados falsos, sem Win32): `parse_instance`, `build_snapshot` (agrupamento, ordem, atividade limitada a
  0–100), `alert_disk` (abaixo de Low, empate, disco sem letra, atividade `None`), `fmt_rate`/`fmt_size`, cores por
  limite, limites `disk`/`disk_space` (padrão, inválido, salvar), diferença de E/S por processo (processo novo, pid
  reutilizado, contador que volta), parse do buffer com os campos novos.
- Monitor: exceção num ciclo não mata a thread e loga uma vez; fallback psutil quando o PDH falha.
- Widget (fakes/Tk como os testes atuais): largura da coluna igual em repouso e alerta, coluna oculta no nível 2,
  clique na coluna abre a janela, item de menu presente.
- Tk real isolado: janela de discos com retrato falso e com o retrato real do PC; captura para `docs/agentes/telas/`.
- Manual (Mateus): widget no Explorer real nas duas telas, alerta disparado (cópia de arquivo grande), tooltip,
  janela e duplo clique.
- Suíte: `py -3.12 -m unittest discover -s tests`.

## Documentação ao fechar
`docs/agentes/interface.md`, `arquitetura.md`, `sensores-coleta.md`, `telas.md`, `estado.md`, `INDICE.md`.
