Atualizado em 2026-10-21 (branch main; menu em todo o widget e tráfego IPv4/IPv6 estimado; sem commit)

# Execução, configuração e verificação
## Ambiente
- Windows com Python/Tkinter; sintaxe requer Python ≥3.10 (`str | None`).
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

## Testes e build
- Suíte automatizada stdlib: `py -3.12 -m unittest discover -s tests -v` (na raiz, sem instalar pytest). Cobre coleta por destino, janela, alertas, recuperação e formatação. Usar `py -3.12`: é o Python do widget (Store) e o único com `psutil`; o `python` do PATH (3.14) não tem.
- Compilação sintática: `py -3.12 -m py_compile` com todas as fontes `.py` da raiz (inclusive `ping_config.py`).
- Suíte também cobre grupos por família/migração legada, troca/retorno/geração, persistência atômica, editor de quatro campos, marcadores, rádios e alinhamento/largura estável. Testes usam mocks/AST para não abrir o widget nem importar entradas Win32.
- Não há CI, instalador, distribuição binária nem comando de build no Git.
- Verificação 2026-10-21: 62 testes aprovados (2,878 s), incluindo regressão Win32 com WindowFromPoint em pai Tk isolado, coleta/divisão/persistência/falha e três modos em Tk real. `py_compile`: 16 fontes (raiz + testes), OK. Leitura real GetIpStatisticsEx IPv4/IPv6 aprovada sem elevação. Nenhum teste usa a barra real ou grava o config.ini local; pendente conferência manual do Mateus.
- Diagnóstico existente: `python3 sensors.py`; as duas entradas devem ser verificadas manualmente em Windows.
- Roteiro futuro: sensores com/sem LHM; GPU indisponível; três modos do widget; arraste/persistência; menu Fechar.
- Verificar boot, instância repetida, Start aberto, DPI/monitor e recuperação após reiniciar Explorer.
- Bandeja: conferir três ícones, fallback MEM, tooltips, clique esquerdo inofensivo e limpeza ao sair.
- Nenhum aplicativo, teste de sensores, build ou instalação foi executado na tarefa de documentação.
- Executado em 2026-10-08, em verificação de documentação: `python sensors.py` devolveu GPU `(52.0, 31.0)` e CPU `69.8`, confirmando NVML e LHM funcionais. O widget em si não foi aberto.
