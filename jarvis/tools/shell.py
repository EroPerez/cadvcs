import subprocess
from pathlib import Path


def run_shell_command(command: str, working_dir: str = "~") -> str:
    cwd = Path(working_dir).expanduser()
    if not cwd.exists():
        cwd = Path.home()
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=30,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n" if output else "") + f"[stderr] {result.stderr}"
        if not output.strip():
            return f"Comando ejecutado. Código de retorno: {result.returncode}"
        if len(output) > 2000:
            output = output[:2000] + "\n... (truncado)"
        return output.strip()
    except subprocess.TimeoutExpired:
        return "Error: el comando superó el límite de 30 segundos"
    except Exception as e:
        return f"Error ejecutando comando: {e}"
