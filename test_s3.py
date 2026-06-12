"""Test end-to-end del blob store S3 (moto: API S3 fiel en memoria).

Cubre lo específico del backend:
  - flujo core completo (branches, merge, conflicto, blame) con los
    blobs viviendo en el bucket — repo.py no nota la diferencia
  - layout de claves objects/ab/cdef... bajo el prefijo configurado
  - dedup: re-put del mismo contenido no re-sube (un solo objeto)
  - dedup ENTRE repos: dos repos con el mismo plano comparten blob
  - descarga por la API con StreamingResponse desde el bucket
  - KeyError homogéneo con el backend local para blobs inexistentes
"""
import io
import os
import tempfile
from pathlib import Path

# Entorno ANTES de importar nada de cadvcs
os.environ.update({
    "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
    "CADVCS_BLOB_URL": "s3://cadvcs-test/blobs",
    "CADVCS_DATA": tempfile.mkdtemp(prefix="cadvcs_s3_"),
})

import boto3
import ezdxf
from moto import mock_aws

from cadvcs.repo import Repo, MergeConflictError
from cadvcs.storage import open_store, S3BlobStore


def check(label, cond):
    assert cond, f"FALLO: {label}"
    print(f"  {label} ✔")


@mock_aws
def main():
    boto3.client("s3").create_bucket(Bucket="cadvcs-test")

    work = Path(tempfile.mkdtemp())
    repo = Repo.init(work)
    check("factory devuelve S3BlobStore con CADVCS_BLOB_URL",
          isinstance(repo.store, S3BlobStore))
    p = work / "plano.dxf"

    def edit(fn):
        doc = ezdxf.readfile(p) if p.exists() else ezdxf.new("R2010")
        fn(doc.modelspace())
        doc.saveas(p)

    # ---- flujo core completo sobre S3 -----------------------------------
    edit(lambda m: (m.add_line((0, 0), (100, 0)), m.add_circle((50, 25), 5)))
    repo.add(p)
    repo.commit("ero", "c1")

    repo.branch_create("variante")
    repo.switch("variante")
    edit(lambda m: [setattr(c.dxf, "center", (70, 30)) for c in m.query("CIRCLE")])
    repo.commit("maria", "c2 mover columna")

    repo.switch("main")
    doc = ezdxf.readfile(p)
    check("switch rematerializa desde el bucket",
          list(doc.modelspace().query("CIRCLE"))[0].dxf.center == (50, 25, 0))
    edit(lambda m: m.add_arc((20, 0), radius=8, start_angle=0, end_angle=90))
    repo.commit("ero", "c3 puerta")

    info = repo.merge("variante", author="ero")
    check("merge por entidad con blobs en S3", info["result"] == "merged")
    msp = ezdxf.readfile(p).modelspace()
    check("resultado del merge correcto",
          list(msp.query("CIRCLE"))[0].dxf.center == (70, 30, 0)
          and len(list(msp.query("ARC"))) == 1)
    rows = repo.blame("plano.dxf")
    check("blame lee el índice con blobs remotos",
          {r["dxftype"] for r in rows} == {"LINE", "CIRCLE", "ARC"})

    # ---- layout de claves y dedup ----------------------------------------
    s3 = boto3.client("s3")
    keys = [o["Key"] for o in
            s3.list_objects_v2(Bucket="cadvcs-test")["Contents"]]
    check("claves con prefijo y sharding blobs/objects/ab/...",
          all(k.startswith("blobs/objects/") and k.count("/") == 3
              for k in keys))
    n_before = len(keys)
    sha, _ = repo.store.put(p)             # re-put del contenido actual
    n_after = len(s3.list_objects_v2(Bucket="cadvcs-test")["Contents"])
    check("re-put no duplica objetos (dedup)", n_after == n_before)

    # Dedup ENTRE repos: mismo plano en otro repo → cero objetos nuevos
    work2 = Path(tempfile.mkdtemp())
    repo2 = Repo.init(work2)
    p2 = work2 / "plano.dxf"
    p2.write_bytes(p.read_bytes())
    repo2.add(p2)
    repo2.commit("ana", "mismo plano en otro repo")
    n_cross = len(s3.list_objects_v2(Bucket="cadvcs-test")["Contents"])
    check("dedup entre repositorios (bucket global)", n_cross == n_after)

    # ---- errores homogéneos ------------------------------------------------
    try:
        repo.store.get("0" * 64, work / "no.bin")
        raise AssertionError("debió lanzar KeyError")
    except KeyError:
        check("KeyError homogéneo para blob inexistente", True)

    # ---- descarga por la API: streaming desde el bucket ----------------------
    from fastapi.testclient import TestClient
    from cadvcs.api.main import app
    client = TestClient(app)
    api_repo_dir = Path(os.environ["CADVCS_DATA"]) / "nave"
    client.post("/repos", json={"name": "nave"})
    buf = io.StringIO()
    ezdxf.readfile(p).write(buf)
    data = buf.getvalue().encode()
    client.put("/repos/nave/files/plano.dxf", content=data)
    client.post("/repos/nave/commits", json={"message": "v1"})
    r = client.get("/repos/nave/files/plano.dxf")
    check("descarga API en streaming desde S3",
          r.status_code == 200 and r.content == data
          and "attachment" in r.headers["content-disposition"])
    check("header X-Blob-Sha256 presente", len(r.headers["x-blob-sha256"]) == 64)

    print("\nS3 blob store OK — todos los checks pasan")


if __name__ == "__main__":
    main()
