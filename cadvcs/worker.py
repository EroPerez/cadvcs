"""Worker de indexado de entidades.

Drena `index_outbox` fuera del path de commit: materializa cada blob
pendiente, extrae sus entidades DXF y las persiste. El commit ya no paga
el coste del parseo — solo escribe el evento en su transacción.

En el MVP el "broker" es la propia tabla outbox por polling, lo que evita
una dependencia de infraestructura y es trivialmente correcto. La
arquitectura objetivo (ARCHITECTURE.md) sustituye el polling por un
relay outbox→Kafka y N consumidores; la lógica de `index_one` no cambia,
solo de dónde llega el `blob_sha`.

Modos:
  - Multi-repo (default): recorre todos los repos bajo CADVCS_DATA y
    drena el outbox de cada uno. Es el modo de despliegue.
  - Un repo: `--repo NOMBRE` para drenar uno concreto.
  - `--once` procesa una pasada y termina (para CI / cron); sin él,
    hace polling con backoff.

Uso:
    python -m cadvcs.worker --once
    python -m cadvcs.worker --interval 2.0
    python -m cadvcs.worker --repo nave --once
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from .repo import Repo, REPO_DIR

logger = logging.getLogger("cadvcs.worker")

DATA_DIR = Path(os.environ.get("CADVCS_DATA", "./cadvcs-data")).resolve()


def _iter_repos(only: str | None):
    if only:
        root = DATA_DIR / only
        if (root / REPO_DIR).exists():
            yield Repo(root)
        return
    if not DATA_DIR.exists():
        return
    for child in sorted(DATA_DIR.iterdir()):
        if (child / REPO_DIR).exists():
            yield Repo(child)


def drain_once(only: str | None = None, batch: int = 100) -> dict:
    """Una pasada sobre todos los repos. Devuelve totales agregados."""
    totals = {"repos": 0, "done": 0, "failed": 0}
    for repo in _iter_repos(only):
        stats = repo.index_drain(batch)
        if stats["done"] or stats["failed"]:
            logger.info("repo %s: %d indexados, %d fallidos",
                        repo.root.name, stats["done"], stats["failed"])
        totals["repos"] += 1
        totals["done"] += stats["done"]
        totals["failed"] += stats["failed"]
    return totals


def run(interval: float, only: str | None, batch: int):
    """Polling con backoff: duplica el sleep hasta 'interval' cuando no
    hay trabajo, y vuelve al mínimo en cuanto procesa algo."""
    logger.info("worker iniciado (data=%s, interval máx=%.1fs)",
                DATA_DIR, interval)
    sleep = 0.1
    while True:
        totals = drain_once(only, batch)
        if totals["done"]:
            sleep = 0.1
        else:
            sleep = min(sleep * 2, interval)
        time.sleep(sleep)


def main(argv=None):
    p = argparse.ArgumentParser(prog="cadvcs.worker")
    p.add_argument("--repo", default=None, help="drenar solo este repo")
    p.add_argument("--once", action="store_true",
                   help="una pasada y salir (CI/cron)")
    p.add_argument("--interval", type=float, default=2.0,
                   help="sleep máximo entre pasadas en modo continuo")
    p.add_argument("--batch", type=int, default=100)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")

    if args.once:
        totals = drain_once(args.repo, args.batch)
        logger.info("pasada única: %d repos, %d indexados, %d fallidos",
                    totals["repos"], totals["done"], totals["failed"])
        return 1 if totals["failed"] else 0
    try:
        run(args.interval, args.repo, args.batch)
    except KeyboardInterrupt:
        logger.info("worker detenido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
