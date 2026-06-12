# Spec 08 — CLI

**Módulo:** `cadvcs/cli.py`, entry point `cadvcs` (pyproject)

## Propósito

Exponer el flujo completo con la gramática de Git para que el coste de aprendizaje sea cero para cualquier desarrollador, y servir de cliente de automatización/CI.

## Comportamiento

Comandos: `init`, `add`, `status` (A/M/D contra HEAD), `commit --user -m`, `log` (first-parent con decoraciones de ramas y tags y marca `[merge]`), `branch` (crear/listar), `switch [--force]`, `tag`, `diff ref_a ref_b` (tree-level más el detalle semántico por entidad en DXF), `merge --user [-m] [--resolve PATH:HANDLE=ours|theirs]...`, `blame`, `lock`/`unlock --user [--force]` y `checkout --ref --out`. Los conflictos de merge se imprimen estructurados en stderr con exit code 1; `--resolve` es repetible y acepta `__file__` para binarios.

## Decisiones de diseño

argparse con subparsers y sin dependencias extra: el CLI consume `repo.Repo` directamente (sin pasar por la API), así que funciona offline contra el repositorio local — útil en pipelines y para el plugin de escritorio. Identidad por flag `--user` en local; la identidad verificada criptográficamente es responsabilidad de la capa API (spec 10).

## Limitaciones conocidas

Sin modo remoto (hablar con la API en vez del repo local) ni salida `--json` para scripting estructurado.
