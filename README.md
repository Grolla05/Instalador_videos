# 🎬 YouTube Downloader — Manual Técnico do Software (Apple HIG & Claymorphism)

Bem-vindo ao **manual técnico oficial** do **YouTube Downloader Desktop**. Este documento serve como especificação arquitetural, guia de engenharia e manual operacional do sistema. Ele descreve a infraestrutura física de concorrência, o ecossistema de design **Claymorphism** responsivo, as lógicas de segurança de token em memória e o fluxo de empacotamento standalone.

---

## 📐 1. Visão Geral da Arquitetura

O aplicativo foi projetado sob o padrão de **Arquitetura Híbrida Desktop**, combinando um backend robusto e portátil escrito em Python com um cliente de renderização de alto desempenho acelerado por hardware local.

```mermaid
graph TD
    subgraph Frontend [Camada Cliente - pywebview WebKit/Blink]
        HTML[index.html] -->|Estilos Estáticos| CSS[global.css]
        HTML -->|Física de Mola/Interações| Anime[Anime.js]
        HTML -->|Requisições Seguras| FetchAPI[Fetch API com X-API-Token]
    end

    subgraph Backend [Servidor Local - Flask & SQLite]
        FlaskApp[app.py - Flask Server]
        Middleware[@app.before_request Security Token Filter]
        SQLite[db.sqlite - Configurações & Preferências]
        QueueManager[ThreadPoolExecutor - Limite Concorrência: 3]
        Ytdl[yt-dlp Engine]
        Fm[FFmpeg / FFprobe]
    end

    FetchAPI -->|Validação de API Key| Middleware
    Middleware -->|Acesso Autorizado| FlaskApp
    FlaskApp -->|Leitura/Escrita| SQLite
    FlaskApp -->|Dispara Tarefas de Download| QueueManager
    QueueManager -->|Orquestra Processo| Ytdl
    Ytdl -->|Mescla Mídia / Conversão| Fm
```

---

## 🎨 2. Sistema de Design: Transição de Interface para Claymorphism & Apple HIG

Este projeto promoveu a **transição e troca completa da antiga interface bidimensional "flat"** por uma sofisticada e tátil estética de **Claymorphism** fundida a **Glassmorphism** (*Clay-glass*), projetada sob as orientações de ergonomia e materiais do **Apple Human Interface Guidelines (HIG)**. A interface agora simula botões inflados em 3D e contêineres esculpidos com propriedades físicas táteis e de iluminação realistas.

### Princípios Físicos da Interface

1. **Curvas Squircle Contínuas (`border-radius: 24px`)**: Substituição de cantos agudos por contornos de arredondamento generoso e transições geométricas suaves.
2. **Efeitos Volumétricos 3D (Dual Inset Shadows)**:
   * **Brilho Interno Superior:** Simula uma fonte de luz batendo no topo da argila (`inset 3px 3px 6px rgba(255, 255, 255, opacity)`).
   * **Sombra de Contorno Inferior:** Cria profundidade e contorno 3D na borda inferior direita (`inset -3px -3px 6px rgba(0, 0, 0, opacity)`).
3. **Física de Molas (Spring Physics com Anime.js)**:
   Toda interação tátil utiliza massa, rigidez e amortecimento elásticos para simular a compressão física real da argila:
   * **Press Down:** No evento de clique (`onmousedown`), os botões deformam-se para `scale: 0.94` instantaneamente usando a curva `spring(0.8, 120, 14, 0)`.
   * **Release:** No evento de soltura (`onmouseup`/`onmouseleave`), retornam de forma amortecida e elástica para `scale: 1` usando `spring(0.8, 100, 12, 0)`.
4. **Modos de Visualização e Acessibilidade**:
   * `Escuro` (Apple Monochrome Dark - Padrão).
   * `Claro` (Apple Warm White, sombras difusas de baixa opacidade).
   * `Sépia` (Tons de papel e leitura confortável).
   * `Alto Contraste` (Contornos puramente brancos sólidos sob fundo preto absoluto, removendo sombras e relevos em conformidade com as diretrizes de acessibilidade).
5. **Redimensionamento Proporcional tipográfico (`--font-scale`)**: Multiplicador de escala de texto segmentado em `0.85x` (Pequeno), `1.0x` (Padrão), `1.15x` (Médio) e `1.30x` (Grande), calculado dinamicamente em CSS para redimensionar todos os componentes sem corromper layouts.

---

## 🚦 3. Concorrência e Gerenciamento da Fila de Downloads

Para garantir a estabilidade do sistema operacional, largura de banda da rede e mitigar bloqueios de IP pelo YouTube, foi desenvolvida uma fila de concorrência ativa estrita:

1. **Limitador de Concorrência (Rate Limiting)**:
   * A execução de downloads em segundo plano utiliza um pool multithreading gerenciado pelo `ThreadPoolExecutor` do módulo `concurrent.futures`.
   * O limite é de no máximo **3 downloads concorrentes simultâneos**. Tarefas excedentes aguardam em estado de fila (`queued`).
2. **Paginação de Sessão (De 5 em 5)**:
   * O frontend consome dinamicamente o status do backend de maneira assíncrona por polling.
   * Os downloads da sessão ativa são paginados em blocos de 5 itens para evitar scroll excessivo e poluição de interface, navegados através de botões táteis elegantes.
3. **Cancelamento Ativo Interrompível**:
   * O Flask mantém um lock concorrente (`downloads_lock`) e uma lista de exclusão mutável (`cancelled_tasks`).
   * No meio de loops de download do `yt-dlp`, o hook de progresso monitora se o `task_id` correspondente foi marcado para cancelamento. Se sim, ele dispara uma exceção interrompendo imediatamente o processo e apagando arquivos parciais (`.part`).
4. **Resiliência e Continuidade (Resume)**:
   * Em caso de perda drástica de rede, o aplicativo preserva os arquivos temporários no disco, permitindo retomar as transferências de onde pararam.

---

## 🛡️ 4. Segurança Local: Isolamento de API (Token Nonce)

Como o backend Flask escuta em uma porta local, um atacante mal-intencionado navegando em um site malicioso poderia, teoricamente, tentar disparar requisições para `127.0.0.1` (ataques de DNS Rebinding ou Cross-Site Request Forgery). 

Para blindar o aplicativo contra exploits e invasão de dados, implementamos um **mecanismo de isolamento nativo de API**:

1. **Geração do Token Unilateral**:
   * No boot do Python (`main.py`), é gerada uma chave randômica única criptográfica de alta entropia (UUIDv4) em tempo de execução e armazenada exclusivamente na RAM (`API_TOKEN`).
2. **Distribuição via Injeção de Script Nativos**:
   * O frontend não tem acesso físico ao token no carregamento da página. Quando a janela do `pywebview` está pronta (`window.addEventListener('pywebviewready')`), ela solicita de forma síncrona o token diretamente do barramento de API nativo do Python (`window.pywebview.api.get_api_token()`).
3. **Validação de Cabeçalho `@app.before_request`**:
   * Todas as requisições para a API Flask do aplicativo interceptam cabeçalhos. Se o cabeçalho `'X-API-Token'` não estiver presente ou não for exatamente igual ao gerado na inicialização, o Flask descarta a chamada sumariamente com código **HTTP 403 Forbidden**.

---

## 💾 5. Persistência de Dados Relacional (SQLite)

O aplicativo utiliza um banco de dados relacional **SQLite** persistente integrado localizado em um diretório gravável do usuário:

* **Caminho no Windows:** `%APPDATA%/Vídeo Downloader 1.1v/db.sqlite`
* **Caminho no Desenvolvimento:** Direcionado na raiz do repositório.
* **Tabelas Principais:**
  * `settings`: Parâmetros chave-valor salvando preferências de acessibilidade (`theme` e `fontScale`), sincronizados dinamicamente a cada mudança de toggle no painel do usuário.
  * `downloads`: Histórico persistente e logs de tarefas de mídia.

---

## 🎬 6. Integração FFmpeg Portátil e Resiliência do yt-dlp

O YouTube transmite transmissões de alta resolução (1080p, 2K, 4K) em canais separados de vídeo e áudio (DASH). Para fundi-los ou converter downloads para MP3, o aplicativo orquestra processos do **FFmpeg**.

> **⚠️ Os binários do FFmpeg NÃO estão incluídos no repositório** (estão no `.gitignore` por serem arquivos de terceiros com ~100 MB cada). Instale-os com o script abaixo.

### ✨ Método Recomendado — Script Automático

Rode o script `setup_ffmpeg.py` incluído no projeto. Ele baixa o pacote oficial da **gyan.dev**, extrai os três executáveis e os coloca automaticamente em `bin/`:

```bash
python setup_ffmpeg.py
```

Para forçar a reinstalação caso os binários já existam:

```bash
python setup_ffmpeg.py --force
```

### Configuração Manual (alternativa)

Caso prefira instalar manualmente:

1. **Acesse as compilações oficiais:**
   * 👉 Visite [Gyan.dev FFmpeg Releases](https://www.gyan.dev/ffmpeg/builds/) e baixe **`ffmpeg-release-essentials.zip`**.
2. **Extraia os binários:**
   * Navegue no `.zip` até a pasta `bin/` e copie **`ffmpeg.exe`**, **`ffprobe.exe`** e **`ffplay.exe`**.
3. **Cole na pasta `bin/` do projeto:**
   * O código detectará os executáveis automaticamente no boot.

---

## 🛠️ Execução e Desenvolvimento Local

### 1. Clonando o Repositório

```bash
git clone https://github.com/seu-usuario/Instalador_videos.git
cd Instalador_videos
```

### 2. Instalando as Dependências Python

```bash
pip install -r requirements.txt
```

### 3. Instalando o FFmpeg (obrigatório)

```bash
python setup_ffmpeg.py
```

> O script baixa automaticamente os binários do FFmpeg (~100 MB) e os coloca em `bin/`. Necessário apenas uma vez.

### 4. Rodar em Ambiente de Desenvolvimento

```bash
python main.py
```

### 5. Rodar Testes de Integração Automatizados

Uma suíte completa de 10 blocos de testes unitários e de integração está disponível para garantir a conformidade da segurança, concorrência e endpoints da API:

```bash
python test_app.py
```

---

## 📦 Pipeline de Empacotamento Automatizado (.exe)

O script [build.py](file:///d:/GitHub/Instalador_videos/build.py) está pré-programado para empacotar o projeto inteiro em um único executável portátil do Windows utilizando o **PyInstaller**.

### Características do Build:

* **Auto-suficiência:** Se você colocou o `ffmpeg.exe` e o `ffprobe.exe` dentro da pasta `bin/`, o empacotador detectará os binários e os incorporará **automaticamente** no `.exe` gerado!
* **Carregamento de Estilos:** A pasta `static` (CSS) e `templates` (HTML) são incluídas no build como dados de recursos locais (`--add-data`), e o Flask está preparado para consumi-las a partir da memória física de extração do PyInstaller.

### Comando para Compilar:

```bash
python build.py
```
O executável compilado de clique único e sem console será exportado para:
`dist/Vídeo Downloader 1.1v.exe`

### ⚡ Criando um Atalho na Área de Trabalho (Shortcut)

Para facilitar o acesso ao seu executável compilado diretamente da Área de Trabalho do Windows com o ícone personalizado, criamos um script utilitário automatizado (`create_shortcut.py`) que faz essa configuração de forma nativa e robusta:

```bash
python create_shortcut.py
```

* **Recuperação de Caminho pelo Registro:** O script consulta o registro do Windows (`winreg`) para localizar a pasta Desktop real do usuário, funcionando perfeitamente mesmo se ela estiver mapeada em caminhos do OneDrive ou traduzida pelo idioma do sistema operacional.

---

## 📁 Estrutura de Arquivos do Projeto

```
├── main.py                # Inicializador Desktop, rotinas de eventos e pywebview
├── app.py                 # Core do Flask, DB SQLite, Threads e cancelamentos ativos
├── updater.py             # Monitor de versão e auto-atualizador do yt-dlp via PyPI
├── test_app.py            # Suíte abrangente de testes unitários e de integração
├── build.py               # Orquestrador do empacotamento PyInstaller
├── create_shortcut.py     # Utilitário para criar o atalho (.lnk) na Área de Trabalho
├── setup_ffmpeg.py        # ✨ Setup automático dos binários FFmpeg (rodar após clonar)
├── static/
│   ├── favicon.png        # [Opcional] Ícone padrão carregado dinamicamente no app
│   └── css/
│       └── global.css     # Design Claymorphic alinhado ao Apple HIG e temas
├── templates/
│   └── index.html         # Template do frontend e micro-interações Anime.js
├── bin/
│   ├── .gitkeep           # Reserva a pasta bin no repositório Git
│   ├── ffmpeg.exe         # ⚠️ NÃO incluso no repo — instalar via setup_ffmpeg.py
│   ├── ffprobe.exe        # ⚠️ NÃO incluso no repo — instalar via setup_ffmpeg.py
│   └── ffplay.exe         # ⚠️ NÃO incluso no repo — instalar via setup_ffmpeg.py
├── icon.ico               # Ícone do executável Windows
├── requirements.txt       # Arquivo de bibliotecas dependentes
└── .gitignore             # Configuração de arquivos ignorados no controle Git
```