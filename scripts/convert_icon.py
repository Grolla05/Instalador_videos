from PIL import Image
import os

png_path = r"C:\Users\fegro\.gemini\antigravity\brain\29828f9c-3308-49cd-ba1c-e3bdf01d0446\youtube_downloader_icon_1776963596370.png"
ico_path = "icon.ico"

if os.path.exists(png_path):
    img = Image.open(png_path)
    # Generate an icon with multiple sizes for better Windows compatibility
    img.save(ico_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Sucesso: Ícone salvo em {ico_path}")
else:
    print("Erro: PNG não encontrado.")
