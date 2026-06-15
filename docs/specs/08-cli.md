# Spec 08 — CLI

**Módulo:** `cadvcs/cli.py`; entry points `cadvcs` y alias corto `cad` (pyproject). Sesión en `cadvcs/auth_store.py` y `cadvcs/login.py`.

## Propósito

Exponer el flujo completo con la gramática de Git para que el coste de aprendizaje sea cero para cualquier desarrollador, servir de cliente de automatización/CI, y gestionar la sesión para eliminar el manejo manual de tokens.

## Comportamiento

Comandos de versionado: `init`, `add`, `status` (A/M/D contra HEAD), `commit [--user] -m`, `log` (first-parent con decoraciones de ramas y tags, marca `[merge]` y salida `--json` con filtros `--author`/`--path`/`--since`/`--limit`), `branch` (crear/listar/`-d`/`-D`), `switch [--force]`, `tag`, `diff ref_a ref_b` (tree-level más el detalle semántico por entidad en DXF), `merge [--user] [-m] [--resolve PATH:HANDLE=ours|theirs]...`, `cherry-pick [--user] [-m]`, `blame`, `lock`/`unlock [--user] [--force]`, `gc` y `checkout --ref --out`. Los conflictos de merge se imprimen estructurados en stderr con exit code 1; `--resolve` es repetible y acepta `__file__` para binarios.

Comandos de sesión: `login` (con `--token` para pegar un JWT una vez, o `--user`/`--password` para el password grant OIDC), `logout`, `whoami` (usuario, roles y caducidad del token) y `token` (imprime el JWT para `curl`/scripts). El token se guarda por servidor en `~/.config/cadvcs/credentials.json` con permisos `0600`; el servidor se elige con `--server` o `CADVCS_SERVER`.

El alias `cad` es equivalente a `cadvcs`: `cad commit ...` en vez de `python -m cadvcs.cli commit ...`.

## Decisiones de diseño

argparse con subparsers y sin dependencias extra: el CLI de versionado consume `repo.Repo` directamente (sin pasar por la API), así que funciona offline contra el repositorio local — útil en pipelines y para el plugin de escritorio. La identidad verificada criptográficamente sigue siendo responsabilidad de la capa API (spec 10); el `--user` del CLI local es declarativo.

`--user` es **opcional** en los comandos que registran autoría: la identidad se resuelve en orden `--user` explícito → variable `CADVCS_USER` → nombre de usuario del token de sesión guardado (claim `preferred_username`/`sub`) → error claro con instrucciones. Esto elimina la repetición de `--user` en cada commit: tras `cad login`, los commits ya saben quién eres. El token se decodifica sin verificar firma solo para mostrar identidad/caducidad (`whoami`); la verificación real la hace siempre la API.

El almacén de credenciales está indexado por servidor para mantener varias sesiones a la vez (p.ej. local y producción), con la URL base normalizada (sin barra final) como clave.

## Limitaciones conocidas

El CLI de versionado no tiene aún modo remoto (operar contra la API en vez del repositorio local); `login`/`token` preparan ese camino guardando la credencial, pero los comandos de versionado siguen operando sobre el disco local. El password grant (ROPC) depende de que el IdP lo tenga habilitado y es para CLIs de confianza; flujos interactivos (device code, authorization code) no están implementados todavía.
