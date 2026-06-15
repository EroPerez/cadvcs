"""Configuración de pytest.

- Hace importable el paquete cadvcs (añade el root al sys.path) para que
  los tests nativos lo importen sin instalación previa.
- Excluye de la colección las suites de tipo *script*: son ficheros que
  ejecutan su lógica al importarse (no exponen funciones `test_`), así que
  si pytest los importara durante la colección los correría dos veces y
  podría romper. El adaptador `test_script_suites.py` los ejecuta como
  subprocesos —la forma visible a pytest— y el CI los corre directamente.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Suites de script que NO deben colectarse como módulos de test pytest.
_SCRIPT_SUITES = {
    "test_api.py", "test_async.py", "test_cli_auth.py", "test_infra.py",
    "test_presigned.py", "test_s3.py", "test_ui.py",
}
collect_ignore = list(_SCRIPT_SUITES)
