"""Content-addressed blob storage.

Cada archivo se guarda una sola vez bajo su SHA-256 (deduplicación gratis).
Layout tipo Git: objects/ab/cdef123...  En producción esto sería S3/OCI
Object Storage con la misma clave; la interfaz no cambiaría.
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path


class BlobStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, digest: str) -> Path:
        return self.root / digest[:2] / digest[2:]

    @staticmethod
    def hash_file(path: Path, chunk_size: int = 1 << 20) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
        return h.hexdigest()

    def put(self, path: Path) -> tuple[str, int]:
        """Guarda el archivo y devuelve (sha256, size). Idempotente."""
        path = Path(path)
        digest = self.hash_file(path)
        dest = self._path_for(digest)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Escritura atómica: tmp + rename para no dejar blobs corruptos
            with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as tmp:
                with open(path, "rb") as src:
                    shutil.copyfileobj(src, tmp)
                tmp_path = Path(tmp.name)
            tmp_path.rename(dest)
        return digest, path.stat().st_size

    def get(self, digest: str, dest: Path) -> Path:
        src = self._path_for(digest)
        if not src.exists():
            raise KeyError(f"Blob {digest} no existe en el store")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return dest

    def open(self, digest: str):
        src = self._path_for(digest)
        if not src.exists():
            raise KeyError(f"Blob {digest} no existe en el store")
        return open(src, "rb")

    def exists(self, digest: str) -> bool:
        return self._path_for(digest).exists()
