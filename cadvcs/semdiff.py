"""Diff semántico de archivos DXF.

La clave: cada entidad DXF tiene un *handle* hexadecimal persistente que
sobrevive a los saves. Eso nos da identidad estable para comparar dos
versiones a nivel de entidad (added / removed / modified) en vez de un
diff binario inútil.

Para cada entidad calculamos un fingerprint = hash de sus atributos DXF
relevantes (geometría, layer, color...). Si el handle existe en ambas
versiones pero el fingerprint cambia → modified, y reportamos qué
atributos cambiaron.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf

from .identity import entity_uid

# Atributos que ignoramos: ruido interno que no representa un cambio de diseño
_IGNORED_ATTRS = {"handle", "owner", "reactors", "material_handle", "plotstyle_handle"}


def _entity_attrs(entity) -> dict:
    """Extrae los atributos DXF serializables de una entidad."""
    attrs = {}
    for key, value in entity.dxf.all_existing_dxf_attribs().items():
        if key in _IGNORED_ATTRS:
            continue
        # Vec2/Vec3 y otros tipos de ezdxf → representación estable
        if hasattr(value, "xyz"):
            value = tuple(round(c, 9) for c in value.xyz)
        elif isinstance(value, float):
            value = round(value, 9)
        attrs[key] = value
    # Casos con geometría fuera de dxf attribs (ej. LWPOLYLINE points)
    if entity.dxftype() == "LWPOLYLINE":
        attrs["_points"] = [tuple(round(c, 9) for c in p) for p in entity.get_points()]
    return attrs


def _fingerprint(attrs: dict) -> str:
    payload = json.dumps(attrs, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def extract_entities(dxf_path: Path) -> dict[str, dict]:
    """Devuelve {uid: {dxftype, layer, fingerprint, attrs, handle}}.

    El uid es el GUID CADVCS de la entidad (identidad estable a través
    de branches y merges) con fallback al handle para blobs legacy. El
    handle real del documento viaja en el registro para que el merge
    pueda localizar la entidad en su doc concreto.
    """
    doc = ezdxf.readfile(str(dxf_path))
    result = {}
    for entity in doc.modelspace():
        attrs = _entity_attrs(entity)
        result[entity_uid(entity)] = {
            "dxftype": entity.dxftype(),
            "layer": entity.dxf.get("layer", "0"),
            "fingerprint": _fingerprint(attrs),
            "attrs": attrs,
            "handle": entity.dxf.handle,
        }
    return result


@dataclass
class SemanticDiff:
    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    modified: list[dict] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.modified)

    def summary(self) -> str:
        return (f"+{len(self.added)} añadidas, "
                f"-{len(self.removed)} eliminadas, "
                f"~{len(self.modified)} modificadas")

    def to_dict(self) -> dict:
        return {"summary": self.summary(), "added": self.added,
                "removed": self.removed, "modified": self.modified}


def diff_entities(old: dict[str, dict], new: dict[str, dict]) -> SemanticDiff:
    diff = SemanticDiff()
    old_handles, new_handles = set(old), set(new)

    for h in sorted(new_handles - old_handles):
        e = new[h]
        diff.added.append({"handle": h, "dxftype": e["dxftype"], "layer": e["layer"]})

    for h in sorted(old_handles - new_handles):
        e = old[h]
        diff.removed.append({"handle": h, "dxftype": e["dxftype"], "layer": e["layer"]})

    for h in sorted(old_handles & new_handles):
        if old[h]["fingerprint"] == new[h]["fingerprint"]:
            continue
        changes = {}
        a_old, a_new = old[h]["attrs"], new[h]["attrs"]
        for key in sorted(set(a_old) | set(a_new)):
            if a_old.get(key) != a_new.get(key):
                changes[key] = {"old": a_old.get(key), "new": a_new.get(key)}
        diff.modified.append({
            "handle": h,
            "dxftype": new[h]["dxftype"],
            "layer": new[h]["layer"],
            "changes": changes,
        })
    return diff


def diff_files(old_path: Path, new_path: Path) -> SemanticDiff:
    return diff_entities(extract_entities(old_path), extract_entities(new_path))
