"""Test de la gestión de sesión del CLI y del alias.

Cubre lo verificable sin un IdP real:
  - alias `cad` y `cadvcs` apuntan al mismo entry-point
  - almacén de credenciales: guardar/leer/borrar, permisos 0600, por-servidor
  - login --token (pegar una vez): se guarda y whoami lo lee
  - token helper: imprime el JWT (para curl/scripts)
  - whoami: muestra usuario, roles y caducidad decodificando el JWT
  - logout: borra la sesión
  - resolver de --user: tras login, commit no necesita --user
  - password grant: construcción de la petición contra un IdP simulado
"""
import base64
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Config aislada para no tocar credenciales reales del usuario
os.environ["CADVCS_CONFIG_DIR"] = tempfile.mkdtemp(prefix="cadvcs_cfg_")

from cadvcs import auth_store


def check(label, cond):
    assert cond, f"FALLO: {label}"
    print(f"  {label} ✔")


def make_jwt(claims: dict) -> str:
    """JWT no firmado (alg=none) solo para tests de decodificación."""
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b64({'alg':'none','typ':'JWT'})}.{b64(claims)}.sig"


def run_cli(*argv, env_extra=None, cwd=None):
    """Ejecuta el CLI como subproceso, devuelve (rc, stdout, stderr)."""
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    r = subprocess.run([sys.executable, "-m", "cadvcs.cli", *argv],
                       capture_output=True, text=True, env=env, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


# ---- 1. almacén de credenciales -------------------------------------------
tok1 = make_jwt({"sub": "ero", "preferred_username": "ero",
                 "roles": ["editor"], "exp": int(time.time()) + 3600})
auth_store.save_token(tok1, "http://localhost:8000")
check("guardar y leer token", auth_store.get_token("http://localhost:8000") == tok1)
check("normaliza la barra final",
      auth_store.get_token("http://localhost:8000/") == tok1)

creds = auth_store.config_dir() / "credentials.json"
mode = stat.S_IMODE(creds.stat().st_mode)
check("permisos 0600 en credentials.json", mode == 0o600)

# por-servidor: dos sesiones a la vez
tok2 = make_jwt({"sub": "maria", "roles": ["admin"]})
auth_store.save_token(tok2, "https://prod.example.com", make_default=False)
check("sesiones independientes por servidor",
      auth_store.get_token("https://prod.example.com") == tok2 and
      auth_store.get_token("http://localhost:8000") == tok1)
check("el default sigue siendo el primero",
      auth_store.current_server() == "http://localhost:8000")

# ---- 2. caducidad ----------------------------------------------------------
expired = make_jwt({"sub": "x", "exp": int(time.time()) - 10})
check("detecta token caducado", auth_store.is_expired(expired))
check("token vigente no marcado como caducado", not auth_store.is_expired(tok1))

# ---- 3. alias cad == cadvcs ------------------------------------------------
# Sin tomllib (no existe en 3.10): comprobamos las líneas del [project.scripts].
import re
pyproject = Path("pyproject.toml").read_text()
scripts_block = pyproject.split("[project.scripts]", 1)[1].split("[", 1)[0]
entries = dict(re.findall(r'(\w+)\s*=\s*"([^"]+)"', scripts_block))
check("alias 'cad' apunta al mismo entry-point que 'cadvcs'",
      entries.get("cad") == entries.get("cadvcs") == "cadvcs.cli:main")

# ---- 4. login --token / whoami / token / logout por CLI --------------------
cfg = tempfile.mkdtemp(prefix="cadvcs_cli_")
env = {"CADVCS_CONFIG_DIR": cfg}
sess_tok = make_jwt({"sub": "ana", "preferred_username": "ana",
                     "roles": ["editor"], "exp": int(time.time()) + 7200})

rc, out, err = run_cli("login", "--token", sess_tok,
                       "--server", "http://localhost:8000", env_extra=env)
check("login --token guarda la sesión", rc == 0 and "guardada" in out and "ana" in out)

rc, out, err = run_cli("whoami", "--server", "http://localhost:8000", env_extra=env)
check("whoami muestra usuario y roles",
      rc == 0 and "ana" in out and "editor" in out and "caduca en" in out)

rc, out, err = run_cli("token", "--server", "http://localhost:8000", env_extra=env)
check("token imprime el JWT para scripts", rc == 0 and out.strip() == sess_tok)

rc, out, err = run_cli("logout", "--server", "http://localhost:8000", env_extra=env)
check("logout borra la sesión", rc == 0 and "cerrada" in out)
rc, out, err = run_cli("whoami", "--server", "http://localhost:8000", env_extra=env)
check("tras logout no hay sesión", rc == 1 and "No hay sesión" in out)

# ---- 5. resolver de --user: commit sin --user tras login -------------------
work = Path(tempfile.mkdtemp())
w = str(work)
run_cli("init", cwd=w)
# DXF con contenido real (uno vacío daría "nada que commitear")
import ezdxf
d = ezdxf.new("R2010"); d.modelspace().add_circle((1, 1), 2); d.saveas(work / "p.dxf")
run_cli("add", "p.dxf", cwd=w)

cfg_empty = tempfile.mkdtemp(prefix="cadvcs_empty_")
# Sin --user, sin login (cfg vacío) y CADVCS_USER vacío → error claro
rc, out, err = run_cli("commit", "-m", "v1", cwd=w,
                       env_extra={"CADVCS_CONFIG_DIR": cfg_empty, "CADVCS_USER": ""})
check("commit sin identidad da error claro",
      rc == 1 and "No sé quién eres" in err)

# Con CADVCS_USER → funciona sin --user
rc, out, err = run_cli("commit", "-m", "v1", cwd=w,
                       env_extra={"CADVCS_CONFIG_DIR": cfg_empty, "CADVCS_USER": "ero"})
check("CADVCS_USER provee la identidad sin --user", rc == 0)

# Tras login, el usuario sale del token (cfg con sesión de ana)
cfg_login = tempfile.mkdtemp(prefix="cadvcs_login_")
run_cli("login", "--token", sess_tok, "--server", "http://localhost:8000",
        env_extra={"CADVCS_CONFIG_DIR": cfg_login})
d = ezdxf.readfile(work / "p.dxf"); d.modelspace().add_point((3, 3))
d.saveas(work / "p.dxf")  # algo nuevo que commitear
rc, out, err = run_cli("commit", "-m", "v2", cwd=w,
                       env_extra={"CADVCS_CONFIG_DIR": cfg_login, "CADVCS_USER": ""})
check("tras login, commit toma el usuario del token (ana)",
      rc == 0 and "c2" in out)

# ---- 6. password grant contra un IdP simulado ------------------------------
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

issued = make_jwt({"sub": "juan", "preferred_username": "juan",
                   "roles": ["editor"]})
received = {}


class IdP(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if "openid-configuration" in self.path:
            body = json.dumps({
                "issuer": f"http://localhost:{self.server.server_port}",
                "token_endpoint": f"http://localhost:{self.server.server_port}/token",
            }).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        received["body"] = self.rfile.read(n).decode()
        body = json.dumps({"access_token": issued, "token_type": "Bearer"}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(body)


srv = HTTPServer(("localhost", 0), IdP)
threading.Thread(target=srv.serve_forever, daemon=True).start()
issuer = f"http://localhost:{srv.server_port}"

from cadvcs import login as login_mod
got = login_mod.password_grant("juan", "secreto", issuer=issuer, client_id="cadvcs")
check("password grant devuelve el access_token del IdP", got == issued)
check("la petición usó grant_type=password con el usuario",
      "grant_type=password" in received["body"] and "username=juan" in received["body"])
srv.shutdown()

print("\nGestión de sesión del CLI OK — todos los checks pasan")
