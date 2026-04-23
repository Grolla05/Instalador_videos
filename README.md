# YTDownloader 🎬

Baixe vídeos e áudios do YouTube gratuitamente em MP3, MP4, WAV, OGG, WEBM e M4A.

## Stack

- **Backend**: Python + Flask + yt-dlp
- **Frontend**: HTML/CSS/JS puro (sem frameworks pagos)
- **Zero custo**: totalmente open-source

## Pré-requisitos

- Python 3.9+
- FFmpeg instalado no PATH ([download aqui](https://ffmpeg.org/download.html))

## Instalação

```bash
pip install -r requirements.txt
```

## Executar

```bash
python app.py
```

Acesse: http://localhost:5000

## Formatos suportados

| Formato | Tipo   | Qualidade         |
|---------|--------|-------------------|
| MP4     | Vídeo  | Melhor disponível |
| MP3     | Áudio  | 192 kbps          |
| WEBM    | Vídeo  | Melhor Web        |
| M4A     | Áudio  | AAC nativo        |
| WAV     | Áudio  | Sem perdas        |
| OGG     | Áudio  | Vorbis            |

## Estrutura

```
├── app.py              # Backend Flask
├── requirements.txt    # Dependências Python
├── templates/
│   └── index.html      # Frontend (página única)
└── downloads/          # Arquivos baixados (criado automaticamente)
```