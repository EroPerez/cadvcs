# Spec 09 — API REST

**Módulos:** `cadvcs/api/main.py`, `cadvcs/api/schemas.py`

## Propósito

Exponer el repositorio por HTTP con semántica REST correcta y contratos tipados, como base para la Web UI, el plugin CAD y cualquier integración.

## Comportamiento

El servidor mantiene una working copy por repositorio bajo `CADVCS_DATA`. Subida con `PUT /repos/{n}/files/{path}` (octet-stream, queda tracked); descarga con `GET .../files/{path}?ref=` desde cualquier commit, rama o tag, sirviendo el blob directo del store con su SHA en header. El resto de rutas mapean 1:1 el dominio: `status`, `commits` (POST/GET), `branches`, `switch`, `tags`, `diff`, `merge`, `merge/resolve`, `blame`, `locks`. La semántica de errores es parte del contrato: **409** para conflictos de merge con payload estructurado completo, **423 Locked** para locks ajenos, **422** para errores de dominio (commit vacío, ref inexistente), **401** de auth — todo vía un exception handler global que traduce `CadVcsError` sin try/except por endpoint. Concurrencia: endpoints síncronos en threadpool, un `threading.Lock` por repositorio serializando mutaciones, conexión SQLite por request.

## Decisiones de diseño

Working copy server-side en vez de API stateless de blobs: es el puente natural desde el modelo del CLI y deja el salto a presigned URLs (cliente sube directo al object storage) como evolución de infraestructura sin cambiar contratos. Seguridad de rutas: validación de slug de repo por Pydantic, guard anti path-traversal con `resolve()` + `is_relative_to` que cubre la forma URL-encoded, y la dir `.cadvcs` inaccesible.

## Limitaciones conocidas

Un solo nodo (el lock por repo es in-process); sin paginación en log/locks; subida síncrona por la API en vez de presigned.
