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

    args = p.parse_args(argv)
    root = Path(args.repo)

    # --- Comandos de sesión: no necesitan repositorio ---
    if args.cmd in ("login", "logout", "whoami", "token"):
        return _auth_command(args)

    try:
        if args.cmd == "init":
            Repo.init(root)
            print(f"Repositorio inicializado en {root.resolve()} (rama main)")
            return 0

        repo = Repo(root)

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
