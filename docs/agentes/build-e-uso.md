Atualizado em 2026-10-27 (branch versao-1.0; exe e instalador 1.0.0 gerados, sem teste real)

# Execução, configuração e verificação
## Ambiente
- Windows com Python/Tkinter; sintaxe requer Python ≥3.10 (`str | None`).
- Dependências: `psutil` e `comtypes` para detectar o espaço livre da barra por UI Automation. Instalação no Python Store do widget: `py -3.12 -m pip install --user comtypes` (validado com 1.4.17). Sem comtypes/UIA funcional, registra uma vez e usa posicionamento original; não exige admin nem driver e mantém compatibilidade HVCI.
- Dependência de execução: `psutil`; atalhos precisam também de `winshell` e `win32com` (pywin32).
- Sensores usam stdlib (`ctypes`, `urllib.request`, `json`), não pacote Python NVML.
- Não há requirements.txt, pyproject.toml, lockfile, versão fixada ou script de empacotamento.
- Versões verificadas em 2026-10-08: `python` = Python 3.14 (`C:\Python314\python.exe`), com o qual `sensors.py` roda; `python3` resolve para o alias do WindowsApps, não validado.
- Sensores de terceiros instalados: LibreHardwareMonitor 0.9.6 (winget) e PawnIO 2.2.0.0.
- Driver NVIDIA fornece nvml.dll; LHM + PawnIO fornece temperatura CPU com HVCI ativo.
- README orienta instalação por `winget install LibreHardwareMonitor.LibreHardwareMonitor`.
- No LHM: Remote Web Server → Run; Start Minimized, Minimize To Tray, Minimize On Close e Run On Windows Startup.
- Tarefa agendada `\LibreHardwareMonitor` confirmada em 2026-10-08: `RunLevel=Highest` (elevada), `UserId=mateu`, `LogonType=Interactive`. É ela que inicia o LHM e supre o requisito de admin descrito no README.

## Comandos a partir da raiz
```text
python3 sys_monitor.py
python3 tray_monitor.py
python3 sensors.py
python3 create_shortcut.py
```
- Use intérprete que possua as dependências; nome `python3` segue README, não garante versão local.
- Prefira python.exe regular para o widget: ele oculta o console; pythonw tem falha de pintura descrita no código.
- README recomendava pythonw.exe, divergindo de `sys_monitor.py` e `create_shortcut.py`; corrigido em 2026-10-08 para recomendar python.exe.

## Atalhos e inicialização
- `create_shortcut.py` cria SEMPRE dois atalhos `SysMonitor.lnk`: Menu Iniciar/Programs e Startup do usuário.
- Apesar do nome `PYTHONW`, usa `sys.executable`, não substitui por pythonw.exe.
- Argumento é caminho entre aspas de `sys_monitor.py`; WorkingDirectory é a pasta do projeto.
- WindowStyle=7 inicia minimizado; widget esconde o console.
- Não cria atalho da edição de bandeja; não presumir que ela seja o destino do Startup.
- Para desativar autostart: remover SysMonitor.lnk de `shell:startup` (README).
- Confirmado em 2026-10-08: `SysMonitor.lnk` presente na pasta Startup do usuário, com autostart ativo.

## Configuração do widget
- `load_config()` mescla `DEFAULTS` com `[window]` de `config.ini` em UTF-8; cria arquivo se faltar.
- Defaults: taskbar; x/y=auto; opacity=0.95; always_on_top=true; font_size=8.
- Cores: bg_color, fg_color, accent_up, accent_down; update_interval_ms=1000.
- `[window] net_split=false` é o novo default, sem regravar arquivos existentes na carga. Menu `Separar IPv4/IPv6 (estimado)` persiste só esta chave pelo mesmo gravador seletivo/atômico do ping. Erro mantém preferência anterior e registra log; não grava defaults nem remove ping legado. Usa proporções de pacotes para estimar bytes por família, portanto não equivale a medição real de bytes IPv4/IPv6. GetIpStatisticsEx dispensa admin/driver; API indisponível mostra total original.
- Docked: taskbar_width=220 e docked_height=36; taskbar calcula largura pela fonte.
- Opacidade, fundo e topmost se aplicam a docked/floating; x/y somente a floating.
- Arraste regrava configuração completa; entradas numéricas/booleanas não têm validação dedicada.
- Valores atuais do arquivo local não foram reproduzidos nem alterados nesta tarefa.

## Limites de uso, temperatura e cores em [usage_limits]
- Uso: `cpu_low`, `cpu_warning`, `cpu_high`, `gpu_low`, `gpu_warning`, `gpu_high`, `mem_low`, `mem_warning`, `mem_high`. Defaults 50/75/90 por métrica; regra `0 ≤ Low < Warning < High ≤ 100`.
- Temperatura: `cpu_temp_low`, `cpu_temp_warning`, `cpu_temp_high`, `gpu_temp_low`, `gpu_temp_warning`, `gpu_temp_high`. Defaults 60/75/85 °C por linha; regra `0 ≤ Low < Warning < High ≤ 120`. MEM não tem temperatura.
- Cores globais: `low_color=#5fb0ff`, `warning_color=#ff9d5f`, `high_color=#ff6b6b`. Formato estrito `#rrggbb`, aceita letras maiúsculas; nomes e forma curta são inválidos. Mesmas cores para todas as métricas e temperaturas. Prevalece o maior limite atingido; abaixo de Low ou leitura ausente, cor normal.
- Números finitos, decimais com ponto. Carga inválida volta ao default somente da linha/cor correspondente, sem reescrever o arquivo. `load_limits` preserva o contrato antigo de uso; `load_preferences` inclui temperaturas e cores.
- Editor valida quinze campos e três cores; grava seletivamente via `ping_config.save_settings`: temporário no mesmo diretório, flush/fsync e os.replace, preservando outras seções e chaves. API `save_limits` também aceita só as linhas desejadas. Publicação somente após persistência bem-sucedida. Cancelar, erro ou Restaurar cores padrão não gravam/aplicam nada antes de Salvar.
- Widget mostra uso e temperatura com cores independentes nos três modos, sem ampliar a coluna embutida; bandeja colore ambas as linhas CPU/GPU, fallback MEM mantém segunda linha branca. Sem pacotes/driver/elevação novos.
- Verificação 2026-10-25 no PowerShell sem TMPDIR: 114 testes em 10,995 s, OK (também 114 em 9,831 s pelo bash); seis casos novos focados em 2,800 s, OK; `py_compile` de 25 fontes, OK. Captura Tk real isolada com PowerShell/System.Drawing. Configuração local preservada por SHA-256. Pendente conferência do Mateus após reinício manual autorizado.

## Opções de silêncio em [ping]
- `mute_after_alerts=5`: quantidade de assuntos de toasts de PERDA por IP para silenciar. `0` desliga o recurso.
- `mute_window_s=120`: janela móvel em segundos (limite inclusivo). Conta avisos de troca por perda e de perda global, inclusive omitidos pelo silêncio; o cooldown global existente continua valendo, e eventos impedidos por cooldown/notify=false não são candidatos a toast.
- `unmute_after_s=1800`: tempo sem NENHUMA resposta falha daquele IP para reativar; uma falha reinicia a espera, mesmo no grupo inativo. Reativação limpa o histórico daquele IP; set_groups limpa todos. Estado em memória, sem persistência de silêncio.
- Defaults declarados em sys_monitor.py e lidos em PingMonitor.from_config, compartilhado pelo widget e pela edição de bandeja. Config existente recebe defaults apenas em memória: o config.ini local não foi alterado nesta tarefa. Sem nova dependência, privilégio ou driver.

## Testes e build
- Suíte automatizada stdlib: `py -3.12 -m unittest discover -s tests -v` (na raiz, sem instalar pytest). Cobre coleta por destino, janela, alertas, recuperação e formatação. Usar `py -3.12`: é o Python do widget (Store) e o único com `psutil`; o `python` do PATH (3.14) não tem.
- Compilação sintática: `py -3.12 -m py_compile` com todas as fontes `.py` da raiz (inclusive `ping_config.py`).
- Suíte também cobre grupos por família/migração legada, troca/retorno/geração, persistência atômica, editor de quatro campos, marcadores, rádios e alinhamento/largura estável. Testes usam mocks/AST para não abrir o widget nem importar entradas Win32.
- Sem CI. Build do exe e do instalador: ver "Exe e instalador (1.0.0)" abaixo.
- Verificação 2026-10-21: 62 testes aprovados (2,878 s), incluindo regressão Win32 com WindowFromPoint em pai Tk isolado, coleta/divisão/persistência/falha e três modos em Tk real. `py_compile`: 16 fontes (raiz + testes), OK. Leitura real GetIpStatisticsEx IPv4/IPv6 aprovada sem elevação. Nenhum teste usa a barra real ou grava o config.ini local; pendente conferência manual do Mateus.
- Verificação tarefa A (2026-10-21): suíte completa com 73 testes em 3,513 s, OK; py_compile de 18 fontes (raiz + testes), OK; git diff --check, OK. Regressão 1920 escrita antes da produção falhou com widget [1087,1574] cobrindo ícones [668,1253] e passou após correção. Novos testes cobrem política/níveis, integração Win32/Tk isolada, snapshots e falhas UIA. Leitura UIA real do monitor principal aprovada sem elevação, sem reiniciar o widget; pendente teste visual do Mateus no monitor menor. Config local preservado por comparação SHA-256.
- Diagnóstico existente: `python3 sensors.py`; as duas entradas devem ser verificadas manualmente em Windows.
- Roteiro futuro: sensores com/sem LHM; GPU indisponível; três modos do widget; arraste/persistência; menu Fechar.
- Verificar boot, instância repetida, Start aberto, DPI/monitor e recuperação após reiniciar Explorer.
- Bandeja: conferir três ícones, fallback MEM, tooltips, clique esquerdo inofensivo e limpeza ao sair.
- Nenhum aplicativo, teste de sensores, build ou instalação foi executado na tarefa de documentação.
- Executado em 2026-10-08, em verificação de documentação: `python sensors.py` devolveu GPU `(52.0, 31.0)` e CPU `69.8`, confirmando NVML e LHM funcionais. O widget em si não foi aberto.

## Exe e instalador (1.0.0)
- Spec e plano: `docs/superpowers/specs/2026-10-26-exe-instalador-design.md` e `docs/superpowers/plans/2026-10-26-exe-instalador.md`.
- `powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1` gera `dist/SysMonitor-Setup-<versão>.exe`; `-SomenteExe` para depois dos exes. Versão vem de `version.py`.
- Etapas: venv `.venv-build` com `py -3.12` (Tk 8.6; não usar `C:\Python314`, Tk 9.0) e `requirements-build.txt` fixado; pré-gera `comtypes.gen` da UIA; PyInstaller pelo `SysMonitor.spec` (pasta única, `SysMonitor.exe` + `SysMonitor-Bandeja.exe`, ambos com console que o código esconde); `--verificar` nos dois exes; baixa o LHM 0.9.6 (`LibreHardwareMonitor.zip`, .NET 4.7.2) com SHA-256 fixado para `build/lhm`; ISCC do Inno Setup 6 (winget, escopo do usuário) com `installer/SysMonitor.iss`.
- `--verificar` (nas duas entradas, `.py` ou exe): importa os módulos tardios, Tcl e (widget) a UIA, imprime versão, pasta de dados e se está congelado; sai 0 sem janela, mutex nem config. Não esconde o console.
- Pasta de dados (`app_paths.data_dir()`): modo `.py` = raiz do projeto (igual a antes); exe = `%APPDATA%\SysMonitor` (config.ini, crash.log, sysmon.log).
- Instalador (admin uma vez): baixa o PawnIO 2.2.0 do release oficial com SHA-256 e roda `-install -silent` se faltar; copia o LHM + `installer/LibreHardwareMonitor.config` e cria a tarefa `SysMonitor LHM` (via `installer/util-instalador.ps1`) se não houver LHM (8085 respondendo ou tarefa `\LibreHardwareMonitor`); grava `HKLM\Software\SysMonitor` (`Version`, `InstalledPawnIO`, `InstalledLHM`, `CreatedTask`), que o desinstalador usa para saber o que remover.
- `build/`, `dist/` e `.venv-build/` ficam fora do Git. Arquivos `.ps1` só ASCII; `.iss` e `LEIA-ME.txt` em UTF-8 com BOM.
- Verificação 2026-10-27: 147 testes OK; `build.ps1` completo saiu 0 (Inno 6.7.3); setup com 16.972.379 bytes, SHA-256 `07c6021ac770da1dc3e8e2b7432de72475db21ef6fa23d650e05e42719ae83d0`. Setup ainda não executado: teste real no Windows Sandbox pendente (roteiro no fim do plano).
