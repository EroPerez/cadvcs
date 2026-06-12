"""Metadata en SQLite — esquema tipo Git, portable a PostgreSQL.

Modelo de datos:
  - commits: DAG de changesets (parent2_id para merge commits)
  - commit_entries: snapshot completo del árbol por commit (flat tree).
    Barato gracias al content-addressing: archivos sin cambios apuntan
    al mismo blob_sha.
  - branches/tags: punteros con nombre a commits (idéntico a Git refs)
  - meta: HEAD (rama actual)
  - tracked: archivos bajo control de versiones (staging-lite)
  - locks: pessimistic locking por archivo con TTL
  - entities: índice semántico DXF indexado POR BLOB (no por revisión),
    así un blob compartido entre N commits se indexa una sola vez.

En producción: PostgreSQL. Locking con SELECT ... FOR UPDATE o advisory
locks; created_at como timestamptz; commit_entries con índice (commit_id).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
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
    parent2_id  INTEGER REFERENCES commits(id),   -- segundo padre en merges
    author      TEXT NOT NULL,
    message     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
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
    head_commit_id  INTEGER REFERENCES commits(id)   -- NULL = rama sin commits
);

CREATE TABLE IF NOT EXISTS tags (
    name       TEXT PRIMARY KEY,
    commit_id  INTEGER NOT NULL REFERENCES commits(id)
);

CREATE TABLE IF NOT EXISTS tracked (
    repo_path TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS locks (
    repo_path   TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    acquired_at TEXT NOT NULL DEFAULT (datetime('now')),
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
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
