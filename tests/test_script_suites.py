"""Adaptador: ejecuta las suites de script existentes bajo pytest.

Las suites históricas (demo.py, test_api.py, ...) son scripts con asserts
y salida propia. En vez de reescribirlas de golpe, aquí se invocan como
subprocesos para que pytest sea el runner único; la migración a funciones
pytest nativas puede hacerse incrementalmente. test_s3/test_presigned se
saltan si falta moto (entorno mínimo).
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Rutas relativas a ROOT. demo.py vive en el root; los test_*.py en tests/.
SCRIPT_SUITES = ["demo.py", "tests/test_api.py"]
OPTIONAL_SUITES = {
    "tests/test_s3.py": "moto",
    "tests/test_presigned.py": "moto.moto_server.threaded_moto_server",
}


@pytest.mark.parametrize("script", SCRIPT_SUITES)
def test_script_suite(script):
    r = subprocess.run([sys.executable, script], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"{script} falló:\n{r.stdout}\n{r.stderr}"


@pytest.mark.parametrize("script,module", list(OPTIONAL_SUITES.items()))
def test_optional_suite(script, module):
    if not (ROOT / script).exists():
        pytest.skip(f"{script} no está en esta rama")
    pytest.importorskip(module.split(".")[0])
    r = subprocess.run([sys.executable, script], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"{script} falló:\n{r.stdout}\n{r.stderr}"
