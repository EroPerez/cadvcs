# Arquitectura de producción — CAD VCS

Este documento define cómo llevar el MVP a un sistema multi-tenant en producción. El modelo de datos del MVP (DAG de commits, refs, tree plano content-addressed, índice semántico por blob) se conserva tal cual; lo que cambia es la infraestructura alrededor.

## Visión general

```
┌──────────────────────────── Clientes ─────────────────────────────┐
│  Plugin AutoCAD   CLI (push/pull/clone)   Web UI (viewer/diff)    │
└──────────────┬──────────┬──────────────────────┬─────────────────┘
               │ HTTPS / OIDC      │                 │
        ┌──────▼───────────────────▼─────────────────▼──────┐
        │            API REST (FastAPI / Spring Boot)        │
        │   auth OIDC · authz por proyecto · rate limiting   │
        └───┬──────────────┬──────────────────┬──────────────┘
            │              │                  │ presigned URLs
   ┌────────▼────────┐ ┌───▼────────┐  ┌──────▼──────────────┐
   │   PostgreSQL    │ │   Redis    │  │  S3 / OCI Object    │
   │ commits, refs,  │ │ cache de   │  │  Storage (blobs     │
   │ locks, entities,│ │ renders,   │  │  content-addressed  │
   │ xref_deps       │ │ sesiones   │  │  por SHA-256)       │
   └────────┬────────┘ └────────────┘  └──────▲──────────────┘
            │ outbox → Kafka                  │
   ┌────────▼─────────────────────────────────┴──────┐
   │                  Kafka (eventos)                 │
   │  commit.created · merge.requested · lock.expired │
   └───┬──────────────┬───────────────┬───────────────┘
       │              │               │
 ┌─────▼─────┐ ┌──────▼──────┐ ┌──────▼────────┐
 │ Worker    │ │ Worker      │ │ Worker        │
 │ indexado  │ │ conversión  │ │ render visual │
 │ entidades │ │ DWG→DXF     │ │ SVG/PNG +     │
 │ (ezdxf)   │ │ (ODA Conv.) │ │ overlay diff  │
 └───────────┘ └─────────────┘ └───────────────┘
        (Kubernetes · autoscaling por lag de consumer)
```

## Flujo de commit

El cliente nunca sube el archivo a través de la API. Calcula el SHA-256 en local y pide a la API un presigned URL de subida; si el blob ya existe en el object storage (dedup), la API responde "ya lo tengo" y se ahorra la transferencia completa — el mismo truco que usa Git LFS. Tras la subida, la API verifica el hash (el object storage puede validar checksum en el PUT), inserta el commit y sus entries en una transacción PostgreSQL, y publica `commit.created` en Kafka mediante el patrón transactional outbox para garantizar que metadata y evento son atómicos. Los workers consumen el evento: el de indexado extrae las entidades DXF y las persiste, el de conversión genera el DXF espejo de cada DWG (necesario porque el diff semántico opera sobre DXF), y el de render produce el SVG por versión que alimenta el diff visual con overlay de colores en la Web UI.

El índice de entidades es la tabla que crece sin control si no se diseña bien: con planos de cientos de miles de entidades conviene particionar `entities` por hash de `blob_sha`, guardar en PostgreSQL solo `(handle, dxftype, layer, fingerprint)` y mover el `attrs_json` completo a un objeto comprimido en el object storage junto al blob, cargándolo solo cuando un merge o blame lo necesita.

## Sincronización remota (push/pull/clone)

El CLI soporta un flujo distribuido tipo Git: los usuarios trabajan en un repositorio local y sincronizan con el servidor central mediante `push` y `pull`. El protocolo de sincronización opera sobre los mismos objetos del modelo (blobs content-addressed + commits con entries):

1. **Negociación**: el cliente obtiene las refs remotas (`sync/refs`) y compara con las locales para determinar qué commits faltan en cada dirección.
2. **Transferencia de blobs**: antes de enviar commits, el cliente consulta qué blobs ya tiene el servidor (`sync/blobs/check`). Solo se transfieren los faltantes — la deduplicación por SHA-256 evita subir el mismo blob dos veces aunque esté en múltiples commits.
3. **Pack de commits**: los commits se envían en orden topológico (padres primero) con sus entries. El servidor los aplica atómicamente y actualiza la ref de la rama.
4. **Optimistic lock**: el push incluye el head esperado de la rama remota. Si la rama avanzó (otro usuario hizo push), el servidor rechaza con 409 — hay que hacer pull primero, igual que `git push` rechaza si hay cambios nuevos.

`clone` descarga todas las ramas y materializa la working copy del branch por defecto. Los remotes se configuran en `.cadvcs/config.json` (múltiples servidores, cada uno con su token de autenticación).

## Locking distribuido

El lock pesimista del MVP se traslada a PostgreSQL con `INSERT ... ON CONFLICT` sobre la tabla de locks dentro de una transacción, o advisory locks si se prefiere semántica de sesión. El TTL se mantiene, pero en producción se complementa con heartbeat desde el plugin de AutoCAD (renueva el lock mientras el archivo está abierto) y un job que publica `lock.expired` para notificar al equipo. Para archivos no-DXF el lock es obligatorio antes de commitear, porque el merge binario no existe: la API lo rechaza si no eres el holder.

## Merge en servidor

El merge es una operación de API, no de cliente: `POST /repos/{id}/merge` calcula el merge-base en PostgreSQL (CTE recursiva sobre el DAG de commits — el algoritmo LCA del MVP se traduce directo), descarga los tres blobs implicados a un worker, ejecuta el merge a nivel de entidad y, si no hay conflictos, sube el blob resultante y crea el merge commit con dos padres. Si hay conflictos, devuelve el detalle estructurado (handle, tipo, razón, valores de cada lado) y la Web UI los presenta sobre el render visual de ambas versiones para que el usuario elija ours/theirs por entidad — la resolución interactiva es otra llamada que aplica las elecciones y commitea.

## XREFs

Las referencias externas convierten cada plano en un nodo de un grafo de dependencias. Se modela con una tabla `xref_deps(commit_id, repo_path, depends_on_path, depends_on_sha)` poblada por el worker de indexado (ezdxf expone los XREFs del DXF). La regla de consistencia es que un commit captura el snapshot completo: si A referencia B, el checkout de A en una versión histórica materializa la versión de B que existía en ese commit, no la actual. Eso ya lo da gratis el tree plano por commit; la tabla de dependencias sirve para validación (avisar si commiteas A sin commitear el B modificado) e impacto inverso ("¿qué planos rompo si cambio B?").

## Seguridad y multi-tenancy

Autenticación OIDC (Keycloak/Auth0/Cognito), autorización por proyecto con roles lector/editor/admin, y aislamiento de tenant por `tenant_id` en todas las tablas con row-level security de PostgreSQL. Los presigned URLs expiran en minutos y van atados al SHA esperado. El object storage cifra at-rest (SSE-KMS) y los blobs son inmutables por construcción: borrado solo vía política de retención y job de garbage collection que elimina blobs no referenciados por ningún commit (mark-and-sweep sobre `commit_entries`, igual que `git gc`).

## Operación

Despliegue en Kubernetes con la API stateless tras un ingress, workers como consumers de Kafka con autoscaling por lag (KEDA), PostgreSQL gestionado (RDS/Aurora u OCI) con réplicas de lectura para log/diff/blame que son read-heavy, y OpenTelemetry de extremo a extremo con el `commit_id` como atributo de correlación. Los renders SVG se cachean en Redis con el par de SHAs como clave, porque el diff visual entre dos versiones concretas es inmutable y cacheable para siempre.

## Mapa MVP → producción

| Componente MVP | Producción |
|---|---|
| SQLite | PostgreSQL particionado + RLS multi-tenant |
| Blob store en filesystem | S3/OCI con presigned URLs y verificación de checksum |
| Indexado síncrono en commit | Worker Kafka (`commit.created`) con transactional outbox |
| Merge en proceso local | Operación de API ejecutada en worker, resolución interactiva en Web UI |
| Solo DXF | DWG vía worker de conversión ODA File Converter |
| Sin XREFs | Tabla de dependencias + validación de snapshot consistente |
| CLI | CLI + plugin AutoCAD (.NET) con lock/heartbeat + Web UI con diff visual |
| Locks con TTL | Locks PostgreSQL + heartbeat del plugin + eventos de expiración |
