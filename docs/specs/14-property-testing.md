# Spec 14 — Property-based testing del merge

**Módulos:** `tests/test_merge_properties.py`, `pytest.ini`, `tests/test_script_suites.py`

## Propósito

Verificar el motor de merge a tres vías —la parte más compleja y sutil del sistema— con propiedades que deben cumplirse para *cualquier* configuración de cambios, en vez de solo los escenarios concretos que se nos ocurra escribir.

## Comportamiento

Una estrategia de hypothesis genera un conjunto de entidades base y asigna a cada una un "destino" que determina cómo divergen ours y theirs respecto al base: sin cambios, modificada en un lado, modificada igual en ambos, modificada distinto (conflicto), borrada en uno o ambos lados, y las dos variantes de modify/delete. Se materializan `base/ours/theirs.dxf` con GUIDs compartidos (ours y theirs derivan del base, heredando identidad), se ejecuta `merge_dxf` y se comprueban invariantes:

Sin pérdida espuria: una entidad sin cambios en ningún lado sobrevive con su fingerprint intacto. Cambios de un solo lado se preservan (ours) o se aplican (theirs). Convergencia: un cambio idéntico en ambos lados no es conflicto. Detección: toda divergencia real produce conflicto, y cada conflicto reportado corresponde a un destino conflictivo. Totalidad de la resolución: resolver todos los conflictos —con theirs, o con elecciones ours/theirs aleatorias por conflicto— siempre produce un merge limpio y un DXF reabrible. Determinismo: la misma entrada da el mismo resultado.

Las cuatro propiedades corren cientos de ejemplos cada una (200 + 150 + 80 + 150, más una corrida de estrés de 600 en la invariante principal durante el desarrollo). El merge resistió todo el fuzzing sin un solo contraejemplo, lo que da una confianza en el motor que los tests por ejemplo no pueden dar.

## Decisiones de diseño

`pytest` pasa a ser el runner unificado; `tests/test_script_suites.py` ejecuta las suites de script históricas (`demo.py`, `test_api.py`, y opcionalmente `test_s3`/`test_presigned` si están presentes y moto está instalado) como subprocesos, de modo que la migración a pytest es incremental y no big-bang: las suites existentes siguen siendo la fuente de verdad de la integración mientras las nuevas se escriben nativas. Un job de CI dedicado corre solo las property tests, sin servicios, para aislar fallos del motor.

## Limitaciones conocidas

Las entidades generadas son círculos (centro como variable de cambio); no se fuzzean tipos heterogéneos ni geometría compleja (polilíneas, bloques), que podrían exponer casos del `_apply_attrs`/Importer no cubiertos. Las propiedades verifican el motor `merge_dxf`, no el merge multi-archivo de `repo.merge` (árbol, fast-forward, binarios) ni el blame, que siguen cubiertos por las suites de ejemplo.
