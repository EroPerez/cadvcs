"""API REST de cadvcs sobre repo.Repo.

Modelo: el servidor mantiene una working copy por repositorio bajo
CADVCS_DATA (default ./cadvcs-data). Los clientes suben contenido con
PUT /files/{path}, y commit/branch/merge operan server-side sobre esa
working copy — el equivalente HTTP del flujo CLI.

Concurrencia: endpoints síncronos (FastAPI los ejecuta en threadpool) +
un threading.Lock por repositorio que serializa toda mutación. SQLite
con WAL aguanta bien este patrón; en producción el lock por repo se
sustituye por transacciones PostgreSQL (ver ARCHITECTURE.md).

Arranque:  uvicorn cadvcs.api.main:app --reload
Docs:      http://localhost:8000/docs (OpenAPI autogenerado)
"""
from __future__ import annotations

import os
import threading
from collections import defaultdict
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from fastapi import Depends

from .. import semdiff
from ..repo import Repo, CadVcsError, LockError, MergeConflictError, REPO_DIR
from ..storage import BlobStore
from . import schemas as S
from .auth import Principal, get_principal

DATA_DIR = Path(os.environ.get("CADVCS_DATA", "./cadvcs-data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

_repo_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

app = FastAPI(
    title="cadvcs API",
    version="0.4.0",
    description="Control de versiones tipo Git para archivos CAD "
                "con merge a nivel de entidad DXF y auth OIDC",
    dependencies=[Depends(get_principal)],   # toda la API requiere JWT válido
)


# ----------------------------------------------------------- helpers
def _repo_root(name: str) -> Path:
    root = (DATA_DIR / name).resolve()
    if root.parent != DATA_DIR:                  # contención anti-traversal
        raise HTTPException(400, "Nombre de repositorio inválido")
    return root


def _open_repo(name: str) -> Repo:
    root = _repo_root(name)
    if not (root / REPO_DIR).exists():
        raise HTTPException(404, f"Repositorio {name} no existe")
    return Repo(root)                            # conexión SQLite por request


def _safe_file_path(repo: Repo, rel_path: str) -> Path:
    p = (repo.root / rel_path).resolve()
    if not p.is_relative_to(repo.root) or REPO_DIR in p.parts:
        raise HTTPException(400, f"Ruta inválida: {rel_path}")
    return p


def _repo_info(repo: Repo, name: str) -> S.RepoInfo:
    return S.RepoInfo(name=name, current_branch=repo.current_branch,
                      head_commit_id=repo.head_commit_id())


# ----------------------------------------------------------- errores
@app.exception_handler(CadVcsError)
def _cadvcs_error(request: Request, exc: CadVcsError):
    status = 423 if isinstance(exc, LockError) else 422
    return JSONResponse(status_code=status, content={"detail": str(exc)})


# ----------------------------------------------------------- repos
@app.post("/repos", response_model=S.RepoInfo, status_code=201)
def create_repo(body: S.RepoCreate):
    root = _repo_root(body.name)
    if (root / REPO_DIR).exists():
        raise HTTPException(409, f"El repositorio {body.name} ya existe")
    repo = Repo.init(root)
    return _repo_info(repo, body.name)


@app.get("/repos", response_model=list[S.RepoInfo])
def list_repos():
    out = []
    for child in sorted(DATA_DIR.iterdir()):
        if (child / REPO_DIR).exists():
            out.append(_repo_info(Repo(child), child.name))
    return out


@app.get("/repos/{name}", response_model=S.RepoInfo)
def get_repo(name: str):
    return _repo_info(_open_repo(name), name)


# ----------------------------------------------------------- archivos
@app.put("/repos/{name}/files/{file_path:path}", response_model=S.UploadResponse)
def upload_file(name: str, file_path: str, body: bytes = Body(media_type="application/octet-stream")):
    """Sube contenido a la working copy y lo marca como tracked."""
    with _repo_locks[name]:
        repo = _open_repo(name)
        dest = _safe_file_path(repo, file_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        repo.add(dest)
        return S.UploadResponse(path=file_path, sha256=BlobStore.hash_file(dest),
                                size=len(body), tracked=True)


@app.get("/repos/{name}/files/{file_path:path}")
def download_file(name: str, file_path: str, ref: str = Query("HEAD")):
    """Descarga el archivo tal como existe en una ref (commit, rama o tag)."""
    repo = _open_repo(name)
    tree = repo._tree(repo.resolve(ref))
    if file_path not in tree:
        raise HTTPException(404, f"{file_path} no existe en {ref}")
    blob_path = repo.store._path_for(tree[file_path]["blob_sha"])
    return FileResponse(blob_path, filename=Path(file_path).name,
                        media_type="application/octet-stream",
                        headers={"X-Blob-Sha256": tree[file_path]["blob_sha"]})


# ----------------------------------------------------------- estado / commits
@app.get("/repos/{name}/status", response_model=S.StatusResponse)
def status(name: str):
    repo = _open_repo(name)
    return S.StatusResponse(branch=repo.current_branch, **repo.status())


@app.post("/repos/{name}/commits", response_model=S.CommitInfo, status_code=201)
def commit(name: str, body: S.CommitRequest,
           who: Principal = Depends(get_principal)):
    with _repo_locks[name]:
        info = _open_repo(name).commit(who.username, body.message)
        return S.CommitInfo(**info)


@app.get("/repos/{name}/commits", response_model=list[S.CommitLogEntry])
def log(name: str, ref: str = Query("HEAD"), limit: int = Query(50, le=500),
        author: str | None = Query(None), path: str | None = Query(None),
        since: str | None = Query(None,
                                  description="fecha mínima ISO, ej. 2026-06-01"),
        before_id: int | None = Query(None,
                                      description="cursor de paginación")):
    return _open_repo(name).log(ref, limit, author=author, path=path,
                                since=since, before_id=before_id)


# ----------------------------------------------------------- branches / tags
@app.get("/repos/{name}/branches", response_model=list[S.BranchInfo])
def branches(name: str):
    return _open_repo(name).branches()


@app.post("/repos/{name}/branches", response_model=S.BranchInfo, status_code=201)
def create_branch(name: str, body: S.BranchCreate):
    with _repo_locks[name]:
        repo = _open_repo(name)
        repo.branch_create(body.name)
        return S.BranchInfo(name=body.name, head_commit_id=repo.head_commit_id(),
                            current=False)


@app.post("/repos/{name}/switch", response_model=S.RepoInfo)
def switch(name: str, body: S.SwitchRequest):
    with _repo_locks[name]:
        repo = _open_repo(name)
        repo.switch(body.branch, force=body.force)
        return _repo_info(repo, name)


@app.get("/repos/{name}/tags", response_model=list[S.TagInfo])
def tags(name: str):
    return _open_repo(name).tags()


@app.post("/repos/{name}/tags", response_model=S.TagInfo, status_code=201)
def create_tag(name: str, body: S.TagCreate):
    with _repo_locks[name]:
        repo = _open_repo(name)
        repo.tag_create(body.name, body.ref)
        return S.TagInfo(name=body.name, commit_id=repo.resolve(body.name))


# ----------------------------------------------------------- diff / merge
@app.get("/repos/{name}/diff")
def diff(name: str, ref_a: str = Query(...), ref_b: str = Query(...)):
    d = _open_repo(name).diff(ref_a, ref_b)
    return {"added": d["added"], "removed": d["removed"],
            "modified": {rp: (sd.to_dict() if isinstance(sd, semdiff.SemanticDiff)
                              else "binary")
                         for rp, sd in d["modified"].items()}}


def _do_merge(name: str, branch: str, author: str, message: str | None,
              resolutions: dict | None = None):
    with _repo_locks[name]:
        try:
            info = _open_repo(name).merge(branch, author, message,
                                          resolutions=resolutions)
        except MergeConflictError as exc:
            conflicts = {
                rp: (c if c == "binary" else
                     [S.EntityConflict(handle=x.handle, dxftype=x.dxftype,
                                       reason=x.reason, ours=x.ours,
                                       theirs=x.theirs).model_dump()
                      for x in c])
                for rp, c in exc.details.items()}
            return JSONResponse(status_code=409,
                                content={"detail": str(exc),
                                         "conflicts": conflicts})
        return S.MergeResponse(result=info["result"],
                               commit_id=info.get("commit_id"),
                               details=info.get("details"),
                               author=author)


@app.post("/repos/{name}/merge",
          response_model=S.MergeResponse,
          responses={409: {"model": S.MergeConflictResponse,
                           "description": "Conflictos de merge"}})
def merge(name: str, body: S.MergeRequest,
          who: Principal = Depends(get_principal)):
    return _do_merge(name, body.branch, who.username, body.message)


@app.post("/repos/{name}/merge/resolve",
          response_model=S.MergeResponse,
          responses={409: {"model": S.MergeConflictResponse,
                           "description": "Quedan conflictos sin resolver"}})
def merge_resolve(name: str, body: S.MergeResolveRequest,
                  who: Principal = Depends(get_principal)):
    """Reintenta el merge aplicando elecciones ours/theirs por handle.

    Stateless: recalcula el merge a tres vías desde las refs; las
    elecciones resuelven los conflictos cubiertos y cualquier handle
    conflictivo no cubierto vuelve como 409 con el detalle restante."""
    return _do_merge(name, body.branch, who.username, body.message,
                     resolutions=body.resolutions)


# ----------------------------------------------------------- blame
@app.get("/repos/{name}/blame/{file_path:path}",
         response_model=list[S.BlameEntry])
def blame(name: str, file_path: str, ref: str = Query("HEAD")):
    return _open_repo(name).blame(file_path, ref)


# ----------------------------------------------------------- locks
@app.get("/repos/{name}/locks", response_model=list[S.LockInfo])
def list_locks(name: str):
    repo = _open_repo(name)
    repo._purge_expired_locks()
    rows = repo.conn.execute(
        "SELECT repo_path, owner, expires_at FROM locks").fetchall()
    return [S.LockInfo(path=r["repo_path"], owner=r["owner"],
                       expires_at=r["expires_at"]) for r in rows]


@app.post("/repos/{name}/locks", response_model=S.LockInfo, status_code=201)
def acquire_lock(name: str, body: S.LockRequest,
                 who: Principal = Depends(get_principal)):
    with _repo_locks[name]:
        repo = _open_repo(name)
        repo.lock(body.path, who.username)
        row = repo.conn.execute(
            "SELECT expires_at FROM locks WHERE repo_path = ?",
            (body.path,)).fetchone()
        return S.LockInfo(path=body.path, owner=who.username,
                          expires_at=row["expires_at"])


@app.delete("/repos/{name}/locks/{file_path:path}", status_code=204)
def release_lock(name: str, file_path: str, force: bool = Query(False),
                 who: Principal = Depends(get_principal)):
    with _repo_locks[name]:
        _open_repo(name).unlock(file_path, who.username, force=force)
