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


def main(argv=None):
    p = argparse.ArgumentParser(prog="cadvcs")
    p.add_argument("--repo", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")
    sub.add_parser("status")

    s = sub.add_parser("add"); s.add_argument("files", nargs="+")

    s = sub.add_parser("commit")
    s.add_argument("--user", required=True)
    s.add_argument("-m", "--message", default="")

    s = sub.add_parser("log")
    s.add_argument("ref", nargs="?", default="HEAD")

    s = sub.add_parser("branch"); s.add_argument("name", nargs="?")
    s = sub.add_parser("switch")
    s.add_argument("name"); s.add_argument("--force", action="store_true")

    s = sub.add_parser("tag")
    s.add_argument("name", nargs="?"); s.add_argument("--ref", default="HEAD")

    s = sub.add_parser("diff")
    s.add_argument("ref_a"); s.add_argument("ref_b")

    s = sub.add_parser("merge")
    s.add_argument("branch"); s.add_argument("--user", required=True)
    s.add_argument("-m", "--message", default=None)
    s.add_argument("--resolve", action="append", default=[],
                   metavar="PATH:HANDLE=CHOICE",
                   help="resolución manual, ej: plano.dxf:31=theirs "
                        "(repetible; '__file__' para binarios)")

    s = sub.add_parser("cherry-pick")
    s.add_argument("ref"); s.add_argument("--user", required=True)
    s.add_argument("-m", "--message", default=None)

    s = sub.add_parser("blame")
    s.add_argument("file"); s.add_argument("--ref", default="HEAD")

    for name in ("lock", "unlock"):
        s = sub.add_parser(name)
        s.add_argument("file"); s.add_argument("--user", required=True)
        if name == "unlock":
            s.add_argument("--force", action="store_true")

    s = sub.add_parser("checkout")
    s.add_argument("file"); s.add_argument("--ref", default="HEAD")
    s.add_argument("--out", default=None)

    args = p.parse_args(argv)
    root = Path(args.repo)

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
            info = repo.commit(args.user, args.message)
            print(f"[{info['branch']} c{info['commit_id']}] "
                  f"{len(info['changed'])} archivo(s): {', '.join(info['changed'])}")

        elif args.cmd == "log":
            for c in repo.log(args.ref):
                refs = c["branches"] + c["tags"]
                decorations = f" ({', '.join(refs)})" if refs else ""
                merge = " [merge]" if c["is_merge"] else ""
                print(f"c{c['id']}{merge}{decorations}  {c['created_at']}  "
                      f"{c['author']:<8} {c['message']}")

        elif args.cmd == "branch":
            if args.name:
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
                info = repo.merge(args.branch, args.user, args.message,
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
                info = repo.cherry_pick(args.ref, args.user, args.message)
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
            repo.lock(args.file, args.user)
            print(f"Lock: {args.file} → {args.user}")

        elif args.cmd == "unlock":
            repo.unlock(args.file, args.user, force=args.force)
            print(f"Unlock: {args.file}")

        elif args.cmd == "checkout":
            out = repo.checkout_file(args.file, args.ref,
                                     Path(args.out) if args.out else None)
            print(f"Checkout {args.ref}:{args.file} → {out}")

        return 0
    except CadVcsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
