"""Diff visual: render SVG con overlay de colores entre dos versiones DXF.

Construye un documento overlay a partir de la versión nueva y lo recolorea
según el diff semántico:

  verde   → entidades añadidas
  ámbar   → entidades modificadas (en su posición nueva)
  rojo    → entidades eliminadas (re-importadas desde la versión vieja)
  gris    → entidades sin cambios (contexto atenuado)

Las modificadas además dibujan su versión VIEJA como fantasma rojo claro,
así el desplazamiento de una columna se ve como par fantasma→actual.
El SVG resultante es inmutable por par de blobs (cacheable para siempre).
"""
from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.addons import Importer
from ezdxf.addons.drawing import Frontend, RenderContext, layout, svg

from .semdiff import diff_files, extract_entities

COLOR_ADDED = (22, 163, 74)        # verde
COLOR_MODIFIED = (217, 119, 6)     # ámbar
COLOR_REMOVED = (220, 38, 38)      # rojo
COLOR_GHOST = (248, 180, 180)      # rojo claro: estado previo de modificadas
COLOR_CONTEXT = (148, 148, 148)    # gris: sin cambios


def _paint(entity, rgb: tuple[int, int, int], reset_layer: bool = False):
    entity.rgb = rgb
    # Sacar la entidad de BYLAYER para que el color pintado mande
    entity.dxf.discard("color")
    if reset_layer:
        # Las importadas se pintan explícitamente: layer 0 evita depender
        # de que el Importer haya arrastrado la tabla de layers
        entity.dxf.layer = "0"


def render_diff_svg(old_path: Path, new_path: Path) -> str:
    """SVG del overlay de cambios entre dos versiones del mismo plano."""
    d = diff_files(old_path, new_path)
    added = {e["handle"] for e in d.added}
    removed = {e["handle"] for e in d.removed}
    modified = {e["handle"] for e in d.modified}

    overlay = ezdxf.readfile(str(new_path))
    msp = overlay.modelspace()
    for entity in msp:
        h = entity.dxf.handle
        if h in added:
            _paint(entity, COLOR_ADDED)
        elif h in modified:
            _paint(entity, COLOR_MODIFIED)
        else:
            _paint(entity, COLOR_CONTEXT)

    # Importar desde la versión vieja: eliminadas (rojo) y el estado
    # previo de las modificadas (fantasma)
    to_import = removed | modified
    if to_import:
        old_doc = ezdxf.readfile(str(old_path))
        src = {e.dxf.handle: e for e in old_doc.modelspace()}
        importer = Importer(old_doc, overlay)
        entities = [src[h] for h in sorted(to_import) if h in src]
        importer.import_entities(entities, msp)
        importer.finalize()
        # Tras finalize, las importadas son las últimas; ezdxf reasigna
        # handles, así que las localizamos por orden de importación
        imported = list(msp)[-len(entities):]
        for original, copy in zip(entities, imported):
            color = (COLOR_REMOVED if original.dxf.handle in removed
                     else COLOR_GHOST)
            _paint(copy, color, reset_layer=True)

    backend = svg.SVGBackend()
    Frontend(RenderContext(overlay), backend).draw_layout(msp)
    return backend.get_string(layout.Page(0, 0))


def render_version_svg(dxf_path: Path) -> str:
    """SVG simple de una versión (para visores y thumbnails)."""
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()
    backend = svg.SVGBackend()
    Frontend(RenderContext(doc), backend).draw_layout(msp)
    return backend.get_string(layout.Page(0, 0))
