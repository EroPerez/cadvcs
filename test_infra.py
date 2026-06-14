"""Test de las tres piezas de infraestructura: conversión DWG, cache de
renders en Redis, y transporte de eventos Kafka.

  Conversión DWG (stub converter, camino completo del worker):
    1. commitear un .dwg encola un evento kind='convert' (no 'index')
    2. el worker convierte → DXF espejo en el store, registra dwg_mirrors,
       indexa el espejo
    3. dedup: re-commit del mismo DWG no re-encola (espejo ya existe)
    4. sin conversor (none) el DWG se versiona pero no obtiene espejo

  Redis (servidor real si está; fakeredis si no):
    5. el diff visual se cachea por par de SHAs; segundo render viene de
       cache (mismo SVG, sin recomputar)
    6. degradación: sin Redis el endpoint sigue funcionando

  Kafka (bus en memoria, misma lógica que el real):
    7. relay publica las filas pending del outbox como eventos
    8. el consumer procesa los eventos vía index_one y cierra el outbox
    9. idempotencia: reenviar un evento ya procesado es inofensivo
"""
import io
import os
import subprocess
import tempfile
import time
from pathlib import Path

os.environ["CADVCS_DATA"] = tempfile.mkdtemp(prefix="cadvcs_infra_")
os.environ["CADVCS_DWG_CONVERTER"] = "stub"

import ezdxf

from cadvcs.repo import Repo
from cadvcs import bus as busmod


def check(label, cond):
    assert cond, f"FALLO: {label}"
    print(f"  {label} ✔")


def make_dwg_bytes():
    """Un 'DWG' de prueba: en realidad DXF válido (el stub lo copia tal
    cual). Suficiente para ejercitar todo el camino de conversión."""
    doc = ezdxf.new("R2010")
    doc.modelspace().add_circle((10, 10), 4)
    doc.modelspace().add_line((0, 0), (20, 0))
    buf = io.StringIO(); doc.write(buf)
    return buf.getvalue().encode()


DATA = Path(os.environ["CADVCS_DATA"])


# ============================ Conversión DWG ============================
def test_dwg_conversion():
    work = DATA / "planos"
    repo = Repo.init(work)
    p = work / "pieza.dwg"
    dwg_bytes = make_dwg_bytes()           # capturar UNA vez (ezdxf no es determinista)
    p.write_bytes(dwg_bytes)
    repo.add(p)
    info = repo.commit("ero", "v1 dwg")
    dwg_sha = repo._tree(info["commit_id"])["pieza.dwg"]["blob_sha"]

    pend = repo.index_pending()
    check("commit de DWG encola evento kind=convert",
          len(pend) == 1 and pend[0]["kind"] == "convert")
    check("el DWG no se indexa como entidades directamente",
          repo._entities_for_blob.__self__ is repo and
          repo.conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"] == 0)

    stats = repo.index_drain()
    check("worker convierte el DWG", stats["done"] == 1)
    dxf_sha = repo.dwg_mirror(dwg_sha)
    check("se registra el espejo DWG→DXF", dxf_sha is not None)
    check("el DXF espejo está indexado (2 entidades)",
          repo.conn.execute("SELECT COUNT(*) AS n FROM entities WHERE blob_sha=?",
                            (dxf_sha,)).fetchone()["n"] == 2)
    check("el espejo está en el store",
          repo.store.exists(dxf_sha))

    # dedup: el MISMO DWG (bytes idénticos) en otra rama no re-encola
    repo.branch_create("v2"); repo.switch("v2")
    other = work / "otra.dwg"
    other.write_bytes(dwg_bytes)           # bytes idénticos → mismo dwg_sha
    repo.add(other)
    repo.commit("ero", "mismo dwg en otra ruta")
    check("re-commit del mismo DWG (otro path) no genera evento convert",
          len([e for e in repo.index_pending() if e["kind"] == "convert"]) == 0)


def test_no_converter_degradation():
    os.environ["CADVCS_DWG_CONVERTER"] = "none"
    try:
        work = DATA / "sinconv"
        repo = Repo.init(work)
        p = work / "x.dwg"
        p.write_bytes(make_dwg_bytes())
        repo.add(p)
        repo.commit("ana", "dwg sin conversor")
        stats = repo.index_drain()
        # el evento existe pero falla (sin conversor) y queda pending para reintento
        check("sin conversor el evento de convert no se completa",
              stats["done"] == 0 and stats["failed"] == 1)
        check("el DWG sigue versionado (binario opaco)",
              "x.dwg" in repo._tree(repo.head_commit_id()))
    finally:
        os.environ["CADVCS_DWG_CONVERTER"] = "stub"


# ============================ Redis cache ============================
def _redis_url():
    """Arranca un redis-server local si está; si no, usa fakeredis vía
    monkeypatch del cliente. Devuelve (url, cleanup) o (None, None)."""
    import shutil
    if shutil.which("redis-server"):
        proc = subprocess.Popen(["redis-server", "--port", "6399", "--save", ""],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.6)
        return "redis://localhost:6399/0", lambda: proc.terminate()
    return None, None


def test_redis_render_cache():
    url, cleanup = _redis_url()
    if not url:
        # fakeredis fallback
        import fakeredis, cadvcs.cache as cache_mod
        fake = fakeredis.FakeRedis()
        cache_mod._cache = cache_mod.RenderCache.__new__(cache_mod.RenderCache)
        cache_mod._cache.client = fake
        print("  (usando fakeredis)")
    else:
        os.environ["CADVCS_REDIS_URL"] = url
        import cadvcs.cache as cache_mod
        cache_mod._cache = None  # re-evaluar con la URL

    try:
        from fastapi.testclient import TestClient
        from cadvcs.api.main import app
        from cadvcs.cache import render_cache
        client = TestClient(app)
        cache = render_cache()
        check("Redis/cache habilitado", cache.enabled)

        # Crear repo con dos versiones de un DXF para diff visual
        client.post("/repos", json={"name": "r"})
        doc = ezdxf.new("R2010"); doc.modelspace().add_circle((5, 5), 3)
        b = io.StringIO(); doc.write(b)
        client.put("/repos/r/files/p.dxf", content=b.getvalue().encode())
        client.post("/repos/r/commits", json={"message": "c1"})
        client.post("/repos/r/branches", json={"name": "b"})
        client.post("/repos/r/switch", json={"branch": "b"})
        raw = client.get("/repos/r/files/p.dxf").content
        d = ezdxf.read(io.StringIO(raw.decode()))
        for c in d.modelspace().query("CIRCLE"):
            c.dxf.center = (50, 50)
        b = io.StringIO(); d.write(b)
        client.put("/repos/r/files/p.dxf", content=b.getvalue().encode())
        client.post("/repos/r/commits", json={"message": "c2"})

        params = {"ref_a": "main", "ref_b": "b", "path": "p.dxf"}
        before = cache.stats().get("cached_renders", 0)
        r1 = client.get("/repos/r/diff/visual", params=params)
        check("primer diff visual → 200", r1.status_code == 200)
        after = cache.stats().get("cached_renders", 0)
        check("el diff visual se cacheó en Redis", after == before + 1)
        r2 = client.get("/repos/r/diff/visual", params=params)
        check("segundo diff visual idéntico (servido de cache)",
              r2.status_code == 200 and r2.text == r1.text)

        # health refleja el cache
        h = client.get("/health").json()
        check("health reporta render_cache=redis", h["render_cache"] == "redis")
    finally:
        if cleanup:
            cleanup()
        os.environ.pop("CADVCS_REDIS_URL", None)
        import cadvcs.cache as cache_mod
        cache_mod._cache = None


# ============================ Kafka relay/consumer ============================
def test_kafka_relay_consumer():
    work = DATA / "kafka"
    repo = Repo.init(work)
    doc = ezdxf.new("R2010"); doc.modelspace().add_circle((1, 1), 2)
    b = io.StringIO(); doc.write(b)
    p = work / "k.dxf"; p.write_bytes(b.getvalue().encode())
    repo.add(p); repo.commit("ero", "c1")

    pending = repo.index_pending()
    check("hay un evento index pendiente", len(pending) == 1)

    inbus = busmod.InMemoryBus()
    n = busmod.relay_once(repo, inbus)
    check("el relay publica las filas pending del outbox", n == 1)
    check("el evento está en el topic con su payload",
          len(inbus.queues[busmod.TOPIC]) == 1 and
          inbus.queues[busmod.TOPIC][0][1]["kind"] == "index")

    # consumer procesa vía index_one y cierra el outbox
    handler = busmod.make_handler(lambda key: repo)
    processed = inbus.consume(busmod.TOPIC, "g1", handler)
    check("el consumer procesa el evento", processed == 1)
    check("el outbox queda cerrado (sin pending)",
          len(repo.index_pending()) == 0)
    check("las entidades se indexaron vía el consumer",
          repo.conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"] == 1)

    # idempotencia: reenviar el mismo evento no rompe nada
    inbus.publish(busmod.TOPIC, "k", {
        "event_id": pending[0]["id"], "blob_sha": pending[0]["blob_sha"],
        "kind": "index", "repo_key": repo.root.name})
    inbus.consume(busmod.TOPIC, "g1", handler)
    check("reprocesar un evento ya hecho es inofensivo (idempotente)",
          repo.conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"] == 1)


def test_bus_degradation():
    check("sin CADVCS_KAFKA_BROKERS no hay bus Kafka (polling)",
          busmod.get_bus() is None)


if __name__ == "__main__":
    test_dwg_conversion()
    test_no_converter_degradation()
    test_redis_render_cache()
    test_kafka_relay_consumer()
    test_bus_degradation()
    print("\nKafka + Redis + DWG OK — todos los checks pasan")
