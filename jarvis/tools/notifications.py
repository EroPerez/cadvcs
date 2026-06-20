import platform
import subprocess


def send_notification(title: str, message: str, urgency: str = "normal") -> str:
    system = platform.system()
    try:
        if system == "Linux":
            subprocess.run(
                ["notify-send", "-u", urgency, title, message], check=True
            )
        elif system == "Darwin":
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], check=True)
        return f"Notificación enviada: '{title}'"
    except FileNotFoundError:
        return "notify-send no encontrado. Instala: sudo apt install libnotify-bin"
    except subprocess.CalledProcessError as e:
        return f"Error al enviar notificación: {e}"
