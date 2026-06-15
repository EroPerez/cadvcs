# Spec 18 — Cache de renders en Redis

**Módulos:** `cadvcs/cache.py` (`RenderCache`, `render_cache`), cableado en los endpoints `render` y `diff/visual` de `cadvcs/api/main.py`

## Propósito

Evitar recomputar renders SVG idénticos. Generar el SVG de una versión o el diff visual entre dos versiones es costoso (parsear DXF, proyectar geometría), y el resultado es inmutable: depende solo de los SHAs de contenido. ARCHITECTURE.md pide cachear los renders en Redis con el par de SHAs como clave.

## Comportamiento

Un render es **inmutable** porque sus entradas son content-addressed: el SVG de una versión depende solo del `blob_sha` de ese DXF, y el diff visual entre dos versiones depende solo del par `(sha_a, sha_b)`. Por tanto la clave de cache es determinista y no necesita invalidación —un par de SHAs identifica un diff visual para siempre. Los endpoints `render` y `diff/visual` consultan Redis con esa clave; si hay hit, devuelven el SVG cacheado sin recomputar; si no, lo generan y lo guardan. El orden importa en el diff (`a→b` no es `b→a`), así que la clave no se normaliza.

Degradación: sin `CADVCS_REDIS_URL` o si Redis no responde, el cache es un **no-op silencioso** (get→None, set→nada). El sistema funciona igual, solo recomputa. Un fallo de Redis nunca propaga a la petición: tanto la conexión inicial como cada get/set están envueltos para que un Redis caído degrade a "sin cache", no a un error 500.

`/health` reporta `render_cache: redis|off` para visibilidad operativa.

## Decisiones de diseño

El no-op ante ausencia o fallo de Redis es deliberado: el cache es una optimización, nunca una dependencia dura. Esto mantiene la propiedad de que el sistema corre sin infraestructura externa (igual que con S3, Kafka y el conversor DWG), y que un incidente de Redis degrada el rendimiento pero no la disponibilidad.

Sin TTL por defecto: como las claves son inmutables, no expiran; la presión de memoria se gestiona con la política de evicción de Redis (`maxmemory-policy allkeys-lru`), no con expiración por clave, porque cualquier render puede volver a pedirse y siempre será válido.

## Limitaciones conocidas

El cache se puebla bajo demanda (lazy), no de forma proactiva por el worker de render; un primer acceso a un diff concreto siempre lo computa. No hay aún un worker de pre-render que caliente el cache tras un commit. La invalidación no existe por diseño (claves inmutables), pero eso implica que un cambio en el algoritmo de render no invalida entradas viejas automáticamente: un despliegue que cambie el SVG generado requeriría un prefijo de versión en la clave (no implementado; las claves actuales no versionan el renderer).
