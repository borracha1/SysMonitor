Atualizado em 2026-10-07 (commit 7400f35)

# Interface e ciclo de vida
## Widget (`sys_monitor.py`)
- `display_mode=taskbar` é padrão: filho de `Shell_TrayWnd`, à esquerda de `TrayNotifyWnd`.
- `docked`: faixa acima da barra; `floating`: caixa arrastável de 150 × 130.
- `MonitorWindow` usa Toplevel de uma única raiz Tk oculta e duradoura.
- Rede ocupa duas linhas; CPU/GPU mostram uso e temperatura; memória mostra percentual.
- Sensores ausentes mostram `--`; `cpu_temp_error` ou `gpu_error` ativa ⚠ vermelho.
- Cores, Segoe UI e tamanho vêm de configuração; largura embutida é medida pela fonte.
- Floating salva x/y ao soltar arraste; docked/taskbar derivam posição da barra.
- Menu direito tem `Fechar`; floating também tem botão ✕.
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
- Tooltips mostram precisão maior e avisos de ausência de sensores; CPU atribui qualquer erro ao LHM não rodando.
- Dimensão vem de `GetSystemMetrics(SM_CXSMICON/SM_CYSMICON)`, não constante de 16 px.
- `make_text_icon()` usa DIB 32 bpp, GDI e ajuste manual de alpha; `TrayIconSlot` gerencia HICON.
- Primeiro desenho ocorre após 1,1 s; atualização a cada 1 s por thread daemon.
- Clique esquerdo não faz nada; clique direito → `Fechar` destrói janela e sai do loop.
- Callback WNDPROC fica referenciado em `_wndproc_ref` durante o processo.
- Não há tratamento de mensagem `TaskbarCreated` para registrar ícones após reiniciar Explorer.
