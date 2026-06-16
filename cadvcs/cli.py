"""CLI de cadvcs — comandos tipo Git.

    cadvcs init
    cadvcs add plano.dxf
    cadvcs status
    cadvcs commit --user ero -m "Planta inicial"
    cadvcs log
    cadvcs branch variante-b        # crear rama
    cadvcs branch                   # listar
    cadvcs switch variante-b
    cadvcs diff main variante-b
    cadvcs merge variante-b --user ero
    cadvcs tag v1.0
    cadvcs blame plano.dxf
    cadvcs lock plano.dxf --user ero / unlock
    cadvcs checkout plano.dxf --ref v1.0 --out plano_v1.dxf

    # Remote sync (like git remote/push/pull/clone)
    cadvcs remote add origin http://localhost:8000
    cadvcs push                     # push current branch to origin
    cadvcs pull                     # pull current branch from origin
    cadvcs clone http://localhost:8000 proyecto-1
"""
from __future__ import annotations

import argparse
import json as _json
import sys
from pathlib import Path

from .repo import Repo, CadVcsError, MergeConflictError


def _print_semdiff(rp, d, indent="  "):
    print(f"{indent}{rp}: {d.summary()}")
    for e in d.added:
        print(f"{indent}  + {e['dxftype']:<12} handle={e['handle']} layer={e['layer']}")
    for e in d.removed:
        print(f"{indent}  - {e['dxftype']:<12} handle={e['handle']} layer={e['layer']}")
    for e in d.modified:
        print(f"{indent}  ~ {e['dxftype']:<12} handle={e['handle']} layer={e['layer']}")
        for attr, ch in e["changes"].items():
            print(f"{indent}      {attr}: {ch['old']} → {ch['new']}")


class _CliError(Exception):
    pass


def _user(args) -> str:
    """Resuelve el autor de una operación sin obligar a teclear --user cada vez.

    Orden de preferencia: --user explícito → variable CADVCS_USER → nombre
    de usuario del token de sesión guardado (claim preferred_username/sub).
    Si nada de eso existe, error con instrucciones.
    """
    import os
    from . import auth_store
    if getattr(args, "user", None):
        return args.user
    env = os.environ.get("CADVCS_USER")
    if env:
        return env
    tok = auth_store.get_token()
    if tok:
        try:
            claims = auth_store.decode_claims(tok)
            who = claims.get("preferred_username") or claims.get("sub")
            if who:
                return who
        except Exception:
            pass
    raise _CliError(
        "No sé quién eres. Pasa --user TU_NOMBRE, define CADVCS_USER, "
        "o inicia sesión con 'cadvcs login'.")


def _auth_command(args) -> int:
    from . import auth_store
    server = auth_store.normalize_server(args.server)

    if args.cmd == "login":
        token = args.token
        if not token and args.user:
            # Password grant contra el IdP OIDC
            import getpass
            from . import login as login_mod
            password = args.password or getpass.getpass("Contraseña: ")
            try:
                token = login_mod.password_grant(
                    args.user, password, issuer=args.issuer)
            except login_mod.LoginError as exc:
                print(f"Error de login: {exc}")
                return 1
        if not token:
            # Pegar el token a mano (una sola vez)
            try:
                token = input("Pega tu token (JWT): ").strip()
            except EOFError:
                token = ""
        if not token:
            print("No se proporcionó token. Usa --token, o --user para "
                  "password grant OIDC.")
            return 1
        auth_store.save_token(token, server)
        # Mostrar a quién se ha guardado
        try:
            claims = auth_store.decode_claims(token)
            who = claims.get("preferred_username") or claims.get("sub") or "?"
            roles = claims.get(__import__("os").environ.get(
                "CADVCS_ROLE_CLAIM", "roles"), [])
            extra = f" como {who}" + (f" (roles: {roles})" if roles else "")
        except Exception:
            extra = ""
        print(f"Sesión guardada para {server}{extra}.")
        if auth_store.is_expired(token):
            print("  Aviso: este token ya está caducado.")
        return 0

    if args.cmd == "logout":
        if auth_store.clear_token(args.server):
            print(f"Sesión cerrada para {server}.")
        else:
            print(f"No había sesión guardada para {server}.")
        return 0

    if args.cmd == "whoami":
        tok = auth_store.get_token(args.server)
        if not tok:
            print(f"No hay sesión para {server}. Inicia con 'cadvcs login'.")
            return 1
        try:
            claims = auth_store.decode_claims(tok)
        except Exception as exc:
            print(f"El token guardado no es un JWT válido: {exc}")
            return 1
        import os as _os, time as _time
        who = claims.get("preferred_username") or claims.get("sub") or "?"
        roles = claims.get(_os.environ.get("CADVCS_ROLE_CLAIM", "roles"), [])
        print(f"Servidor:  {server}")
        print(f"Usuario:   {who}")
        print(f"Roles:     {roles or '(ninguno)'}")
        exp = claims.get("exp")
        if exp:
            left = int(exp - _time.time())
            estado = "caducado" if left <= 0 else f"caduca en {left//60} min"
            print(f"Token:     {estado}")
        return 0

    if args.cmd == "token":
        tok = auth_store.get_token(args.server)
        if not tok:
            return 1  # silencioso: pensado para $(cadvcs token) en scripts
        print(tok)
        return 0
    return 1


def _get_client(repo, remote_name: str):
    """Build a Client from the repo's remote config + saved token."""
    from . import remote as remote_mod, auth_store
    from .client import Client, ClientError
    cfg = remote_mod.get_remote(repo.vcs_dir, remote_name)
    if cfg is None:
        raise _CliError(
            f"Remote '{remote_name}' no configurado. "
            f"Usa 'cadvcs remote add {remote_name} <url>'")
    token = auth_store.get_token(cfg["url"])
    return Client(cfg["url"], cfg["repo"], token=token)


def _remote_command(repo, args) -> int:
    from . import remote as remote_mod
    if args.remote_cmd == "add":
        repo_name = args.repo_name or repo.root.name
        try:
            remote_mod.add_remote(repo.vcs_dir, args.name, args.url, repo_name)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Remote '{args.name}' → {args.url} (repo: {repo_name})")
    elif args.remote_cmd == "remove":
        try:
            remote_mod.remove_remote(repo.vcs_dir, args.name)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Remote '{args.name}' eliminado")
    else:
        remotes = remote_mod.list_remotes(repo.vcs_dir)
        if not remotes:
            print("No hay remotes configurados.")
        for name, cfg in remotes.items():
            print(f"  {name}\t{cfg['url']}\t(repo: {cfg['repo']})")
    return 0


def _push_command(repo, args) -> int:
    from .client import ClientError
    client = _get_client(repo, args.remote)
    branch = args.branch or repo.current_branch

    # Get remote refs to know what it already has
    try:
        remote_refs = client.get_refs()
    except ClientError:
        # Repo might not exist yet, create it
        try:
            client.ensure_repo()
            remote_refs = {"branches": {}, "tags": {}}
        except ClientError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    remote_head = remote_refs["branches"].get(branch)

    # Get local branch head
    row = repo.conn.execute(
        "SELECT head_commit_id FROM branches WHERE name = ?",
        (branch,)).fetchone()
    if not row or row["head_commit_id"] is None:
        print(f"Branch {branch} has no commits to push")
        return 0
    local_head = row["head_commit_id"]

    if remote_head == local_head:
        print("Everything up-to-date")
        return 0

    # Collect commits to push: walk from local_head back, stop at remote_head
    remote_ancestors = set()
    if remote_head is not None:
        remote_ancestors = repo._ancestors(remote_head)

    from collections import deque
    queue = deque([local_head])
    visited = set()
    to_push = []
    while queue:
        cid = queue.popleft()
        if cid in visited or cid in remote_ancestors:
            continue
        visited.add(cid)
        row = repo.conn.execute(
            "SELECT id, parent_id, parent2_id, author, message, created_at "
            "FROM commits WHERE id = ?", (cid,)).fetchone()
        if not row:
            continue
        entries = repo.conn.execute(
            "SELECT repo_path, blob_sha, size_bytes FROM commit_entries "
            "WHERE commit_id = ?", (cid,)).fetchall()
        to_push.append({
            "id": row["id"],
            "parent_id": row["parent_id"],
            "parent2_id": row["parent2_id"],
            "author": row["author"],
            "message": row["message"],
            "created_at": row["created_at"],
            "entries": {e["repo_path"]: {"blob_sha": e["blob_sha"],
                                          "size_bytes": e["size_bytes"]}
                        for e in entries},
        })
        if row["parent_id"]:
            queue.append(row["parent_id"])
        if row["parent2_id"]:
            queue.append(row["parent2_id"])

    to_push.sort(key=lambda c: c["id"])

    if not to_push:
        print("Everything up-to-date")
        return 0

    # Collect all blob SHAs needed
    all_shas = set()
    for c in to_push:
        for e in c["entries"].values():
            all_shas.add(e["blob_sha"])

    # Check which blobs the remote needs
    print(f"Pushing {len(to_push)} commit(s) to {args.remote}/{branch}...")
    try:
        blob_check = client.check_blobs(sorted(all_shas))
        need_shas = set(blob_check["need"])
    except ClientError:
        need_shas = all_shas

    # Upload missing blobs
    if need_shas:
        print(f"Uploading {len(need_shas)} blob(s)...")
        for i, sha in enumerate(sorted(need_shas), 1):
            data = repo.store.open(sha).read()
            try:
                client.upload_blob(sha, data)
            except ClientError as exc:
                print(f"error uploading blob {sha[:12]}: {exc}",
                      file=sys.stderr)
                return 1
            if i % 10 == 0 or i == len(need_shas):
                print(f"  {i}/{len(need_shas)} blobs uploaded")

    # Push commits
    pack = {
        "commits": [
            {"parent_id": c["parent_id"], "parent2_id": c["parent2_id"],
             "author": c["author"], "message": c["message"],
             "created_at": c["created_at"], "entries": c["entries"]}
            for c in to_push
        ],
        "branch": branch,
        "branch_head": remote_head,
    }
    try:
        result = client.push_pack(pack)
    except ClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Pushed {result['pushed']} commit(s) → {branch} "
          f"(head: c{result['head_commit_id']})")
    return 0


def _pull_command(repo, args) -> int:
    from .client import ClientError
    client = _get_client(repo, args.remote)
    branch = args.branch or repo.current_branch

    # Get local branch head
    row = repo.conn.execute(
        "SELECT head_commit_id FROM branches WHERE name = ?",
        (branch,)).fetchone()
    local_head = row["head_commit_id"] if row else None

    print(f"Pulling {args.remote}/{branch}...")
    try:
        pack = client.pull_pack(branch, since_commit_id=local_head)
    except ClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    commits = pack["commits"]
    if not commits:
        print("Already up-to-date")
        return 0

    # Download missing blobs
    all_shas = set(pack.get("blobs", []))
    need_shas = {sha for sha in all_shas if not repo.store.exists(sha)}
    if need_shas:
        print(f"Downloading {len(need_shas)} blob(s)...")
        for i, sha in enumerate(sorted(need_shas), 1):
            try:
                data = client.download_blob(sha)
            except ClientError as exc:
                print(f"error downloading blob {sha[:12]}: {exc}",
                      file=sys.stderr)
                return 1
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(data)
                tmp_path = Path(tmp.name)
            try:
                repo.store.put(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)
            if i % 10 == 0 or i == len(need_shas):
                print(f"  {i}/{len(need_shas)} blobs downloaded")

    # Apply commits (in topological order, parents first)
    id_map: dict[int, int] = {}
    # Existing commits map to themselves
    existing = repo.conn.execute("SELECT id FROM commits").fetchall()
    for r in existing:
        id_map[r["id"]] = r["id"]

    new_count = 0
    for cd in commits:
        if cd["id"] in id_map:
            continue  # already have this commit
        p1 = id_map.get(cd["parent_id"]) if cd.get("parent_id") else None
        p2 = id_map.get(cd["parent2_id"]) if cd.get("parent2_id") else None
        with repo.conn:
            cid = repo.conn.insert_id(
                "INSERT INTO commits (parent_id, parent2_id, author, "
                "message, created_at) VALUES (?, ?, ?, ?, ?)",
                (p1, p2, cd["author"], cd["message"], cd["created_at"]))
            repo.conn.executemany(
                "INSERT INTO commit_entries (commit_id, repo_path, "
                "blob_sha, size_bytes) VALUES (?, ?, ?, ?)",
                [(cid, rp, e["blob_sha"], e["size_bytes"])
                 for rp, e in cd["entries"].items()])
        id_map[cd["id"]] = cid
        new_count += 1

    # Update branch ref
    if new_count > 0:
        remote_head = pack["head_commit_id"]
        local_new_head = id_map.get(remote_head)
        if local_new_head:
            with repo.conn:
                existing_branch = repo.conn.execute(
                    "SELECT 1 FROM branches WHERE name = ?",
                    (branch,)).fetchone()
                if existing_branch:
                    repo.conn.execute(
                        "UPDATE branches SET head_commit_id = ? "
                        "WHERE name = ?", (local_new_head, branch))
                else:
                    repo.conn.execute(
                        "INSERT INTO branches (name, head_commit_id) "
                        "VALUES (?, ?)", (branch, local_new_head))

    # If we pulled into the current branch, update the workdir
    if branch == repo.current_branch and new_count > 0:
        head_tree = repo._tree(repo.head_commit_id())
        for rp, entry in head_tree.items():
            repo.store.get(entry["blob_sha"], repo.root / rp)
        with repo.conn:
            repo.conn.execute("DELETE FROM tracked")
            repo.conn.executemany(
                "INSERT INTO tracked (repo_path) VALUES (?)",
                [(rp,) for rp in head_tree])

    print(f"Pulled {new_count} new commit(s) from {args.remote}/{branch}")
    return 0


def _clone_command(args) -> int:
    from .client import Client, ClientError
    from . import auth_store, remote as remote_mod

    dest = Path(args.dest or args.repo_name)
    if dest.exists() and any(dest.iterdir()):
        print(f"error: {dest} already exists and is not empty",
              file=sys.stderr)
        return 1

    token = auth_store.get_token(args.url.rstrip("/"))
    client = Client(args.url, args.repo_name, token=token)

    print(f"Cloning {args.url}/{args.repo_name} into {dest}...")

    # Verify repo exists
    try:
        info = client.get_repo_info()
    except ClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Init local repo
    repo = Repo.init(dest)

    # Save remote config
    remote_mod.add_remote(repo.vcs_dir, "origin", args.url, args.repo_name)

    # Pull all branches
    try:
        refs = client.get_refs()
    except ClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    default_branch = info.get("current_branch", "main")

    # Pull each branch
    for branch_name, head_id in refs["branches"].items():
        if head_id is None:
            continue
        pack = client.pull_pack(branch_name)
        commits = pack.get("commits", [])
        if not commits:
            continue

        # Download blobs
        all_shas = set(pack.get("blobs", []))
        need_shas = {sha for sha in all_shas if not repo.store.exists(sha)}
        if need_shas:
            for sha in sorted(need_shas):
                data = client.download_blob(sha)
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(data)
                    tmp_path = Path(tmp.name)
                try:
                    repo.store.put(tmp_path)
                finally:
                    tmp_path.unlink(missing_ok=True)

        # Apply commits
        id_map: dict[int, int] = {}
        existing = repo.conn.execute("SELECT id FROM commits").fetchall()
        for r in existing:
            id_map[r["id"]] = r["id"]

        for cd in commits:
            if cd["id"] in id_map:
                continue
            p1 = id_map.get(cd["parent_id"]) if cd.get("parent_id") else None
            p2 = id_map.get(cd["parent2_id"]) if cd.get("parent2_id") else None
            with repo.conn:
                cid = repo.conn.insert_id(
                    "INSERT INTO commits (parent_id, parent2_id, author, "
                    "message, created_at) VALUES (?, ?, ?, ?, ?)",
                    (p1, p2, cd["author"], cd["message"], cd["created_at"]))
                repo.conn.executemany(
                    "INSERT INTO commit_entries (commit_id, repo_path, "
                    "blob_sha, size_bytes) VALUES (?, ?, ?, ?)",
                    [(cid, rp, e["blob_sha"], e["size_bytes"])
                     for rp, e in cd["entries"].items()])
            id_map[cd["id"]] = cid

        # Update branch
        remote_head = pack["head_commit_id"]
        local_head = id_map.get(remote_head)
        if local_head:
            with repo.conn:
                existing_branch = repo.conn.execute(
                    "SELECT 1 FROM branches WHERE name = ?",
                    (branch_name,)).fetchone()
                if existing_branch:
                    repo.conn.execute(
                        "UPDATE branches SET head_commit_id = ? "
                        "WHERE name = ?", (local_head, branch_name))
                else:
                    repo.conn.execute(
                        "INSERT INTO branches (name, head_commit_id) "
                        "VALUES (?, ?)", (branch_name, local_head))

        print(f"  {branch_name} → c{local_head}")

    # Checkout default branch working copy
    try:
        repo.switch(default_branch, force=True)
    except CadVcsError:
        pass

    # Create tags
    for tag_name, commit_id in refs.get("tags", {}).items():
        try:
            repo.tag_create(tag_name, str(commit_id))
        except CadVcsError:
            pass

    print(f"Cloned into {dest.resolve()}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="cadvcs")
    p.add_argument("--repo", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")
    sub.add_parser("status")

    s = sub.add_parser("add"); s.add_argument("files", nargs="+")

    s = sub.add_parser("commit")
    s.add_argument("--user", default=None)
    s.add_argument("-m", "--message", default="")

    s = sub.add_parser("log")
    s.add_argument("ref", nargs="?", default="HEAD")
    s.add_argument("--author"); s.add_argument("--path")
    s.add_argument("--since"); s.add_argument("--limit", type=int, default=50)
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("branch"); s.add_argument("name", nargs="?")
    s.add_argument("-d", "--delete", action="store_true")
    s.add_argument("-D", "--force-delete", action="store_true")
    sub.add_parser("gc")
    s = sub.add_parser("switch")
    s.add_argument("name"); s.add_argument("--force", action="store_true")

    s = sub.add_parser("tag")
    s.add_argument("name", nargs="?"); s.add_argument("--ref", default="HEAD")

    s = sub.add_parser("diff")
    s.add_argument("ref_a"); s.add_argument("ref_b")

    s = sub.add_parser("merge")
    s.add_argument("branch"); s.add_argument("--user", default=None)
    s.add_argument("-m", "--message", default=None)
    s.add_argument("--resolve", action="append", default=[],
                   metavar="PATH:HANDLE=CHOICE",
                   help="resolución manual, ej: plano.dxf:31=theirs "
                        "(repetible; '__file__' para binarios)")

    s = sub.add_parser("cherry-pick")
    s.add_argument("ref"); s.add_argument("--user", default=None)
    s.add_argument("-m", "--message", default=None)

    s = sub.add_parser("blame")
    s.add_argument("file"); s.add_argument("--ref", default="HEAD")

    for name in ("lock", "unlock"):
        s = sub.add_parser(name)
        s.add_argument("file"); s.add_argument("--user", default=None)
        if name == "unlock":
            s.add_argument("--force", action="store_true")

    s = sub.add_parser("checkout")
    s.add_argument("file"); s.add_argument("--ref", default="HEAD")
    s.add_argument("--out", default=None)

    # --- Gestión de sesión / login (evita pegar tokens a mano) ---
    s = sub.add_parser("login", help="iniciar sesión y guardar el token")
    s.add_argument("--server", default=None,
                   help="URL de la API (default: CADVCS_SERVER o localhost:8000)")
    s.add_argument("--token", default=None,
                   help="pegar un JWT directamente (se guarda y no se pide más)")
    s.add_argument("--user", default=None, help="usuario para password grant OIDC")
    s.add_argument("--password", default=None,
                   help="contraseña (si se omite con --user, se pide por teclado)")
    s.add_argument("--issuer", default=None, help="issuer OIDC (default: CADVCS_OIDC_ISSUER)")

    s = sub.add_parser("logout", help="cerrar sesión y borrar el token guardado")
    s.add_argument("--server", default=None)

    s = sub.add_parser("whoami", help="mostrar la identidad del token guardado")
    s.add_argument("--server", default=None)

    s = sub.add_parser("token", help="imprimir el token guardado (para curl, scripts)")
    s.add_argument("--server", default=None)

    # --- Remote management (git remote equivalent) ---
    s = sub.add_parser("remote", help="manage remotes (like git remote)")
    rs = s.add_subparsers(dest="remote_cmd")
    ra = rs.add_parser("add", help="add a remote")
    ra.add_argument("name", help="remote name (e.g. origin)")
    ra.add_argument("url", help="server URL (e.g. http://localhost:8000)")
    ra.add_argument("--repo-name", default=None,
                    help="repo name on server (default: local dir name)")
    rr = rs.add_parser("remove", help="remove a remote")
    rr.add_argument("name")
    rs.add_parser("list", help="list remotes")

    # --- Push / Pull / Clone ---
    s = sub.add_parser("push", help="push commits to a remote server")
    s.add_argument("remote", nargs="?", default="origin",
                   help="remote name (default: origin)")
    s.add_argument("branch", nargs="?", default=None,
                   help="branch to push (default: current branch)")

    s = sub.add_parser("pull", help="pull commits from a remote server")
    s.add_argument("remote", nargs="?", default="origin",
                   help="remote name (default: origin)")
    s.add_argument("branch", nargs="?", default=None,
                   help="branch to pull (default: current branch)")

    s = sub.add_parser("clone", help="clone a remote repo locally")
    s.add_argument("url", help="server URL (e.g. http://localhost:8000)")
    s.add_argument("repo_name", help="repo name on the server")
    s.add_argument("dest", nargs="?", default=None,
                   help="local directory (default: repo name)")

    args = p.parse_args(argv)
    root = Path(args.repo) if args.cmd != "clone" else Path(".")

    # --- Comandos de sesión: no necesitan repositorio ---
    if args.cmd in ("login", "logout", "whoami", "token"):
        return _auth_command(args)

    # --- Clone: no necesita un repo existente ---
    if args.cmd == "clone":
        return _clone_command(args)

    try:
        if args.cmd == "init":
            Repo.init(root)
            print(f"Repositorio inicializado en {root.resolve()} (rama main)")
            return 0

        repo = Repo(root)

        # --- Remote management ---
        if args.cmd == "remote":
            return _remote_command(repo, args)

        # --- Push / Pull ---
        if args.cmd == "push":
            return _push_command(repo, args)

        if args.cmd == "pull":
            return _pull_command(repo, args)

        if args.cmd == "add":
            repo.add(*[Path(f) for f in args.files])
            print(f"Tracked: {', '.join(args.files)}")

        elif args.cmd == "status":
            st = repo.status()
            print(f"Rama: {repo.current_branch}")
            for kind, mark in (("new", "A"), ("modified", "M"), ("deleted", "D")):
                for rp in st[kind]:
                    print(f"  {mark} {rp}")
            if not (st["new"] or st["modified"] or st["deleted"]):
                print("  workdir limpio")

        elif args.cmd == "commit":
            info = repo.commit(_user(args), args.message)
            print(f"[{info['branch']} c{info['commit_id']}] "
                  f"{len(info['changed'])} archivo(s): {', '.join(info['changed'])}")

        elif args.cmd == "log":
            entries = repo.log(args.ref, args.limit, author=args.author,
                               path=args.path, since=args.since)
            if args.json:
                print(_json.dumps(entries, indent=2, ensure_ascii=False))
                return 0
            for c in entries:
                refs = c["branches"] + c["tags"]
                decorations = f" ({', '.join(refs)})" if refs else ""
                merge = " [merge]" if c["is_merge"] else ""
                print(f"c{c['id']}{merge}{decorations}  {c['created_at']}  "
                      f"{c['author']:<8} {c['message']}")

        elif args.cmd == "gc":
            stats = repo.gc()
            print(f"gc: {stats['commits_removed']} commits, "
                  f"{stats['blobs_removed']} blobs, "
                  f"{stats['bytes_freed']} bytes liberados")

        elif args.cmd == "branch":
            if args.name and (args.delete or args.force_delete):
                repo.branch_delete(args.name, force=args.force_delete)
                print(f"Rama {args.name} eliminada")
            elif args.name:
                repo.branch_create(args.name)
                print(f"Rama {args.name} creada en c{repo.head_commit_id()}")
            else:
                for b in repo.branches():
                    mark = "*" if b["current"] else " "
                    print(f"{mark} {b['name']} → c{b['head_commit_id']}")

        elif args.cmd == "switch":
            repo.switch(args.name, force=args.force)
            print(f"Cambiado a rama {args.name}")

        elif args.cmd == "tag":
            if args.name:
                repo.tag_create(args.name, args.ref)
                print(f"Tag {args.name} → {args.ref}")
            else:
                for t in repo.tags():
                    print(f"{t['name']} → c{t['commit_id']}")

        elif args.cmd == "diff":
            d = repo.diff(args.ref_a, args.ref_b)
            for rp in d["added"]:
                print(f"  A {rp}")
            for rp in d["removed"]:
                print(f"  D {rp}")
            for rp, sd in d["modified"].items():
                if sd is None:
                    print(f"  M {rp} (binario)")
                else:
                    _print_semdiff(rp, sd)

        elif args.cmd == "merge":
            resolutions: dict = {}
            for spec in args.resolve:
                try:
                    path_part, choice = spec.rsplit("=", 1)
                    rp, handle = path_part.rsplit(":", 1)
                    assert choice in ("ours", "theirs")
                except (ValueError, AssertionError):
                    print(f"error: --resolve inválido: {spec} "
                          f"(formato PATH:HANDLE=ours|theirs)", file=sys.stderr)
                    return 2
                resolutions.setdefault(rp, {})[handle] = choice
            try:
                info = repo.merge(args.branch, _user(args), args.message,
                                  resolutions=resolutions or None)
                if info["result"] == "already-up-to-date":
                    print("Ya actualizado")
                elif info["result"] == "fast-forward":
                    print(f"Fast-forward a c{info['commit_id']}")
                else:
                    print(f"Merge OK → c{info['commit_id']}")
                    for rp, detail in info.get("details", {}).items():
                        print(f"  {rp}: {detail}")
            except MergeConflictError as exc:
                print(f"error: {exc}", file=sys.stderr)
                for rp, conf in exc.details.items():
                    if conf == "binary":
                        print(f"  {rp}: binario divergente (usa lock + manual)",
                              file=sys.stderr)
                    else:
                        for c in conf:
                            print(f"  {rp}: {c.reason} {c.dxftype} "
                                  f"handle={c.handle}", file=sys.stderr)
                return 1

        elif args.cmd == "cherry-pick":
            try:
                info = repo.cherry_pick(args.ref, _user(args), args.message)
                if info["result"] == "empty":
                    print("Nada que aplicar (cambios ya presentes)")
                else:
                    print(f"Cherry-pick OK → c{info['commit_id']}")
            except MergeConflictError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1

        elif args.cmd == "blame":
            for row in repo.blame(args.file, args.ref):
                cid = f"c{row.get('commit_id', '?')}"
                print(f"{cid:<5} {row.get('author', '?'):<8} "
                      f"{row['dxftype']:<12} handle={row['handle']} "
                      f"layer={row['layer']}  «{row.get('message', '')}»")

        elif args.cmd == "lock":
            u = _user(args)
            repo.lock(args.file, u)
            print(f"Lock: {args.file} → {u}")

        elif args.cmd == "unlock":
            repo.unlock(args.file, _user(args), force=args.force)
            print(f"Unlock: {args.file}")

        elif args.cmd == "checkout":
            out = repo.checkout_file(args.file, args.ref,
                                     Path(args.out) if args.out else None)
            print(f"Checkout {args.ref}:{args.file} → {out}")

        return 0
    except _CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except CadVcsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
