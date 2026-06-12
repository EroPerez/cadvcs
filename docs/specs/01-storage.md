# Spec 01 — Almacenamiento content-addressed

**Módulo:** `cadvcs/storage.py`

## Propósito

Almacenar el contenido binario de cada versión de cada archivo de forma inmutable, deduplicada y verificable, desacoplando el contenido (blobs) de la metadata (commits, refs).

## Comportamiento

Cada archivo se identifica por el SHA-256 de su contenido y se guarda una única vez bajo `objects/<sha[:2]>/<sha[2:]>`, el mismo layout de sharding que usa Git para evitar directorios con millones de entradas. `put()` es idempotente: si el blob ya existe, no se reescribe — esto da deduplicación automática entre versiones, ramas y archivos idénticos. La escritura es atómica (fichero temporal + `rename` en el mismo directorio) para que un crash a mitad de escritura nunca deje un blob corrupto direccionable. `get()` materializa un blob en cualquier destino y `hash_file()` calcula el digest por chunks de 1 MiB para no cargar archivos grandes en memoria.

## Decisiones de diseño

El content-addressing es la decisión de la que cuelga todo lo demás: hace baratos los snapshots completos por commit (archivos sin cambios apuntan al mismo blob), da integridad verificable (el nombre ES el checksum), y permite que el índice semántico se asocie al blob en vez de a la revisión. La interfaz (`put`/`get`/`exists` por digest) es deliberadamente idéntica a la de un object storage S3/OCI con el SHA como key, de modo que el backend de producción es un cambio de implementación, no de modelo.

## Limitaciones conocidas

No hay compresión delta entre versiones consecutivas (xdelta3 reduciría el storage de archivos CAD que cambian poco entre saves) ni garbage collection de blobs huérfanos — ver ROADMAP.
