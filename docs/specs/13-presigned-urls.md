# Spec 13 — Subida/descarga directa a object storage (presigned)

**Módulos:** `cadvcs/storage.py` (`presigned_put/get`, `register`), `cadvcs/repo.py` (`stage_blob`, staged en status/commit), endpoints `blobs/{sha}/upload-url`, `staged/{path}`, `files/{path}?presigned`

## Propósito

Sacar al servidor del camino de los bytes para archivos grandes: el cliente sube y descarga directamente contra object storage, igual que Git LFS. Completa la externalización de estado iniciada con PostgreSQL (metadata) y S3 (blobs).

## Comportamiento

Subida en tres pasos, dedup-aware. El cliente calcula el SHA-256 en local y pide una URL de subida; si el blob ya está en el bucket, la API responde `exists:true` sin URL y no hay transferencia alguna (el truco de ahorro de Git LFS). Si no, devuelve un PUT presigned y el cliente sube los bytes directamente a object storage — la API nunca los ve. Después, un registro `staged` apunta el `repo_path` al SHA ya subido, y el commit lo incluye tomando `(sha, size)` del staging sin leer disco. La descarga con `?presigned=true` responde un 307 hacia una URL GET presigned, así los bytes salen directos del bucket. Las rutas `PUT/GET /files` por la API siguen disponibles para el backend local y archivos pequeños.

La integridad se preserva porque la clave del objeto es el propio SHA: el cliente sube bajo su hash declarado, y el `register` server-side verifica que el objeto existe antes de aceptarlo; una política de bucket o un verificador asíncrono puede rechazar mismatches. El blob staged se indexa por el worker (spec 12) igual que cualquier otro.

## Decisiones de diseño

El estado `staged` (tabla `repo_path → blob_sha, size`) es la pieza que permite commitear un blob que nunca tocó la working copy local, sin bifurcar la lógica de commit: status y commit consultan staging primero y caen al fichero en disco si no hay entrada. Es deliberadamente pequeño y se limpia en cada commit.

## Limitaciones conocidas

Los blobs subidos por presigned no pasan por la inyección server-side de GUIDs (spec 11), porque la API no tiene el fichero local: su identidad cae al handle vía `entity_uid` hasta que un cliente inyecte GUIDs antes de subir. La verificación de que el SHA subido coincide con el contenido es responsabilidad de la política del bucket o de un verificador asíncrono, no del path de commit. El backend local no soporta presigned (responde 409): allí la API ya sirve los bytes directamente sin coste de red entre cliente y storage.
