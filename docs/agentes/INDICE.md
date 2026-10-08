Atualizado em 2026-10-07 (branch main, commit 7400f35)

# SysMonitor · entrada para agentes
Monitor local de rede, CPU, GPU e memória para usuários de Windows com HVCI ativo.
Há widget Tkinter integrado à barra e alternativa de três ícones na bandeja.
Stack: Python 3 (mínimo sintático 3.10), Tkinter, psutil, ctypes/Win32, NVML e LHM/PawnIO.
Versões instaladas de bibliotecas e sensores: (a confirmar); não há manifesto com versões.

## Comandos (para tarefas futuras; não executados nesta documentação)
```text
python3 sys_monitor.py
python3 tray_monitor.py
python3 sensors.py
python3 create_shortcut.py
```
Não há suíte automatizada nem comando de build no repositório.

## Estado
Sem versão formal declarada. Branch `main`; base de código `7400f35`.
Última mudança funcional: migração HWiNFO → NVML/LHM; detalhes em [estado.md](estado.md).

## Se a tarefa mexe em… leia…
| Se a tarefa mexe em… | Leia |
|---|---|
| módulos, fluxo de dados, concorrência ou armazenamento | [arquitetura.md](arquitetura.md) |
| coleta, GPU, temperatura da CPU, falhas de sensores | [sensores-coleta.md](sensores-coleta.md) |
| widget, barra de tarefas, bandeja, renderização | [interface.md](interface.md) e [armadilhas.md](armadilhas.md) |
| execução, dependências, atalhos, configuração, testes | [build-e-uso.md](build-e-uso.md) |
| sumiço, travamento, Explorer, ctypes ou regressão | [armadilhas.md](armadilhas.md) |
| histórico, limitações, pendências ou versão | [estado.md](estado.md) |

## Regras invioláveis
- Não mudar branch, commitar, publicar, criar tag ou release sem autorização explícita.
- Preservar compatibilidade com HVCI e manter o aplicativo sem privilégio elevado.
- Não copiar segredos; registrar só localização. Não incluir logs, cache ou backup em commits.
- `config.ini` já está rastreado; não alterar configuração local fora do escopo.
- Atualizar cabeçalhos, estado e áreas tocadas ao fechar marcos.

## Histórico e referências
- [README existente](../../README.md) (há divergências documentadas em build-e-uso).
- [Estado e marcos Git](estado.md); `git log` é o histórico técnico disponível.
- Não existem specs, planos, changelog ou `docs/superpowers/` nesta base.
