# Histórico de tráfego: períodos curtos, zoom, seleção, filtro e ping (SysMonitor 1.1.0)

Data: 2026-11-06. Continua `2026-11-06-historico-trafego-design.md`, cuja primeira etapa o Mateus já testou e aprovou.
Registro: `D:/dev/memoria-compartilhada/pedidos/2026-11-06-claude-sysmonitor-historico-trafego.md`.

## Objetivo
Investigar um momento específico na janela do histórico: aproximar um trecho, ler seus números, isolar uma medida e ver
se o ping subiu junto com o tráfego.

Pedidos originais: "adicionar os períodos de tempo de 5 e 15 minutos também e opção de eu arrastar o mouse e ele selecionar
um período que eu selecionei e opção de dar um zoom in e zoom out"; "quando eu clicar só em download, mostrar só download, e
mesma coisa com os outros up, ping, perda".

## Decisões do Mateus
- A seleção com o mouse dá zoom no trecho e mostra um resumo.
- Ping é uma linha nova com o tempo de resposta em ms. Perda são as duas marcas vermelhas.

## Fora desta etapa
Arrastar o gráfico para os lados, valor ao passar o mouse, exportação e períodos maiores que 4 h.

## Períodos e modo de exibição
- Botões `5 min`, `15 min`, `1 h` e `4 h`, além de `+` e `−`.
- **Ao vivo:** um período escolhido segue o tempo real e atualiza a cada 5 s, como hoje. O botão fica destacado.
- **Parado:** zoom ou seleção fixam um trecho `[início, fim]`. Nenhum botão de período fica destacado, e o gráfico não muda
  com o tempo.
- Clicar em qualquer botão de período volta ao vivo.
- Trocar de família mantém o modo e o trecho, para comparar as duas no mesmo momento. Clicar de novo em v4/v6 na barra idem.
- Fechar a janela descarta o trecho parado. Ao reabrir, volta ao vivo no último período escolhido.
- Um trecho parado pode envelhecer além de 4 h e ficar sem dados: aparece vazio, e o botão de período resolve.

## Zoom
- Passo de 25%: aproximar multiplica a duração por 0,75; afastar divide por 0,75.
- A roda do mouse usa como âncora o ponto sob o mouse, que continua no mesmo lugar da tela. Fora da área do gráfico, usa o centro.
- Botões `+` e `−` e as teclas `+`, `=`, `-` e as do teclado numérico usam o centro.
- Duração entre 1 min e 4 h. Fim nunca depois de agora, início nunca antes de agora − 4 h; ao bater num limite, o trecho desliza
  para dentro mantendo a duração.
- Dar zoom no modo ao vivo fixa o trecho a partir do que está na tela.

## Seleção
- Com o botão esquerdo no gráfico, arrastar desenha uma faixa translúcida, limitada à área do gráfico.
- Soltar com menos de 4 px de deslocamento não faz nada.
- Soltar depois de arrastar fixa o trecho selecionado. Trecho menor que 1 min vira 1 min em torno do centro dele, com as mesmas
  regras de limite do zoom.
- Durante o arraste, a atualização de 5 s não redesenha, para não apagar a faixa.
- Esc durante o arraste cancela a seleção. Fora do arraste, fecha a janela, como hoje.

## Resumo
- Uma linha abaixo dos botões, só no modo parado, quebrando o texto se faltar largura. Exemplo:
  `20:14 – 20:31 · ↓ pico 48.0 Mbps, média 12.0 Mbps · ↑ pico 3.0 Mbps, média 1.0 Mbps · ping pico 120 ms, média 30 ms · 4 intervalos com falha`.
- Calculado sobre os pontos de 5 s do trecho, não sobre o que foi reduzido para caber em pixels.
- Só entram as medidas visíveis no filtro. Medida sem nenhum dado no trecho aparece como `sem dados`.
- "Intervalos com falha" conta os pontos de 5 s com marca 1 ou 2.
- O pico do resumo pode ser menor que o valor de 1 s visto no widget, porque cada ponto já é a média de 5 s.

## Filtro
- Itens da legenda clicáveis: `↓ download`, `↑ upload`, `ping` e `perda` (os dois marcadores vermelhos formam um item só).
- Um clique mostra só aquele item. Clicar em outro troca; clicar de novo no ativo volta a mostrar tudo. O ativo fica destacado.
- O filtro dura até fechar o programa, como o período, e vale para as duas famílias.
- A escala se ajusta ao que está visível: a linha de download sem o filtro divide o eixo com o upload; filtrada, usa só o pico dela.
- Só `ping`: esconde o eixo esquerdo. Só `perda`: esconde os dois eixos de valor e mantém o de tempo.

## Ping
- **Linha:** cor fixa `#c9a0ff`, com escala própria em ms no eixo direito (0, metade e pico, inteiros). Zero aparece como `0 ms`.
- **Coleta:** `PingMonitor.take_worst_rtts()` devolve o maior tempo de resposta de cada família desde a última leitura e zera,
  como `take_loss_marks`. `None` se nenhum IP respondeu. Ignora os que não responderam; 0 ms é uma resposta válida. Não depende
  de `notify`.
- **Ponto:** guarda o maior valor do intervalo de 5 s, arredondado para ms inteiro. Sem resposta no intervalo: vazio, e a linha é interrompida.
- **Redução:** quando há mais pontos que pixels, cada pixel usa o maior valor, como as demais medidas.

## Formato do arquivo
- Duas colunas novas no fim: `epoch,v4_down,v4_up,v6_down,v6_up,v4_mark,v6_mark,v4_ping,v6_ping`.
- A leitura aceita 7 colunas (arquivo atual, ping vazio) e 9. Qualquer outra quantidade é linha malformada. O histórico que já está
  no PC do Mateus (938 linhas de 7 colunas, conferido em 2026-11-06) tem que continuar aparecendo.
- A reescrita ao iniciar converte tudo para 9 colunas.
- Ping negativo é linha malformada.
- Voltar para uma versão anterior descarta as linhas novas ao ler, sem quebrar: perde no máximo as últimas 4 h.

## Eixo de tempo
Marcas no primeiro passo de `15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200 s` que dê no máximo 5 intervalos no trecho. Com passo abaixo
de 60 s, o rótulo inclui os segundos. Mantém a cada 15 min em 1 h e a cada 1 h em 4 h, e dá a cada 1 min em 5 min.

## Componentes
Sem arquivo novo.
- `ping_monitor.py`: `take_worst_rtts`.
- `traffic_history.py`:
  - `Point` e `FamilyPoint` ganham o ping, opcional, para não invalidar quem já os monta.
  - `add_sample` recebe os tempos.
  - `points_between(family, start, end)`; `points` passa a usá-la.
  - `build_chart` recebe as medidas visíveis e devolve também a linha de ping e o eixo direito.
  - Funções puras novas: `zoom_view`, `selection_view`, `x_to_time` e `summarize`.
- `traffic_history_ui.py`: modo ao vivo ou parado, botões, legenda clicável, roda do mouse, teclado, arraste e linha de resumo.
  Regra de cálculo fica nas funções puras.

## Testes (escritos antes do código)
- **Ping:** pior tempo por família, zera ao ler, `None` sem resposta, 0 ms válido, independente de `notify`, zerado por `set_groups`.
- **Arquivo:** arquivo de 7 colunas continua sendo lido e vira 9; 9 colunas ida e volta; ping vazio; 0 ms não vira vazio; 8 colunas e ping negativo ignorados.
- **Zoom e seleção:** âncora preservada, limites de 1 min e 4 h, deslizar nos limites, seleção invertida (direita para esquerda), seleção curta.
- **Resumo:** picos e médias com pontos vazios, sem dados, só as medidas visíveis, contagem de falhas.
- **Gráfico:** filtros, escala só com o visível, eixo direito, passos do eixo de tempo nos quatro períodos e em 1 min.
- **Janela:** ao vivo e parado, troca de família mantendo o trecho, volta ao vivo, arraste sem redesenhar, Esc, filtro ligando e desligando.
  Tudo sem mostrar janela real; a captura final confere a aparência.

## Segurança e compatibilidade
Sem rede nova, privilégio, driver ou dependência. O arquivo passa a ter também tempos de resposta, ainda sem IP, site ou programa.

## Entrega
Continua 1.1.0, ainda não publicada, na branch `versao-1.1`. Hermes executa e Claude revisa. Instalador para o teste do Mateus. Push e release
só com aprovação dele.
