Atualizado em 2026-10-21 (branch main; automático mostra grupo com perda; commit "perda de pacotes por grupo IPv4/IPv6")

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

## Marco 2026-10-20 · perda de pacotes
- `ping_monitor.py` coleta todos os destinos por ciclo, padrão `8.8.8.8`, `1.1.1.1`, com janela independente por IP e contrato `Metrics.ping` nas duas entradas.
- Taskbar/docked: duas linhas sempre visíveis, com IP, perda e RTT; floating: uma linha por alvo. Cor de problema individual, largura medida pela fonte; `enabled=false` esconde a coluna. Tooltip da bandeja por IP, limitado ao buffer do Shell.
- Alertas preservados: somente falha de todos os destinos conta como indisponibilidade; toast inclui perdas individuais. Ver [sensores-coleta.md](sensores-coleta.md).
- Testes stdlib escritos e executados primeiro em vermelho; validação final: `py -3.12 -m unittest discover -s tests -v`, `py_compile` das quatro fontes e ICMP real sem abrir o widget. Widget reiniciado em 20/10 22h48 (Python 3.12 da Store): barra mostra `8.8.8.8 0% 31ms` / `1.1.1.1 0% 13ms`; falta o teste real do Mateus. Sem commit.

## Marco 2026-10-20 · grupos IPv4/IPv6 e troca por perda
- Editor reformulado: `Configurar destinos…`, quatro campos separados por família e preferido no automático; validação pura identifica campo/família, rejeita duplicados, total vazio e preferido vazio. Menu com rádios Automático/Só IPv4/Só IPv6, grupos vazios desabilitados.
- Config nova: `targets_v4`, `targets_v6`, `mode`, `preferred`, `return_clean_cycles=60`; compatibilidade com `targets` antiga antes da aplicação de defaults. Persistência seletiva/atômica em `save_ping_settings`, removendo chave antiga sem despejar defaults.
- Coleta continua nos dois grupos mesmo no manual; seleção automática mostra o outro grupo com perda atual se o exibido respondeu por completo, e retorna ao preferido após a sequência limpa do grupo exibido. Trocas geram log/toast e preservam janelas. Queda exige falha de todos os IPs de todos os grupos. Coleta sequencial mantida (~4 s no pior caso com quatro timeouts).
- `set_mode` e `set_groups` protegidos por lock/geração; modo preserva histórico, grupos zeram histórico/alertas e publicam placeholders. Se edição remover a família manual atual, o modo acompanha a família restante e é persistido.
- Contrato nas duas classes Metrics/snapshot: `ping` ativo, `ping_family`, `ping_auto`, `ping_other`. Barra/docked/floating mostram só ativo com marcador separado, duas linhas alinhadas em pixels e largura reservada somente pelo grupo ativo (marcador + pior IP, RTT reservado de 1000 ms ou timeout configurado maior). Troca de família refaz o layout no lugar, sem reconstruir; editar grupos reconstrói imediatamente. Bandeja mostra ativo antes do inativo e prioriza ativo no limite de 127 caracteres.
- TDD: novos testes de grupos executados primeiro em vermelho; suíte final `py -3.12 -m unittest discover -s tests -v`: 43 testes, 0,266 s, OK. `py -3.12 -m py_compile` aprovado para todas as sete fontes da raiz. Sem commit/branch/push.
- Teste anterior em Tk com janelas ocultas confirmou alinhamento e ausência de sobreposição no IPv6, mas não verificou espaçamento justo no IPv4; suas larguras medidas antes desta correção não são referência para o layout atual. Conferência interativa posterior no Explorer/DPI do usuário continua pendente.
- Correção em 2026-10-21 deste marco: vão excessivo entre ping IPv4 e CPU causado pela reserva de IPs inativos. Regressão escrita antes da correção: `test_ping_column_width_follows_active_group` falhou com `AssertionError: 222 != 144` (fonte falsa de 6 px/caractere). Agora usa apenas grupo ativo e timeout realista; `_update_labels` detecta mudança de família e ajusta taskbar/docked/floating sem reconstrução, sem novo embedding e sem relayout a cada tick. Família inicial usa a mesma função pura no monitor e widget.
- Validação da correção: regressão aprovada; `py -3.12 -m unittest discover -s tests -v`: 48 testes em 0,389 s, OK. `py -3.12 -m py_compile` aprovado para todas as sete fontes `.py` da raiz. Fakes cobrem ida/volta entre famílias, gap exato de 10 px, alinhamento, timeout maior, família inicial e ausência de reconstrução. Diff atual de `config.ini` preservado exatamente como encontrado (chaves dos grupos, modo auto e preferido IPv4); sem reiniciar widget, commit, troca de branch ou push.
- Ping ICMP real isolado ~6 s, quatro padrões em auto, notificações desativadas: `ping=(('8.8.8.8', 0.0, 33.0, True), ('1.1.1.1', 0.0, 14.0, True))`; `ping_family=ipv4`, `ping_auto=True`; `ping_other=(('2001:4860:4860::8888', 0.0, 37.0, True), ('2606:4700:4700::1111', 0.0, 37.0, True))`. Thread encerrada com join.
- Correção em 2026-10-21 deste marco (automático): regra anterior fazia failover para o grupo limpo e ocultava perda no grupo inativo. Regressão `test_auto_shows_group_with_loss` escrita/executada antes da correção: `AssertionError: 'ipv4' != 'ipv6'` (1 teste, 0,001 s, FAILED). Agora qualquer falha atual do outro grupo com o exibido limpo seleciona o grupo com perda; perda nos dois mantém a seleção. Retorno usa 60 ciclos limpos consecutivos do grupo exibido, não do preferido, com prioridade para mostrar perda. Removido o limiar antigo de troca do construtor, configuração, defaults e documentação; janelas e relayout preservados.
- Validação desta correção: regressão isolada passou; `py -3.12 -m unittest discover -s tests -v`: 54 testes em 0,422 s, OK. `py -3.12 -m py_compile` aprovado para todas as sete fontes `.py` da raiz. Casos cobrem 59/60 ciclos, reset por falha, perda simultânea, prioridade sobre retorno, manual, grupos vazios, histórico e mensagens com IPs/tempo. Testes antigos de failover foram substituídos/adaptados à seleção por perda, sem remover cobertura de alertas globais, persistência ou layout. `config.ini` e seu diff foram comparados com o início e permanecem idênticos; sem reiniciar widget, commit, troca de branch ou push. Ativação no widget existente aguarda reinício manual autorizado.
- Fechamento 2026-10-21: widget reiniciado com a versão final; Mateus testou com regra no roteador descartando `2001:4860:4860::8888` → automático passou de IPv4 para IPv6 sozinho, linha em vermelho `100% --ms`, coluna ajustada sem vão. Commit `9ccd25a` na `main`, push feito pelo Mateus em 21/10. `config.ini` fica fora do commit: é a configuração local dele; os padrões estão em `DEFAULTS`.

## Limitações e próximos passos
- Sem histórico/gráficos; README menciona gráfico como possibilidade, não compromisso.
- Temperatura CPU depende de LHM em execução; GPU atende apenas primeira NVIDIA.
- Suíte `unittest` para ping; sem manifesto de dependências ou build distribuível.
- Nenhuma tarefa funcional em andamento está registrada no repositório consultado.
- Pendências de verificação remanescentes: uso efetivo da edição de bandeja; o que já foi confirmado está em `Verificações de 2026-10-08`.
- Confirmar manualmente comportamento da bandeja após restart de Explorer; código não implementa re-registro.
- Riscos de coleta/concorrência estão em [armadilhas.md](armadilhas.md); não foram corrigidos nesta tarefa só de documentação.

## Manutenção
- Ao fechar marco: atualizar este estado, cabeçalhos e áreas alteradas com o commit de código de referência.
- Cabeçalhos desta entrega referem-se à base funcional estudada, não ao commit posterior que adiciona a documentação.
- Delegações devem indicar o índice e somente os arquivos de área necessários.
