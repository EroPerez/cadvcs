"""Gestion de usuarios locales con password hashing y JWT self-signed.

Cuando CADVCS_OIDC_ISSUER no esta configurado, este modulo proporciona
un sistema de login nativo con usuarios almacenados en una base de datos
centralizada (SQLite o PostgreSQL) separada de los repositorios.

Tokens:
  - Se firman con HS256 usando CADVCS_SECRET_KEY (generado automaticamente
    si no se provee, pero efimero entre reinicios en ese caso).
  - Expiran segun CADVCS_TOKEN_EXPIRE_MINUTES (default 480 = 8h).
  - El claim 'iss' es 'cadvcs-local' para distinguirlos de tokens OIDC.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt as _bcrypt
import jwt
from pydantic import BaseModel


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode("utf-8"),
                          _bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, pw_hash: str) -> bool:
    return _bcrypt.checkpw(password.encode("utf-8"), pw_hash.encode("utf-8"))

SECRET_KEY = os.environ.get("CADVCS_SECRET_KEY", "")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)

TOKEN_EXPIRE_MINUTES = int(os.environ.get("CADVCS_TOKEN_EXPIRE_MINUTES", "480"))
LOCAL_ISSUER = "cadvcs-local"

_USERS_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT UNIQUE NOT NULL,
    email       TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name   TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT 'editor',
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);
"""


class UserRecord(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: str


class UserStore:
    """Almacen de usuarios en SQLite centralizado."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_USERS_SCHEMA)

    def create_user(self, username: str, email: str, password: str,
                    full_name: str = "", role: str = "editor") -> UserRecord:
        pw_hash = _hash_password(password)
        try:
            cur = self._conn.execute(
                "INSERT INTO users (username, email, password_hash, full_name, role) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, email, pw_hash, full_name, role))
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            msg = str(exc).lower()
            if "username" in msg:
                raise ValueError(f"El usuario '{username}' ya existe")
            if "email" in msg:
                raise ValueError(f"El email '{email}' ya esta registrado")
            raise ValueError("Usuario o email duplicado")
        return self._row_to_record(
            self._conn.execute("SELECT * FROM users WHERE id = ?",
                               (cur.lastrowid,)).fetchone())

    def authenticate(self, username: str, password: str) -> UserRecord | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE (username = ? OR email = ?) AND is_active = 1",
            (username, username)).fetchone()
        if row is None:
            return None
        if not _verify_password(password, row["password_hash"]):
            return None
        return self._row_to_record(row)

    def get_by_username(self, username: str) -> UserRecord | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1",
            (username,)).fetchone()
        return self._row_to_record(row) if row else None

    def get_by_id(self, user_id: int) -> UserRecord | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE id = ? AND is_active = 1",
            (user_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def list_users(self) -> list[UserRecord]:
        rows = self._conn.execute(
            "SELECT * FROM users WHERE is_active = 1 ORDER BY username"
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def update_role(self, username: str, role: str) -> UserRecord | None:
        self._conn.execute(
            "UPDATE users SET role = ?, updated_at = strftime('%Y-%m-%d %H:%M:%S', 'now') "
            "WHERE username = ?", (role, username))
        self._conn.commit()
        return self.get_by_username(username)

    def update_password(self, username: str, new_password: str) -> bool:
        pw_hash = bcrypt.hash(new_password)
        cur = self._conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = strftime('%Y-%m-%d %H:%M:%S', 'now') "
            "WHERE username = ? AND is_active = 1", (pw_hash, username))
        self._conn.commit()
        return cur.rowcount > 0

    def deactivate(self, username: str) -> bool:
        cur = self._conn.execute(
            "UPDATE users SET is_active = 0, updated_at = strftime('%Y-%m-%d %H:%M:%S', 'now') "
            "WHERE username = ?", (username,))
        self._conn.commit()
        return cur.rowcount > 0

    def user_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            id=row["id"], username=row["username"], email=row["email"],
            full_name=row["full_name"], role=row["role"],
            is_active=bool(row["is_active"]), created_at=row["created_at"])


def create_token(user: UserRecord) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "preferred_username": user.username,
        "email": user.email,
        "roles": [user.role],
        "iss": LOCAL_ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_local_token(token: str) -> dict | None:
    try:
        claims = jwt.decode(
            token, SECRET_KEY, algorithms=["HS256"],
            options={"require": ["exp", "sub", "iss"]})
        if claims.get("iss") != LOCAL_ISSUER:
            return None
        return claims
    except jwt.PyJWTError:
        return None
