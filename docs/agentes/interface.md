Atualizado em 2026-10-21 (branch main; automático mostra perda e preserva relayout; commit "perda de pacotes por grupo IPv4/IPv6")

# Interface e ciclo de vida
## Widget (`sys_monitor.py`)
- `display_mode=taskbar` é padrão: filho de `Shell_TrayWnd`, à esquerda de `TrayNotifyWnd`.
- `docked`: faixa acima da barra; `floating`: caixa arrastável de 150 × 130.
- `MonitorWindow` usa Toplevel de uma única raiz Tk oculta e duradoura.
- Rede ocupa duas linhas; CPU/GPU mostram uso e temperatura; memória mostra percentual.
- Ping habilitado: os três modos mostram somente o grupo ativo em duas linhas. Marcador separado `v4·A`/`v6·A` no automático, `v4`/`v6` no manual; IPs alinhados em pixels, segunda linha vazia se houver só um IP. Antes da coleta: `IP --`; perda/última falha deixa apenas aquela linha vermelha.
- Coluna/painel medidos somente pelo grupo ativo: reserva do marcador `v6·A ` + pior `IP 100% 1000ms` daquele grupo; se `timeout_ms > 1000`, a reserva usa esse timeout. Gap entre ping e CPU na barra: exatamente 10 px, igual às outras colunas. `enabled=false` esconde a coluna.
- Família inicial compartilhada com `PingMonitor` por função pura: manual usa o modo; auto usa o preferido, ou o outro grupo se estiver vazio. No `_update_labels` (thread Tk), mudança de `ping_family` recalcula o layout no lugar: taskbar recalcula colunas/`embed_width`, atualiza `embedder.width`, reposiciona controles na altura atual e chama `reposition`; docked redimensiona painel e geometria; floating redimensiona painel e janela pelo conteúdo, preservando posição. Sem mudança de família, nenhum relayout. Sem reconstrução nem novo embedding/log na troca; editar grupos continua reconstruindo.
- Automático mostra onde está a perda: falha em algum IP do outro grupo com todos os exibidos respondendo troca imediatamente para o outro; perda nos dois mantém o exibido. Só volta ao preferido após `return_clean_cycles` (padrão 60) ciclos consecutivos sem nenhuma falha no grupo exibido. Mostrar perda tem prioridade sobre esse retorno. Grupo vazio nunca é exibido; manual nunca troca por perda. Trocas preservam janelas e acionam o relayout acima, sem reconstruir; log/toast identifica família e IPs com falha, ou tempo sem perda do grupo antes exibido no retorno.
- Sensores ausentes mostram `--`; `cpu_temp_error` ou `gpu_error` ativa ⚠ vermelho.
- Cores, Segoe UI e tamanho vêm de configuração; largura embutida é medida pela fonte.
- Floating salva x/y ao soltar arraste; docked/taskbar derivam posição da barra.
- Menu direito, só com ping habilitado e monitor existente: rádios `Automático`, `Só IPv4`, `Só IPv6` (grupo vazio desabilitado), `Configurar destinos…`, separador e `Fechar`. Seleção persiste `mode`, aplica `set_mode` imediatamente, sem reconstrução; falha de gravação mantém modo anterior e registra log. Floating também tem botão ✕.
- Editor único `Toplevel(self.master)` do root oculto, nunca filho do widget embutido no Explorer: topmost, centralizado, não redimensionável, quatro campos `IPv4 1`, `IPv4 2`, `IPv6 1`, `IPv6 2` e rádios de preferido no automático. Validação estrita por família, duplicados canônicos rejeitados, pelo menos um IP e preferido não vazio; Salvar/Cancelar, Enter/Esc, erro vermelho local. Reabrir traz a instância existente para frente.
- Salvar persiste `targets_v4`, `targets_v6`, `preferred` antes de aplicar `set_groups`; erro não aplica nada. Se a edição esvaziar a família manual atual, modo acompanha a única família restante, também persistido. Reconstrução intencional usa `reconfigure_requested`: imediata, sem pausa de 2 s, sem contar perda nem log `window lost`.
- Verificação atual por fakes/AST: alinhamento das duas linhas, expansão IPv4→IPv6, encolhimento IPv6→IPv4 e ausência de relayout sem mudança nos três modos. A validação anterior em Tk oculto não comprovava espaçamento justo no IPv4; a correção ainda aguarda conferência interativa no Explorer/DPI do usuário após reinício manual autorizado. Esta tarefa não reiniciou o widget.
- Taskbar exige clique no texto: pixels da cor transparente são click-through.
- Coordenadas do menu no modo taskbar vêm de `GetCursorPos`, não de Tk.
- Eventos de menu usam bind do Toplevel, não `bind_all`, para sobreviver à reconstrução.

## Embedding e recuperação
- DPI awareness é habilitado antes de criar qualquer janela no modo taskbar.
- `TaskbarEmbedder.embed()` muda WS_POPUP para WS_CHILD e chama SetParent.
- Reaplica WS_EX_LAYERED depois do reparent e usa LWA_COLORKEY com `#010101`.
- Posiciona com coordenadas relativas ao pai (y=0) e acompanha altura/largura da bandeja.
- `_maintain_position()` verifica saúde do HWND, tenta re-embedding e solicita reconstrução se necessário.
- `main()` espera até 60 s pela barra no boot; ausência ou embedding falho leva a docked só na sessão.
- Janela perdida é reconstruída após 2 s; cinco perdas consecutivas com duração <15 s levam a docked.
- Docked recalcula posição a cada cinco ticks; topmost é reafirmado por tick em docked/floating.
- Destruição cancela after, quebra referências embedder/font e encerra mainloop sem destruir a raiz.

## Bandeja (`tray_monitor.py`)
- Três ícones reais: rede ↑/↓; uso/temperatura CPU; uso/temperatura GPU.
- Sem uso GPU disponível, terceiro ícone vira memória; com GPU, memória aparece no tooltip.
- Tooltip de rede: grupo ativo primeiro com marcador, depois inativo; orçamento de 127 caracteres prioriza o ativo, cortando inativo e, se necessário, resumo de velocidade antes dele. Placeholders antes da primeira coleta também são aceitos. CPU atribui qualquer erro ao LHM não rodando.
- Dimensão vem de `GetSystemMetrics(SM_CXSMICON/SM_CYSMICON)`, não constante de 16 px.
- `make_text_icon()` usa DIB 32 bpp, GDI e ajuste manual de alpha; `TrayIconSlot` gerencia HICON.
- Primeiro desenho ocorre após 1,1 s; atualização a cada 1 s por thread daemon.
- Clique esquerdo não faz nada; clique direito → `Fechar` destrói janela e sai do loop.
- Callback WNDPROC fica referenciado em `_wndproc_ref` durante o processo.
- Não há tratamento de mensagem `TaskbarCreated` para registrar ícones após reiniciar Explorer.
