# SysMonitor

Widget leve de monitoramento de sistema (substituto do TrafficMonitor),
feito para funcionar com o Memory Integrity / Core Isolation (HVCI) do
Windows LIGADO — sem precisar de driver de kernel não assinado.

## Como funciona

- Rede (upload/download), CPU % e memória % vêm do `psutil`
  (contadores nativos do Windows, sem driver nenhum).
- Uso/temperatura da GPU vêm do NVML da NVIDIA (`nvml.dll`, instalado
  junto com o driver), lido via ctypes em `sensors.py`.
- Temperatura da CPU vem do servidor web local do LibreHardwareMonitor
  (`http://127.0.0.1:8085/data.json`). O LHM lê o sensor do Ryzen pelo
  driver PawnIO, que é ASSINADO e funciona com HVCI ativo.
- Se alguma leitura falhar, o widget mostra "--" no campo e um ⚠
  discreto, em vez de travar (era esse o bug original do
  TrafficMonitor: ele quebrava com exceção não tratada quando o índice
  do sensor mudava).
- Antes era usado o HWiNFO64, mas na versão Free a Shared Memory
  desliga sozinha depois de 12 horas (o ⚠ aparecia por isso).

## Pré-requisitos

1. Driver NVIDIA instalado (traz o `nvml.dll`).
2. LibreHardwareMonitor + PawnIO:
   `winget install LibreHardwareMonitor.LibreHardwareMonitor`
   (instala o PawnIO como dependência).
3. No LHM: Options → Remote Web Server → Run (porta 8085),
   Start Minimized, Minimize To Tray, Minimize On Close e
   Run On Windows Startup. Ele precisa rodar como admin (a tarefa
   de inicialização que ele cria já faz isso).

## Rodando

```
cd D:\dev\pc\SysMonitor
python3 sys_monitor.py
```

Para rodar sem a janela de console (recomendado no dia a dia), use
`pythonw.exe` no lugar de `python3.exe`/`python.exe`:

```
pythonw.exe sys_monitor.py
```

## Configuração

`config.ini` (criado automaticamente na primeira execução) permite
ajustar: posição da janela, opacidade, cores, tamanho de fonte e
intervalo de atualização. A posição também é salva automaticamente
quando você arrasta o widget.

## Iniciar com o Windows (opcional)

Rode uma vez:

```
python3 create_shortcut.py
```

Isso cria um atalho em `shell:startup` que inicia o SysMonitor junto
com o login do Windows. Para desativar, apague o atalho
`SysMonitor.lnk` da pasta de inicialização
(`Win+R` → `shell:startup`).

## Arquivos

- `sys_monitor.py` — janela/GUI (tkinter) e loop de coleta.
- `sensors.py` — leitura de GPU (NVML) e temperatura da CPU (LHM);
  `python sensors.py` mostra os valores atuais para teste.
- `create_shortcut.py` — cria atalhos de Menu Iniciar e de
  inicialização automática.
- `config.ini` — configurações do usuário (gerado automaticamente).

## Limitações conhecidas

- Depende do LibreHardwareMonitor estar rodando para a temperatura
  da CPU (o Windows não expõe esse sensor sem driver nesta placa).
- Não mostra gráfico histórico (só o valor atual), diferente do
  TrafficMonitor. Pode ser adicionado depois se você quiser.
- Testado em um sistema com CPU AMD Ryzen 7 5700 + GPU NVIDIA
  RTX 4060. A CPU usa o sensor `Core (Tctl/Tdie)` do LHM (com
  `CPU Package` como alternativa para Intel); a GPU usa a primeira
  placa NVIDIA.
