"""Almacén de credenciales del CLI.

Guarda el token de sesión en disco para no tener que pegarlo a mano en
cada llamada a la API o a la Web UI. Ubicación estándar XDG
(`~/.config/cadvcs/credentials.json`, o `$CADVCS_CONFIG_DIR` si se define),
con permisos 0600 (solo el dueño lee/escribe) porque un token es secreto.

El almacén guarda por *servidor* (URL base de la API): así puedes tener
sesiones distintas contra varios despliegues a la vez. El servidor "por
defecto" es el que se usa cuando no se especifica ninguno.
"""
from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path


def config_dir() -> Path:
    override = os.environ.get("CADVCS_CONFIG_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "cadvcs"


def _creds_path() -> Path:
    return config_dir() / "credentials.json"


def _load_all() -> dict:
    path = _creds_path()
    if not path.exists():
        return {"default_server": None, "servers": {}}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"default_server": None, "servers": {}}


def _save_all(data: dict) -> None:
    path = _creds_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Escribir y restringir permisos a 0600 (rw solo del dueño)
    path.write_text(json.dumps(data, indent=2))
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass  # algunos sistemas de archivos no soportan chmod


def normalize_server(server: str | None) -> str:
    """URL base sin barra final. None → variable de entorno o localhost."""
    server = (server or os.environ.get("CADVCS_SERVER")
              or "http://localhost:8000")
    return server.rstrip("/")


def save_token(token: str, server: str | None = None,
               make_default: bool = True) -> str:
    server = normalize_server(server)
    data = _load_all()
    data["servers"][server] = {"token": token, "saved_at": int(time.time())}
    if make_default or not data.get("default_server"):
        data["default_server"] = server
    _save_all(data)
    return server


def get_token(server: str | None = None) -> str | None:
    data = _load_all()
    if server is None:
        server = os.environ.get("CADVCS_SERVER") or data.get("default_server")
    if server is None:
        return None
    entry = data["servers"].get(normalize_server(server))
    return entry["token"] if entry else None


def clear_token(server: str | None = None) -> bool:
    """Borra la sesión de un servidor (o del default). True si había algo."""
    data = _load_all()
    if server is None:
        server = data.get("default_server")
    if server is None:
        return False
    server = normalize_server(server)
    existed = data["servers"].pop(server, None) is not None
    if data.get("default_server") == server:
        # elegir otro default si queda alguno
        data["default_server"] = next(iter(data["servers"]), None)
    _save_all(data)
    return existed


def current_server() -> str | None:
    data = _load_all()
    return os.environ.get("CADVCS_SERVER") or data.get("default_server")


def list_sessions() -> dict:
    data = _load_all()
    return {"default": data.get("default_server"),
            "servers": list(data["servers"].keys())}


# --------------------------------------------------------------------------
# Utilidades de token (decodificación sin verificar firma: solo para mostrar
# al usuario su identidad y caducidad; la VERIFICACIÓN real la hace la API).
# --------------------------------------------------------------------------
def decode_claims(token: str) -> dict:
    """Decodifica el payload de un JWT sin verificar la firma.

    Es seguro para 'whoami' porque solo se usa para mostrar info al
    usuario; nunca para autorizar. La API siempre re-verifica la firma.
    """
    import base64
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("no parece un JWT (se esperaban 3 partes)")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)  # repad base64url
    return json.loads(base64.urlsafe_b64decode(payload))


def token_expiry(token: str) -> int | None:
    try:
        return decode_claims(token).get("exp")
    except Exception:
        return None


def is_expired(token: str, skew: int = 0) -> bool:
    exp = token_expiry(token)
    if exp is None:
        return False  # sin exp: no podemos afirmar que caducó
    return time.time() + skew >= exp
