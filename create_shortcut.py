import os
import sys
import subprocess
import winreg

def get_desktop_path():
    """Recupera o caminho real da Área de Trabalho (Desktop) consultando o Registro do Windows."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        )
        desktop_path, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        # Expande variáveis de ambiente como %USERPROFILE% ou %ONEDRIVE%
        return os.path.expandvars(desktop_path)
    except Exception:
        # Fallback padrão
        return os.path.join(os.environ["USERPROFILE"], "Desktop")

def create_desktop_shortcut():
    """Cria um atalho (.lnk) na Área de Trabalho do usuário para o executável compilado."""
    if sys.platform != "win32":
        print("[ERR] Este script de criação de atalhos é exclusivo para sistemas operacionais Windows.")
        return False

    HERE = os.path.dirname(os.path.abspath(__file__))
    
    # Caminho do executável compilado
    exe_name = "Vídeo Downloader 1.1v.exe"
    exe_path = os.path.join(HERE, "dist", exe_name)
    
    if not os.path.exists(exe_path):
        print(f"[ERR] Executável não encontrado em: {exe_path}")
        print("[TIP] Certifique-se de rodar primeiro o comando 'python build.py' para gerar o executável na pasta 'dist'.")
        return False

    # Caminho do ícone
    icon_path = os.path.join(HERE, "icon.ico")
    if not os.path.exists(icon_path):
        # Se não houver icon.ico na raiz, podemos apontar para o próprio executável como fonte do ícone
        icon_path = exe_path

    # Obtém o caminho da Área de Trabalho do usuário de forma segura através do Registro
    desktop_dir = get_desktop_path()
    shortcut_path = os.path.join(desktop_dir, "Vídeo Downloader 1.1v.lnk")

    print(f"[LOG] Criando atalho na Área de Trabalho em: {shortcut_path}")

    # Comando PowerShell para criar o atalho utilizando o objeto COM WScript.Shell
    ps_command = (
        f'$Shell = New-Object -ComObject WScript.Shell; '
        f'$Shortcut = $Shell.CreateShortcut("{shortcut_path}"); '
        f'$Shortcut.TargetPath = "{exe_path}"; '
        f'$Shortcut.WorkingDirectory = "{os.path.dirname(exe_path)}"; '
        f'$Shortcut.IconLocation = "{icon_path}"; '
        f'$Shortcut.Save()'
    )

    try:
        # Executa o comando via PowerShell de forma silenciosa
        result = subprocess.run(
            ["powershell", "-Command", ps_command],
            capture_output=True,
            text=True,
            check=True
        )
        print("[SUCCESS] Atalho da Área de Trabalho criado com sucesso!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERR] Falha ao criar o atalho via PowerShell: {e.stderr}")
        return False

if __name__ == "__main__":
    create_desktop_shortcut()
