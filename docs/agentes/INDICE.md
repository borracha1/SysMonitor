Atualizado em 2026-11-06 (1.1.0 na versao-1.1, commits locais, sem push; Latest v1.0.1)

# SysMonitor · entrada para agentes
Monitor local de rede, CPU, GPU e memória para usuários de Windows com HVCI ativo.
Há widget Tkinter integrado à barra e alternativa de três ícones na bandeja.
Stack: Python 3 (mínimo sintático 3.10), Tkinter, psutil, ctypes/Win32, NVML e LHM/PawnIO.
Versões verificadas em 2026-10-08: Python 3.14, LibreHardwareMonitor 0.9.6, PawnIO 2.2.0.0; não há manifesto com versões.

## Comandos (para tarefas futuras; não executados nesta documentação)
```text
python3 sys_monitor.py
python3 tray_monitor.py
python3 sensors.py
python3 create_shortcut.py
```
Testes automatizados (stdlib, na raiz): `py -3.12 -m unittest discover -s tests -v`. Build do exe e do instalador: `powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1` (ver build-e-uso.md).

## Estado
Versão 1.0.3 (`version.py`) na `versao-1.0.3`, commit local `03a76ec`, sem push; instalada e testada pelo Mateus em 2026-11-06 (menu e gravação ok; reabertura não conferida). 1.0.2 publicada na `main` em `062332f` (2026-11-04), sem tag nem release; a Latest continua `v1.0.1`.
Última mudança local: versão 1.1.0 na `versao-1.1`, histórico de tráfego estimado por família, CSV local de 4 h e janela 1 h/4 h por clique/menu. TDD nas cinco tarefas, 273 testes OK e `--verificar` código 0; sem build nem reinício do widget. Revisão/instalador pelo Claude e teste real do Mateus pendentes. As preferências de toast por família e silêncio por IP da 1.0.3 permanecem. Motivo real da recusa de HWND e Kbps no canto continuam sem causa conhecida. Detalhes e verificações em [estado.md](estado.md).

## Se a tarefa mexe em… leia…
| Se a tarefa mexe em… | Leia |
|---|---|
| como as telas estão hoje (capturas com legenda) | [telas.md](telas.md) |
| módulos, fluxo de dados, concorrência ou armazenamento | [arquitetura.md](arquitetura.md) |
| coleta, GPU, temperatura da CPU, falhas de sensores | [sensores-coleta.md](sensores-coleta.md) |
| widget, barra de tarefas, bandeja, renderização | [interface.md](interface.md) e [armadilhas.md](armadilhas.md) |
| execução, dependências, atalhos, configuração, testes, build do exe/instalador | [build-e-uso.md](build-e-uso.md) |
| sumiço, travamento, Explorer, ctypes ou regressão | [armadilhas.md](armadilhas.md) |
| histórico, limitações, pendências ou versão | [estado.md](estado.md) |

## Regras invioláveis
- Não mudar branch, commitar, publicar, criar tag ou release sem autorização explícita.
- Preservar compatibilidade com HVCI e manter o aplicativo sem privilégio elevado.
- Não copiar segredos; registrar só localização. Não incluir logs, cache ou backup em commits.
- `config.ini` já está rastreado; não alterar configuração local fora do escopo.
- Atualizar cabeçalhos, estado e áreas tocadas ao fechar marcos.

## Histórico e referências
- [README existente](../../README.md); a divergência sobre `pythonw.exe` foi corrigida em 2026-10-08.
- [Estado e marcos Git](estado.md); `git log` é o histórico técnico disponível.
- Specs e planos em `docs/superpowers/` (exe e instalador 1.0.0: 2026-10-26).
