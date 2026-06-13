# Spec 15 — Web UI

**Módulos:** `cadvcs/web/index.html` (SPA), montaje en `cadvcs/api/main.py`

## Propósito

Dar una interfaz visual a todo el sistema y, sobre todo, cerrar el lazo del conflicto de fusión: ver ambos lados de cada entidad en discordia y elegir cuál conservar, alimentando el endpoint `merge/resolve` ya existente.

## Comportamiento

Una SPA en vanilla JS (sin toolchain de build) servida por FastAPI como ficheros estáticos en `/ui/`, con redirect desde `/`. El shell es público —es lo que carga el navegador, sin token— mientras que cada llamada de datos que hace pasa por la autenticación de la API; en modo OIDC el UI adjunta el Bearer de un campo de token guardado en `sessionStorage`. La app es un shell de aplicación con tres zonas acopladas (rail de repos y ramas, lienzo del plano, panel de contexto) y cinco vistas: historial con decoraciones de ramas/tags, comparación con diff visual SVG, fusión con el resolutor de conflictos, autoría por entidad y gestión de bloqueos.

El resolutor es la pieza central: cuando una fusión devuelve 409, renderiza cada conflicto como una "nube de revisión" (rojo, el color real de las revisiones en CAD) con los dos lados —ours y theirs— mostrando el valor en discordia; al elegir un lado por entidad, un contador refleja el progreso y, cuando todos están resueltos, el botón envía las elecciones a `merge/resolve`. La resolución parcial vuelve a mostrar solo lo que falta, igual que el contrato de la API.

## Decisiones de diseño

El lenguaje visual es la mesa de dibujo, no la pantalla: workspace blanco papel (los planos renderizan oscuro-sobre-claro, como un plano físico), azul de cianotipo como estructura y un único acento rojo que es semántico —eliminado/conflicto/nube de revisión— en vez de decorativo. Todo dato de ingeniería (SHAs, handles, coordenadas, commit ids) va en monoespaciada: es la firma tipográfica, fiel a las herramientas técnicas. Vanilla JS en un solo fichero en vez de un framework con build: cero dependencias de tooling, servible tal cual, y suficiente para un shell de esta superficie.

## Verificación

Además de servirse y renderizar, hay un **test de contrato UI↔API**: extrae del JavaScript cada ruta que el UI invoca (colapsando las concatenaciones de path en comodines) y verifica que cada una existe como ruta real en la app FastAPI. Eso detecta deriva entre front y API —un endpoint renombrado, un typo— sin navegador. El smoke por HTTP confirma que un 409 real produce exactamente el shape que el resolutor consume.

## Limitaciones conocidas

Sin verificación visual automatizada (no hay navegador headless en CI): el test cubre que se sirve, el contrato de rutas y el flujo de datos, no el render pixel a pixel. La subida de planos desde el UI usa el `PUT /files` síncrono; el flujo presigned (spec 13) no está cableado en el front todavía. No hay edición de geometría en el navegador: la resolución elige ours/theirs por entidad, no una tercera versión editada a mano.
