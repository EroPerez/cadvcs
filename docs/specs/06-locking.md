# Spec 06 — Locking pesimista

**Módulos:** `cadvcs/repo.py` (lock/unlock/_check_locks), tabla `locks`

## Propósito

Proteger los archivos que no admiten merge (DWG y binarios en general) del clásico "el último que guarda pisa al anterior": el lock con check-out/check-in es la única salvaguarda real para contenido no fusionable, el mismo modelo de Autodesk Vault o SVN con `needs-lock`.

## Comportamiento

`lock(path, owner, ttl)` adquiere de forma atómica (INSERT con clave primaria en `repo_path`; el constraint hace el trabajo de exclusión) con un TTL por defecto de 8 horas que evita locks huérfanos de sesiones muertas — la purga de expirados corre antes de cada operación de lock. La adquisición es re-entrante para el mismo owner. `commit` verifica que ningún archivo cambiado esté lockeado por otro usuario y falla con `LockError` si lo está; `unlock` solo lo permite al holder salvo `force` explícito. En la API el owner sale del JWT (spec 10), el lock ajeno responde 423 Locked, y `GET /locks` lista los activos.

## Decisiones de diseño

El lock es complemento del merge, no sustituto: para DXF el merge por entidad hace el trabajo y el lock es opcional; para binarios es la única protección. El TTL en vez de locks eternos refleja una realidad operativa — la gente se va de vacaciones con archivos bloqueados — y la ruta de producción añade heartbeat desde el plugin CAD para renovarlo mientras el archivo esté realmente abierto.

## Limitaciones conocidas

Sin notificaciones al expirar o liberar (evento `lock.expired` en la arquitectura de producción) y sin jerarquía de locks (lockear una carpeta/disciplina completa).
