# Spec 11 — Identidad de entidad por GUID

**Módulo:** `cadvcs/identity.py`, integrado en `semdiff.py`, `merge.py` y `repo.py`

## Propósito

Sustituir el handle DXF (identidad por-archivo, colisionable entre ramas y reasignada por el Importer) por una identidad global y estable: un GUID propio por entidad que viaja con ella a través de saves, branches y merges.

## Comportamiento

En cada commit, los DXF cambiados reciben un GUID (`uuid4().hex`) como XDATA bajo el appid `CADVCS` en toda entidad del modelspace que aún no lo tenga; si se inyectó alguno, el archivo se re-guarda antes de calcular su SHA, de modo que el blob commiteado ya lleva la identidad. La identidad efectiva (`entity_uid`) es ese GUID con fallback al handle, así los blobs anteriores a esta versión funcionan sin migración. `extract_entities` indexa por uid (conservando el handle real en el registro para localizar entidades en documentos concretos), y diff, merge, resolución y blame operan sobre uids de forma transparente.

Tres consecuencias directas. Primera: desaparecen los falsos conflictos add/add — dos ramas que añaden entidades distintas con el mismo handle (el caso normal, porque ambas asignan el siguiente handle libre del base) ahora tienen uids distintos y el merge importa ambas. Segunda: la identidad sobrevive a los merges — el Importer de ezdxf descarta XDATA, así que tras importar se re-aplica el GUID a cada copia (`copy_uid`). Tercera: blame se reescribió como descenso por el DAG completo en vez de la cadena first-parent — para cada uid se sigue al padre cuya versión tiene el mismo fingerprint, y el commit donde ningún padre coincide es el responsable; combinado con los GUIDs, una entidad creada en una rama y fusionada se atribuye a su autor y commit originales, no al merge commit.

## Decisiones de diseño

XDATA bajo appid propio es el mecanismo estándar de extensión de DXF/DWG: AutoCAD y el resto del ecosistema lo preservan en ediciones normales, no afecta a la geometría ni al render, y no entra en el fingerprint (que se calcula solo sobre atributos DXF, de modo que inyectar identidad nunca cuenta como "modificación de diseño"). Solo se inyecta en archivos del changeset actual: tocar los no cambiados los convertiría en modificados espurios.

## Limitaciones conocidas

Una copia de entidad hecha dentro del CAD duplica también su XDATA: dos entidades con el mismo GUID (la extracción se queda con la última). La mitigación —detectar uids duplicados al commitear y re-generar el GUID de los duplicados— está en el backlog. El primer commit de un archivo legacy reescribe sus bytes (inyección inicial), un cambio one-shot esperado.
