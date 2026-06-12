# Spec 04 — Merge a tres vías por entidad

**Módulo:** `cadvcs/merge.py`, orquestado desde `repo.py`

## Propósito

Fusionar automáticamente dos ramas que modificaron el mismo plano cuando los cambios no colisionan, reportando como conflicto únicamente las colisiones reales — el equivalente CAD del merge textual de Git.

## Comportamiento

Dado el merge-base (LCA del DAG, calculado en `repo.merge_base`), cada handle se clasifica en cada lado respecto al base como unchanged/modified/added/deleted. La matriz de decisión: cambios solo en theirs se aplican sobre el documento de ours (atributos para modified, importación vía `ezdxf.addons.Importer` para added — con `finalize()` para arrastrar layers y estilos —, borrado para deleted); cambios iguales en ambos lados convergen sin conflicto; y colisionan modify/modify con fingerprints distintos, modify/delete en cualquier dirección, y add/add con el mismo handle y contenido distinto. Antes del merge de contenido, `repo.merge` resuelve los casos triviales a nivel de árbol: fast-forward cuando ours es ancestro de theirs, already-up-to-date, y "solo cambió un lado" tomando el blob directamente. Si hay cualquier conflicto, no se escribe nada: el workdir se restaura al estado de ours y se lanza `MergeConflictError` con el detalle estructurado.

## Decisiones de diseño

El caso add/add merece mención: los handles DXF se asignan secuencialmente por archivo, así que dos ramas que parten del mismo base pueden asignar el mismo handle a entidades nuevas distintas. Tratarlo como conflicto explícito (en vez de asumir identidad) es la única opción correcta. El merge es todo-o-nada por diseño: un merge parcialmente aplicado en el workdir sería un estado inconsistente imposible de razonar.

## Limitaciones conocidas

Las entidades importadas desde theirs reciben handle nuevo en el documento fusionado — su identidad histórica se reinicia y el blame las atribuirá al merge commit. Los PDM comerciales resuelven esto con GUIDs propios por entidad (ver ROADMAP). Binarios no-DXF divergentes no son fusionables: se reportan como conflicto de archivo completo.
