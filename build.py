"""
build.py — empacota o YouTube Downloader como .exe com PyInstaller.

Uso:
    python build.py

Saída:
    dist/Vídeo Downloader 1.1v.exe   (arquivo único, sem console)
"""

import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# Inclui as pastas de recursos no bundle
bin_dir = os.path.join(HERE, "bin")
add_data_args = [
    "--add-data", f"{os.path.join(HERE, 'templates')};templates",
    "--add-data", f"{os.path.join(HERE, 'static')};static",
]
# If the bin directory exists and has files (besides just .gitkeep), bundle it
if os.path.exists(bin_dir) and len(os.listdir(bin_dir)) > 1:
    add_data_args += ["--add-data", f"{bin_dir};bin"]

args = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--onefile",
    "--windowed",               # sem janela de console
    "--name", "Vídeo Downloader 1.1v",
    "--icon", os.path.join(HERE, "icon.ico"),
] + add_data_args + [
    # Ponto de entrada
    os.path.join(HERE, "main.py"),
]

print("[LOG] Iniciando build...\n")
result = subprocess.run(args, cwd=HERE)

if result.returncode == 0:
    print("\n[SUCCESS] Build concluido! -> dist/Vídeo Downloader 1.1v.exe")
else:
    print("\n[ERROR] Build falhou. Verifique os erros acima.")
    sys.exit(result.returncode)
