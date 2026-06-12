# Spec 03 — Diff semántico por entidad DXF

**Módulo:** `cadvcs/semdiff.py`

## Propósito

Convertir el diff entre dos versiones de un plano de "el binario cambió" a "qué entidades de diseño se añadieron, eliminaron o modificaron, y en qué atributos".

## Comportamiento

La identidad de cada entidad es su **handle DXF**, un identificador hexadecimal que persiste entre saves del mismo documento. `extract_entities()` recorre el modelspace y produce, por handle, el tipo DXF, la layer, un diccionario de atributos serializables (con redondeo a 9 decimales para estabilidad de coma flotante, y caso especial para los puntos de LWPOLYLINE) y un **fingerprint** SHA-256 truncado del JSON canónico de esos atributos. `diff_entities()` compara dos mapas: handles solo en el nuevo → added, solo en el viejo → removed, en ambos con fingerprint distinto → modified con el detalle atributo a atributo (valor viejo → nuevo).

## Decisiones de diseño

El fingerprint permite comparar versiones sin re-comparar atributos uno a uno, y al persistirse en el índice `entities`, el diff entre dos versiones históricas cualesquiera es un par de lecturas de BD sin parsear DXF. Atributos internos sin significado de diseño (`handle`, `owner`, `reactors`...) se excluyen para que un re-save sin cambios reales no genere ruido.

## Limitaciones conocidas

Solo modelspace (no paperspace/layouts ni bloques anidados); los handles son por-archivo, lo que tiene consecuencias en merge (ver spec 04); DWG requiere conversión previa a DXF.
