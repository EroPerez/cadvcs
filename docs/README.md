# Documentación

## Specs de funcionalidades implementadas

| # | Spec | Módulo |
|---|------|--------|
| 01 | [Almacenamiento content-addressed](specs/01-storage.md) | `storage.py` |
| 02 | [Modelo de datos tipo Git](specs/02-data-model.md) | `db.py` |
| 03 | [Diff semántico por entidad DXF](specs/03-semantic-diff.md) | `semdiff.py` |
| 04 | [Merge a tres vías por entidad](specs/04-merge.md) | `merge.py` |
| 05 | [Resolución interactiva de conflictos](specs/05-conflict-resolution.md) | `merge.py`, API |
| 06 | [Locking pesimista](specs/06-locking.md) | `repo.py` |
| 07 | [Blame por entidad](specs/07-blame.md) | `repo.py` |
| 08 | [CLI](specs/08-cli.md) | `cli.py` |
| 09 | [API REST](specs/09-rest-api.md) | `api/main.py` |
| 10 | [Autenticación OIDC](specs/10-auth-oidc.md) | `api/auth.py` |
| 11 | [Identidad de entidad por GUID](specs/11-entity-guids.md) | `identity.py` |
| 15 | [Web UI](specs/15-web-ui.md) | `web/index.html` |

## Otros documentos

- [IMPROVEMENTS.md](IMPROVEMENTS.md) — backlog razonado de mejoras
- [../ARCHITECTURE.md](../ARCHITECTURE.md) — arquitectura objetivo de producción
- [architecture.svg](architecture.svg) — diagrama de la arquitectura