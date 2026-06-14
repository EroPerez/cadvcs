"""Test del indexado asíncrono: transactional outbox + worker.

Propiedades verificadas:
  1. commit NO indexa: tras commitear, entities está vacía y hay un
     evento pending en el outbox (el coste de parseo sale del path)
  2. el worker drena el outbox y entonces entities se puebla
  3. red de seguridad: un diff/blame ANTES de que el worker corra
     indexa bajo demanda y cierra el evento (correctitud no depende
     del worker; solo la latencia)
  4. dedup: un blob ya indexado no genera evento
  5. idempotencia: drenar dos veces no duplica ni falla
  6. el worker multi-repo recorre todos los repos bajo CADVCS_DATA
"""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("CADVCS_DATA", tempfile.mkdtemp(prefix="cadvcs_async_"))

import ezdxf

from cadvcs.repo import Repo
from cadvcs import worker


def check(label, cond):
    assert cond, f"FALLO: {label}"
    print(f"  {label} ✔")


def count(repo, table, where=""):
    return repo.conn.execute(
        f"SELECT COUNT(*) AS n FROM {table} {where}").fetchone()["n"]


DATA = Path(os.environ["CADVCS_DATA"])
work = DATA / "nave"
repo = Repo.init(work)
p = work / "plano.dxf"


def edit(fn):
    doc = ezdxf.readfile(p) if p.exists() else ezdxf.new("R2010")
    fn(doc.modelspace())
    doc.saveas(p)


# ---- 1. commit no indexa, encola evento -----------------------------------
edit(lambda m: (m.add_line((0, 0), (100, 0)), m.add_circle((50, 25), 5)))
repo.add(p)
info = repo.commit("ero", "c1")
sha = repo._tree(info["commit_id"])["plano.dxf"]["blob_sha"]
check("entities vacía tras commit (no indexa síncrono)",
      count(repo, "entities") == 0)
check("evento pending en el outbox",
      count(repo, "index_outbox", "WHERE status='pending'") == 1)

# ---- 2. el worker drena y puebla entities ----------------------------------
totals = worker.drain_once("nave")
check("worker indexa el blob", totals["done"] == 1 and totals["failed"] == 0)
check("entities poblada tras el worker", count(repo, "entities") == 2)
check("evento marcado done",
      count(repo, "index_outbox", "WHERE status='done'") == 1
      and count(repo, "index_outbox", "WHERE status='pending'") == 0)

# ---- 3. red de seguridad: lectura on-demand antes del worker ------------------
repo.branch_create("v2"); repo.switch("v2")
edit(lambda m: [setattr(c.dxf, "center", (70, 30)) for c in m.query("CIRCLE")])
info2 = repo.commit("maria", "c2 mover")
sha2 = repo._tree(info2["commit_id"])["plano.dxf"]["blob_sha"]
check("nuevo evento pending (sin worker aún)",
      count(repo, "index_outbox", "WHERE status='pending'") == 1)
# Un diff fuerza la lectura del blob nuevo → indexado on-demand
d = repo.diff("main", "v2")
check("diff correcto SIN haber corrido el worker para sha2",
      len(d["modified"]["plano.dxf"].modified) == 1)
check("la lectura on-demand cerró el evento outbox",
      count(repo, "index_outbox", "WHERE status='pending'") == 0)

# ---- 4. dedup: un blob ya indexado no genera evento ---------------------------
# Provocamos bytes idénticos copiando el archivo tal cual a otra rama:
# mismo SHA → si ya está indexado, no se encola un segundo evento.
repo.switch("main")
worker.drain_once("nave")                       # asegurar main indexado
main_sha = repo._tree(repo.head_commit_id())["plano.dxf"]["blob_sha"]
repo.branch_create("dup"); repo.switch("dup")
edit(lambda m: m.add_arc((300, 0), radius=3, start_angle=0, end_angle=90))
repo.commit("ero", "c-dup arco lejano")
# revertir a los bytes EXACTOS del blob de main (mismo SHA garantizado)
repo.store.get(main_sha, p)
info_dup = repo.commit("ero", "c-dup vuelve a bytes de main")
check("blob idéntico a uno ya indexado no encola evento",
      repo.conn.execute(
          "SELECT COUNT(*) AS n FROM index_outbox WHERE blob_sha=? "
          "AND status='pending'", (main_sha,)).fetchone()["n"] == 0)

# ---- 5. idempotencia del drenado ----------------------------------------------
worker.drain_once("nave")                       # drena pendientes legítimos
t2 = worker.drain_once("nave")
check("drain sobre outbox vacío no reprocesa",
      t2["done"] == 0 and t2["failed"] == 0)

# ---- 6. worker multi-repo -----------------------------------------------------
repo_b = Repo.init(DATA / "otra")
pb = DATA / "otra" / "x.dxf"
doc = ezdxf.new("R2010"); doc.modelspace().add_circle((1, 1), 2); doc.saveas(pb)
repo_b.add(pb); repo_b.commit("ana", "c1 otra")
totals = worker.drain_once()  # sin filtro: todos los repos
check("worker multi-repo recorre todos los repos bajo CADVCS_DATA",
      totals["repos"] == 2 and totals["done"] == 1)

print("\nIndexado asíncrono OK — todos los checks pasan")
