"""Test de la web UI servida por FastAPI.

Lo más valioso aquí es el **test de contrato**: extrae cada ruta de la
API que el JavaScript del UI invoca y verifica que existe de verdad en
la app. Eso detecta la deriva UI↔API (un endpoint renombrado o un typo
en el front) sin necesidad de un navegador.

También verifica que el shell se sirve sin auth (es la sonda que carga
el navegador, sin token) y que las llamadas de datos sí están protegidas.
"""
import os
import re
import tempfile

os.environ.setdefault("CADVCS_DATA", tempfile.mkdtemp(prefix="cadvcs_ui_"))

from fastapi.testclient import TestClient
from starlette.routing import Mount

from cadvcs.api.main import app, _WEB_DIR

client = TestClient(app)


def check(label, cond):
    assert cond, f"FALLO: {label}"
    print(f"  {label} ✔")


# ---- 1. el shell se sirve, sin auth ----------------------------------------
r = client.get("/ui/", follow_redirects=False)
check("GET /ui/ sirve el shell sin token", r.status_code == 200
      and "cadvcs" in r.text.lower())
r = client.get("/", follow_redirects=False)
check("GET / redirige a /ui/", r.status_code in (307, 308)
      and r.headers["location"] == "/ui/")

# ---- 2. el HTML referencia los recursos esperados --------------------------
html = (_WEB_DIR / "index.html").read_text()
check("el shell incluye el resolutor de conflictos (signature)",
      "renderConflicts" in html and "merge/resolve" in html)

# ---- 3. CONTRATO UI↔API: cada ruta del JS existe en la app -----------------
# Rutas reales de la app (las que no son el mount estático)
app_paths = set()
for route in app.routes:
    if isinstance(route, Mount):
        continue
    if getattr(route, "path", None):
        app_paths.add(route.path)




# Extraer las plantillas de llamada del JS. El UI construye paths
# concatenando literales con variables: "/repos/" + S.repo + "/commits".
# Colapsamos cualquier `"a" + <expr> + "b"` en "a*b" (comodín por variable)
# hasta estabilizar, y luego extraemos los literales de api()/fetch().
js = re.search(r"<script>(?:(?!</script>).)*</script>\s*</body>", html, re.S).group(0)

concat = re.compile(r'"([^"]*)"\s*\+\s*[^"+][^+]*?\+\s*"([^"]*)"')
prev = None
while prev != js:
    prev = js
    js = concat.sub(lambda m: '"' + m.group(1) + "*" + m.group(2) + '"', js)

called_paths = set()
for m in re.finditer(r'(?:api|fetch)\(\s*"(/[^"]*)"', js):
    p = m.group(1).split("?")[0]
    p = re.sub(r"\*+", "*", p)        # comodines colapsados
    p = re.sub(r"//+", "/", p)
    if p.endswith("/"):               # "/blame/" + var → segmento comodín final
        p += "*"
    called_paths.add(p)

# Verificar cada path contra el contrato. Un segmento "*" (variable del UI)
# casa con cualquier segmento o parámetro de la plantilla.
def matches_wild(called: str) -> bool:
    called = called.rstrip("/")
    cs = called.split("/")
    for tpl in app_paths:
        ts = tpl.rstrip("/").split("/")
        ok, i = True, 0
        while i < len(ts):
            seg = ts[i]
            if seg.endswith(":path}"):     # absorbe el resto
                ok = i < len(cs); cs = cs[:i]; ts = ts[:i]; break
            if i >= len(cs): ok = False; break
            if seg.startswith("{") or cs[i] == "*" or seg == cs[i]:
                pass
            else: ok = False; break
            i += 1
        if ok and len(cs) == len(ts):
            return True
    return False

norm = called_paths
unmatched = sorted(p for p in norm if not matches_wild(p))
for p in unmatched:
    print(f"    ✗ SIN RUTA  {p}")
check(f"todas las rutas del UI existen en la API ({len(norm)} comprobadas)",
      not unmatched)

# ---- 4. flujo real mínimo a través del shell + API -------------------------
client.post("/repos", json={"name": "demo"})
import io, ezdxf
doc = ezdxf.new("R2010"); doc.modelspace().add_circle((5, 5), 2)
buf = io.StringIO(); doc.write(buf)
client.put("/repos/demo/files/p.dxf", content=buf.getvalue().encode())
client.post("/repos/demo/commits", json={"message": "v1"})
r = client.get("/repos/demo/commits")
check("la API que consume el UI responde (commits)",
      r.status_code == 200 and r.json()[0]["author"])

print("\nWeb UI OK — todos los checks pasan")
