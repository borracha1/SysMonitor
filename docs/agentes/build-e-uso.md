Atualizado em 2026-10-07 (commit 7400f35)

# Execução, configuração e verificação
## Ambiente
- Windows com Python/Tkinter; sintaxe requer Python ≥3.10 (`str | None`).
- Dependência de execução: `psutil`; atalhos precisam também de `winshell` e `win32com` (pywin32).
- Sensores usam stdlib (`ctypes`, `urllib.request`, `json`), não pacote Python NVML.
- Não há requirements.txt, pyproject.toml, lockfile, versão fixada ou script de empacotamento.
- Versões de Python e bibliotecas efetivamente usadas na implantação: (a confirmar).
- Driver NVIDIA fornece nvml.dll; LHM + PawnIO fornece temperatura CPU com HVCI ativo.
- README orienta instalação por `winget install LibreHardwareMonitor.LibreHardwareMonitor`.
- No LHM: Remote Web Server → Run; Start Minimized, Minimize To Tray, Minimize On Close e Run On Windows Startup.
- README diz que a tarefa de inicialização do LHM já executa como admin; configuração real: (a confirmar).

## Comandos a partir da raiz
```text
python3 sys_monitor.py
python3 tray_monitor.py
python3 sensors.py
python3 create_shortcut.py
```
- Use intérprete que possua as dependências; nome `python3` segue README, não garante versão local.
- Prefira python.exe regular para o widget: ele oculta o console; pythonw tem falha de pintura descrita no código.
- README recomenda pythonw.exe, mas diverge de `sys_monitor.py` e `create_shortcut.py`; README foi preservado.

## Atalhos e inicialização
- `create_shortcut.py` cria SEMPRE dois atalhos `SysMonitor.lnk`: Menu Iniciar/Programs e Startup do usuário.
- Apesar do nome `PYTHONW`, usa `sys.executable`, não substitui por pythonw.exe.
- Argumento é caminho entre aspas de `sys_monitor.py`; WorkingDirectory é a pasta do projeto.
- WindowStyle=7 inicia minimizado; widget esconde o console.
- Não cria atalho da edição de bandeja; não presumir que ela seja o destino do Startup.
- Para desativar autostart: remover SysMonitor.lnk de `shell:startup` (README).

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
