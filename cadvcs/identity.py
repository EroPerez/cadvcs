"""Identidad estable de entidades mediante GUID en XDATA.

Los handles DXF son por-archivo: dos ramas que parten del mismo base
asignan los mismos handles a entidades nuevas distintas (falsos add/add),
y el Importer reasigna handles al fusionar (la identidad histórica se
perdía en cada merge). La solución estándar de los PDM: un GUID propio
por entidad, inyectado como XDATA bajo el appid CADVCS en el primer
commit que toca la entidad, que viaja con ella a través de saves,
branches y merges.

La identidad efectiva (`entity_uid`) es el GUID si existe, con fallback
al handle — los blobs anteriores a esta versión siguen funcionando sin
migración.
"""
from __future__ import annotations

import uuid

APPID = "CADVCS"
_GUID_CODE = 1000  # string XDATA


def entity_uid(entity) -> str:
    """GUID CADVCS de la entidad, o su handle como fallback legacy."""
    if entity.has_xdata(APPID):
        for code, value in entity.get_xdata(APPID):
            if code == _GUID_CODE:
                return str(value)
    return entity.dxf.handle


def ensure_guids(doc) -> int:
    """Inyecta GUID a toda entidad del modelspace que no lo tenga.

    Devuelve cuántos inyectó (0 → el documento no cambió y no hace
    falta re-guardarlo).
    """
    added = 0
    for entity in doc.modelspace():
        if not entity.has_xdata(APPID):
            if APPID not in doc.appids:
                doc.appids.add(APPID)
            entity.set_xdata(APPID, [(_GUID_CODE, uuid.uuid4().hex)])
            added += 1
    return added


def copy_uid(src_entity, dst_entity, dst_doc) -> None:
    """Re-aplica el GUID tras un Importer (que descarta XDATA)."""
    if not src_entity.has_xdata(APPID):
        return
    if APPID not in dst_doc.appids:
        dst_doc.appids.add(APPID)
    dst_entity.set_xdata(APPID, src_entity.get_xdata(APPID))
