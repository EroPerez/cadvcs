"""Test end-to-end de la API REST con fastapi.testclient.

Ejercita el flujo completo vía HTTP: crear repo, subir DXF, commit,
branches, switch, merge automático verificado descargando el blob
fusionado, merge con conflicto → 409 estructurado, locks → 423,
diff, log, tags y blame.
"""
import io
import os
import tempfile
from pathlib import Path

os.environ["CADVCS_DATA"] = tempfile.mkdtemp(prefix="cadvcs_api_")

import ezdxf
from fastapi.testclient import TestClient

from cadvcs.api.main import app

client = TestClient(app)


def dxf_bytes(build) -> bytes:
    """Construye un DXF en memoria y devuelve sus bytes."""
    doc = build()
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


def dxf_from_bytes(data: bytes):
    return ezdxf.read(io.StringIO(data.decode()))


def upload(path: str, data: bytes):
    r = client.put(f"/repos/nave/files/{path}", content=data,
                   headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    return r.json()


def check(label, cond):
    assert cond, f"FALLO: {label}"
    print(f"  {label} ✔")


# ---- crear repo --------------------------------------------------------
r = client.post("/repos", json={"name": "nave"})
check("POST /repos → 201", r.status_code == 201)
check("rama inicial main", r.json()["current_branch"] == "main")
check("nombre inválido rechazado",
      client.post("/repos", json={"name": "../evil"}).status_code == 422)
check("path traversal literal rechazado",
      client.put("/repos/nave/files/../../etc/passwd",
                 content=b"x").status_code in (400, 404))
check("path traversal URL-encoded rechazado (guard propio)",
      client.put("/repos/nave/files/%2e%2e/%2e%2e/etc/passwd",
                 content=b"x").status_code == 400)

# ---- v1: subir y commitear ----------------------------------------------
def planta_v1():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "MUROS"})
    msp.add_line((100, 0), (100, 50), dxfattribs={"layer": "MUROS"})
    msp.add_circle((50, 25), radius=5, dxfattribs={"layer": "COLUMNAS"})
    return doc

upload("plano.dxf", dxf_bytes(planta_v1))
r = client.get("/repos/nave/status")
check("status: plano.dxf como new", r.json()["new"] == ["plano.dxf"])

r = client.post("/repos/nave/commits",
                json={"author": "ero", "message": "Planta inicial"})
check("POST /commits → 201 (c1)", r.status_code == 201
      and r.json()["commit_id"] == 1)
check("commit sin cambios → 422",
      client.post("/repos/nave/commits",
                  json={"author": "ero"}).status_code == 422)

# ---- rama variante-b: maria mueve la columna ------------------------------
client.post("/repos/nave/branches", json={"name": "variante-b"})
r = client.post("/repos/nave/switch", json={"branch": "variante-b"})
check("switch a variante-b", r.json()["current_branch"] == "variante-b")

current = client.get("/repos/nave/files/plano.dxf").content
doc = dxf_from_bytes(current)
for c in doc.modelspace().query("CIRCLE"):
    c.dxf.center = (70, 30)
buf = io.StringIO(); doc.write(buf)
upload("plano.dxf", buf.getvalue().encode())
client.post("/repos/nave/commits",
            json={"author": "maria", "message": "Mover columna"})

# ---- en main: ero añade la puerta ------------------------------------------
client.post("/repos/nave/switch", json={"branch": "main"})
current = client.get("/repos/nave/files/plano.dxf").content
doc = dxf_from_bytes(current)
check("switch rematerializó main (columna en 50,25)",
      list(doc.modelspace().query("CIRCLE"))[0].dxf.center == (50, 25, 0))
doc.modelspace().add_arc((20, 0), radius=8, start_angle=0, end_angle=90,
                         dxfattribs={"layer": "PUERTAS"})
buf = io.StringIO(); doc.write(buf)
upload("plano.dxf", buf.getvalue().encode())
client.post("/repos/nave/commits",
            json={"author": "ero", "message": "Añadir puerta"})

# ---- diff vía API -----------------------------------------------------------
r = client.get("/repos/nave/diff",
               params={"ref_a": "main", "ref_b": "variante-b"})
d = r.json()["modified"]["plano.dxf"]
check("GET /diff con detalle semántico", len(d["modified"]) == 1
      and d["modified"][0]["dxftype"] == "CIRCLE")

# ---- merge automático --------------------------------------------------------
r = client.post("/repos/nave/merge",
                json={"branch": "variante-b", "author": "ero"})
check("POST /merge → merged", r.status_code == 200
      and r.json()["result"] == "merged")

merged = dxf_from_bytes(client.get("/repos/nave/files/plano.dxf").content)
msp = merged.modelspace()
check("merge trajo la columna movida",
      list(msp.query("CIRCLE"))[0].dxf.center == (70, 30, 0))
check("merge conservó la puerta", len(list(msp.query("ARC"))) == 1)

client.post("/repos/nave/tags", json={"name": "v1.0"})

# ---- conflicto modify/modify → 409 -------------------------------------------
client.post("/repos/nave/branches", json={"name": "propuesta-x"})
client.post("/repos/nave/switch", json={"branch": "propuesta-x"})
doc = dxf_from_bytes(client.get("/repos/nave/files/plano.dxf").content)
for c in doc.modelspace().query("CIRCLE"):
    c.dxf.center = (10, 10)
buf = io.StringIO(); doc.write(buf)
upload("plano.dxf", buf.getvalue().encode())
client.post("/repos/nave/commits", json={"author": "maria", "message": "a 10,10"})

client.post("/repos/nave/switch", json={"branch": "main"})
doc = dxf_from_bytes(client.get("/repos/nave/files/plano.dxf").content)
for c in doc.modelspace().query("CIRCLE"):
    c.dxf.center = (90, 40)
buf = io.StringIO(); doc.write(buf)
upload("plano.dxf", buf.getvalue().encode())
client.post("/repos/nave/commits", json={"author": "ero", "message": "a 90,40"})

r = client.post("/repos/nave/merge",
                json={"branch": "propuesta-x", "author": "ero"})
check("merge con conflicto → 409", r.status_code == 409)
conf = r.json()["conflicts"]["plano.dxf"][0]
check("conflicto estructurado modify/modify",
      conf["reason"] == "modify/modify" and conf["dxftype"] == "CIRCLE")
check("payload incluye ours y theirs",
      conf["ours"]["attrs"]["center"] != conf["theirs"]["attrs"]["center"])

# ---- locks vía API --------------------------------------------------------------
r = client.post("/repos/nave/locks", json={"path": "plano.dxf", "owner": "ero"})
check("POST /locks → 201", r.status_code == 201)
check("lock ajeno → 423",
      client.post("/repos/nave/locks",
                  json={"path": "plano.dxf", "owner": "maria"}).status_code == 423)
check("commit de otro autor con lock ajeno → 423",
      client.put("/repos/nave/files/plano.dxf", content=b"dummy").status_code == 200
      and client.post("/repos/nave/commits",
                      json={"author": "maria"}).status_code == 423)
# restaurar workdir y liberar
client.post("/repos/nave/switch", json={"branch": "main", "force": True})
check("DELETE /locks → 204",
      client.delete("/repos/nave/locks/plano.dxf",
                    params={"owner": "ero"}).status_code == 204)

# ---- log, blame, descarga histórica -----------------------------------------------
log = client.get("/repos/nave/commits").json()
check("log con merge commit decorado",
      any(c["is_merge"] and "v1.0" in c["tags"] for c in log))

blame = client.get("/repos/nave/blame/plano.dxf").json()
arc = next(b for b in blame if b["dxftype"] == "ARC")
check("blame atribuye la puerta a ero", arc["author"] == "ero"
      and arc["message"] == "Añadir puerta")

hist = dxf_from_bytes(
    client.get("/repos/nave/files/plano.dxf", params={"ref": "1"}).content)
check("descarga de versión histórica (c1: 3 entidades)",
      len(list(hist.modelspace())) == 3)

print("\nAPI OK — todos los checks pasan")
