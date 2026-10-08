Atualizado em 2026-10-08 (commit 4b40627)

# Estado e histórico
## Base documentada
- Branch: `main`; commit funcional: `7400f3565d89ede39041d2449301a8a7b70b8ff0`.
- Nenhuma versão formal declarada no código/documentação e nenhum mecanismo de release no repositório.
- Duas entradas coexistem: widget (`sys_monitor.py`) e ícones (`tray_monitor.py`).
- README e atalhos apontam para o widget; uso efetivo atual da edição de bandeja: (a confirmar).
- Não havia `CLAUDE.md` ou `AGENTS.md` antigo no diretório consultado nem nos arquivos rastreados.
- Portanto não há conteúdo antigo de CLAUDE.md a migrar.
- Criação de CLAUDE.md e AGENTS.md bloqueada pela proteção do ambiente, que exige aprovação interativa indisponível nesta execução.
- Entrega parcial: arquivos de área criados; pontos de entrada e commit aguardam resolução desse bloqueio.

## Marcos verificados no Git
| Commit | Data | Marco |
|---|---|---|
| `1764c9a` | 2026-10-04 | Base do widget compatível com HVCI, bandeja, coletor e atalhos |
| `7400f35` | 2026-10-05 | Troca HWiNFO por NVML/LHM; remove hwinfo_reader.py e create_hwinfo_startup.py |
| `5baf4ad` | 2026-10-07 | Documentação técnica por área para agentes |
| `4b40627` | 2026-10-07 | telas.md com capturas; publicado no GitHub em 2026-10-08 |
- Razão da migração: HWiNFO Free desliga Shared Memory após 12 horas.
- [README](../../README.md) relata teste em Ryzen 7 5700 + NVIDIA RTX 4060; não revalidado nesta tarefa.
- Histórico de decisões de interface também está nos comentários/docstrings do código, resumido em [armadilhas.md](armadilhas.md).
- Não há specs/planos em docs/superpowers, changelog ou LEIAME nesta base consultada.

## Verificações de 2026-10-08
- Tarefa agendada `\LibreHardwareMonitor` confirmada: `RunLevel=Highest` (elevada), `UserId=mateu`, `LogonType=Interactive`. Ela inicia o LHM e supre o requisito de admin citado no README.
- Config do LHM confirma `listenerPort=8085`, `runWebServerMenuItem`, `startMinMenuItem`, `minTrayMenuItem` e `minCloseMenuItem` ativos.
- `python sensors.py` executado com Python 3.14: GPU `(52.0, 31.0)`, CPU `69.8`. NVML e LHM funcionais de ponta a ponta.
- `SysMonitor.lnk` presente na pasta Startup do usuário; autostart do widget ativo.
- O LHM usa `HttpListener` sobre o http.sys, por isso o listener da porta 8085 aparece como PID 4 (System) no `netstat`; o processo real é `LibreHardwareMonitor` (sessão 1).
- HWiNFO64 8.54 permanece instalado em `C:\Program Files\HWiNFO64`, já sem uso pelo projeto.
- Correção publicada: o README recomendava `pythonw.exe`, que tem falha de pintura nesta máquina; passou a recomendar `python.exe`.

## Limitações e próximos passos
- Sem histórico/gráficos; README menciona gráfico como possibilidade, não compromisso.
- Temperatura CPU depende de LHM em execução; GPU atende apenas primeira NVIDIA.
- Sem testes automatizados, manifesto de dependências ou build distribuível.
- Nenhuma tarefa funcional em andamento está registrada no repositório consultado.
- Pendências de verificação remanescentes: uso efetivo da edição de bandeja; o que já foi confirmado está em `Verificações de 2026-10-08`.
- Confirmar manualmente comportamento da bandeja após restart de Explorer; código não implementa re-registro.
- Riscos de coleta/concorrência estão em [armadilhas.md](armadilhas.md); não foram corrigidos nesta tarefa só de documentação.

## Manutenção
- Ao fechar marco: atualizar este estado, cabeçalhos e áreas alteradas com o commit de código de referência.
- Cabeçalhos desta entrega referem-se à base funcional estudada, não ao commit posterior que adiciona a documentação.
- Delegações devem indicar o índice e somente os arquivos de área necessários.
