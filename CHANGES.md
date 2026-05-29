# Histórico de Alterações — Evolução Premium e Estilização Claymorphic

Este arquivo documenta detalhadamente todas as modificações estruturais, visuais e arquiteturais realizadas no projeto do **YouTube Downloader** nesta sessão, com o objetivo de implementar a **transição completa da antiga interface 2D flat para a nova estética tátil de Claymorphism** alinhada ao **Apple HIG**, além de garantir a integridade da compilação portátil autossuficiente.

---

## 💎 Transição de Interface: Upgrade para Claymorphism Premium
Esta atualização representa um marco de design na plataforma, substituindo superfícies estáticas bidimensionais comuns por elementos realistas em 3D que respondem de maneira tátil à compressão elástica. Toda a folha de estilos e animações físicas foram reprojetadas para suportar a sensação de relevo suave, argila esculpida e botões inflados interativos.

---

## 🎨 1. Estilização Premium Claymorphism & Glassmorphism
* **Localização:** `static/css/global.css`
* **Implementação:**
  * **Variáveis de Sombra:** Criação de variáveis `--clay-btn`, `--clay-card` e `--clay-input` no `:root` e especialização em cada tema (`claro`, `sepia`, `contraste`).
  * **Botões 3D Táteis (`.btn`):** Introdução de gradientes iOS e sombras internas duplas (`inset 3px 3px 6px` para simular iluminação do topo esquerdo e `inset -3px -3px 6px` para profundidade do canto inferior direito).
  * **Inputs Recessivos (`input[type="text"]`):** Sombras internas acentuadas que dão o aspecto de "esculpido para dentro" (*recessed clay*).
  * **Contêineres Clay-Glass (`.card` e `.dl-card`):** Fusão de Glassmorphism com Claymorphism através de fundos translúcidos desfocados (`backdrop-filter: blur(24px)`) e bordas arredondadas e contínuas estilo **Squircle** generosas (`24px`).
  * **Trilhos de Progresso Néon:** O trilho de progresso foi reestilizado com sombras internas profundas e o preenchimento ganhou um gradiente brilhante tridimensional (`linear-gradient(90deg, var(--accent), #34C759)`).
  * **Acessibilidade no Alto Contraste:** No tema `contraste`, todos os efeitos claymorphic de relevo são desabilitados em favor de contornos sólidos de alta visibilidade (preto e branco puro).

## 🚀 2. Micro-interações e Física de Molas Físicas (Anime.js)
* **Localização:** `templates/index.html`
* **Implementação:**
  * **`bindSprings()` Refinado:** Qualquer elemento interativo (`.spring-interactive`) agora deforma elasticamente a escala para `0.94` ao clique (`onmousedown`) em vez de `0.96`, simulando a compressão de argila. O retorno bouncy à escala original `1` é processado com constantes de física real: `spring(0.8, 120, 14, 0)` na compressão e `spring(0.8, 100, 12, 0)` na expansão.
  * **Entradas de Card Amortecidas:** A adição de cards de downloads na fila ocorre com translação Y (`translateY: [20, 0]`) e expansão de escala elástica (`scale: [0.95, 1]`) simultâneas e amortecidas.
  * **Saídas por Cancelamento:** Ao cancelar um download, o card executa um encolhimento elástico (`scale: 0.93`), elevação (`translateY: -15`) e desvanecimento suave antes de ser removido do DOM.
  * **Widgets e Toasts:** O painel de acessibilidade flutuante e a rotação da engrenagem utilizam constantes de amortecimento real em vez de caminhos lineares de transição.

## 🛡️ 3. Correções Arquiteturais para Compilação e Distribuição (.exe)
* **Localizações:** `app.py`, `build.py` e `main.py`
* **Implementação:**
  * **Correção de Carregamento CSS no Executável (`app.py`)**: Adicionado o parâmetro `static_folder=_resource_path("static")` na inicialização do Flask, forçando a aplicação a carregar a folha de estilos do diretório temporário `_MEIPASS` em produção.
  * **Empacotamento da Pasta Estática (`build.py`)**: Adicionada a pasta `static` nos argumentos `--add-data` do PyInstaller, assegurando que o `global.css` e qualquer recurso estático sejam embutidos no binário final.
  * **Suporte Seguro a Ícones em Tempo de Execução (`main.py`)**: Implementada uma verificação de existência segura de arquivo para o ícone `static/favicon.png` na inicialização do `webview.start()`, evitando falhas de execução e garantindo suporte multiplataforma.

---

## 📺 4. Expansão de Suporte a Resoluções (Incluindo HD+)
* **Localizações:** `templates/index.html`, `app.py` e `test_app.py`
* **Implementação:**
  * **Interface de Seleção Ampliada (`index.html`)**: O menu de resoluções foi expandido para cobrir o espectro completo de 360p (SD) até 2160p (4K). Foram incluídas as opções específicas **480p (SD)** e a resolução ultra-larga **HD+ (1600x720)**.
  * **Lógica de Filtragem Inteligente (`app.py`)**: 
    * Implementado suporte dedicado para a resolução **HD+**, utilizando o filtro `[height<=720][width<=1600]` do yt-dlp. Isso garante que o sistema priorize o formato ultra-largo quando disponível, mantendo a compatibilidade descendente com o 720p padrão.
    * Refatoração da função `build_ydl_opts` para lidar dinamicamente com qualquer altura de resolução informada via frontend, garantindo que o FFmpeg seja acionado para realizar o merge de áudio e vídeo em alta qualidade.
  * **Validação de Backend (`test_app.py`)**: Adicionados novos casos de teste unitário para validar se as strings de formato geradas para 480p e HD+ estão corretas e seguem os padrões exigidos pelo yt-dlp.
