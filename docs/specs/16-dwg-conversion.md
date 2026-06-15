# Spec 16 — Conversión DWG → DXF

**Módulos:** `cadvcs/convert.py`, worker de conversión en `cadvcs/repo.py` (`_convert_dwg`, `index_one` kind=convert), tabla `dwg_mirrors`, columna `kind` en `index_outbox`

## Propósito

Soportar DWG de verdad. El diff semántico, el merge y el blame operan sobre entidades DXF; un DWG es un binario opaco que el sistema no puede inspeccionar. Para que un DWG entre en el modelo de entidades necesita un **DXF espejo**, y generarlo es el trabajo del worker de conversión.

## Comportamiento

Al commitear un `.dwg`, el commit encola en el outbox un evento con `kind='convert'` (frente a `kind='index'` de los DXF), en la misma transacción. El worker, al procesar ese evento, materializa el DWG desde el store, lo convierte a DXF mediante el conversor configurado, le inyecta GUIDs para identidad estable de entidades, guarda el DXF espejo en el store (content-addressed, igual que cualquier blob), registra la relación en `dwg_mirrors (dwg_sha → dxf_sha)` e indexa el espejo. A partir de ahí, el DWG tiene diff de entidades, blame y render como si fuera un DXF, operando sobre su espejo.

La conversión es idempotente y deduplicada: si un DWG ya tiene espejo (mismo `dwg_sha`), no se vuelve a encolar ni a convertir. El espejo es estable porque, dada una versión del conversor, el mismo DWG produce el mismo DXF.

El motor de conversión es un **backend pluggable** seleccionado por `CADVCS_DWG_CONVERTER`: `aspose` (Aspose.CAD, requiere la librería y licencia), `oda` (ODA File Converter, binario externo vía `CADVCS_ODA_BIN`), o `none`. Sin conversor, el sistema degrada con gracia: el DWG se versiona como binario opaco —se puede subir, descargar y bloquear— pero no obtiene espejo ni diff de entidades, exactamente como antes de esta spec. Añadir un backend es implementar `Converter.to_dxf(src, dst)`; el resto del sistema solo conoce esa interfaz, nunca el motor concreto.

## Decisiones de diseño

El conversor real (Aspose.CAD, ODA) es software propietario/licenciado que no se puede asumir presente, así que la abstracción pluggable es lo que permite tener el camino completo del worker —encolado, conversión, espejo, índice, dedup, degradación— construido y verificado de extremo a extremo sin depender del motor: los tests usan un `StubConverter` que ejercita todo el flujo. Cuando haya licencia de Aspose o el binario ODA, es solo seleccionar el backend; cero cambios en el worker o el modelo.

El espejo se modela como un blob más en el store content-addressed (no un formato especial), de modo que toda la maquinaria existente —dedup, S3, gc— aplica sin cambios.

## Limitaciones conocidas

La conversión real no se puede verificar en CI sin licencia/binario; el `StubConverter` (que trata el "DWG" de entrada como DXF válido) verifica el flujo del worker pero no la fidelidad de la conversión geométrica, que depende del motor. El gc no recolecta espejos huérfanos todavía: si un DWG deja de estar referenciado, su DXF espejo permanece en `dwg_mirrors` y en el store (trabajo futuro, análogo al gc multi-repo de S3). La identidad de entidades del espejo se basa en GUIDs inyectados tras la conversión; como el conversor puede no preservar handles entre versiones del DWG, dos versiones del mismo DWG podrían no compartir identidad de entidad si el conversor reordena —en la práctica se mitiga inyectando GUIDs, pero la estabilidad depende del determinismo del motor.
