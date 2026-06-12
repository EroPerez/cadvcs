"""Repositorio cadvcs — modelo tipo Git para archivos CAD.

Conceptos (paralelo directo con Git):
  - commit: changeset multi-archivo, nodo de un DAG (merges → 2 padres)
  - branch / tag: refs con nombre que apuntan a commits
  - HEAD: rama actual (en tabla meta)
  - add / status: tracking de archivos y comparación workdir ↔ HEAD
  - merge: a tres vías con merge-base (LCA); para DXF la resolución es
    A NIVEL DE ENTIDAD — cambios que no colisionan se fusionan solos
  - blame: por entidad DXF, qué commit la tocó por última vez

Diferencias deliberadas con Git:
  - Tree plano (commit_entries), sin objetos tree jerárquicos
  - Pessimistic locking opcional por archivo (binarios no-DXF no se
    pueden mergear: el lock es la única protección)
  - Índice semántico por blob para diff/merge/blame sin re-parsear
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db, semdiff, merge as merge_mod
from .storage import BlobStore

REPO_DIR = ".cadvcs"
DEFAULT_BRANCH = "main"
DEFAULT_LOCK_TTL = timedelta(hours=8)


class CadVcsError(Exception):
    pass


class LockError(CadVcsError):
    pass


class MergeConflictError(CadVcsError):
    def __init__(self, message, details):
        super().__init__(message)
        self.details = details  # {repo_path: list[Conflict] | 'binary'}


def _utcnow_str(delta: timedelta = timedelta()) -> str:
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%d %H:%M:%S")


class Repo:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.vcs_dir = self.root / REPO_DIR
        if not self.vcs_dir.exists():
            raise CadVcsError(f"No hay repo en {self.root} (ejecuta init)")
        self.store = BlobStore(self.vcs_dir / "objects")
        self.conn = db.connect(self.vcs_dir / "metadata.db")

    @classmethod
    def init(cls, root: Path) -> "Repo":
        (Path(root).resolve() / REPO_DIR).mkdir(parents=True, exist_ok=True)
        repo = cls(root)
        with repo.conn:
            repo.conn.execute(
                "INSERT OR IGNORE INTO branches (name, head_commit_id) VALUES (?, NULL)",
                (DEFAULT_BRANCH,))
            repo.conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('HEAD', ?)",
                (DEFAULT_BRANCH,))
        return repo

    # ================================================== refs / HEAD
    @property
    def current_branch(self) -> str:
        return self.conn.execute(
            "SELECT value FROM meta WHERE key = 'HEAD'").fetchone()["value"]

    def head_commit_id(self) -> int | None:
        row = self.conn.execute(
            "SELECT head_commit_id FROM branches WHERE name = ?",
            (self.current_branch,)).fetchone()
        return row["head_commit_id"] if row else None

    def resolve(self, ref: str) -> int:
        """Resuelve 'HEAD', rama, tag o id numérico a commit_id."""
        if ref == "HEAD":
            cid = self.head_commit_id()
            if cid is None:
                raise CadVcsError("HEAD sin commits todavía")
            return cid
        row = self.conn.execute(
            "SELECT head_commit_id AS c FROM branches WHERE name = ?", (ref,)
        ).fetchone()
        if row:
            if row["c"] is None:
                raise CadVcsError(f"La rama {ref} no tiene commits")
            return row["c"]
        row = self.conn.execute(
            "SELECT commit_id AS c FROM tags WHERE name = ?", (ref,)).fetchone()
        if row:
            return row["c"]
        if ref.isdigit():
            row = self.conn.execute(
                "SELECT id AS c FROM commits WHERE id = ?", (int(ref),)).fetchone()
            if row:
                return row["c"]
        raise CadVcsError(f"Ref desconocida: {ref}")

    def _tree(self, commit_id: int | None) -> dict[str, dict]:
        """{repo_path: {blob_sha, size_bytes}} del commit (vacío si None)."""
        if commit_id is None:
            return {}
        rows = self.conn.execute(
            "SELECT repo_path, blob_sha, size_bytes FROM commit_entries "
            "WHERE commit_id = ?", (commit_id,)).fetchall()
        return {r["repo_path"]: dict(r) for r in rows}

    # ================================================== locking
    def _purge_expired_locks(self):
        with self.conn:
            self.conn.execute("DELETE FROM locks WHERE expires_at < ?",
                              (_utcnow_str(),))

    def lock(self, repo_path: str, owner: str, ttl: timedelta = DEFAULT_LOCK_TTL):
        self._purge_expired_locks()
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO locks (repo_path, owner, expires_at) "
                    "VALUES (?, ?, ?)", (repo_path, owner, _utcnow_str(ttl)))
        except Exception:
            holder = self.conn.execute(
                "SELECT owner FROM locks WHERE repo_path = ?",
                (repo_path,)).fetchone()
            if holder and holder["owner"] == owner:
                return
            raise LockError(f"{repo_path} bloqueado por {holder['owner']}")

    def unlock(self, repo_path: str, owner: str, force: bool = False):
        holder = self.conn.execute(
            "SELECT owner FROM locks WHERE repo_path = ?", (repo_path,)).fetchone()
        if not holder:
            return
        if holder["owner"] != owner and not force:
            raise LockError(f"Lock pertenece a {holder['owner']}")
        with self.conn:
            self.conn.execute("DELETE FROM locks WHERE repo_path = ?", (repo_path,))

    def _check_locks(self, repo_paths: list[str], author: str):
        self._purge_expired_locks()
        for rp in repo_paths:
            holder = self.conn.execute(
                "SELECT owner FROM locks WHERE repo_path = ?", (rp,)).fetchone()
            if holder and holder["owner"] != author:
                raise LockError(f"{rp} bloqueado por {holder['owner']}")

    # ================================================== add / status
    def add(self, *paths: Path):
        with self.conn:
            for p in paths:
                rp = str(Path(p).resolve().relative_to(self.root))
                if not (self.root / rp).exists():
                    raise CadVcsError(f"{rp} no existe")
                self.conn.execute(
                    "INSERT OR IGNORE INTO tracked (repo_path) VALUES (?)", (rp,))

    def _tracked(self) -> list[str]:
        return [r["repo_path"] for r in
                self.conn.execute("SELECT repo_path FROM tracked").fetchall()]

    def status(self) -> dict[str, list[str]]:
        head = self._tree(self.head_commit_id())
        st = {"new": [], "modified": [], "deleted": [], "clean": []}
        for rp in sorted(self._tracked()):
            fs_path = self.root / rp
            if not fs_path.exists():
                if rp in head:
                    st["deleted"].append(rp)
                continue
            sha = BlobStore.hash_file(fs_path)
            if rp not in head:
                st["new"].append(rp)
            elif head[rp]["blob_sha"] != sha:
                st["modified"].append(rp)
            else:
                st["clean"].append(rp)
        return st

    def is_dirty(self) -> bool:
        st = self.status()
        return bool(st["new"] or st["modified"] or st["deleted"])

    # ================================================== commit
    def commit(self, author: str, message: str = "",
               parent2_id: int | None = None) -> dict:
        st = self.status()
        changed = st["new"] + st["modified"] + st["deleted"]
        if not changed and parent2_id is None:
            raise CadVcsError("Nada que commitear (workdir limpio)")
        self._check_locks(changed, author)

        parent_id = self.head_commit_id()
        entries = {}
        for rp in self._tracked():
            fs_path = self.root / rp
            if not fs_path.exists():
                continue  # borrado: simplemente no entra en el snapshot
            sha, size = self.store.put(fs_path)
            entries[rp] = (sha, size)
            if fs_path.suffix.lower() == ".dxf":
                self._index_blob(sha, fs_path)

        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO commits (parent_id, parent2_id, author, message) "
                "VALUES (?, ?, ?, ?)", (parent_id, parent2_id, author, message))
            cid = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO commit_entries (commit_id, repo_path, blob_sha, "
                "size_bytes) VALUES (?, ?, ?, ?)",
                [(cid, rp, sha, size) for rp, (sha, size) in entries.items()])
            # Los archivos borrados dejan de estar tracked
            for rp in st["deleted"]:
                self.conn.execute("DELETE FROM tracked WHERE repo_path = ?", (rp,))
            self.conn.execute(
                "UPDATE branches SET head_commit_id = ? WHERE name = ?",
                (cid, self.current_branch))
        return {"commit_id": cid, "branch": self.current_branch,
                "files": len(entries), "changed": changed}

    def _index_blob(self, blob_sha: str, dxf_path: Path):
        exists = self.conn.execute(
            "SELECT 1 FROM entities WHERE blob_sha = ? LIMIT 1",
            (blob_sha,)).fetchone()
        if exists:
            return
        ents = semdiff.extract_entities(dxf_path)
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO entities (blob_sha, handle, dxftype, "
                "layer, fingerprint, attrs_json) VALUES (?, ?, ?, ?, ?, ?)",
                [(blob_sha, h, e["dxftype"], e["layer"], e["fingerprint"],
                  json.dumps(e["attrs"], default=str)) for h, e in ents.items()])

    def _entities_for_blob(self, blob_sha: str) -> dict[str, dict]:
        rows = self.conn.execute(
            "SELECT handle, dxftype, layer, fingerprint, attrs_json "
            "FROM entities WHERE blob_sha = ?", (blob_sha,)).fetchall()
        if not rows:
            # Blob no indexado (p.ej. importado): indexar bajo demanda
            with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            self.store.get(blob_sha, tmp_path)
            self._index_blob(blob_sha, tmp_path)
            tmp_path.unlink()
            return self._entities_for_blob(blob_sha)
        return {r["handle"]: {"dxftype": r["dxftype"], "layer": r["layer"],
                              "fingerprint": r["fingerprint"],
                              "attrs": json.loads(r["attrs_json"])}
                for r in rows}

    # ================================================== branch / tag / switch
    def branch_delete(self, name: str, force: bool = False):
        if name == self.current_branch:
            raise CadVcsError("No se puede borrar la rama actual")
        row = self.conn.execute(
            "SELECT head_commit_id FROM branches WHERE name = ?", (name,)
        ).fetchone()
        if not row:
            raise CadVcsError(f"La rama {name} no existe")
        # Protección estilo git branch -d: no borrar trabajo no mergeado
        if not force and row["head_commit_id"] is not None:
            head = self.head_commit_id()
            if head is None or row["head_commit_id"] not in self._ancestors(head):
                raise CadVcsError(
                    f"{name} tiene commits no alcanzables desde "
                    f"{self.current_branch} (usa force)")
        with self.conn:
            self.conn.execute("DELETE FROM branches WHERE name = ?", (name,))

    def tag_delete(self, name: str):
        with self.conn:
            cur = self.conn.execute("DELETE FROM tags WHERE name = ?", (name,))
        if cur.rowcount == 0:
            raise CadVcsError(f"El tag {name} no existe")

    def gc(self) -> dict:
        """Mark-and-sweep: elimina commits inalcanzables desde cualquier
        ref y los blobs/índices que solo ellos referenciaban."""
        # MARK: alcanzable desde todas las ramas y tags
        roots = [r["head_commit_id"] for r in self.conn.execute(
            "SELECT head_commit_id FROM branches "
            "WHERE head_commit_id IS NOT NULL").fetchall()]
        roots += [r["commit_id"] for r in self.conn.execute(
            "SELECT commit_id FROM tags").fetchall()]
        reachable: set[int] = set()
        for root in roots:
            reachable |= self._ancestors(root)

        all_commits = {r["id"] for r in self.conn.execute(
            "SELECT id FROM commits").fetchall()}
        dead_commits = all_commits - reachable

        # SWEEP de metadata
        with self.conn:
            if dead_commits:
                marks = ",".join("?" * len(dead_commits))
                ids = list(dead_commits)
                self.conn.execute(
                    f"DELETE FROM commit_entries WHERE commit_id IN ({marks})",
                    ids)
                self.conn.execute(
                    f"DELETE FROM commits WHERE id IN ({marks})", ids)
        live_blobs = {r["blob_sha"] for r in self.conn.execute(
            "SELECT DISTINCT blob_sha FROM commit_entries").fetchall()}
        # Los archivos del workdir actual también están vivos
        for rp in self._tracked():
            fs = self.root / rp
            if fs.exists():
                live_blobs.add(BlobStore.hash_file(fs))

        # SWEEP de blobs e índice semántico
        dead_blobs = 0
        freed = 0
        for shard in self.store.root.iterdir():
            if not shard.is_dir():
                continue
            for obj in shard.iterdir():
                sha = shard.name + obj.name
                if sha not in live_blobs:
                    freed += obj.stat().st_size
                    obj.unlink()
                    dead_blobs += 1
        if dead_blobs:
            with self.conn:
                placeholders = ",".join("?" * len(live_blobs)) or "''"
                self.conn.execute(
                    f"DELETE FROM entities WHERE blob_sha NOT IN "
                    f"({placeholders})", list(live_blobs))
        return {"commits_removed": len(dead_commits),
                "blobs_removed": dead_blobs, "bytes_freed": freed}

    def branch_create(self, name: str):
        if self.conn.execute("SELECT 1 FROM branches WHERE name = ?",
                             (name,)).fetchone():
            raise CadVcsError(f"La rama {name} ya existe")
        with self.conn:
            self.conn.execute(
                "INSERT INTO branches (name, head_commit_id) VALUES (?, ?)",
                (name, self.head_commit_id()))

    def branches(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT name, head_commit_id FROM branches ORDER BY name").fetchall()
        return [dict(r) | {"current": r["name"] == self.current_branch}
                for r in rows]

    def tag_create(self, name: str, ref: str = "HEAD"):
        with self.conn:
            self.conn.execute("INSERT INTO tags (name, commit_id) VALUES (?, ?)",
                              (name, self.resolve(ref)))

    def tags(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT name, commit_id FROM tags ORDER BY name").fetchall()]

    def switch(self, branch: str, force: bool = False):
        if not self.conn.execute("SELECT 1 FROM branches WHERE name = ?",
                                 (branch,)).fetchone():
            raise CadVcsError(f"La rama {branch} no existe")
        if not force and self.is_dirty():
            raise CadVcsError(
                "Workdir con cambios sin commitear (usa force para descartar)")

        target_row = self.conn.execute(
            "SELECT head_commit_id FROM branches WHERE name = ?",
            (branch,)).fetchone()
        target_tree = self._tree(target_row["head_commit_id"])
        current_tree = self._tree(self.head_commit_id())

        # Materializar el árbol destino en el workdir
        for rp, entry in target_tree.items():
            self.store.get(entry["blob_sha"], self.root / rp)
        for rp in current_tree:
            if rp not in target_tree:
                (self.root / rp).unlink(missing_ok=True)

        with self.conn:
            self.conn.execute("UPDATE meta SET value = ? WHERE key = 'HEAD'",
                              (branch,))
            self.conn.execute("DELETE FROM tracked")
            self.conn.executemany(
                "INSERT INTO tracked (repo_path) VALUES (?)",
                [(rp,) for rp in target_tree])

    # ================================================== log / checkout / diff
    def _ancestors(self, commit_id: int) -> set[int]:
        seen, stack = set(), [commit_id]
        while stack:
            cid = stack.pop()
            if cid in seen:
                continue
            seen.add(cid)
            row = self.conn.execute(
                "SELECT parent_id, parent2_id FROM commits WHERE id = ?",
                (cid,)).fetchone()
            stack += [p for p in (row["parent_id"], row["parent2_id"]) if p]
        return seen

    def merge_base(self, a: int, b: int) -> int | None:
        """LCA simple: primer ancestro de b (BFS) que es ancestro de a."""
        ancestors_a = self._ancestors(a)
        queue = [b]
        seen = set()
        while queue:
            cid = queue.pop(0)
            if cid in seen:
                continue
            seen.add(cid)
            if cid in ancestors_a:
                return cid
            row = self.conn.execute(
                "SELECT parent_id, parent2_id FROM commits WHERE id = ?",
                (cid,)).fetchone()
            queue += [p for p in (row["parent_id"], row["parent2_id"]) if p]
        return None

    def log(self, ref: str = "HEAD", limit: int = 50,
            author: str | None = None, path: str | None = None,
            since: str | None = None, before_id: int | None = None) -> list[dict]:
        """Historia first-parent con filtros y paginación por cursor.

        author/since filtran por autor y fecha mínima (ISO); path conserva
        solo commits que TOCARON ese archivo (su blob difiere del padre);
        before_id es el cursor: continúa por debajo de ese commit.
        """
        out, cid = [], self.resolve(ref)
        skipping = before_id is not None
        while cid and len(out) < limit:
            row = self.conn.execute(
                "SELECT id, parent_id, parent2_id, author, message, created_at "
                "FROM commits WHERE id = ?", (cid,)).fetchone()
            if skipping:
                if row["id"] == before_id:
                    skipping = False
                cid = row["parent_id"]
                continue
            if author and row["author"] != author:
                cid = row["parent_id"]
                continue
            if since and row["created_at"] < since:
                break  # first-parent es descendente en el tiempo
            if path:
                sha = self.conn.execute(
                    "SELECT blob_sha FROM commit_entries "
                    "WHERE commit_id = ? AND repo_path = ?",
                    (row["id"], path)).fetchone()
                parent_sha = self.conn.execute(
                    "SELECT blob_sha FROM commit_entries "
                    "WHERE commit_id = ? AND repo_path = ?",
                    (row["parent_id"], path)).fetchone() if row["parent_id"] else None
                touched = (sha is None) != (parent_sha is None) or (
                    sha and parent_sha and sha["blob_sha"] != parent_sha["blob_sha"])
                if not touched:
                    cid = row["parent_id"]
                    continue
            d = dict(row)
            d["is_merge"] = row["parent2_id"] is not None
            d["branches"] = [b["name"] for b in self.conn.execute(
                "SELECT name FROM branches WHERE head_commit_id = ?",
                (row["id"],)).fetchall()]
            d["tags"] = [t["name"] for t in self.conn.execute(
                "SELECT name FROM tags WHERE commit_id = ?", (row["id"],)).fetchall()]
            out.append(d)
            cid = row["parent_id"]  # first-parent log, como git log --first-parent
        return out

    def checkout_file(self, repo_path: str, ref: str = "HEAD",
                      dest: Path | None = None) -> Path:
        tree = self._tree(self.resolve(ref))
        if repo_path not in tree:
            raise CadVcsError(f"{repo_path} no existe en {ref}")
        return self.store.get(tree[repo_path]["blob_sha"],
                              Path(dest) if dest else self.root / repo_path)

    def diff(self, ref_a: str, ref_b: str) -> dict:
        """Diff entre dos refs: cambios de árbol + diff semántico por DXF."""
        ta, tb = self._tree(self.resolve(ref_a)), self._tree(self.resolve(ref_b))
        out = {"added": sorted(set(tb) - set(ta)),
               "removed": sorted(set(ta) - set(tb)),
               "modified": {}}
        for rp in sorted(set(ta) & set(tb)):
            sa, sb = ta[rp]["blob_sha"], tb[rp]["blob_sha"]
            if sa == sb:
                continue
            if rp.lower().endswith(".dxf"):
                out["modified"][rp] = semdiff.diff_entities(
                    self._entities_for_blob(sa), self._entities_for_blob(sb))
            else:
                out["modified"][rp] = None  # binario: solo "cambió"
        return out

    # ================================================== merge

    def _merge_trees(self, base_id: int | None, ours_id: int,
                     theirs_id: int,
                     resolutions: dict[str, dict[str, str]]):
        """Merge a tres vías de árboles completos sobre el workdir.

        Aplica al workdir los cambios de theirs que no colisionan (y las
        resoluciones manuales); devuelve (conflicts, details). Compartido
        por merge() y cherry_pick().
        """
        base_t = self._tree(base_id)
        ours_t = self._tree(ours_id)
        theirs_t = self._tree(theirs_id)
        conflicts: dict[str, object] = {}
        merge_details: dict[str, str] = {}

        for rp in sorted(set(base_t) | set(ours_t) | set(theirs_t)):

            b = base_t.get(rp, {}).get("blob_sha")
            o = ours_t.get(rp, {}).get("blob_sha")
            t = theirs_t.get(rp, {}).get("blob_sha")

            if o == t or t == b:
                continue                       # sin cambios que traer
            if o == b:                         # solo cambió theirs → tomarlo
                if t is None:
                    (self.root / rp).unlink(missing_ok=True)
                    with self.conn:
                        self.conn.execute(
                            "DELETE FROM tracked WHERE repo_path = ?", (rp,))
                    merge_details[rp] = "theirs (borrado)"
                else:
                    self.store.get(t, self.root / rp)
                    with self.conn:
                        self.conn.execute(
                            "INSERT OR IGNORE INTO tracked (repo_path) "
                            "VALUES (?)", (rp,))
                    merge_details[rp] = "theirs"
                continue

            # Ambos lados divergen del base → merge de contenido
            if rp.lower().endswith(".dxf") and b and o and t:
                with tempfile.TemporaryDirectory() as td:
                    td = Path(td)
                    pb, po, pt = td / "base.dxf", td / "ours.dxf", td / "theirs.dxf"
                    self.store.get(b, pb)
                    self.store.get(o, po)
                    self.store.get(t, pt)
                    res = merge_mod.merge_dxf(pb, po, pt, self.root / rp,
                                              resolutions.get(rp))
                if res.ok:
                    applied = (res.applied_modified + res.applied_added +
                               res.applied_deleted + res.resolved)
                    if applied == 0:
                        # Convergencia total: nada que traer de theirs.
                        # Restaurar los bytes exactos de ours para no
                        # generar un commit no-op por el re-save del DXF.
                        self.store.get(o, self.root / rp)
                        continue
                    merge_details[rp] = res.summary()
                else:
                    conflicts[rp] = res.conflicts
            else:
                # Binario divergente (o DXF con borrado de archivo completo):
                # solo resoluble a nivel de archivo
                file_choice = resolutions.get(rp, {}).get("__file__")
                if file_choice == "ours":
                    merge_details[rp] = "ours (resolución manual)"
                elif file_choice == "theirs":
                    if t is None:
                        (self.root / rp).unlink(missing_ok=True)
                        with self.conn:
                            self.conn.execute(
                                "DELETE FROM tracked WHERE repo_path = ?", (rp,))
                    else:
                        self.store.get(t, self.root / rp)
                        with self.conn:
                            self.conn.execute(
                                "INSERT OR IGNORE INTO tracked (repo_path) "
                                "VALUES (?)", (rp,))
                    merge_details[rp] = "theirs (resolución manual)"
                else:
                    conflicts[rp] = "binary"      # requiere resolución manual
        return conflicts, merge_details

    def merge(self, other_branch: str, author: str,
              message: str | None = None,
              resolutions: dict[str, dict[str, str]] | None = None) -> dict:
        """Merge de other_branch en la rama actual.

        `resolutions` permite resolver conflictos de un intento previo:
        {repo_path: {handle: 'ours'|'theirs'}} para entidades DXF, y la
        clave especial '__file__' para binarios divergentes completos.
        """
        resolutions = resolutions or {}
        ours_id = self.head_commit_id()
        theirs_id = self.resolve(other_branch)
        if ours_id is None:
            raise CadVcsError("La rama actual no tiene commits")
        if self.is_dirty():
            raise CadVcsError("Workdir sucio: commitea o descarta antes de merge")
        if theirs_id == ours_id or theirs_id in self._ancestors(ours_id):
            return {"result": "already-up-to-date"}

        base_id = self.merge_base(ours_id, theirs_id)

        # Fast-forward: ours es ancestro de theirs
        if base_id == ours_id:
            with self.conn:
                self.conn.execute(
                    "UPDATE branches SET head_commit_id = ? WHERE name = ?",
                    (theirs_id, self.current_branch))
            self.switch(self.current_branch, force=True)  # rematerializar
            return {"result": "fast-forward", "commit_id": theirs_id}

        conflicts, merge_details = self._merge_trees(
            base_id, ours_id, theirs_id, resolutions)

        if conflicts:
            # Restaurar workdir al estado de ours
            self.switch(self.current_branch, force=True)
            raise MergeConflictError(
                f"Merge con conflictos en {len(conflicts)} archivo(s)", conflicts)

        info = self.commit(
            author=author,
            message=message or f"Merge {other_branch} into {self.current_branch}",
            parent2_id=theirs_id)
        info["result"] = "merged"
        info["details"] = merge_details
        return info

    def cherry_pick(self, ref: str, author: str,
                    message: str | None = None,
                    resolutions: dict[str, dict[str, str]] | None = None) -> dict:
        """Aplica los cambios de UN commit sobre la rama actual.

        Tres vías con base = primer padre del commit elegido y theirs =
        el commit; el resultado es un commit normal (un solo padre) en
        la rama actual. Conflictos y resoluciones funcionan igual que en
        merge. Para merge commits se usa el primer padre como mainline.
        """
        resolutions = resolutions or {}
        ours_id = self.head_commit_id()
        if ours_id is None:
            raise CadVcsError("La rama actual no tiene commits")
        if self.is_dirty():
            raise CadVcsError(
                "Workdir sucio: commitea o descarta antes de cherry-pick")
        theirs_id = self.resolve(ref)
        row = self.conn.execute(
            "SELECT parent_id, message FROM commits WHERE id = ?",
            (theirs_id,)).fetchone()
        base_id = row["parent_id"]
        if base_id is None:
            raise CadVcsError(
                "No se puede aplicar cherry-pick de un commit raíz")

        conflicts, details = self._merge_trees(
            base_id, ours_id, theirs_id, resolutions)

        if conflicts:
            self.switch(self.current_branch, force=True)
            raise MergeConflictError(
                f"Cherry-pick con conflictos en {len(conflicts)} archivo(s)",
                conflicts)
        if not details:
            return {"result": "empty", "commit_id": None,
                    "details": {}}

        info = self.commit(
            author=author,
            message=message or
            f"{row['message']} (cherry picked from c{theirs_id})")
        info["result"] = "cherry-picked"
        info["details"] = details
        return info

    # ================================================== blame
    def blame(self, repo_path: str, ref: str = "HEAD") -> list[dict]:
        """Para cada entidad de la versión actual: último commit que la tocó.

        Recorre la cadena first-parent desde ref hacia atrás; una entidad se
        atribuye al commit donde su fingerprint difiere del padre (o aparece).
        """
        if not repo_path.lower().endswith(".dxf"):
            raise CadVcsError("blame solo soporta DXF")
        chain = self.log(ref, limit=10_000)
        current_sha = None
        for c in chain:
            tree = self._tree(c["id"])
            if repo_path in tree:
                current_sha = tree[repo_path]["blob_sha"]
                break
        if current_sha is None:
            raise CadVcsError(f"{repo_path} no existe en {ref}")

        current = self._entities_for_blob(current_sha)
        attribution: dict[str, dict] = {}
        pending = set(current)

        for i, c in enumerate(chain):
            if not pending:
                break
            tree = self._tree(c["id"])
            parent_tree = self._tree(chain[i + 1]["id"]) if i + 1 < len(chain) else {}
            sha = tree.get(repo_path, {}).get("blob_sha")
            psha = parent_tree.get(repo_path, {}).get("blob_sha")
            if sha is None:
                continue
            ents = self._entities_for_blob(sha)
            pents = self._entities_for_blob(psha) if psha else {}
            for h in list(pending):
                if h not in ents:
                    continue
                changed_here = (h not in pents or
                                pents[h]["fingerprint"] != ents[h]["fingerprint"])
                if changed_here:
                    attribution[h] = {"commit_id": c["id"], "author": c["author"],
                                      "message": c["message"]}
                    pending.discard(h)

        return [{"handle": h, "dxftype": current[h]["dxftype"],
                 "layer": current[h]["layer"], **attribution.get(h, {})}
                for h in sorted(current)]
