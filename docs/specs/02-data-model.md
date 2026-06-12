# Spec 02 — Modelo de datos tipo Git

**Módulo:** `cadvcs/db.py`

## Propósito

Persistir la historia como un DAG de changesets multi-archivo con refs nombradas, replicando el modelo mental de Git sobre SQLite con un esquema deliberadamente portable a PostgreSQL.

## Comportamiento

`commits` forma el DAG: cada fila tiene `parent_id` y un `parent2_id` opcional que convierte el commit en merge commit. `commit_entries` es el árbol plano de cada commit — la lista completa de `(repo_path, blob_sha)` que existía en ese momento; gracias al content-addressing, un snapshot completo cuesta solo las filas de la tabla, no copias de archivos. `branches` y `tags` son punteros nombrados a commits (refs), `meta` guarda el HEAD (rama actual), `tracked` es el staging-lite de archivos bajo control, y `entities` es el índice semántico DXF **indexado por blob_sha** — un blob compartido por N commits se indexa exactamente una vez.

## Decisiones de diseño

Tree plano en vez de objetos tree jerárquicos como Git: para repositorios CAD (decenas-cientos de archivos por proyecto, no cientos de miles) el coste por commit es trivial y el modelo mental y las queries son mucho más simples — el diff de árboles es un join. SQLite con WAL y `busy_timeout` aguanta el patrón de la API (conexión por request, un writer serializado por repo); las transacciones explícitas con `with conn` en toda mutación evitan transacciones implícitas abiertas, el bug clásico de sqlite3 en Python que detectamos y corregimos en desarrollo.

## Limitaciones conocidas

Sin multi-tenancy ni particionado; `entities.attrs_json` crece linealmente con la complejidad de los planos — la estrategia de producción (solo fingerprints en BD, attrs comprimidos junto al blob) está en ARCHITECTURE.md.
