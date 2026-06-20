import subprocess
import platform
import time
import psutil


def get_system_info() -> str:
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    uptime_secs = time.time() - psutil.boot_time()
    h, m = int(uptime_secs // 3600), int((uptime_secs % 3600) // 60)

    return (
        f"Sistema: {platform.system()} {platform.release()}\n"
        f"CPU: {cpu:.1f}% ({psutil.cpu_count(logical=False)} núcleos físicos, "
        f"{psutil.cpu_count()} lógicos)\n"
        f"RAM: {mem.percent:.1f}% usado "
        f"({mem.used / 1024**3:.1f} GB / {mem.total / 1024**3:.1f} GB)\n"
        f"Disco /: {disk.percent:.1f}% usado "
        f"({disk.used / 1024**3:.1f} GB / {disk.total / 1024**3:.1f} GB)\n"
        f"Uptime: {h}h {m}m"
    )


def get_battery_info() -> str:
    battery = psutil.sensors_battery()
    if battery is None:
        return "No se detectó batería (posiblemente es un desktop)"

    status = "Cargando" if battery.power_plugged else "Descargando"
    secs = battery.secsleft

    if secs == psutil.POWER_TIME_UNLIMITED:
        time_str = "∞ (conectado a corriente)"
    elif secs == psutil.POWER_TIME_UNKNOWN or secs < 0:
        time_str = "tiempo desconocido"
    else:
        time_str = f"{secs // 3600}h {(secs % 3600) // 60}m restantes"

    return f"Batería: {battery.percent:.0f}% — {status} — {time_str}"


def control_volume(action: str, value: int = None) -> str:
    system = platform.system()

    if system == "Linux":
        cmds = {
            "get": ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
            "mute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
            "unmute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
        }
        if action == "get":
            r = subprocess.run(cmds["get"], capture_output=True, text=True)
            return r.stdout.strip() or "No se pudo obtener volumen"
        if action == "set" and value is not None:
            v = max(0, min(150, value))
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{v}%"])
            return f"Volumen → {v}%"
        if action == "up":
            inc = value or 10
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"+{inc}%"])
            return f"Volumen subido {inc}%"
        if action == "down":
            dec = value or 10
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"-{dec}%"])
            return f"Volumen bajado {dec}%"
        if action in ("mute", "unmute"):
            subprocess.run(cmds[action])
            return "Audio silenciado" if action == "mute" else "Audio activado"

    elif system == "Darwin":
        if action == "set" and value is not None:
            subprocess.run(["osascript", "-e", f"set volume output volume {value}"])
            return f"Volumen → {value}%"
        if action == "mute":
            subprocess.run(["osascript", "-e", "set volume output muted true"])
            return "Audio silenciado"
        if action == "unmute":
            subprocess.run(["osascript", "-e", "set volume output muted false"])
            return "Audio activado"

    return f"Acción '{action}' ejecutada"


def control_brightness(action: str, value: int = None) -> str:
    try:
        if action == "get":
            cur = int(subprocess.run(["brightnessctl", "get"], capture_output=True, text=True).stdout.strip())
            mx = int(subprocess.run(["brightnessctl", "max"], capture_output=True, text=True).stdout.strip())
            return f"Brillo actual: {int(cur / mx * 100)}%"
        if action == "set" and value is not None:
            v = max(5, min(100, value))
            subprocess.run(["brightnessctl", "set", f"{v}%"])
            return f"Brillo → {v}%"
        if action == "up":
            inc = value or 10
            subprocess.run(["brightnessctl", "set", f"+{inc}%"])
            return f"Brillo subido {inc}%"
        if action == "down":
            dec = value or 10
            subprocess.run(["brightnessctl", "set", f"{dec}%-"])
            return f"Brillo bajado {dec}%"
    except FileNotFoundError:
        return "brightnessctl no encontrado. Instala: sudo apt install brightnessctl"
    return f"Acción '{action}' ejecutada"


def power_action(action: str) -> str:
    system = platform.system()
    actions_linux = {
        "shutdown": ["systemctl", "poweroff"],
        "restart": ["systemctl", "reboot"],
        "sleep": ["systemctl", "suspend"],
    }
    actions_mac = {
        "shutdown": ["sudo", "shutdown", "-h", "now"],
        "restart": ["sudo", "shutdown", "-r", "now"],
        "sleep": ["pmset", "sleepnow"],
    }

    if action == "lock":
        if system == "Linux":
            for cmd in (
                ["loginctl", "lock-session"],
                ["gnome-screensaver-command", "-l"],
                ["xdg-screensaver", "lock"],
                ["i3lock"],
            ):
                try:
                    subprocess.Popen(cmd)
                    return "Pantalla bloqueada"
                except FileNotFoundError:
                    continue
            return "No se encontró un comando de bloqueo de pantalla"
        if system == "Darwin":
            subprocess.Popen(["pmset", "displaysleepnow"])
            return "Pantalla bloqueada"

    cmds = actions_linux if system == "Linux" else actions_mac
    if action in cmds:
        subprocess.Popen(cmds[action])
        labels = {"shutdown": "Apagando", "restart": "Reiniciando", "sleep": "Suspendiendo"}
        return f"{labels[action]} el sistema..."

    return f"Acción '{action}' no reconocida"
