"""Test end-to-end de la API: OIDC real + resolución interactiva.

Setup OIDC autocontenido: genera un par RSA, publica la clave pública
como JWKS en fichero, y firma JWTs RS256 para 'ero' y 'maria'. La API
valida firma, exp, audience e issuer — la ruta de producción completa
salvo el fetch HTTP del JWKS.

Flujo probado:
  1. Casos 401: sin token, firma de otra clave, token expirado, aud mala
  2. Identidad desde el token: commits con author = preferred_username
  3. Conflicto modify/modify → 409 → POST /merge/resolve {theirs} → 200
     y verificación del blob fusionado
  4. Segunda ronda de conflicto resuelta con 'ours'
  5. Resolución parcial: 2 conflictos, 1 resolución → 409 con el restante
  6. Locks con owner del token
"""
import io
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

# ---- setup OIDC ANTES de importar la app -----------------------------------
ISSUER, AUDIENCE = "https://idp.test", "cadvcs"
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_evil_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_key.public_key()))
_jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
_jwks_path = Path(tempfile.mkdtemp()) / "jwks.json"
_jwks_path.write_text(json.dumps({"keys": [_jwk]}))

os.environ.update({
    "CADVCS_DATA": tempfile.mkdtemp(prefix="cadvcs_api_"),
    "CADVCS_OIDC_ISSUER": ISSUER,
    "CADVCS_OIDC_AUDIENCE": AUDIENCE,
    "CADVCS_OIDC_JWKS_FILE": str(_jwks_path),
})

import ezdxf
from fastapi.testclient import TestClient

from cadvcs.api.main import app

client = TestClient(app)


def mint(username: str, *, key=_key, aud=AUDIENCE, exp_offset=3600) -> str:
    return jwt.encode(
        {"sub": str(uuid.uuid5(uuid.NAMESPACE_DNS, username)),
         "preferred_username": username, "iss": ISSUER, "aud": aud,
         "exp": int(time.time()) + exp_offset, "iat": int(time.time())},
        key, algorithm="RS256", headers={"kid": "test-key"})


ERO = {"Authorization": f"Bearer {mint('ero')}"}
MARIA = {"Authorization": f"Bearer {mint('maria')}"}


def check(label, cond):
    assert cond, f"FALLO: {label}"
    print(f"  {label} ✔")


def upload(path: str, data: bytes, headers=ERO):
    r = client.put(f"/repos/nave/files/{path}", content=data, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def get_dxf(ref="HEAD"):
    data = client.get("/repos/nave/files/plano.dxf",
                      params={"ref": ref}, headers=ERO).content
    return ezdxf.read(io.StringIO(data.decode()))


def put_dxf(doc, headers=ERO):
    buf = io.StringIO()
    doc.write(buf)
    upload("plano.dxf", buf.getvalue().encode(), headers)


def circle_center(doc):
    return list(doc.modelspace().query("CIRCLE"))[0].dxf.center


# ---- 1. casos 401 ------------------------------------------------------------
check("sin token → 401",
      client.get("/repos").status_code == 401)
check("firma de otra clave → 401",
      client.get("/repos", headers={
          "Authorization": f"Bearer {mint('ero', key=_evil_key)}"
      }).status_code == 401)
check("token expirado → 401",
      client.get("/repos", headers={
          "Authorization": f"Bearer {mint('ero', exp_offset=-60)}"
      }).status_code == 401)
check("audience incorrecta → 401",
      client.get("/repos", headers={
          "Authorization": f"Bearer {mint('ero', aud='otra-api')}"
      }).status_code == 401)
check("token válido → 200", client.get("/repos", headers=ERO).status_code == 200)

# ---- 2. identidad desde el token -----------------------------------------------
client.post("/repos", json={"name": "nave"}, headers=ERO)

def planta():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "MUROS"})
    msp.add_circle((50, 25), radius=5, dxfattribs={"layer": "COLUMNAS"})
    return doc

put_dxf(planta())
r = client.post("/repos/nave/commits", json={"message": "Planta inicial"},
                headers=ERO)
check("commit sin author en body (sale del JWT)", r.status_code == 201)
log = client.get("/repos/nave/commits", headers=ERO).json()
check("author del commit = preferred_username del token",
      log[0]["author"] == "ero")

# ---- 3. conflicto → 409 → resolve theirs → 200 -----------------------------------
client.post("/repos/nave/branches", json={"name": "propuesta"}, headers=ERO)
client.post("/repos/nave/switch", json={"branch": "propuesta"}, headers=MARIA)
doc = get_dxf()
for c in doc.modelspace().query("CIRCLE"):
    c.dxf.center = (10, 10)
put_dxf(doc, MARIA)
client.post("/repos/nave/commits", json={"message": "Columna a 10,10"},
            headers=MARIA)

client.post("/repos/nave/switch", json={"branch": "main"}, headers=ERO)
doc = get_dxf()
for c in doc.modelspace().query("CIRCLE"):
    c.dxf.center = (90, 40)
put_dxf(doc)
client.post("/repos/nave/commits", json={"message": "Columna a 90,40"},
            headers=ERO)

r = client.post("/repos/nave/merge", json={"branch": "propuesta"}, headers=ERO)
check("merge conflictivo → 409", r.status_code == 409)
conflict = r.json()["conflicts"]["plano.dxf"][0]
handle = conflict["handle"]
check("payload con handle y ambos lados",
      conflict["reason"] == "modify/modify"
      and conflict["ours"]["attrs"]["center"] == [90.0, 40.0, 0.0]
      and conflict["theirs"]["attrs"]["center"] == [10.0, 10.0, 0.0])

r = client.post("/repos/nave/merge/resolve",
                json={"branch": "propuesta",
                      "resolutions": {"plano.dxf": {handle: "theirs"}}},
                headers=ERO)
check("resolve theirs → 200 merged", r.status_code == 200
      and r.json()["result"] == "merged")
check("detalle registra la resolución manual",
      "resueltas manualmente" in r.json()["details"]["plano.dxf"])
check("blob fusionado tiene el valor de theirs",
      circle_center(get_dxf()) == (10, 10, 0))
log = client.get("/repos/nave/commits", headers=ERO).json()
check("merge commit con dos padres y author del token",
      log[0]["is_merge"] and log[0]["author"] == "ero")

# ---- 4. segunda ronda resuelta con ours ----------------------------------------------
client.post("/repos/nave/branches", json={"name": "propuesta-2"}, headers=ERO)
client.post("/repos/nave/switch", json={"branch": "propuesta-2"}, headers=MARIA)
doc = get_dxf()
for c in doc.modelspace().query("CIRCLE"):
    c.dxf.center = (1, 1)
put_dxf(doc, MARIA)
client.post("/repos/nave/commits", json={"message": "a 1,1"}, headers=MARIA)

client.post("/repos/nave/switch", json={"branch": "main"}, headers=ERO)
doc = get_dxf()
for c in doc.modelspace().query("CIRCLE"):
    c.dxf.center = (99, 49)
put_dxf(doc)
client.post("/repos/nave/commits", json={"message": "a 99,49"}, headers=ERO)

r = client.post("/repos/nave/merge/resolve",
                json={"branch": "propuesta-2",
                      "resolutions": {"plano.dxf": {handle: "ours"}}},
                headers=ERO)
check("resolve ours → 200 y conserva el valor de main",
      r.status_code == 200 and circle_center(get_dxf()) == (99, 49, 0))

# ---- 5. resolución parcial → 409 con lo restante -----------------------------------------
client.post("/repos/nave/branches", json={"name": "propuesta-3"}, headers=ERO)
client.post("/repos/nave/switch", json={"branch": "propuesta-3"}, headers=MARIA)
doc = get_dxf()
msp = doc.modelspace()
for c in msp.query("CIRCLE"):
    c.dxf.center = (2, 2)
line = list(msp.query("LINE"))[0]
line.dxf.end = (200, 0)
line_handle = line.dxf.handle
put_dxf(doc, MARIA)
client.post("/repos/nave/commits", json={"message": "círculo y muro"},
            headers=MARIA)

client.post("/repos/nave/switch", json={"branch": "main"}, headers=ERO)
doc = get_dxf()
msp = doc.modelspace()
for c in msp.query("CIRCLE"):
    c.dxf.center = (3, 3)
list(msp.query("LINE"))[0].dxf.end = (300, 0)
put_dxf(doc)
client.post("/repos/nave/commits", json={"message": "círculo y muro v2"},
            headers=ERO)

r = client.post("/repos/nave/merge", json={"branch": "propuesta-3"}, headers=ERO)
check("dos conflictos detectados",
      r.status_code == 409 and len(r.json()["conflicts"]["plano.dxf"]) == 2)

r = client.post("/repos/nave/merge/resolve",
                json={"branch": "propuesta-3",
                      "resolutions": {"plano.dxf": {handle: "theirs"}}},
                headers=ERO)
remaining = r.json()["conflicts"]["plano.dxf"]
check("resolución parcial → 409 solo con el conflicto restante",
      r.status_code == 409 and len(remaining) == 1
      and remaining[0]["handle"] == line_handle)

r = client.post("/repos/nave/merge/resolve",
                json={"branch": "propuesta-3",
                      "resolutions": {"plano.dxf": {handle: "theirs",
                                                    line_handle: "ours"}}},
                headers=ERO)
doc = get_dxf()
check("resolución completa mixta → 200",
      r.status_code == 200
      and circle_center(doc) == (2, 2, 0)                       # theirs
      and list(doc.modelspace().query("LINE"))[0].dxf.end == (300, 0, 0))  # ours

# ---- 6. locks con identidad del token --------------------------------------------------------
r = client.post("/repos/nave/locks", json={"path": "plano.dxf"}, headers=ERO)
check("lock con owner del JWT", r.status_code == 201
      and r.json()["owner"] == "ero")
check("maria no puede adquirirlo → 423",
      client.post("/repos/nave/locks", json={"path": "plano.dxf"},
                  headers=MARIA).status_code == 423)
check("maria no puede liberarlo → 423",
      client.delete("/repos/nave/locks/plano.dxf",
                    headers=MARIA).status_code == 423)
check("ero lo libera → 204",
      client.delete("/repos/nave/locks/plano.dxf",
                    headers=ERO).status_code == 204)

print("\nAPI OK — todos los checks pasan")
