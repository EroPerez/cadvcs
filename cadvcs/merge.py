"""Merge a tres vías de archivos DXF a nivel de entidad.

Dado base (ancestro común), ours y theirs:

  1. Clasificamos el cambio de cada handle en cada lado respecto a base:
     unchanged / modified / added / deleted.
  2. Cambios que no colisionan se aplican automáticamente sobre OURS:
       - modificado solo en theirs  → aplicar atributos de theirs
       - añadido solo en theirs     → importar la entidad
       - borrado solo en theirs     → borrar (si ours no lo modificó)
  3. Colisiones reales se reportan como conflictos (sin auto-resolución):
       - modified/modified con fingerprints distintos
       - modified/deleted en cualquier dirección
       - add/add con el mismo handle y distinto contenido (los handles
         DXF son por-archivo: dos ramas pueden asignar el mismo handle a
         entidades nuevas distintas — caso real que hay que detectar)

Limitación conocida (documentada): las entidades importadas desde theirs
reciben un handle nuevo en el doc fusionado; su identidad histórica se
reinicia. Los PDM comerciales resuelven esto con GUIDs propios por entidad.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from ezdxf.addons import Importer

from .semdiff import extract_entities

UNCHANGED, MODIFIED, ADDED, DELETED = "unchanged", "modified", "added", "deleted"


def _classify(base: dict, side: dict) -> dict[str, str]:
    """Estado de cada handle en `side` respecto a `base`."""
    states = {}
    for h in set(base) | set(side):
        in_base, in_side = h in base, h in side
        if in_base and not in_side:
            states[h] = DELETED
        elif not in_base and in_side:
            states[h] = ADDED
        elif base[h]["fingerprint"] != side[h]["fingerprint"]:
            states[h] = MODIFIED
        else:
            states[h] = UNCHANGED
    return states


@dataclass
class Conflict:
    handle: str
    dxftype: str
    reason: str            # 'modify/modify', 'modify/delete', 'add/add'
    ours: dict | None
    theirs: dict | None


@dataclass
class MergeResult:
    merged_path: Path | None = None
    applied_modified: int = 0
    applied_added: int = 0
    applied_deleted: int = 0
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts

    def summary(self) -> str:
        if self.conflicts:
            return f"CONFLICTO ({len(self.conflicts)} entidades)"
        return (f"auto-merge: ~{self.applied_modified} "
                f"+{self.applied_added} -{self.applied_deleted}")


def _json_to_dxf_value(value):
    """Los attrs vienen de JSON: listas numéricas → tuplas (puntos/vectores)."""
    if isinstance(value, list):
        return tuple(_json_to_dxf_value(v) for v in value)
    return value


def _apply_attrs(entity, attrs: dict):
    for key, value in attrs.items():
        if key == "_points" and entity.dxftype() == "LWPOLYLINE":
            entity.set_points([_json_to_dxf_value(p) for p in value])
            continue
        if key.startswith("_"):
            continue
        try:
            entity.dxf.set(key, _json_to_dxf_value(value))
        except (AttributeError, ValueError, TypeError):
            pass  # atributo no asignable en este tipo: lo ignoramos


def merge_dxf(base_path: Path, ours_path: Path, theirs_path: Path,
              out_path: Path) -> MergeResult:
    base = extract_entities(base_path)
    ours = extract_entities(ours_path)
    theirs = extract_entities(theirs_path)

    ours_state = _classify(base, ours)
    theirs_state = _classify(base, theirs)
    result = MergeResult()

    to_modify, to_add, to_delete = [], [], []

    for h in sorted(set(ours_state) | set(theirs_state)):
        so = ours_state.get(h, UNCHANGED if h in base else None)
        st = theirs_state.get(h, UNCHANGED if h in base else None)

        # Solo existe/cambió en un lado, o cambió igual en ambos
        if st in (None, UNCHANGED):
            continue
        e_theirs = theirs.get(h)

        if st == ADDED:
            if so == ADDED:
                if ours[h]["fingerprint"] == e_theirs["fingerprint"]:
                    continue  # añadieron lo mismo
                result.conflicts.append(Conflict(
                    h, e_theirs["dxftype"], "add/add", ours[h], e_theirs))
            else:
                to_add.append(h)

        elif st == MODIFIED:
            if so == UNCHANGED:
                to_modify.append(h)
            elif so == MODIFIED:
                if ours[h]["fingerprint"] == e_theirs["fingerprint"]:
                    continue  # convergieron al mismo estado
                result.conflicts.append(Conflict(
                    h, e_theirs["dxftype"], "modify/modify", ours[h], e_theirs))
            elif so == DELETED:
                result.conflicts.append(Conflict(
                    h, e_theirs["dxftype"], "modify/delete", None, e_theirs))

        elif st == DELETED:
            if so == UNCHANGED:
                to_delete.append(h)
            elif so == MODIFIED:
                result.conflicts.append(Conflict(
                    h, ours[h]["dxftype"], "modify/delete", ours[h], None))
            # so == DELETED: ambos lo borraron, nada que hacer

    if result.conflicts:
        return result

    # --- Aplicar deltas de theirs sobre el documento de ours -------------
    ours_doc = ezdxf.readfile(str(ours_path))
    msp = ours_doc.modelspace()
    by_handle = {e.dxf.handle: e for e in msp}

    for h in to_modify:
        if h in by_handle:
            _apply_attrs(by_handle[h], theirs[h]["attrs"])
            result.applied_modified += 1

    for h in to_delete:
        if h in by_handle:
            msp.delete_entity(by_handle[h])
            result.applied_deleted += 1

    if to_add:
        theirs_doc = ezdxf.readfile(str(theirs_path))
        src_by_handle = {e.dxf.handle: e for e in theirs_doc.modelspace()}
        importer = Importer(theirs_doc, ours_doc)
        importer.import_entities(
            [src_by_handle[h] for h in to_add if h in src_by_handle],
            ours_doc.modelspace(),
        )
        importer.finalize()  # arrastra layers/linetypes/estilos necesarios
        result.applied_added += len(to_add)

    ours_doc.saveas(str(out_path))
    result.merged_path = Path(out_path)
    return result
