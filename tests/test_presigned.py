"""Test del flujo presigned (Git-LFS style) con moto.

Verifica que el servidor sale del path de bytes:
  1. handshake upload-url: blob nuevo → presigned PUT; el cliente sube
     DIRECTO a S3 (simulado con requests sobre el endpoint moto) sin
     pasar bytes por la API
  2. dedup: segundo upload-url del mismo SHA → {exists:true}, sin URL
  3. staged + commit: el blob subido se registra por referencia y el
     commit lo incluye sin que la API lea los bytes
  4. el worker indexa el blob staged (es DXF) igual que cualquier otro
  5. descarga presigned: 307 redirect a una URL GET de S3
  6. presigned sobre backend local → 409 (no aplica)
"""
import io
import os
import tempfile

os.environ.update({
    "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
    "CADVCS_BLOB_URL": "s3://cadvcs-presigned/blobs",
    "CADVCS_DATA": tempfile.mkdtemp(prefix="cadvcs_ps_"),
})

import boto3
import ezdxf
from moto import mock_aws
from moto.moto_server.threaded_moto_server import ThreadedMotoServer


def check(label, cond):
    assert cond, f"FALLO: {label}"
    print(f"  {label} ✔")


def main():
    # Servidor moto real por HTTP: las URLs presigned tienen que ser
    # consumibles por un cliente HTTP de verdad, no solo por boto in-proc.
    server = ThreadedMotoServer(port=0)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    os.environ["CADVCS_S3_ENDPOINT"] = endpoint

    import requests
    boto3.client("s3", endpoint_url=endpoint).create_bucket(
        Bucket="cadvcs-presigned")

    from fastapi.testclient import TestClient
    from cadvcs.api.main import app
    from cadvcs.storage import BlobStore
    from cadvcs.repo import Repo
    from cadvcs import worker
    client = TestClient(app)

    client.post("/repos", json={"name": "nave"})

    # Construir un DXF y su SHA, como haría el cliente en local
    doc = ezdxf.new("R2010")
    doc.modelspace().add_circle((50, 25), 5)
    doc.modelspace().add_line((0, 0), (100, 0))
    buf = io.StringIO(); doc.write(buf)
    data = buf.getvalue().encode()
    tmp = os.path.join(os.environ["CADVCS_DATA"], "_calc.dxf")
    with open(tmp, "wb") as f:
        f.write(data)
    sha = BlobStore.hash_file(tmp)

    # ---- 1. handshake: blob nuevo → presigned PUT --------------------------
    r = client.post(f"/repos/nave/blobs/{sha}/upload-url")
    check("upload-url para blob nuevo da exists:false + URL",
          r.status_code == 200 and r.json()["exists"] is False
          and r.json()["upload_url"].startswith(endpoint))
    put_url = r.json()["upload_url"]

    # El CLIENTE sube directo a S3 (los bytes NO pasan por la API)
    up = requests.put(put_url, data=data)
    check("PUT directo del cliente a S3 → 200", up.status_code == 200)

    # ---- 2. dedup: mismo SHA ya está → exists:true sin URL ------------------
    r = client.post(f"/repos/nave/blobs/{sha}/upload-url")
    check("upload-url de blob existente → exists:true sin URL",
          r.json()["exists"] is True and "upload_url" not in r.json())

    # ---- 3. staged + commit por referencia ---------------------------------
    r = client.put("/repos/nave/staged/plano.dxf",
                   json={"sha256": sha, "size": len(data)})
    check("registro staged → 200", r.status_code == 200)
    st = client.get("/repos/nave/status").json()
    check("status ve el blob staged como new", st["new"] == ["plano.dxf"])
    r = client.post("/repos/nave/commits", json={"message": "v1 presigned"})
    check("commit incluye el blob staged (sin leer bytes en la API)",
          r.status_code == 201 and r.json()["changed"] == ["plano.dxf"])

    repo = Repo(os.path.join(os.environ["CADVCS_DATA"], "nave"))
    committed_sha = repo._tree(repo.head_commit_id())["plano.dxf"]["blob_sha"]
    check("el SHA commiteado es el que subió el cliente", committed_sha == sha)

    # ---- 4. el worker indexa el blob staged --------------------------------
    totals = worker.drain_once("nave")
    check("worker indexa el blob subido por presigned", totals["done"] == 1)
    ents = repo._entities_for_blob(sha)
    check("entidades extraídas del blob remoto", len(ents) == 2)

    # ---- 5. descarga presigned: 307 redirect a S3 --------------------------
    r = client.get("/repos/nave/files/plano.dxf",
                   params={"presigned": True}, follow_redirects=False)
    check("descarga presigned → 307 redirect", r.status_code == 307
          and r.headers["location"].startswith(endpoint))
    # La URL del redirect es consumible por un cliente HTTP real
    got = requests.get(r.headers["location"])
    check("el redirect entrega los bytes correctos desde S3",
          got.status_code == 200 and got.content == data)

    # descarga normal (streaming por la API) sigue disponible
    r = client.get("/repos/nave/files/plano.dxf")
    check("descarga normal por streaming sigue OK",
          r.status_code == 200 and r.content == data)

    server.stop()
    print("\nPresigned URLs OK — todos los checks pasan")


@mock_aws
def local_backend_rejects():
    """presigned sobre backend local → 409."""
    import importlib
    os.environ.pop("CADVCS_BLOB_URL", None)
    os.environ.pop("CADVCS_S3_ENDPOINT", None)
    os.environ["CADVCS_DATA"] = tempfile.mkdtemp(prefix="cadvcs_local_")
    from fastapi.testclient import TestClient
    from cadvcs.api.main import app
    c = TestClient(app)
    c.post("/repos", json={"name": "loc"})
    r = c.post("/repos/loc/blobs/" + "a" * 64 + "/upload-url")
    check("upload-url en backend local → 409", r.status_code == 409)


if __name__ == "__main__":
    main()
    local_backend_rejects()
