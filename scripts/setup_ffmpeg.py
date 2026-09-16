"""
setup_ffmpeg.py — Baixa e instala automaticamente os binários do FFmpeg na pasta bin/.

Uso:
    python setup_ffmpeg.py

O script irá:
  1. Verificar se os binários já existem em bin/
  2. Baixar o pacote ffmpeg-release-essentials.zip da gyan.dev
  3. Extrair apenas ffmpeg.exe, ffprobe.exe e ffplay.exe para bin/
  4. Limpar os arquivos temporários
"""

import os
import sys
import shutil
import zipfile
import tempfile
import urllib.request
from pathlib import Path

# ── Configurações ─────────────────────────────────────────────────────────────
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
BINARIES   = ["ffmpeg.exe", "ffprobe.exe", "ffplay.exe"]
BIN_DIR    = Path(__file__).parent / "bin"

# ── Cores ANSI para terminal ──────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def _enable_ansi():
    """Habilita cores ANSI no terminal do Windows."""
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

def _print_header():
    print(f"\n{BOLD}{CYAN}{'─' * 52}{RESET}")
    print(f"{BOLD}{CYAN}  FFmpeg Setup — Vídeo Downloader{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 52}{RESET}\n")

def _check_existing() -> list[str]:
    """Retorna lista de binários que já existem em bin/."""
    return [b for b in BINARIES if (BIN_DIR / b).exists()]

def _format_size(bytes_total: int) -> str:
    if bytes_total >= 1_048_576:
        return f"{bytes_total / 1_048_576:.1f} MB"
    return f"{bytes_total / 1024:.1f} KB"

def _download_with_progress(url: str, dest: Path):
    """Baixa um arquivo exibindo barra de progresso no terminal."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )

    with urllib.request.urlopen(req, timeout=60) as response:
        total = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        bar_width = 40

        with open(dest, "wb") as out:
            while True:
                chunk = response.read(65536)  # 64 KB por chunk
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)

                if total:
                    pct  = downloaded / total
                    done = int(bar_width * pct)
                    bar  = "█" * done + "░" * (bar_width - done)
                    size = _format_size(downloaded)
                    tot  = _format_size(total)
                    print(
                        f"\r  {CYAN}[{bar}]{RESET} {pct*100:5.1f}%  {size}/{tot}",
                        end="",
                        flush=True,
                    )
                else:
                    print(
                        f"\r  Baixando... {_format_size(downloaded)}",
                        end="",
                        flush=True,
                    )

    print()  # nova linha após a barra

def _extract_binaries(zip_path: Path) -> list[str]:
    """
    Extrai apenas os .exe do FFmpeg para bin/.
    O zip da gyan.dev tem estrutura: ffmpeg-<versão>-essentials_build/bin/<exe>
    """
    extracted = []
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    # Garante que o .gitkeep existe para o Git rastrear a pasta bin/
    gitkeep = BIN_DIR / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text(
            "# Este arquivo garante que a pasta bin/ seja rastreada pelo Git,\n"
            "# mesmo quando os binários do FFmpeg (*.exe) estão no .gitignore.\n"
            "#\n"
            "# Para instalar o FFmpeg automaticamente, rode na raiz do projeto:\n"
            "#   python setup_ffmpeg.py\n"
        )

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()

        for binary in BINARIES:
            # Encontra o caminho do binário dentro do zip (qualquer subpasta /bin/)
            match = next(
                (m for m in members if m.endswith(f"/bin/{binary}") or m == binary),
                None,
            )
            if not match:
                print(f"  {YELLOW}⚠  {binary} não encontrado no pacote.{RESET}")
                continue

            # Extrai apenas esse arquivo para a pasta bin/
            source = zf.open(match)
            target = BIN_DIR / binary
            with open(target, "wb") as out:
                shutil.copyfileobj(source, out)

            extracted.append(binary)
            print(f"  {GREEN}✔  {binary}{RESET}")

    return extracted

def main():
    _enable_ansi()
    _print_header()

    # 1. Verifica binários existentes
    existing = _check_existing()
    if len(existing) == len(BINARIES):
        print(f"{GREEN}✔  Todos os binários já estão instalados em bin/{RESET}\n")
        for b in existing:
            size = _format_size((BIN_DIR / b).stat().st_size)
            print(f"   • {b}  ({size})")
        print(f"\n{YELLOW}Nenhuma ação necessária. Use --force para reinstalar.{RESET}\n")

        if "--force" not in sys.argv:
            return

        print(f"\n{YELLOW}--force detectado. Reinstalando...{RESET}\n")

    elif existing:
        missing = [b for b in BINARIES if b not in existing]
        print(f"{YELLOW}⚠  Binários presentes: {', '.join(existing)}{RESET}")
        print(f"{YELLOW}⚠  Faltando:           {', '.join(missing)}{RESET}\n")
    else:
        print(f"{YELLOW}Nenhum binário FFmpeg encontrado em bin/{RESET}\n")

    # 2. Download
    print(f"{BOLD}Baixando FFmpeg Essentials...{RESET}")
    print(f"  Fonte: {CYAN}{FFMPEG_URL}{RESET}\n")

    tmp_dir  = Path(tempfile.mkdtemp())
    zip_path = tmp_dir / "ffmpeg-essentials.zip"

    try:
        _download_with_progress(FFMPEG_URL, zip_path)
        print(f"\n{GREEN}✔  Download concluído ({_format_size(zip_path.stat().st_size)}){RESET}\n")

        # 3. Extração
        print(f"{BOLD}Extraindo binários para bin/{RESET}\n")
        extracted = _extract_binaries(zip_path)

        if extracted:
            print(f"\n{BOLD}{GREEN}✔  FFmpeg instalado com sucesso!{RESET}")
            print(f"   {len(extracted)} binário(s) copiado(s) para: {BIN_DIR}\n")
        else:
            print(f"\n{RED}✘  Nenhum binário pôde ser extraído. Verifique o pacote baixado.{RESET}\n")
            sys.exit(1)

    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}⚠  Download cancelado pelo usuário.{RESET}\n")
        sys.exit(0)
    except Exception as exc:
        print(f"\n{RED}✘  Erro durante o setup: {exc}{RESET}\n")
        sys.exit(1)
    finally:
        # 4. Limpeza dos temporários
        shutil.rmtree(tmp_dir, ignore_errors=True)

if __name__ == "__main__":
    main()
