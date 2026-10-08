Atualizado em 2026-10-08 (commit 4b40627)

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
- Docked: taskbar_width=220 e docked_height=36; taskbar calcula largura pela fonte.
- Opacidade, fundo e topmost se aplicam a docked/floating; x/y somente a floating.
- Arraste regrava configuração completa; entradas numéricas/booleanas não têm validação dedicada.
- Valores atuais do arquivo local não foram reproduzidos nem alterados nesta tarefa.

## Testes e build
- Não há suíte automatizada, CI, instalador, distribuição binária nem comando de build no Git.
- Diagnóstico existente: `python3 sensors.py`; as duas entradas devem ser verificadas manualmente em Windows.
- Roteiro futuro: sensores com/sem LHM; GPU indisponível; três modos do widget; arraste/persistência; menu Fechar.
- Verificar boot, instância repetida, Start aberto, DPI/monitor e recuperação após reiniciar Explorer.
- Bandeja: conferir três ícones, fallback MEM, tooltips, clique esquerdo inofensivo e limpeza ao sair.
- Nenhum aplicativo, teste de sensores, build ou instalação foi executado na tarefa de documentação.
- Executado em 2026-10-08, em verificação de documentação: `python sensors.py` devolveu GPU `(52.0, 31.0)` e CPU `69.8`, confirmando NVML e LHM funcionais. O widget em si não foi aberto.
