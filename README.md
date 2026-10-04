# SysMonitor

Widget leve de monitoramento de sistema (substituto do TrafficMonitor),
feito para funcionar com o Memory Integrity / Core Isolation (HVCI) do
Windows LIGADO — sem precisar de driver de kernel não assinado.

## Como funciona

- Rede (upload/download), CPU % e memória % vêm do `psutil`
  (contadores nativos do Windows, sem driver nenhum).
- Temperatura da CPU e uso/temperatura da GPU vêm da memória
  compartilhada do HWiNFO64 (`Global\HWiNFO_SENS_SM2`), lida via ctypes
  em `hwinfo_reader.py`. O HWiNFO64 usa um driver de kernel ASSINADO
  digitalmente, então funciona mesmo com HVCI ativo.
- Se o HWiNFO64 não estiver rodando, o widget mostra "--" nos campos
  de temperatura/GPU e um aviso discreto, em vez de travar (era esse
  o bug original do TrafficMonitor: ele quebrava com exceção não
  tratada quando o índice do sensor mudava).

## Pré-requisitos

1. HWiNFO64 (Free) instalado — já está em
   `C:\Program Files\HWiNFO64\HWiNFO64.EXE`.
2. No HWiNFO64: menu de configurações (ícone de engrenagem) →
   marcar "Shared Memory Support" (ou garantir que
   `C:\Program Files\HWiNFO64\HWiNFO64.INI` tem `SensorsSM=1` na
   seção `[Settings]`).
3. Deixar o HWiNFO64 aberto (pode ficar minimizado/na bandeja).
   A versão Free não aceita o parâmetro `-s` (isso é exclusivo do
   HWiNFO Pro pago) — então ele precisa estar com a janela normal
   aberta, mesmo que minimizada.

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
- `hwinfo_reader.py` — leitor standalone da memória compartilhada do
  HWiNFO64 (pode ser reusado em outros scripts).
- `create_shortcut.py` — cria atalhos de Menu Iniciar e de
  inicialização automática.
- `config.ini` — configurações do usuário (gerado automaticamente).

## Limitações conhecidas

- Depende do HWiNFO64 estar rodando para temperatura de CPU/GPU
  (não tem workaround sem ele, dado o bloqueio do HVCI a drivers
  não assinados).
- Não mostra gráfico histórico (só o valor atual), diferente do
  TrafficMonitor. Pode ser adicionado depois se você quiser.
- Testado em um sistema com CPU AMD Ryzen 7 5700 + GPU NVIDIA
  RTX 4060. Os rótulos de sensores (`CPU (Tctl/Tdie)`, `Temperatura
  GPU`, `Carga do núcleo da GPU`) podem variar em outros hardwares;
  o código busca por padrões em português e inglês, mas pode
  precisar de ajuste fino se os nomes dos sensores forem diferentes.
