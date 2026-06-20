import subprocess
from pathlib import Path
from typing import Optional
import platform


def search_files(
    pattern: str, directory: str = "~", file_type: str = "any"
) -> str:
    search_dir = Path(directory).expanduser()
    if not search_dir.exists():
        return f"Directorio '{directory}' no encontrado"

    type_flag = []
    if file_type == "file":
        type_flag = ["-type", "f"]
    elif file_type == "directory":
        type_flag = ["-type", "d"]

    try:
        cmd = [
            "find", str(search_dir),
            "-maxdepth", "6",
            "-iname", f"*{pattern}*",
        ] + type_flag
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        lines = [l for l in result.stdout.strip().split("\n") if l]
        if not lines:
            return f"No se encontraron elementos con patrón '{pattern}' en {directory}"
        total = len(lines)
        shown = lines[:20]
        out = f"Encontrado(s): {total} resultado(s)\n"
        out += "\n".join(f"  {l}" for l in shown)
        if total > 20:
            out += f"\n  ... y {total - 20} más"
        return out
    except subprocess.TimeoutExpired:
        return "Búsqueda tardó demasiado. Especifica un directorio más concreto."
    except Exception as e:
        return f"Error en búsqueda: {e}"


def open_file(path: str) -> str:
    file_path = Path(path).expanduser()
    if not file_path.exists():
        return f"Archivo '{path}' no encontrado"
    system = platform.system()
    try:
        if system == "Linux":
            subprocess.Popen(["xdg-open", str(file_path)])
        elif system == "Darwin":
            subprocess.Popen(["open", str(file_path)])
        return f"Abriendo {file_path.name}..."
    except Exception as e:
        return f"Error al abrir '{path}': {e}"


def list_directory(path: str = "~", show_hidden: bool = False) -> str:
    dir_path = Path(path).expanduser()
    if not dir_path.exists():
        return f"'{path}' no existe"
    if not dir_path.is_dir():
        return f"'{path}' no es un directorio"
    try:
        items = sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        if not show_hidden:
            items = [i for i in items if not i.name.startswith(".")]
        lines = [f"Contenido de {dir_path}:"]
        for item in items[:40]:
            if item.is_dir():
                lines.append(f"  [DIR]  {item.name}/")
            else:
                size = item.stat().st_size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024**2:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / 1024**2:.1f} MB"
                lines.append(f"  [FILE] {item.name:<42} {size_str:>10}")
        if len(items) > 40:
            lines.append(f"  ... y {len(items) - 40} elementos más")
        return "\n".join(lines)
    except PermissionError:
        return f"Sin permiso para leer '{path}'"


def read_file(path: str, max_lines: int = 100) -> str:
    file_path = Path(path).expanduser()
    if not file_path.exists():
        return f"Archivo '{path}' no encontrado"
    if not file_path.is_file():
        return f"'{path}' no es un archivo"
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        truncated = len(lines) > max_lines
        snippet = "\n".join(lines[:max_lines])
        result = f"--- {file_path.name} ---\n{snippet}"
        if truncated:
            result += f"\n\n[... truncado a {max_lines} de {len(lines)} líneas]"
        return result
    except Exception as e:
        return f"Error al leer '{path}': {e}"


def create_directory(path: str) -> str:
    dir_path = Path(path).expanduser()
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        return f"Directorio creado: {dir_path}"
    except Exception as e:
        return f"Error al crear directorio: {e}"
