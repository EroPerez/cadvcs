"""Property-based testing del motor de merge a tres vías.

Estrategia: hypothesis genera un conjunto de entidades base y asigna a
cada una un "destino" (fate) que determina cómo difieren ours y theirs
respecto al base. Materializamos base.dxf / ours.dxf / theirs.dxf con
GUIDs COMPARTIDOS (ours y theirs derivan de base, así heredan identidad),
ejecutamos merge_dxf y verificamos invariantes que deben cumplirse para
CUALQUIER configuración:

  - sin pérdida espuria: una entidad sin cambios en ningún lado sobrevive
  - cambios de un solo lado se aplican (theirs) o se preservan (ours)
  - convergencia: cambio idéntico en ambos lados no es conflicto
  - detección: divergencia real (modify/modify, modify/delete, add/add
    con contenido distinto) produce conflicto
  - totalidad de la resolución: resolver TODOS los conflictos con un
    lado u otro siempre produce un merge limpio
  - determinismo: misma entrada → mismo resultado

Las entidades son círculos (centro = identidad visual del cambio): fáciles
de mutar de forma controlada y de comparar por fingerprint.
"""
import tempfile
from pathlib import Path

import ezdxf
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cadvcs import identity
from cadvcs.merge import merge_dxf
from cadvcs.semdiff import extract_entities

# Destinos posibles de cada entidad base respecto a (ours, theirs)
FATES = [
    "unchanged",        # igual en ambos
    "mod_ours",         # solo ours la cambia
    "mod_theirs",       # solo theirs la cambia
    "mod_both_same",    # ambos la cambian igual (convergencia)
    "mod_both_diff",    # ambos la cambian distinto (CONFLICTO modify/modify)
    "del_ours",         # ours la borra
    "del_theirs",       # theirs la borra
    "del_both",         # ambos la borran
    "mod_ours_del_theirs",   # CONFLICTO modify/delete
    "del_ours_mod_theirs",   # CONFLICTO modify/delete
]

# Fates que producen conflicto sin resolución
CONFLICT_FATES = {"mod_both_diff", "mod_ours_del_theirs", "del_ours_mod_theirs"}


@st.composite
def scenario(draw):
    """Genera (lista de (fate, base_y, ours_y, theirs_y), n_added_ours,
    n_added_theirs). Las x son el índice (identidad posicional al crear)."""
    n = draw(st.integers(min_value=0, max_value=8))
    fates = draw(st.lists(st.sampled_from(FATES), min_size=n, max_size=n))
    # Coordenada Y distinta por entidad para que los cambios sean detectables
    ys = draw(st.lists(st.integers(min_value=0, max_value=1000),
                       min_size=n, max_size=n, unique=True))
    n_add_ours = draw(st.integers(min_value=0, max_value=3))
    n_add_theirs = draw(st.integers(min_value=0, max_value=3))
    return list(zip(fates, ys)), n_add_ours, n_add_theirs


def _build(scenario_data, tmp: Path):
    """Materializa base/ours/theirs.dxf según el escenario.

    Devuelve (paths, expected) donde expected describe, por uid, qué
    debería pasar, para verificar invariantes tras el merge.
    """
    entities, n_add_ours, n_add_theirs = scenario_data
    base_path = tmp / "base.dxf"
    ours_path = tmp / "ours.dxf"
    theirs_path = tmp / "theirs.dxf"

    # --- base: un círculo por entidad, GUID inyectado ---
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for i, (_fate, y) in enumerate(entities):
        msp.add_circle((0, y), radius=5)
    identity.ensure_guids(doc)
    doc.saveas(base_path)

    # uid por posición en base (orden de modelspace estable)
    base_doc = ezdxf.readfile(base_path)
    base_uids = [identity.entity_uid(e) for e in base_doc.modelspace()]

    def derive(side: str, path: Path, n_add: int):
        d = ezdxf.readfile(base_path)
        m = d.modelspace()
        ents = list(m)  # mismo orden que base_uids
        for i, (fate, y) in enumerate(entities):
            e = ents[i]
            mod_val = {"mod_ours": (10, y), "mod_theirs": (20, y),
                       "mod_both_same": (30, y),
                       "mod_both_diff": (40 if side == "ours" else 50, y)}
            delete = (
                (fate == "del_ours" and side == "ours") or
                (fate == "del_theirs" and side == "theirs") or
                (fate == "del_both") or
                (fate == "mod_ours_del_theirs" and side == "theirs") or
                (fate == "del_ours_mod_theirs" and side == "ours"))
            if delete:
                m.delete_entity(e)
                continue
            if fate == "mod_ours" and side == "ours":
                e.dxf.center = mod_val["mod_ours"]
            elif fate == "mod_theirs" and side == "theirs":
                e.dxf.center = mod_val["mod_theirs"]
            elif fate == "mod_both_same":
                e.dxf.center = mod_val["mod_both_same"]
            elif fate == "mod_both_diff":
                e.dxf.center = mod_val["mod_both_diff"]
            elif fate == "mod_ours_del_theirs" and side == "ours":
                e.dxf.center = (60, y)
            elif fate == "del_ours_mod_theirs" and side == "theirs":
                e.dxf.center = (70, y)
        # entidades nuevas exclusivas de cada lado (uid propio nuevo)
        for j in range(n_add):
            na = m.add_circle((100 + j, -1 - j if side == "ours" else 1 + j),
                              radius=2)
        identity.ensure_guids(d)  # GUID a las nuevas
        d.saveas(path)

    derive("ours", ours_path, n_add_ours)
    derive("theirs", theirs_path, n_add_theirs)

    expected = {base_uids[i]: fate for i, (fate, _y) in enumerate(entities)}
    return (base_path, ours_path, theirs_path), expected


@settings(max_examples=200, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(scenario())
def test_merge_invariants(scenario_data):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (base, ours, theirs), expected = _build(scenario_data, td)
        out = td / "merged.dxf"
        result = merge_dxf(base, ours, theirs, out)

        has_conflict_fate = any(f in CONFLICT_FATES for f in expected.values())

        if has_conflict_fate:
            # INVARIANTE: las divergencias reales se detectan como conflicto
            assert not result.ok, (
                "esperado conflicto para fates "
                f"{[f for f in expected.values() if f in CONFLICT_FATES]}")
            # y cada conflicto reportado corresponde a un fate conflictivo
            conflict_uids = {c.handle for c in result.conflicts}
            for uid in conflict_uids:
                assert expected.get(uid) in CONFLICT_FATES or uid not in expected
            return

        # Sin fates conflictivos → merge limpio
        assert result.ok, f"conflicto inesperado: {[c.reason for c in result.conflicts]}"
        merged = extract_entities(out)
        base_e = extract_entities(base)
        ours_e = extract_entities(ours)
        theirs_e = extract_entities(theirs)

        for uid, fate in expected.items():
            if fate == "unchanged":
                # INVARIANTE: sin cambios en ningún lado → sobrevive igual
                assert uid in merged, f"entidad {fate} perdida"
                assert merged[uid]["fingerprint"] == base_e[uid]["fingerprint"]
            elif fate == "mod_ours":
                # INVARIANTE: cambio solo de ours → se preserva
                assert uid in merged
                assert merged[uid]["fingerprint"] == ours_e[uid]["fingerprint"]
            elif fate == "mod_theirs":
                # INVARIANTE: cambio solo de theirs → se aplica
                assert uid in merged
                assert merged[uid]["fingerprint"] == theirs_e[uid]["fingerprint"]
            elif fate == "mod_both_same":
                # INVARIANTE: convergencia → presente con el valor común
                assert uid in merged
                assert merged[uid]["fingerprint"] == ours_e[uid]["fingerprint"]
            elif fate in ("del_ours", "del_theirs", "del_both"):
                # INVARIANTE: borrado no conflictivo → ausente del resultado
                assert uid not in merged, f"entidad {fate} debería estar borrada"


@settings(max_examples=150, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(scenario())
def test_resolution_totality(scenario_data):
    """Resolver TODOS los conflictos (siempre 'theirs') produce merge limpio."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (base, ours, theirs), expected = _build(scenario_data, td)
        out = td / "merged.dxf"
        first = merge_dxf(base, ours, theirs, out)
        if first.ok:
            return  # nada que resolver
        resolutions = {c.handle: "theirs" for c in first.conflicts}
        resolved = merge_dxf(base, ours, theirs, out, resolutions=resolutions)
        # INVARIANTE: resolver todos los conflictos siempre converge
        assert resolved.ok, (
            f"quedaron conflictos tras resolver todos: "
            f"{[c.reason for c in resolved.conflicts]}")


@settings(max_examples=80, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(scenario())
def test_merge_determinism(scenario_data):
    """Misma entrada → mismo resultado (ok y conjunto de conflictos)."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (base, ours, theirs), _ = _build(scenario_data, td)
        r1 = merge_dxf(base, ours, theirs, td / "m1.dxf")
        r2 = merge_dxf(base, ours, theirs, td / "m2.dxf")
        # INVARIANTE: determinismo
        assert r1.ok == r2.ok
        assert {c.handle for c in r1.conflicts} == {c.handle for c in r2.conflicts}
        if r1.ok:
            e1 = extract_entities(td / "m1.dxf")
            e2 = extract_entities(td / "m2.dxf")
            assert {u: v["fingerprint"] for u, v in e1.items()} == \
                   {u: v["fingerprint"] for u, v in e2.items()}


@settings(max_examples=150, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(scenario(), st.randoms(use_true_random=True))
def test_resolution_mixed_totality(scenario_data, rng):
    """Resolver cada conflicto con un lado ALEATORIO siempre converge."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (base, ours, theirs), expected = _build(scenario_data, td)
        out = td / "merged.dxf"
        first = merge_dxf(base, ours, theirs, out)
        if first.ok:
            return
        resolutions = {c.handle: rng.choice(["ours", "theirs"])
                       for c in first.conflicts}
        resolved = merge_dxf(base, ours, theirs, out, resolutions=resolutions)
        # INVARIANTE: cualquier combinación de elecciones converge
        assert resolved.ok, (
            f"resolución mixta dejó conflictos: "
            f"{[c.reason for c in resolved.conflicts]}")
        # y el resultado es un DXF válido y reabrible
        reopened = extract_entities(out)
        assert isinstance(reopened, dict)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
