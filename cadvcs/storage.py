"""Content-addressed blob storage.

Cada archivo se guarda una sola vez bajo su SHA-256 (deduplicación gratis).
Layout tipo Git: objects/ab/cdef123...  En producción esto sería S3/OCI
Object Storage con la misma clave; la interfaz no cambiaría.
"""
from __future__ import annotations

import hashlib
import os
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


class S3BlobStore:
    """Blob store content-addressed sobre object storage S3-compatible.

    Misma interfaz que BlobStore local (put/get/open/exists/hash_file);
    la clave del objeto es el SHA-256 con el mismo sharding ab/cdef...,
    de modo que el modelo no cambia: solo el backend.

    Configuración:
      CADVCS_BLOB_URL    s3://bucket[/prefijo]
      CADVCS_S3_ENDPOINT endpoint alternativo (MinIO, OCI Object Storage
                         en modo S3-compat, LocalStack). Vacío = AWS.
      Credenciales por la cadena estándar de AWS (env, perfil, IAM role).

    La deduplicación entre repositorios sale gratis: el bucket es global
    y dos repos con el mismo plano comparten blob.
    """

    def __init__(self, url: str):
        import boto3

        assert url.startswith("s3://"), url
        rest = url[5:]
        self.bucket, _, prefix = rest.partition("/")
        self.prefix = prefix.strip("/")
        endpoint = os.environ.get("CADVCS_S3_ENDPOINT") or None
        self.s3 = boto3.client("s3", endpoint_url=endpoint)

    hash_file = staticmethod(BlobStore.hash_file)

    def _key(self, digest: str) -> str:
        shard = f"objects/{digest[:2]}/{digest[2:]}"
        return f"{self.prefix}/{shard}" if self.prefix else shard

    def exists(self, digest: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.s3.head_object(Bucket=self.bucket, Key=self._key(digest))
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def put(self, path: Path) -> tuple[str, int]:
        path = Path(path)
        digest = self.hash_file(path)
        if not self.exists(digest):
            # upload_file gestiona multipart para archivos grandes
            self.s3.upload_file(
                str(path), self.bucket, self._key(digest),
                ExtraArgs={"Metadata": {"sha256": digest}})
        return digest, path.stat().st_size

    def get(self, digest: str, dest: Path) -> Path:
        from botocore.exceptions import ClientError
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.s3.download_file(self.bucket, self._key(digest), str(dest))
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                raise KeyError(f"Blob {digest} no existe en el store")
            raise
        return dest

    def open(self, digest: str):
        """File-like de solo lectura (streaming desde el bucket)."""
        from botocore.exceptions import ClientError
        try:
            return self.s3.get_object(
                Bucket=self.bucket, Key=self._key(digest))["Body"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                raise KeyError(f"Blob {digest} no existe en el store")
            raise

    def presigned_put(self, digest: str, expires: int = 900) -> str:
        """URL para que el CLIENTE suba el blob directo a S3 (PUT).

        El servidor nunca toca los bytes. La clave es el SHA, así que la
        integridad se preserva: el cliente sube bajo su propio hash y un
        verificador posterior (o la política del bucket) puede rechazar
        mismatches. Expira en `expires` segundos."""
        return self.s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": self._key(digest)},
            ExpiresIn=expires)

    def presigned_get(self, digest: str, expires: int = 900,
                      filename: str | None = None) -> str:
        """URL para que el CLIENTE descargue el blob directo de S3 (GET)."""
        params = {"Bucket": self.bucket, "Key": self._key(digest)}
        if filename:
            params["ResponseContentDisposition"] = (
                f'attachment; filename="{filename}"')
        return self.s3.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expires)

    def register(self, digest: str, size: int) -> tuple[str, int]:
        """Confirma un blob ya subido por presigned PUT.

        Verifica que el objeto existe (el cliente completó la subida) y
        devuelve (digest, size) como `put`. No re-sube nada."""
        if not self.exists(digest):
            raise KeyError(f"Blob {digest} no está en el store "
                           f"(el cliente no completó el PUT presigned)")
        return digest, size


def open_store(local_root: Path):
    """Factory: S3 si CADVCS_BLOB_URL está definido, local en caso contrario.

    Se lee el entorno en cada llamada (no en import) para que tests y
    procesos puedan cambiar de backend sin reimportar.
    """
    url = os.environ.get("CADVCS_BLOB_URL")
    if url:
        return S3BlobStore(url)
    return BlobStore(local_root)
