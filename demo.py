"""Demo end-to-end: branches, merge a nivel de entidad, conflictos, blame.

Escenario:
  c1 (main)        ero crea la planta: 2 muros + 1 columna
  ├─ variante-b    maria mueve la columna             (c2)
  └─ main          ero añade una puerta (ARC)          (c3)
  c4 = merge variante-b → main  SIN conflicto: cambios en entidades
       distintas se fusionan automáticamente
  Luego: dos ramas mueven la MISMA columna a sitios distintos → conflicto
  modify/modify detectado y merge abortado.
"""
import shutil
import tempfile
from pathlib import Path

import ezdxf

from cadvcs.repo import Repo, MergeConflictError

work = Path(tempfile.mkdtemp(prefix="cadvcs_git_"))
print(f"Workspace: {work}\n")

repo = Repo.init(work)
plano = work / "plano.dxf"

# ---- c1 en main -----------------------------------------------------------
doc = ezdxf.new("R2010")
msp = doc.modelspace()
msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "MUROS"})
msp.add_line((100, 0), (100, 50), dxfattribs={"layer": "MUROS"})
msp.add_circle((50, 25), radius=5, dxfattribs={"layer": "COLUMNAS"})
doc.saveas(plano)

repo.add(plano)
print("status:", repo.status())
c1 = repo.commit("ero", "Planta inicial")
print(f"c{c1['commit_id']} en {c1['branch']}\n")

# ---- rama variante-b: maria mueve la columna -------------------------------
repo.branch_create("variante-b")
repo.switch("variante-b")
doc = ezdxf.readfile(plano)
for c in doc.modelspace().query("CIRCLE"):
    c.dxf.center = (70, 30)
doc.saveas(plano)
c2 = repo.commit("maria", "Mover columna a (70,30)")
print(f"c{c2['commit_id']} en variante-b")

# ---- de vuelta en main: ero añade una puerta -------------------------------
repo.switch("main")
doc = ezdxf.readfile(plano)  # switch rematerializó la versión de main
assert list(doc.modelspace().query("CIRCLE"))[0].dxf.center == (50, 25, 0), \
    "switch debe restaurar el estado de main"
doc.modelspace().add_arc((20, 0), radius=8, start_angle=0, end_angle=90,
                         dxfattribs={"layer": "PUERTAS"})
doc.saveas(plano)
c3 = repo.commit("ero", "Añadir puerta")
print(f"c{c3['commit_id']} en main\n")

# ---- diff entre ramas -------------------------------------------------------
d = repo.diff("main", "variante-b")
print("diff main → variante-b:")
for rp, sd in d["modified"].items():
    print(f"  {rp}: {sd.summary()}")

# ---- merge sin conflicto: entidades distintas -------------------------------
info = repo.merge("variante-b", author="ero")
print(f"\nmerge variante-b → main: {info['result']} c{info['commit_id']}")
for rp, detail in info["details"].items():
    print(f"  {rp}: {detail}")

doc = ezdxf.readfile(plano)
msp = doc.modelspace()
circle = list(msp.query("CIRCLE"))[0]
arcs = list(msp.query("ARC"))
assert circle.dxf.center == (70, 30, 0), "el merge debe traer la columna movida"
assert len(arcs) == 1, "el merge debe conservar la puerta de main"
print("verificación: columna movida ✔  puerta conservada ✔")

repo.tag_create("v1.0")

# ---- conflicto modify/modify -------------------------------------------------
repo.branch_create("propuesta-x")
repo.switch("propuesta-x")
doc = ezdxf.readfile(plano)
for c in doc.modelspace().query("CIRCLE"):
    c.dxf.center = (10, 10)
doc.saveas(plano)
repo.commit("maria", "Columna a (10,10)")

repo.switch("main")
doc = ezdxf.readfile(plano)
for c in doc.modelspace().query("CIRCLE"):
    c.dxf.center = (90, 40)
doc.saveas(plano)
repo.commit("ero", "Columna a (90,40)")

print("\nmerge propuesta-x → main (misma entidad movida en ambas ramas):")
try:
    repo.merge("propuesta-x", author="ero")
    raise AssertionError("debería haber conflicto")
except MergeConflictError as exc:
    for rp, confs in exc.details.items():
        for c in confs:
            print(f"  CONFLICTO {rp}: {c.reason} {c.dxftype} handle={c.handle}")
            print(f"    ours:   center={c.ours['attrs'].get('center')}")
            print(f"    theirs: center={c.theirs['attrs'].get('center')}")

# El workdir queda restaurado a main tras el conflicto
doc = ezdxf.readfile(plano)
assert list(doc.modelspace().query("CIRCLE"))[0].dxf.center == (90, 40, 0)
print("workdir restaurado a main tras conflicto ✔")

# ---- log y blame ---------------------------------------------------------------
print("\n--- log main ---")
for c in repo.log("HEAD"):
    refs = c["branches"] + c["tags"]
    deco = f" ({', '.join(refs)})" if refs else ""
    merge_mark = " [merge]" if c["is_merge"] else ""
    print(f"c{c['id']}{merge_mark}{deco}  {c['author']:<6} {c['message']}")

print("\n--- blame plano.dxf ---")
for row in repo.blame("plano.dxf"):
    print(f"c{row.get('commit_id','?'):<3} {row.get('author','?'):<6} "
          f"{row['dxftype']:<8} handle={row['handle']:<4} "
          f"«{row.get('message','')}»")

shutil.rmtree(work)
print("\nDemo OK")
