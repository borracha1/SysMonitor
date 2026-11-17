Atualizado em 2026-11-16 (1.2.0 local: discos)

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
Versão 1.1.0 (`version.py`) publicada em 2026-11-14: `main` = `versao-1.1`, tag `v1.1.0`, release oficial (Latest), aprovada pelo Mateus após teste real.
Inclui a 1.0.3 (avisos por família), o histórico (5/15 min/1 h/4 h, zoom, seleção com resumo, filtro), duas janelas abertas pelo clique no widget (Tráfego; Latência e perda, com uma linha por IP e faixas de perda; CSV de 11 colunas, lê 7 e 9) e o top 3 de programas por CPU e por memória em tooltip do widget e da bandeja. 480 testes OK. Pendências: assinatura de código; `pip-audit` limpo (2026-11-14). Detalhes em [estado.md](estado.md).

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
| discos: coluna do widget, janela Discos, E/S por processo | [interface.md](interface.md), [arquitetura.md](arquitetura.md), [sensores-coleta.md](sensores-coleta.md) e [telas.md](telas.md) |
| tooltip do top 3 de CPU/MEM (widget e bandeja) | [interface.md](interface.md), [arquitetura.md](arquitetura.md) e [armadilhas.md](armadilhas.md) |

## Versão 1.2.0 (publicada)
Discos (coluna no widget, janela `SysMonitor · Discos`, top 3 por E/S) publicada em 2026-11-16: `main` = `versao-1.2`, tag `v1.2.0`, release oficial (Latest). Inclui a 1.1.1. `version.py` = 1.2.0.

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
