from .system import get_system_info, get_battery_info, control_volume, control_brightness, power_action
from .apps import open_application, close_application, list_running_apps
from .files import search_files, open_file, list_directory, read_file, create_directory
from .web import open_url, web_search
from .clipboard import get_clipboard, set_clipboard
from .notifications import send_notification
from .shell import run_shell_command

TOOL_DEFINITIONS = [
    {
        "name": "get_system_info",
        "description": "Obtiene información del sistema: CPU, RAM, disco, uptime",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_battery_info",
        "description": "Obtiene estado de la batería: porcentaje, estado de carga, tiempo restante",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "control_volume",
        "description": "Controla el volumen del sistema (get/set/up/down/mute/unmute)",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "up", "down", "mute", "unmute"],
                    "description": "Acción de volumen",
                },
                "value": {
                    "type": "integer",
                    "description": "Valor 0-100 para 'set', o incremento para 'up'/'down'",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "control_brightness",
        "description": "Controla el brillo de la pantalla (get/set/up/down). Linux: requiere brightnessctl.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "up", "down"],
                    "description": "Acción de brillo",
                },
                "value": {
                    "type": "integer",
                    "description": "Valor 0-100 para 'set', o incremento para 'up'/'down'",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "power_action",
        "description": "Controla el estado de energía: apagar, reiniciar, suspender o bloquear pantalla",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["shutdown", "restart", "sleep", "lock"],
                    "description": "Acción de energía",
                }
            },
            "required": ["action"],
        },
    },
    {
        "name": "open_application",
        "description": "Abre una aplicación o programa",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nombre o comando de la aplicación (ej: firefox, code, spotify, nautilus)",
                }
            },
            "required": ["name"],
        },
    },
    {
        "name": "close_application",
        "description": "Cierra una aplicación por nombre de proceso",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nombre del proceso a cerrar",
                },
                "force": {
                    "type": "boolean",
                    "description": "Forzar cierre inmediato (SIGKILL). Default: false (SIGTERM)",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_running_apps",
        "description": "Lista los procesos/aplicaciones en ejecución con uso de memoria",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Filtro opcional por nombre de proceso",
                }
            },
            "required": [],
        },
    },
    {
        "name": "search_files",
        "description": "Busca archivos o directorios en el sistema de archivos",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Nombre o patrón a buscar (ej: '*.pdf', 'proyecto')",
                },
                "directory": {
                    "type": "string",
                    "description": "Directorio donde buscar. Default: ~ (home)",
                },
                "file_type": {
                    "type": "string",
                    "enum": ["any", "file", "directory"],
                    "description": "Tipo de elemento. Default: any",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "open_file",
        "description": "Abre un archivo con la aplicación predeterminada del sistema",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Ruta al archivo"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_directory",
        "description": "Lista el contenido de un directorio",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Ruta del directorio. Default: ~ (home)",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "Mostrar archivos ocultos (comenzando con punto)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "read_file",
        "description": "Lee el contenido de un archivo de texto",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Ruta al archivo"},
                "max_lines": {
                    "type": "integer",
                    "description": "Máximo de líneas a leer. Default: 100",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "create_directory",
        "description": "Crea un directorio (incluyendo directorios padre si no existen)",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Ruta del directorio a crear"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "open_url",
        "description": "Abre una URL en el navegador predeterminado",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL a abrir"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_search",
        "description": "Abre una búsqueda web en el navegador",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Término de búsqueda"},
                "engine": {
                    "type": "string",
                    "enum": ["google", "duckduckgo", "youtube"],
                    "description": "Motor de búsqueda. Default: google",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_clipboard",
        "description": "Obtiene el contenido actual del portapapeles",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_clipboard",
        "description": "Escribe texto en el portapapeles",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Texto a copiar"}
            },
            "required": ["text"],
        },
    },
    {
        "name": "send_notification",
        "description": "Envía una notificación de escritorio",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título"},
                "message": {"type": "string", "description": "Cuerpo del mensaje"},
                "urgency": {
                    "type": "string",
                    "enum": ["low", "normal", "critical"],
                    "description": "Nivel de urgencia. Default: normal",
                },
            },
            "required": ["title", "message"],
        },
    },
    {
        "name": "run_shell_command",
        "description": (
            "Ejecuta un comando de shell arbitrario. "
            "Usar solo cuando no haya herramienta dedicada. "
            "Timeout: 30 segundos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Comando a ejecutar"},
                "working_dir": {
                    "type": "string",
                    "description": "Directorio de trabajo. Default: ~",
                },
            },
            "required": ["command"],
        },
    },
]


def execute_tool(name: str, inputs: dict) -> str:
    handlers = {
        "get_system_info": lambda i: get_system_info(),
        "get_battery_info": lambda i: get_battery_info(),
        "control_volume": lambda i: control_volume(i.get("action"), i.get("value")),
        "control_brightness": lambda i: control_brightness(i.get("action"), i.get("value")),
        "power_action": lambda i: power_action(i["action"]),
        "open_application": lambda i: open_application(i["name"]),
        "close_application": lambda i: close_application(i["name"], i.get("force", False)),
        "list_running_apps": lambda i: list_running_apps(i.get("filter")),
        "search_files": lambda i: search_files(
            i["pattern"], i.get("directory", "~"), i.get("file_type", "any")
        ),
        "open_file": lambda i: open_file(i["path"]),
        "list_directory": lambda i: list_directory(
            i.get("path", "~"), i.get("show_hidden", False)
        ),
        "read_file": lambda i: read_file(i["path"], i.get("max_lines", 100)),
        "create_directory": lambda i: create_directory(i["path"]),
        "open_url": lambda i: open_url(i["url"]),
        "web_search": lambda i: web_search(i["query"], i.get("engine", "google")),
        "get_clipboard": lambda i: get_clipboard(),
        "set_clipboard": lambda i: set_clipboard(i["text"]),
        "send_notification": lambda i: send_notification(
            i["title"], i["message"], i.get("urgency", "normal")
        ),
        "run_shell_command": lambda i: run_shell_command(
            i["command"], i.get("working_dir", "~")
        ),
    }

    if name not in handlers:
        return f"Error: herramienta '{name}' no encontrada"

    try:
        return handlers[name](inputs)
    except Exception as e:
        return f"Error ejecutando {name}: {e}"
