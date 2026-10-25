Atualizado em 2026-10-25 (branch main; limites de temperatura e cores; sem commit)

# Telas

![Widget na barra de tarefas (ampliado 3×): rede ↑↓, CPU e GPU com uso e temperatura, memória](telas/barra.png)

![Editor de limites de uso e temperatura: caixas Low/Warning/High configuráveis, uso CPU/GPU/MEMÓRIA e temperatura CPU/GPU](telas/limites-de-uso.png)

Editor Tk real capturado em 2026-10-25: quinze campos, defaults de uso 50/75/90 e temperatura 60/75/85 °C; caixas clicáveis de cores globais, ajuda das faixas 0–100/0–120, Restaurar cores padrão e Salvar/Cancelar. Captura de 376 × 426 px somente da área cliente, pelo retângulo winfo_rootx/rooty/width/height e PowerShell/System.Drawing.CopyFromScreen, sem Pillow. Raiz própria oculta e config.ini temporário (inalterado); editor/raiz destruídos e processo de captura finalizado. Imagem conferida visualmente, sem cortes. Não é captura do widget em uso nem validação das cores no Explorer.

Os modos `docked` (faixa acima da barra) e `floating` (caixa arrastável) não foram capturados.
