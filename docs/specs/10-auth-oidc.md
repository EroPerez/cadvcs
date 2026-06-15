# Spec 10 — Autenticación OIDC

**Módulo:** `cadvcs/api/auth.py`

## Propósito

Identidad verificada criptográficamente en toda la API: el author de commits y merges y el owner de locks dejan de ser strings del body que cualquier cliente puede falsificar.

## Comportamiento

Toda la API exige Bearer JWT RS256 (dependencia a nivel de app). La clave de firma se resuelve contra el JWKS del identity provider: descubrimiento OIDC estándar vía `{issuer}/.well-known/openid-configuration`, override directo con `CADVCS_OIDC_JWKS_URL`, o fichero local con `CADVCS_OIDC_JWKS_FILE` para tests y despliegues air-gapped. La validación exige firma, `exp`, `sub`, `aud` (`CADVCS_OIDC_AUDIENCE`) e `iss`. El principal resultante expone `sub`, `username` (`preferred_username` → `email` → `sub`), `email` y `roles`; los endpoints mutadores lo inyectan con `Depends(get_principal)` y usan `username` como author/owner. Sin issuer configurado, la API arranca en modo dev sin auth con warning explícito.

La autorización es por rol jerárquico: `viewer` ⊂ `editor` ⊂ `admin`. La app exige `viewer` a nivel global; las mutaciones exigen `editor`, y operaciones sensibles como liberar un lock ajeno por la fuerza exigen `admin`. Los roles salen del token (`CADVCS_ROLE_CLAIM`, soporta claims anidados estilo Keycloak `realm_access.roles`), con `CADVCS_DEFAULT_ROLES` para el comportamiento sin claim (`""` = deny-by-default en producción).

Del lado cliente, el CLI gestiona la sesión (spec 08): `cadvcs login` obtiene y guarda el token —pegándolo con `--token` o vía password grant OIDC— y los comandos lo usan sin que el usuario lo manipule a mano. El token se decodifica en el cliente solo para mostrar identidad/caducidad (`whoami`); la verificación criptográfica real ocurre siempre en la API.

## Decisiones de diseño

Algoritmo fijado a RS256 — nunca se acepta `none` ni HS256, cerrando el vector clásico de confusión de algoritmo donde un atacante firma con la clave pública como secreto HMAC. PyJWKClient con cache de claves evita un fetch de JWKS por request. El modo fichero hace el test suite autocontenido: genera su par RSA, publica el JWKS y firma tokens reales, cubriendo los 401 de firma ajena, expiración y audience incorrecta por la misma ruta de código que producción.

## Limitaciones conocidas

La autorización es por rol global (viewer/editor/admin), no todavía por **proyecto/repositorio**: un `editor` puede editar cualquier repo, no solo los suyos. Sin refresh del JWKS ante rotación de claves con `kid` desconocido, y sin scopes de grano fino por operación — siguiente parada del ROADMAP de seguridad. En el cliente, el login soporta `--token` y password grant (ROPC); los flujos interactivos (device code, authorization code con callback) no están implementados.
