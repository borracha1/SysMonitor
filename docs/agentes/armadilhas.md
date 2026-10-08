Atualizado em 2026-10-07 (commit 7400f35)

# Armadilhas e decisões
| Problema / decisão | Causa e regra para não repetir | Fonte |
|---|---|---|
| HWiNFO Free perde sensores após 12 h | Shared Memory desliga; migração para NVML + LHM/PawnIO, sem limite equivalente documentado | `sensors.py`, commit 7400f35 |
| TrafficMonitor falhava ao mudar índice de sensor | Tratar ausência como `None`/`--` e aviso, não exceção fatal | `README.md`, `SensorReader` |
| Janela topmost não fica dentro da barra Win11 | Explorer ganha composição na área da barra; usar filho via SetParent ou ícones reais | `sys_monitor.py`, `tray_monitor.py` |
| Widget some mesmo com topmost | Z-order da faixa topmost muda; reafirmar SetWindowPos nos ticks | `_reassert_topmost()` |
| Primeiro SetParent parecia falhar | Coordenadas são relativas ao pai; y de tela coloca filho fora da barra | `TaskbarEmbedder.reposition()` |
| Filho fica coberto pela ponte XAML | Reaplicar WS_EX_LAYERED DEPOIS de SetParent; não usar Tk alpha/topmost no modo taskbar | `TaskbarEmbedder.embed()` |
| Preto puro quebra menu no tema escuro | Cor-chave é #010101; clicar no texto, não no fundo transparente | `EMBED_KEY_COLOR`, comentário do embedding |
| GUI pode travar Explorer | Pai/filho entre processos compartilham filas de input; I/O lento deve ficar no Collector | `sys_monitor.py` |
| pythonw não pinta janela alpha neste PC | Código escolhe python.exe e oculta console; README diverge | `hide_console_window()`, `create_shortcut.py` |
| Tcl aborta após reconstruir janela | GC pode liberar antigo tk.Tk em thread errada; raiz única e Toplevel por janela | `MonitorWindow` docstring |
| Atalho inicia antes de Explorer | Esperar barra por até 60 s e usar fallback docked; não desistir imediatamente | `main()` |
| Handle 64 bits truncado por ctypes | Declarar argtypes/restype adequados; implementação existente não garante cobertura de toda API | `tray_monitor.py`, `_u32` |
| Texto GDI transparente/invisível | Desenho não preenche alpha; usar max(R,G,B) para cobertura | `make_text_icon()` |
| Clique esquerdo encerra por acidente | Left-click intencionalmente sem ação; saída só pelo menu direito | `wnd_proc()`, `show_exit_menu()` |

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
