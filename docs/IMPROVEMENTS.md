# Mejoras propuestas

Backlog razonado de evolución, ordenado por área. La arquitectura objetivo completa está en [ARCHITECTURE.md](../ARCHITECTURE.md); esto detalla el camino incremental.

## Núcleo de versionado

**Identidad de entidad por GUID.** La mayor limitación actual: los handles DXF son por-archivo, colisionan entre ramas (add/add) y se reinician al importar entidades en un merge. La solución de los PDM comerciales es inyectar un GUID propio como XDATA en cada entidad al primer commit, y usar ese GUID como identidad en diff/merge/blame. Elimina los falsos add/add, preserva la atribución de blame a través de merges, y habilita rename/move tracking entre archivos.

**Compresión delta en el blob store.** Los DXF cambian poco entre saves; xdelta3 entre versiones consecutivas del mismo `repo_path` reduciría el storage drásticamente, manteniendo el SHA del contenido completo como identidad y reconstruyendo bajo demanda (el modelo packfile de Git).

**Garbage collection.** Implementado (PR gc): mark-and-sweep sobre `commit_entries`. Pendiente el **gc multi-repo en bucket S3 compartido**: como el bucket es global para deduplicación entre repos, el sweep de blobs en backend S3 está desactivado por seguridad (`blob_sweep=False`) — un blob no referenciado por un repo puede estarlo por otro. La versión correcta es un job que une el conjunto vivo de TODOS los schemas/repos antes de borrar, ejecutado fuera del request.

**Soporte de paperspace, layouts y bloques.** El diff/merge actual opera solo sobre modelspace; los layouts de impresión y las definiciones de bloque son cambios de diseño reales que hoy pasan como "binario cambió".

**Rebase y cherry-pick.** Con el merge a tres vías ya implementado, cherry-pick es un merge con base = padre del commit elegido; rebase es la iteración de cherry-picks. Útil para el flujo "traer solo este cambio de la variante B".

## API y seguridad

**Autorización por proyecto y rol.** Roles lector/editor/admin por repositorio, mapeados desde claims o grupos del token OIDC, con chequeo en dependencia FastAPI. Hoy cualquier token válido puede todo.

**Presigned URLs.** El cliente calcula el SHA, pide URL de subida, y si el blob existe la API responde "ya lo tengo" sin transferencia (modelo Git LFS). Desacopla el ancho de banda de archivos del proceso API.

**Paginación y filtros** en log (`?author=`, `?path=`, `?since=`), locks y listados; salida `--json` en el CLI; modo remoto del CLI contra la API.

**Webhooks** en commit/merge/tag para integración con CI y notificaciones de equipo.

## Infraestructura (camino a ARCHITECTURE.md)

**PostgreSQL** como primer paso de producción: el esquema ya es portable; el lock in-process por repo se sustituye por transacciones (`INSERT ... ON CONFLICT` para locks, CTE recursiva para el merge-base) y habilita múltiples réplicas de la API.

**Workers asíncronos** para el indexado de entidades (hoy síncrono en el commit): outbox transaccional + Kafka, con el worker de conversión DWG→DXF (ODA File Converter) como segundo consumidor — esto desbloquea el soporte DWG real.

**Object storage S3/OCI** detrás de la interfaz actual de `BlobStore`.

## Experiencia de usuario

**Diff visual.** Render de ambas versiones a SVG con `ezdxf.addons.drawing` y overlay de colores (rojo eliminado, verde añadido, ámbar modificado). Es la feature de mayor impacto percibido: los usuarios CAD piensan en geometría, no en listas de atributos. Cacheable para siempre por par de SHAs.

**UI de resolución de conflictos** sobre ese render: pintar ambos lados, elegir ours/theirs por entidad clicando, y enviar el `merge/resolve` ya implementado.

**Plugin AutoCAD (.NET)** con check-out/check-in integrado, lock automático al abrir y heartbeat de renovación.

## Calidad

Migrar los scripts de verificación a **pytest** con fixtures parametrizadas; property-based testing del merge con hypothesis (generar tripletas base/ours/theirs aleatorias y verificar invariantes: el merge nunca pierde entidades no conflictivas, resolución total siempre converge); benchmark de indexado con planos de 100k+ entidades.
