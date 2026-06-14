# cadvcs — Control de versiones tipo Git para archivos CAD

Versionado para archivos CAD (DXF/DWG) con modelo Git completo: DAG de commits multi-archivo, branches, tags, merge a tres vías con **resolución a nivel de entidad DXF**, blame por entidad, y pessimistic locking para binarios no mergeables.

## Arquitectura de producción

![Arquitectura de producción](docs/architecture.svg)

Detalle completo en [ARCHITECTURE.md](ARCHITECTURE.md). Las specs de cada funcionalidad implementada y el backlog de mejoras están en [docs/](docs/).

## Arquitectura del código

```
cadvcs/
├── storage.py   Blob store content-addressed (SHA-256, layout objects/ab/cd...)
├── db.py        Esquema tipo Git: commits (DAG), commit_entries (tree plano),
│                branches/tags (refs), locks (TTL), entities (índice por blob)
├── semdiff.py   Extracción y diff semántico DXF: identidad por handle
├── merge.py     Merge a 3 vías por entidad: clasifica cambios vs merge-base,
│                auto-fusiona lo que no colisiona, reporta conflictos reales
├── repo.py      API: add/status/commit/log/branch/switch/tag/diff/merge/blame
└── cli.py       CLI con comandos tipo Git
```

## Capacidades tipo Git

```bash
cadvcs init                          # crea rama main
cadvcs add plano.dxf                 # tracking
cadvcs status                        # A/M/D vs HEAD
cadvcs commit --user ero -m "..."    # changeset multi-archivo, nodo del DAG
cadvcs log                           # first-parent, con decoraciones (ramas, tags)
cadvcs branch variante-b             # refs baratas (puntero a commit)
cadvcs switch variante-b             # materializa el árbol destino en el workdir
cadvcs diff main variante-b          # tree-level + semántico por entidad en DXF
cadvcs merge variante-b --user ero   # 3 vías con merge-base (LCA del DAG)
cadvcs tag v1.0
cadvcs blame plano.dxf               # último commit que tocó cada entidad
cadvcs lock plano.dxf --user ero     # pesimista, para binarios no mergeables
cadvcs checkout plano.dxf --ref v1.0 --out plano_v1.dxf
```

## El merge a nivel de entidad

La pieza diferencial. Con base = merge-base(ours, theirs), cada handle DXF se clasifica en cada lado como unchanged/modified/added/deleted:

- Cambios en **entidades distintas** se fusionan automáticamente (maria movió la columna en su rama, ero añadió una puerta en main → el merge produce un DXF con ambas cosas).
- Colisiones reales se reportan como conflictos estructurados sin auto-resolver: modify/modify sobre el mismo handle, modify/delete, y add/add con el mismo handle (los handles DXF son por-archivo y dos ramas pueden asignar el mismo a entidades nuevas distintas).
- Fast-forward y already-up-to-date se detectan igual que en Git.

```
merge variante-b → main: merged c4
  plano.dxf: auto-merge: ~1 +0 -0

merge propuesta-x → main:
  CONFLICTO plano.dxf: modify/modify CIRCLE handle=31
    ours:   center=(90.0, 40.0, 0.0)
    theirs: center=(10.0, 10.0, 0.0)
```

Limitación documentada: las entidades importadas desde theirs reciben handle nuevo en el doc fusionado (identidad histórica reiniciada). Los PDM comerciales lo resuelven con GUIDs propios por entidad.

## Decisiones de diseño

1. **Tree plano por commit** en vez de objetos tree jerárquicos: cada commit lista (repo_path, blob_sha). Con content-addressing, los archivos sin cambios reutilizan el mismo blob — snapshot completo barato, modelo mental simple.
2. **Índice semántico por blob, no por revisión**: la tabla `entities` se indexa una vez por SHA único. diff/merge/blame entre versiones históricas nunca re-parsean DXF.
3. **Locking pesimista como complemento, no sustituto**: el merge por entidad cubre DXF; para DWG/binarios divergentes el merge se rechaza y el lock es la protección.
4. **blame por fingerprint**: recorre la cadena first-parent y atribuye cada entidad al commit donde su fingerprint cambió respecto al padre.

## Uso por API

```python
from cadvcs.repo import Repo, MergeConflictError

repo = Repo.init("/proyectos/nave")
repo.add(path)
repo.commit("ero", "Planta inicial")
repo.branch_create("variante-b"); repo.switch("variante-b")
# ... editar y commitear ...
repo.switch("main")
try:
    info = repo.merge("variante-b", author="ero")
except MergeConflictError as e:
    for path, conflicts in e.details.items(): ...
```

Demo completa (`python demo.py`): dos usuarios, dos ramas, merge automático verificado con asserts, conflicto modify/modify, restauración del workdir, log y blame.

## Producción

Ver **ARCHITECTURE.md**: API REST + PostgreSQL + S3/OCI con presigned URLs, workers Kafka (indexado, conversión DWG→DXF con ODA, render para diff visual), transactional outbox, locking con heartbeat desde el plugin AutoCAD, grafo de XREFs, multi-tenancy con RLS y gc de blobs estilo `git gc`.

## API REST (FastAPI)

La API expone el mismo `repo.py` por HTTP, con working copy server-side por repositorio bajo `CADVCS_DATA`. Endpoints síncronos en threadpool + un lock por repo serializando mutaciones (SQLite WAL con `busy_timeout`); en producción ese lock se sustituye por transacciones PostgreSQL.

```bash
pip install -r requirements.txt
uvicorn cadvcs.api.main:app --reload     # docs en http://localhost:8000/docs
```

```
POST   /repos                          crear repo            → 201
GET    /repos | /repos/{name}          listar / info
PUT    /repos/{n}/files/{path}         subir a working copy (octet-stream)
GET    /repos/{n}/files/{path}?ref=    descargar blob de cualquier ref
GET    /repos/{n}/status               A/M/D vs HEAD
POST   /repos/{n}/commits              {author, message}     → 201 | 422 | 423
GET    /repos/{n}/commits?ref=&limit=  log decorado
POST   /repos/{n}/branches | GET       crear / listar ramas
POST   /repos/{n}/switch               {branch, force}
POST   /repos/{n}/tags | GET           crear / listar tags
GET    /repos/{n}/diff?ref_a=&ref_b=   tree-level + semántico por entidad
POST   /repos/{n}/merge                {branch, author}      → 200 | 409
GET    /repos/{n}/blame/{path}?ref=    atribución por entidad
POST   /repos/{n}/locks | GET          adquirir / listar     → 201 | 423
DELETE /repos/{n}/locks/{path}?owner=  liberar               → 204
```

Semántica HTTP: 409 para conflictos de merge con payload estructurado (handle, razón, ours/theirs), 423 Locked para locks ajenos, 422 para errores de dominio (commit vacío, ref inexistente). El conflicto 409 devuelve exactamente lo que una UI de resolución necesita:

```json
{
  "detail": "Merge con conflictos en 1 archivo(s)",
  "conflicts": {
    "plano.dxf": [{
      "handle": "31", "dxftype": "CIRCLE", "reason": "modify/modify",
      "ours":   {"attrs": {"center": [90.0, 40.0, 0.0]}},
      "theirs": {"attrs": {"center": [10.0, 10.0, 0.0]}}
    }]
  }
}
```

Seguridad MVP: validación de slug de repo, guard anti path-traversal en rutas de archivo (incluida la forma URL-encoded), y la dir `.cadvcs` inaccesible vía API. Test end-to-end en `test_api.py` (24 checks: flujo completo de ramas y merge vía HTTP, 409 estructurado, 423 de locks, descarga histórica).

## Resolución interactiva de conflictos

El ciclo del 409 se cierra de forma **stateless**: `POST /repos/{n}/merge/resolve` recalcula el merge a tres vías desde las refs aplicando elecciones por handle, así que no hay sesión de merge en servidor ni estado intermedio que limpiar.

```json
POST /repos/nave/merge/resolve
{
  "branch": "propuesta",
  "resolutions": {
    "plano.dxf": { "31": "theirs", "2F": "ours" },
    "render.png": { "__file__": "theirs" }
  }
}
```

Semántica por tipo de conflicto al elegir `theirs`: en modify/modify se aplican los atributos de theirs; en modify/delete se re-importa la entidad borrada (o se borra la modificada, según la dirección); en add/add se sustituye el contenido (mismo dxftype → atributos; distinto → reemplazo de entidad). La clave `__file__` resuelve binarios divergentes completos. La **resolución parcial devuelve 409 solo con los conflictos restantes**, lo que permite a una UI resolver de forma incremental. En CLI: `cadvcs merge rama --user ero --resolve plano.dxf:31=theirs` (repetible).

## Auth OIDC

Toda la API requiere JWT Bearer RS256 validado contra el JWKS del identity provider (descubierto vía `/.well-known/openid-configuration`, con override por `CADVCS_OIDC_JWKS_URL` o fichero local para tests/air-gapped). El `author` de commits y merges y el `owner` de locks salen de `preferred_username` del token — el cliente ya no puede suplantar identidad por body.

```bash
export CADVCS_OIDC_ISSUER=https://idp.example.com/realms/cad
export CADVCS_OIDC_AUDIENCE=cadvcs
uvicorn cadvcs.api.main:app
```

Sin issuer configurado la API arranca en modo dev sin auth (principal `dev`) con warning explícito. El test suite genera su propio par RSA y JWKS, firma tokens reales para dos usuarios y cubre los 401 (sin token, firma ajena, expirado, audience incorrecta) además del flujo completo de resolución.

## Blob store en S3/OCI

Los blobs pueden vivir en object storage S3-compatible definiendo `CADVCS_BLOB_URL=s3://bucket/prefijo` (credenciales por la cadena estándar de AWS; `CADVCS_S3_ENDPOINT` para MinIO, OCI Object Storage en modo S3-compat o LocalStack). La interfaz es idéntica al backend local —misma clave SHA-256 con sharding `objects/ab/cdef...`— así que `repo.py` no cambia. El bucket es global: la deduplicación funciona también **entre repositorios** (dos repos con el mismo plano comparten blob). La descarga por la API pasa a streaming desde el store, sin tocar disco intermedio. Suite específica en `test_s3.py` (moto), también en CI.
## Producción

La metadata puede vivir en **PostgreSQL** definiendo `CADVCS_DB_URL` (formato `postgresql://user:pass@host/db`): un schema por repositorio mantiene el SQL idéntico entre backends y aísla repos entre sí. Sin la variable, cada repo usa su SQLite local como siempre. El wrapper de conexión normaliza paramstyle, `INSERT OR IGNORE`/`ON CONFLICT`, transacciones e ids autogenerados; los timestamps son TEXT UTC en ambos para que la expiración de locks compare igual. Ambas suites corren contra los dos backends en CI.

Despliegue con Docker:

```bash
cp .env.example .env   # definir POSTGRES_PASSWORD y el issuer OIDC
docker compose up -d   # PostgreSQL 16 + API con healthchecks
curl localhost:8000/health
```

`GET /health` (sin token: es la sonda de Kubernetes/LB) verifica conectividad de metadata y escritura en storage, y reporta el backend activo. La imagen corre como usuario no privilegiado con `HEALTHCHECK` integrado.

## Tests

Las suites de script (`demo.py`, `test_api.py`, `test_s3.py`, `test_async.py`, `test_presigned.py`) cubren integración end-to-end y corren en CI sobre ambos backends. Además, `tests/` contiene **property-based tests** del motor de merge con hypothesis: generan cientos de configuraciones aleatorias de cambios base/ours/theirs y verifican invariantes (sin pérdida espuria, cambios de un lado preservados, convergencia, detección de conflictos, totalidad de la resolución, determinismo). `pytest` es el runner unificado (`python -m pytest`); el adaptador `tests/test_script_suites.py` ejecuta las suites de script para una migración incremental.
## Indexado asíncrono

El parseo de entidades DXF sale del path de commit mediante **transactional outbox**: el commit escribe un evento `pending` en `index_outbox` en su misma transacción, y `python -m cadvcs.worker` lo drena en segundo plano (multi-repo sobre `CADVCS_DATA`, `--once` para CI o polling con backoff para despliegue). La correctitud no depende del worker: si un diff/merge/blame toca un blob aún no indexado, `_entities_for_blob` lo indexa bajo demanda y cierra el evento, así que el worker solo reduce latencia. `docker-compose.yml` incluye el servicio worker. Suite en `test_async.py`, en CI sobre ambos backends.

## Subida y descarga directas a object storage (presigned)

Con backend S3, el servidor puede salir del path de bytes para archivos grandes (modelo Git-LFS). Flujo de subida dedup-aware:

1. El cliente calcula el SHA-256 en local y pide `POST /repos/{n}/blobs/{sha}/upload-url`. Si el blob ya existe → `{exists:true}` sin URL (cero transferencia). Si no → `{exists:false, upload_url}` (PUT presigned).
2. El cliente hace `PUT` directo a object storage con esa URL — los bytes nunca pasan por la API.
3. `PUT /repos/{n}/staged/{path}` con `{sha256,size}` registra el blob por referencia; el `commit` siguiente lo incluye sin leer bytes.

Descarga: `GET /files/{path}?presigned=true` devuelve un `307` a una URL GET presigned (la descarga sale directa de S3). La subida/descarga por la API (`PUT/GET /files`) siguen disponibles para el backend local y archivos pequeños. Suite en `test_presigned.py` (moto server por HTTP real), en CI sobre ambos backends.
## Web UI

Interfaz visual servida por la propia API en `/ui/` (redirect desde `/`). Cubre todo el sistema —historial, comparación con diff visual, fusión, autoría y bloqueos— y su pieza central es el **resolutor de conflictos**: ante un 409 de fusión, muestra cada entidad en discordia con sus dos lados y permite elegir ours/theirs por entidad, enviando las elecciones a `merge/resolve`. SPA en vanilla JS sin build; el shell es público y las llamadas de datos llevan el token. El lenguaje visual es la mesa de dibujo: papel blanco, azul de cianotipo y rojo de revisión semántico, con monoespaciada para todo dato (SHAs, handles, coordenadas). Verificado con un test de contrato UI↔API que comprueba que cada ruta invocada por el front existe en la API.

## Infraestructura: conversión DWG, Kafka, Redis

El sistema soporta tres servicios de producción, **todos opcionales con degradación a no-op**:

- **Conversión DWG→DXF** (`CADVCS_DWG_CONVERTER`): un `.dwg` commiteado encola un evento `convert`; el worker genera su DXF espejo (registrado en `dwg_mirrors`), sobre el que operan diff, blame y render. Backend pluggable: `aspose` (Aspose.CAD, requiere licencia), `oda` (ODA File Converter vía `CADVCS_ODA_BIN`) o `none` (DWG como binario opaco). Spec 16.
- **Eventos sobre Kafka** (`CADVCS_KAFKA_BROKERS`): el outbox (fuente de verdad transaccional) se publica en Kafka por un *relay* y lo consumen workers en un consumer group que escala horizontalmente. `python -m cadvcs.worker --mode relay|consume`. Sin Kafka, el worker de polling sigue funcionando. Spec 17.
- **Cache de renders en Redis** (`CADVCS_REDIS_URL`): los SVG de render y diff visual son inmutables (dependen solo de los SHAs de contenido), así que se cachean por clave de SHAs sin invalidación. Sin Redis, se recomputa. Spec 18.

`docker-compose.yml` levanta el stack completo (PostgreSQL, Redis, Kafka en KRaft, API, relay, consumer). `/health` reporta el estado de cada pieza. Suite en `test_infra.py` (Redis real, bus Kafka en memoria, stub converter), en CI sobre ambos backends.
