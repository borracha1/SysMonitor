Atualizado em 2026-10-25 (branch main; limites de uso; sem commit)

# Armadilhas e decisões
| Problema / decisão | Causa e regra para não repetir | Fonte |
|---|---|---|
| HWiNFO Free perde sensores após 12 h | Shared Memory desliga; migração para NVML + LHM/PawnIO, sem limite equivalente documentado | `sensors.py`, commit 7400f35 |
| TrafficMonitor falhava ao mudar índice de sensor | Tratar ausência como `None`/`--` e aviso, não exceção fatal | `README.md`, `SensorReader` |
| Janela topmost não fica dentro da barra Win11 | Explorer ganha composição na área da barra; usar filho via SetParent ou ícones reais | `sys_monitor.py`, `tray_monitor.py` |
| Widget some mesmo com topmost | Z-order da faixa topmost muda; reafirmar SetWindowPos nos ticks | `_reassert_topmost()` |
| Primeiro SetParent parecia falhar | Coordenadas são relativas ao pai; y de tela coloca filho fora da barra | `TaskbarEmbedder.reposition()` |
| Filho fica coberto pela ponte XAML | Reaplicar WS_EX_LAYERED DEPOIS de SetParent; não usar Tk alpha/topmost no modo taskbar | `TaskbarEmbedder.embed()` |
| Cor-chave deixa cliques atravessarem o fundo | Manter #010101 no texto e uma Toplevel irmã com LWA_ALPHA=1 abaixo dele; SetParent antes de WS_EX_LAYERED nas duas. Não voltar a exigir clique nos traços das letras | `TaskbarEmbedder`, `test_taskbar_clicks.py` |
| GUI pode travar Explorer | Pai/filho entre processos compartilham filas de input; I/O lento deve ficar nos coletores. UIA inteira (inclusive inicialização COM/cliente) fica na daemon dedicada; Tk só lê snapshot sob lock curto, nunca aguarda UIA nem faz join | `sys_monitor.py`, `taskbar_space.py` |
| COM/UIA falha por apartment incompatível | comtypes inicializa a thread no primeiro import; configurar temporariamente coinit_flags=0 nesse import e inicializar explicitamente MTA se o módulo já existe. Criar/usar/liberar objetos na worker; não importar cliente UIA na thread Tk | `TaskbarSpaceMonitor.run` |
| Monitor menor: widget cobre apps centralizados | Bandeja não informa fim dos ícones. Medir regiões UIA, priorizar conteúdo completo: direita 0 → esquerda 0 → direita 1 → esquerda 1 → direita 2 → esquerda 2. Direita alinhada no fim da região; esquerda no início. Não desligar net_split no config; só reduzir exibição. Sem dados válidos preserva comportamento antigo; sem espaço nem no nível 2 há fallback explícito com log | `choose_layout`, `TaskbarEmbedder` |
| Relayout pode reentrar no split | Mudança de nível durante relayout pode destruir as células em uma chamada aninhada; ao retornar, comparar active com self._net_active e sair se mudou, antes de pintar | `MonitorWindow._update_net_split`, `test_split_activation_relayout_reenters_and_disables_cells` |
| pythonw não pinta janela alpha neste PC | Código escolhe python.exe e oculta console; README diverge | `hide_console_window()`, `create_shortcut.py` |
| Tcl aborta após reconstruir janela | GC pode liberar antigo tk.Tk em thread errada; raiz única e Toplevel por janela | `MonitorWindow` docstring |
| Atalho inicia antes de Explorer | Esperar barra por até 60 s e usar fallback docked; não desistir imediatamente | `main()` |
| Handle 64 bits truncado por ctypes | Declarar argtypes/restype adequados; implementação existente não garante cobertura de toda API | `tray_monitor.py`, `_u32` |
| Texto GDI transparente/invisível | Desenho não preenche alpha; usar max(R,G,B) para cobertura | `make_text_icon()` |
| Clique esquerdo encerra por acidente | Left-click intencionalmente sem ação; saída só pelo menu direito | `wnd_proc()`, `show_exit_menu()` |
| Falha UIA transitória faz o widget piscar/sobrepor ícones | Falha de varredura por HWND preserva o último snapshot bom sem renovar timestamp; expira aos 6 s. Só falha fatal do worker (hwnd=None) limpa tudo; log de varredura uma vez por HWND informa keeping last layout | `TaskbarSpaceMonitor._failure` |

## Barras secundárias e testes Tk
- Shell_SecondaryTrayWnd não tem TrayNotifyWnd: nunca posicionar junto da borda da tela como se ela fosse bandeja. Sem UIA válida daquela barra, ocultar/não criar; usar SystemTray.* para o limite direito, mesmo com mod Windhawk.
- Falha/destruição de secundária não pode chamar master.quit: interromperia o principal e contaria quick_losses indevidamente. Gerente é externo ao ciclo de reconstrução principal e tem after próprio; esperas do principal devem processar eventos Tk.
- Uma sessão só, com Metrics/PingMonitor compartilhados e editor único. Rebuild simples do principal não recria secundárias; edição de grupos recria todas. Cancelar after e quebrar referência principal↔sessão ao fechar.
- Testes de múltiplos widgets com Mock devem limpar históricos da factory (guardam root/sessão nos argumentos) e referências cíclicas na thread Tk antes de iniciar workers. Reproduzido aborto nativo `Tcl_AsyncDelete: async handler deleted by the wrong thread` quando o GC de uma worker recolheu uma raiz de teste; corrigido o teardown, seguido de duas suítes completas aprovadas. Não remover o isolamento em janelas-pai nem reiniciar o Explorer para testar.
- DPI misto não foi resolvido/validado: fontes Tk usam a escala do interpretador, sem ajuste dedicado por monitor. Mantida a awareness existente e coordenadas de tela; o cenário previsto/testado é 100% nos dois monitores. Conferir manualmente outras escalas.

## Editor de limites na bandeja
- `wait_window` de Tk é um laço modal aninhado na mesma thread das mensagens Win32. `Fechar` pode chegar com o editor aberto: no WM_DESTROY chamar `preferences.close()` ANTES de PostQuitMessage, liberando wait_window; só postar WM_QUIT pode impedir o retorno ao finally. Manter também close idempotente no finally. Nunca criar/manipular Tk na worker de refresh dos ícones.
- Testes devem usar `tempfile.TemporaryDirectory()` sem indexar `os.environ['TMPDIR']`: PowerShell comum pode não definir a variável (quatro KeyError reproduzidos). Ao mover import puro para o topo, ajustar namespaces dos testes AST que carregam apenas definições, sem importar a entrada Win32.

## Limites e riscos visíveis no código
- Bandeja não registra `TaskbarCreated`; sobrevivência dos ícones a restart de Explorer: (a confirmar) em execução.
- `Collector._stop` é Event e sobrescreve nome interno de Thread; não adicionar join sem revisar essa colisão.
- Coleta duplicada: modificar `metrics_collector.py` não modifica automaticamente o widget.
- NVML só sinaliza erro de leitura quando ambas as consultas falham; ausência parcial pode não acender ⚠.
- Reset de contador de rede pode produzir velocidade negativa; mudança de relógio também afeta delta.
- psutil pode matar Collector por exceção; proteção best-effort está nos sensores, não na coleta inteira.
- Bandeja tem refresher infinito daemon; remoção de ícones pode concorrer com atualização ao encerrar.
- Logs de exceção ajudam a investigar saída silenciosa, mas não provam captura de abort nativo Tcl/Win32.
- `crash.log` não tem rotação; `sysmon.log` usa descarte completo acima do limite, não arquivo histórico.
- Defaults inválidos no config não são saneados; converter fonte/intervalo/posição pode falhar.
