# Spec 05 — Resolución interactiva de conflictos

**Módulos:** `cadvcs/merge.py` (parámetro `resolutions`), `repo.py`, endpoint `POST /merge/resolve`

## Propósito

Cerrar el ciclo del conflicto: tras un merge rechazado, permitir elegir ours/theirs por entidad (o por archivo completo para binarios) y commitear el resultado.

## Comportamiento

La resolución es **stateless**: `POST /repos/{n}/merge/resolve` no consume una sesión guardada del 409 anterior — recalcula el merge a tres vías completo desde las refs y aplica las elecciones `{repo_path: {handle: "ours"|"theirs"}}` allí donde la clasificación detecta conflicto. Semántica al elegir `theirs`: en modify/modify se aplican sus atributos; en modify/delete se re-importa la entidad que ours borró, o se borra la que ours modificó, según la dirección; en add/add se sustituye el contenido (atributos si el dxftype coincide, reemplazo de entidad si no). Elegir `ours` deja el lado local intacto. La clave especial `__file__` resuelve binarios divergentes tomando el blob completo de un lado. **La resolución parcial devuelve 409 con únicamente los conflictos restantes**, habilitando resolución incremental desde una UI. En CLI: `cadvcs merge rama --user ero --resolve plano.dxf:31=theirs` (repetible).

## Decisiones de diseño

Stateless elimina la gestión de sesiones de merge (expiración, limpieza, invalidación si la rama avanza entre el 409 y el resolve): si las refs cambiaron, el recálculo simplemente opera sobre la realidad actual. El payload del 409 contiene los atributos completos de ambos lados por conflicto — exactamente lo que una UI necesita para pintar la elección sin llamadas adicionales.

## Limitaciones conocidas

No hay resolución "manual" (un tercer valor distinto de ours/theirs, p. ej. editar la entidad durante la resolución); el flujo para eso es resolver, hacer checkout y commitear la edición encima.
