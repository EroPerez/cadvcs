"""Capa de metadata con doble backend: SQLite (default) y PostgreSQL.

Selección por entorno: si CADVCS_DB_URL está definido (formato
postgresql://user:pass@host[:port]/dbname), toda la metadata vive en
PostgreSQL con UN SCHEMA POR REPOSITORIO (search_path), lo que mantiene
el SQL de repo.py idéntico entre backends y es a la vez un patrón
legítimo de aislamiento multi-repo. Sin la variable, cada repo usa su
SQLite local en .cadvcs/metadata.db, como siempre.

El wrapper Conn normaliza las diferencias:
  - estilo de parámetros: '?' (sqlite) → '%s' (psycopg)
  - 'INSERT OR IGNORE' → 'INSERT ... ON CONFLICT DO NOTHING'
  - transacciones: `with conn:` agrupa con commit/rollback en ambos
    (en psycopg delega en connection.transaction(); la conexión opera
    en autocommit fuera de bloques, igual que el uso real en sqlite)
  - insert_id(): lastrowid (sqlite) vs RETURNING id (postgres)

Los timestamps se guardan como TEXT 'YYYY-MM-DD HH:MM:SS' UTC en ambos
backends para que las comparaciones de expiración de locks (orden
lexicográfico = orden temporal en ese formato) sean idénticas.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

DB_URL = os.environ.get("CADVCS_DB_URL")

_SQLITE_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commits (
    id          INTEGER PRIMARY KEY,
    parent_id   INTEGER REFERENCES commits(id),
    parent2_id  INTEGER REFERENCES commits(id),
    author      TEXT NOT NULL,
    message     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS commit_entries (
    commit_id   INTEGER NOT NULL REFERENCES commits(id),
    repo_path   TEXT NOT NULL,
    blob_sha    TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    PRIMARY KEY (commit_id, repo_path)
);

CREATE TABLE IF NOT EXISTS branches (
    name            TEXT PRIMARY KEY,
    head_commit_id  INTEGER REFERENCES commits(id)
);

CREATE TABLE IF NOT EXISTS tags (
    name       TEXT PRIMARY KEY,
    commit_id  INTEGER NOT NULL REFERENCES commits(id)
);

CREATE TABLE IF NOT EXISTS tracked (
    repo_path TEXT PRIMARY KEY
);

-- Blobs subidos por el cliente directamente a object storage (presigned)
-- y registrados por referencia: el commit los toma de aquí sin leer disco.
CREATE TABLE IF NOT EXISTS staged (
    repo_path  TEXT PRIMARY KEY,
    blob_sha   TEXT NOT NULL,
    size_bytes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS locks (
    repo_path   TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    acquired_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    blob_sha    TEXT NOT NULL,
    handle      TEXT NOT NULL,
    dxftype     TEXT NOT NULL,
    layer       TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    attrs_json  TEXT NOT NULL,
    PRIMARY KEY (blob_sha, handle)
);

-- Transactional outbox: eventos de indexado escritos en la MISMA
-- transacción del commit, drenados por un worker. status: pending →
-- done (o queda pending para reintento). Garantiza que metadata y
-- evento son atómicos sin depender de un broker en el path de commit.
CREATE TABLE IF NOT EXISTS index_outbox (
    id         INTEGER PRIMARY KEY,
    blob_sha   TEXT NOT NULL,
    repo_key   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    attempts   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON index_outbox(status) WHERE status = 'pending';
"""

_PG_NOW = "to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')"
_PG_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS meta ("
    " key TEXT PRIMARY KEY, value TEXT NOT NULL)",

    "CREATE TABLE IF NOT EXISTS commits ("
    " id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
    " parent_id INTEGER REFERENCES commits(id),"
    " parent2_id INTEGER REFERENCES commits(id),"
    " author TEXT NOT NULL,"
    " message TEXT NOT NULL DEFAULT '',"
    f" created_at TEXT NOT NULL DEFAULT {_PG_NOW})",

    "CREATE TABLE IF NOT EXISTS commit_entries ("
    " commit_id INTEGER NOT NULL REFERENCES commits(id),"
    " repo_path TEXT NOT NULL,"
    " blob_sha TEXT NOT NULL,"
    " size_bytes BIGINT NOT NULL,"
    " PRIMARY KEY (commit_id, repo_path))",

    "CREATE TABLE IF NOT EXISTS branches ("
    " name TEXT PRIMARY KEY,"
    " head_commit_id INTEGER REFERENCES commits(id))",

    "CREATE TABLE IF NOT EXISTS tags ("
    " name TEXT PRIMARY KEY,"
    " commit_id INTEGER NOT NULL REFERENCES commits(id))",

    "CREATE TABLE IF NOT EXISTS tracked (repo_path TEXT PRIMARY KEY)",

    "CREATE TABLE IF NOT EXISTS staged ("
    " repo_path TEXT PRIMARY KEY,"
    " blob_sha TEXT NOT NULL,"
    " size_bytes BIGINT NOT NULL)",

    "CREATE TABLE IF NOT EXISTS locks ("
    " repo_path TEXT PRIMARY KEY,"
    " owner TEXT NOT NULL,"
    f" acquired_at TEXT NOT NULL DEFAULT {_PG_NOW},"
    " expires_at TEXT NOT NULL)",

    "CREATE TABLE IF NOT EXISTS entities ("
    " blob_sha TEXT NOT NULL,"
    " handle TEXT NOT NULL,"
    " dxftype TEXT NOT NULL,"
    " layer TEXT NOT NULL,"
    " fingerprint TEXT NOT NULL,"
    " attrs_json TEXT NOT NULL,"
    " PRIMARY KEY (blob_sha, handle))",

    "CREATE TABLE IF NOT EXISTS index_outbox ("
    " id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
    " blob_sha TEXT NOT NULL,"
    " repo_key TEXT NOT NULL,"
    " status TEXT NOT NULL DEFAULT 'pending',"
    " attempts INTEGER NOT NULL DEFAULT 0,"
    f" created_at TEXT NOT NULL DEFAULT {_PG_NOW})",

    "CREATE INDEX IF NOT EXISTS idx_outbox_pending"
    " ON index_outbox(status) WHERE status = 'pending'",
]

_OR_IGNORE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO", re.IGNORECASE)


class Conn:
    """Wrapper uniforme sobre sqlite3.Connection o psycopg.Connection."""

    def __init__(self, raw, pg: bool):
        self.raw = raw
        self.pg = pg
        self._tx = None

    # -------------------------------------------------- traducción SQL
    def _tr(self, sql: str) -> str:
        if not self.pg:
            return sql
        if _OR_IGNORE.match(sql):
            sql = _OR_IGNORE.sub("INSERT INTO", sql)
            sql += " ON CONFLICT DO NOTHING"
        return sql.replace("?", "%s")

    def execute(self, sql: str, params=()):
        return self.raw.execute(self._tr(sql), params)

    def executemany(self, sql: str, seq):
        if self.pg:
            with self.raw.cursor() as cur:
                cur.executemany(self._tr(sql), list(seq))
            return cur
        return self.raw.executemany(sql, seq)

    def insert_id(self, sql: str, params=()) -> int:
        """INSERT que devuelve el id autogenerado en ambos backends."""
        if self.pg:
            return self.raw.execute(self._tr(sql) + " RETURNING id",
                                    params).fetchone()["id"]
        return self.raw.execute(sql, params).lastrowid

    # -------------------------------------------------- transacciones
    def __enter__(self):
        if self.pg:
            self._tx = self.raw.transaction()
            self._tx.__enter__()
            return self
        self.raw.__enter__()
        return self

    def __exit__(self, *exc):
        if self.pg:
            tx, self._tx = self._tx, None
            return tx.__exit__(*exc)
        return self.raw.__exit__(*exc)


def _schema_name(repo_key: str) -> str:
    return "cadvcs_" + re.sub(r"[^a-z0-9_]", "_", repo_key.lower())[:48]


def connect(db_path: Path, repo_key: str | None = None) -> Conn:
    """Conexión de metadata.

    Con CADVCS_DB_URL → PostgreSQL, un schema por repo (repo_key).
    Sin ella → SQLite en db_path (comportamiento histórico).
    """
    if DB_URL:
        import psycopg
        from psycopg.rows import dict_row
        schema = _schema_name(repo_key or db_path.parent.parent.name)
        raw = psycopg.connect(DB_URL, row_factory=dict_row, autocommit=True)
        raw.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        raw.execute(f'SET search_path TO "{schema}"')
        for stmt in _PG_SCHEMA:
            raw.execute(stmt)
        return Conn(raw, pg=True)

    raw = sqlite3.connect(db_path)
    raw.row_factory = sqlite3.Row
    raw.executescript(_SQLITE_SCHEMA)
    return Conn(raw, pg=False)
