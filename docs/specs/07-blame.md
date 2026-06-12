# Spec 07 — Blame por entidad

**Módulo:** `cadvcs/repo.py` (`blame`)

## Propósito

Responder "¿quién tocó esta columna por última vez y en qué commit?" a nivel de entidad de diseño, no de archivo — la trazabilidad que un archivo binario versionado entero no puede dar.

## Comportamiento

Para la versión de un archivo en una ref, recorre la cadena first-parent hacia atrás y atribuye cada handle al primer commit (más reciente) donde su fingerprint difiere del que tenía en el commit padre, o donde aparece por primera vez. El resultado lista, por entidad de la versión actual: handle, tipo, layer, y el commit/author/message responsable. Toda la comparación se hace contra el índice `entities` por blob — cero parseo de DXF.

## Decisiones de diseño

First-parent (como `git log --first-parent`) da la narrativa de la rama principal: los cambios que entraron por merge se atribuyen al merge commit, lo cual es coherente con la limitación de identidad de handles importados (spec 04). El recorte temprano (`pending`) hace que el coste sea proporcional a la profundidad hasta cubrir todas las entidades, no a la historia completa.

## Limitaciones conocidas

Hereda la limitación de identidad del merge: una entidad re-importada en un merge se atribuye al merge commit, no a su autor original en la rama de origen.
