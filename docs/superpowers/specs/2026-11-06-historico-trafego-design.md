# Histórico de tráfego por família (SysMonitor 1.1.0)

Data: 2026-11-06. Registro: `D:/dev/memoria-compartilhada/pedidos/2026-11-06-claude-sysmonitor-historico-trafego.md`.

## Objetivo
Ao clicar na parte v4 ou v6 da rede no widget, o Mateus vê um gráfico das últimas 1 h ou 4 h daquela família,
para descobrir quando houve picos e se as falhas de ping coincidiram com eles.

Pedido original: "quando eu clicar na parte do v4 ou v6 eu pode visualizar um histórico de 1h ou 4h do tráfego
de cada um. Pode ser numa janela aberta a parte se for muito complicado de fazer de outra forma."

## Decisões do Mateus
- Gráfico de download e upload ao longo do tempo, com as falhas de ping marcadas.
- Um gráfico por vez, abrindo na família clicada, com botões para trocar de família e de período.
- Marcas em duas intensidades: vermelho forte com todos os IPs da família sem resposta, vermelho claro com só um.
- O histórico sobrevive ao reinício: últimas 4 h em disco, num CSV gravado a cada minuto.

## Fora desta versão
Modo bandeja, valor ao passar o mouse, períodos maiores que 4 h, exportação, tempo de retenção configurável e
gráfico do tráfego total sem separação por família.

## Limitação conhecida
Os valores por família são estimados. O Windows sem admin só dá o total real de bytes, e `split_rates` divide esse
total pela proporção de pacotes de cada família. A janela diz "estimado" no título.

## Componentes
### `traffic_history.py` (novo, sem Tk)
- `TrafficHistory(path, log, clock=time.time)`: guarda os pontos, lê e grava o CSV. É a única peça que toca no arquivo.
  Tudo sob um lock, porque o gravador escreve de uma thread e a janela lê de outra.
- `TrafficRecorder(threading.Thread)`, daemon: a cada 1 s lê `metrics.net_rates`, pede as marcas ao ping e alimenta
  o histórico. Thread própria para que disco lento não atrase a coleta do widget nem a interface.
- Funções puras: acumular amostras num ponto de 5 s; `points(family, period_s, now)`; `build_chart(...)`, que
  devolve linhas, faixas e rótulos prontos para desenhar, sem tocar em Tk.

### `traffic_history_ui.py` (novo)
`TrafficHistoryWindow`: janela única do processo, que só desenha o resultado de `build_chart`.

### Alterações
- `ping_monitor.py`: `take_loss_marks()`. Devolve a pior marca de cada família desde a última chamada e zera o
  acumulado. A coleta dentro de `_record` é exata; ler `metrics.ping` a cada segundo poderia perder falhas,
  porque os dois ciclos não andam juntos. As marcas não dependem de `notify` nem de `notify_ipv4/6`:
  com os avisos desligados, o gráfico continua marcando.
- `sys_monitor.py`: clique esquerdo, item de menu, início do gravador em `main()` e gravação final ao sair.
- `version.py`: 1.1.0. `.gitignore`: `trafego-historico.csv`, porque rodando do código-fonte `data_dir()` é a
  pasta do repositório.

## Dados
- **Ponto:** um a cada 5 s, alinhado a múltiplos de 5 do relógio. Média de cada velocidade no intervalo e pior marca
  (0 nenhuma, 1 algum IP da família sem resposta, 2 todos). Família sem IPs configurados, ou ping desligado: marca 0.
- **Horário:** `time.time()`, para continuar válido depois de reiniciar. Rótulos em hora local.
- **Sem medição:** se `net_rates` for `None` o intervalo inteiro, as velocidades ficam vazias e a linha é interrompida.
  Nesse caso a marca é mantida.
- **Arquivo:** `data_dir()/trafego-historico.csv`, cerca de 170 KB em 4 h. Só horário, velocidades e marcas: nenhum
  IP, site ou programa. Colunas: `epoch,v4_down,v4_up,v6_down,v6_up,v4_mark,v6_mark`, velocidades em bytes/s inteiros.
  Atenção: `net_rates` é `((up_v4, up_v6), (down_v4, down_v6))`, isto é, o índice 0 é upload.
- **Gravação:** acrescenta os pontos novos a cada 60 s e uma última vez ao sair. Numa queda de energia perde no máximo
  cerca de 1 min.
- **Limpeza:** ao iniciar e a cada 1 h, reescreve o arquivo só com as últimas 4 h, de forma atômica (temporário +
  `os.replace`, como em `save_settings`).
- **Leitura ao iniciar:** ignora linha malformada, com mais de 4 h ou com horário mais de 60 s no futuro, e ordena por
  horário. A reescrita ao iniciar também resolve a linha cortada por queda de energia: sem ela, a próxima gravação
  colaria o texto novo na linha cortada e estragaria as duas.
- **Falha de disco:** registra uma vez no log, mantém os pontos na memória (no máximo 4 h, 2.880) e tenta de novo no
  ciclo seguinte. Nada disso pode encerrar o gravador nem afetar o widget.

## Clique
- **Barra de tarefas:** `<Button-1>` na janela do texto e na apanhadora, como o menu direito. A posição vem de
  `GetCursorPos` e `GetWindowRect` da célula de rede, porque as coordenadas do Tk não são confiáveis em filho de janela de
  outro processo (mesmo motivo de `show_menu`).
- **Metades:** função pura `net_family_at(x, left, widths)`. A metade v4 vai do início da coluna até o fim do valor
  v4; a metade v6 é o restante. Vale para as duas linhas (↑ e ↓). Fora da coluna de rede, o clique não faz nada.
- **Sem separação na tela:** com a separação desligada ou compactada por falta de espaço, clicar na coluna de rede abre a
  última família vista. Esse valor fica só na memória; o padrão é IPv4.
- **Modos com arraste:** soltar sem ter movido mais de 3 px conta como clique. Arrastar continua movendo o widget.
- **Menu direito:** "Histórico de tráfego…", antes de "Configurar limites de uso…". Abre a última família vista.

## Janela
- `Toplevel(self.master)` da raiz oculta, nunca filha do widget embutido no Explorer (mesma regra do editor de destinos).
  Assim ela sobrevive à reconstrução do widget quando o Explorer reinicia.
- Janela única no processo, com qualquer número de barras. Clicar de novo traz para a frente e troca para a família clicada.
- Abre na tela do clique, centrada nela. Redimensionável, com tamanho inicial de cerca de 800x360. Esc fecha.
- Título: "SysMonitor · Histórico de tráfego (estimado)". Botões `IPv4`, `IPv6`, `1 h` e `4 h`. Abre em 1 h; o período
  escolhido vale até fechar o programa.
- Atualiza a cada 5 s só enquanto aberta. O `after` é cancelado ao fechar e nada é desenhado com a janela fechada.
- Desenho em `Canvas`, sem dependência nova. Download e upload usam `accent_down` e `accent_up` do config, com
  legenda. Velocidades formatadas por `fmt_speed`, como no widget.
- **Escala:** linear, do zero ao maior valor visível no período.
- **Eixo de tempo:** marcas a cada 15 min em 1 h e a cada 1 h em 4 h, com a hora local.
- **Quando há mais pontos que pixels:** cada pixel usa o maior valor de cada velocidade e a pior marca entre os pontos
  dele, para picos e falhas não sumirem.
- **Buracos:** intervalo acima de 15 s sem ponto interrompe a linha.
- **Marcas:** faixas verticais atrás das linhas, vermelho forte para marca 2 e vermelho claro para marca 1.
- **Sem dados ainda:** mensagem "Coletando dados…". Com menos dados que o período, o trecho anterior fica vazio.

## Testes (escritos antes do código)
- **Ponto:** média, pior marca, intervalo sem medição, alinhamento a 5 s.
- **Arquivo:** ida e volta, linha cortada, linha malformada, horário antigo e futuro, limpeza, falha de gravação que
  mantém os dados e tenta de novo, com relógio falso e pasta temporária. Nunca o `config.ini` nem o CSV reais.
- **Ping:** `take_loss_marks` com marca 0, 1 e 2, zerando após a leitura, acumulando entre leituras, independente de
  `notify`, zerada por `set_groups`.
- **Gráfico:** `build_chart` com picos preservados na redução, buraco, escala, marcas e rótulos nos dois períodos.
- **Clique:** `net_family_at` nas duas metades, nos limites e fora da coluna; soltar com e sem movimento.
- **Janela e menu:** janela única, troca de família ao clicar de novo, cancelamento do `after` ao fechar, item no menu,
  seguindo os testes de interface existentes. O clique real no Explorer só se confere no teste do Mateus.

## Segurança e compatibilidade
Sem rede nova, privilégio elevado, driver nem dependência; continua compatível com HVCI. Antes da release, conferir
a seção A de `D:/dev/docs/seguranca.md` e anotar em `estado.md`.

## Entrega
Branch `versao-1.1` a partir da `versao-1.0.3`. Hermes executa e Claude revisa. Instalador para o teste do Mateus.
Push e release só com aprovação dele. Atualizar `docs/agentes/`: `interface.md`, `arquitetura.md`, `build-e-uso.md`,
`estado.md` e `INDICE.md`.
