# 🎬 YouTube Downloader — Desktop App (Apple HIG Premium)

Um aplicativo desktop de alta performance e visualmente deslumbrante (em conformidade com o **Apple Human Interface Guidelines**) projetado para baixar vídeos e extrair áudios do YouTube com facilidade, velocidade, segurança local e resiliência de rede.

---

## ✨ Recursos de Elite do Projeto

### 🎨 1. Menu de Acessibilidade e Temas Dinâmicos

* **Engrenagem de Acessibilidade:** Um botão elegante flutuante com ícone de engrenagem e física de molas (Anime.js) que rotaciona e abre um painel dropdown translúcido (*glassmorphic*).
* **4 Temas de Alto Padrão (Apple HIG):**
  * `Escuro (Padrão)`: Fundo preto profundo e acentos azul iOS.
  * `Claro`: Fundo branco limpo, superfícies claras e acentos azul iOS.
  * `Sépia`: Tons pastéis suaves (bege/charcoal) para extremo conforto em leituras prolongadas.
  * `Alto Contraste`: Fundo preto puro e contornos brancos sólidos para acessibilidade de alta visibilidade.
* **Redimensionamento Tipográfico Dinâmico (`--font-scale`):** Multiplicador de escala de texto segmentado em `0.85x` (Pequeno), `1.0x` (Padrão), `1.15x` (Médio) e `1.30x` (Grande), alterando proporcionalmente toda a interface sem quebrar grids.
* **Prevenção de Flicker (Head Script):** Script síncrono ultra-rápido injetado no `<head>` que aplica o tema salvo no `localStorage` antes da renderização do CSS, prevenindo 100% de piscadas brancas (FOUC).

### 🚦 2. Concorrência Limitada (Rate Limiting) e Fila

* **Fila por ThreadPool:** Limite inteligente de concorrência ativa fixado em no máximo **3 downloads simultâneos** via `ThreadPoolExecutor` no Flask.
* **Segmentação por Página ("De 5 em 5"):** A fila de downloads exibe os itens da sessão atual organizados em páginas dinâmicas e fluidas com chevrons de paginação glassmorphic.
* **Retomada de Downloads (Resume):** Arquivos temporários inacabados (`.part` e `.ytdl`) são mantidos caso ocorram oscilações drásticas de rede, permitindo continuar a transferência exatamente de onde parou.

### 🛡️ 3. Isolamento de API e Segurança CORS/CSRF

* **Token Nonce Isolado:** O Python gera um UUID randômico único a cada inicialização e o compartilha de forma estritamente privada com o container nativo da janela `pywebview`.
* **Filtro de Intercepção:** Um middleware `@app.before_request` bloqueia sumariamente (HTTP 403) qualquer chamada aos endpoints de dados que não forneça o cabeçalho `'X-API-Token'` correto, blindando a API local contra exploits de navegadores externos comuns.

### 💾 4. Persistência Relacional (SQLite Local)

* **Banco SQLite local:** Banco embutido persistente em `%APPDATA%/YouTubeDownloader/db.sqlite` para gravação do histórico de downloads e preferências do menu de acessibilidade (tema e tamanho de fonte).

---

## 🎬 Configurando o FFmpeg Portátil (ffmpeg.exe e ffprobe.exe)

O FFmpeg é o motor que junta vídeos em 1080p ou superior (o YouTube transmite canais de vídeo e áudio separados em alta definição) e converte mídias para MP3. 

Para tornar o aplicativo **totalmente portátil e independente de instalações de sistema**:

### Passo a Passo para Download:

1. **Acesse o site oficial de compilações para Windows:**
   👉 [Gyan.dev FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/)
2. **Baixe o pacote leve de release:**
   * Na seção **release builds**, baixe o arquivo zip chamado **`ffmpeg-release-essentials.zip`** (ou use o link direto [ffmpeg-release-essentials.zip](https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip)).
3. **Extraia os arquivos executáveis:**
   * Abra o arquivo `.zip` baixado, navegue até a pasta interna **`bin/`** e localize os dois arquivos: **`ffmpeg.exe`** e **`ffprobe.exe`**.
4. **Cole no Projeto:**
   * Cole ambos os executáveis (`ffmpeg.exe` e `ffprobe.exe`) diretamente dentro da pasta **`bin/`** localizada na raiz deste repositório:
     `d:/GitHub/Instalador_videos/bin/` (substituindo o `.gitkeep`).

---

## 🛠️ Instalação e Execução (Desenvolvimento)

### 1. Instalar Dependências

```bash
pip install -r requirements.txt
```

### 2. Executar como App Desktop Nativo

```bash
python main.py
```

### 3. Rodar a Suíte de Testes Automatizados

```bash
python test_app.py
```

---

## 📦 Empacotando em um Arquivo Standalone (.exe)

O script [build.py](file:///d:/GitHub/Instalador_videos/build.py) está pré-programado para empacotar o projeto em um executável de clique único utilizando o **PyInstaller**.

* Se você colocou o `ffmpeg.exe` e o `ffprobe.exe` na pasta `bin/`, o empacotador detectará os arquivos automaticamente e **irá embuti-los de forma nativa** dentro do `.exe` gerado!
* Execute o comando de build no terminal:

  ```bash
  python build.py
  ```

* O executável final totalmente autossuficiente e pronto para distribuição estará localizado em:
  `dist/YouTubeDownloader.exe`

---

## 📁 Estrutura Organizada do Repositório

```
├── main.py                # Ponto de entrada Desktop (Pywebview)
├── app.py                 # Backend Flask, SQLite e Threads de download
├── updater.py             # Verificação e Auto-atualizador do yt-dlp via PyPI
├── test_app.py            # Cobertura abrangente de testes automatizados
├── build.py               # Script de compilação automatizado para .exe
├── static/
│   └── css/
│       └── global.css     # Folha de estilos unificada (HIG e temas)
├── templates/
│   └── index.html         # Frontend e lógicas de visualização Javascript
├── bin/
│   ├── .gitkeep           # Preserva pasta bin vazia no controle Git
│   ├── ffmpeg.exe         # [Opcional] Binário portátil de codificação
│   └── ffprobe.exe        # [Opcional] Binário portátil de análise de mídia
├── icon.ico               # Ícone do executável Windows
├── requirements.txt       # Lista de dependências Python
└── .gitignore             # Ignora caches, downloads e arquivos de build locais
```