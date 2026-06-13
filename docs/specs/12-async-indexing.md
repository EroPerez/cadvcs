# Spec 12 — Indexado asíncrono (transactional outbox + worker)

**Módulos:** `cadvcs/repo.py` (outbox en commit, `index_*`), `cadvcs/worker.py`, tabla `index_outbox`

## Propósito

Sacar el parseo de entidades DXF del camino crítico del commit. Antes, cada commit de un plano grande pagaba el coste de extraer todas sus entidades de forma síncrona; ahora el commit solo escribe un evento y un worker hace el indexado en segundo plano.

## Comportamiento

En la misma transacción que inserta el commit y sus entries, se escribe un evento `pending` en `index_outbox` por cada blob DXF nuevo del changeset — el patrón transactional outbox, que garantiza que metadata y evento son atómicos sin meter un broker en el path de commit. Si el blob ya está indexado (dedup por SHA), no se encola. El `worker` drena el outbox: materializa cada blob, extrae sus entidades, las persiste y marca el evento `done`; ante error incrementa `attempts` y lo deja pendiente para reintento. Corre en modo multi-repo recorriendo `CADVCS_DATA`, con `--once` para CI/cron o polling con backoff exponencial para despliegue.

La propiedad que hace esto seguro: `_entities_for_blob` ya indexaba bajo demanda los blobs no indexados (el fallback que existía para blobs importados en merges). Eso significa que **la correctitud no depende del worker** — si un diff, merge o blame toca un blob cuyo evento aún está pendiente, lo indexa en el acto y cierra el evento. El worker solo mejora la latencia: mueve el coste fuera del commit, pero una lectura nunca espera ni falla por su ausencia. Esta red de seguridad es lo que permite diferir sin introducir una ventana de inconsistencia.

## Decisiones de diseño

Outbox por polling en vez de Kafka directo: el broker es la propia tabla, lo que mantiene cero dependencias de infraestructura en el MVP y es trivialmente correcto y testeable. La arquitectura objetivo (ARCHITECTURE.md) sustituye el polling por un relay outbox→Kafka con N consumidores; `index_one` no cambia, solo de dónde llega el `blob_sha`. El indexado on-demand preexistente convirtió lo que habría sido un cambio arriesgado (¿y si el worker se cae?) en uno seguro por construcción.

## Limitaciones conocidas

El worker es at-least-once sin lease: dos workers sobre el mismo repo podrían tomar el mismo evento (el `INSERT OR IGNORE` en `entities` y el marcado idempotente lo hacen inofensivo, pero malgastan trabajo). Un `SELECT ... FOR UPDATE SKIP LOCKED` en PostgreSQL daría reparto exclusivo — está en el ROADMAP. Por el modelo schema-por-repo, dos repositorios con el mismo nombre de directorio comparten schema en PostgreSQL; en producción el repo_key debe ser un identificador único (slug + tenant), no el basename.
