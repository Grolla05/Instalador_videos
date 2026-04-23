"""
build.py — empacota o YouTube Downloader como .exe com PyInstaller.

Uso:
    python build.py

Saída:
    dist/YouTubeDownloader.exe   (arquivo único, sem console)
"""

import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))

args = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--onefile",
    "--windowed",               # sem janela de console
    "--name", "YouTubeDownloader",
    "--icon", os.path.join(HERE, "icon.ico"),

    # Inclui as pastas de recursos no bundle
    "--add-data", f"{os.path.join(HERE, 'templates')};templates",

    # Ponto de entrada
    os.path.join(HERE, "main.py"),
]

print("[LOG] Iniciando build...\n")
result = subprocess.run(args, cwd=HERE)

if result.returncode == 0:
    print("\n[SUCCESS] Build concluido! -> dist/YouTubeDownloader.exe")
else:
    print("\n[ERROR] Build falhou. Verifique os erros acima.")
    sys.exit(result.returncode)
