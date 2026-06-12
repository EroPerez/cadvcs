# Spec 10 — Autenticación OIDC

**Módulo:** `cadvcs/api/auth.py`

## Propósito

Identidad verificada criptográficamente en toda la API: el author de commits y merges y el owner de locks dejan de ser strings del body que cualquier cliente puede falsificar.

## Comportamiento

Toda la API exige Bearer JWT RS256 (dependencia a nivel de app). La clave de firma se resuelve contra el JWKS del identity provider: descubrimiento OIDC estándar vía `{issuer}/.well-known/openid-configuration`, override directo con `CADVCS_OIDC_JWKS_URL`, o fichero local con `CADVCS_OIDC_JWKS_FILE` para tests y despliegues air-gapped. La validación exige firma, `exp`, `sub`, `aud` (`CADVCS_OIDC_AUDIENCE`) e `iss`. El principal resultante expone `sub`, `username` (`preferred_username` → `email` → `sub`) y `email`; los endpoints mutadores lo inyectan con `Depends(get_principal)` y usan `username` como author/owner. Sin issuer configurado, la API arranca en modo dev sin auth con warning explícito.

## Decisiones de diseño

Algoritmo fijado a RS256 — nunca se acepta `none` ni HS256, cerrando el vector clásico de confusión de algoritmo donde un atacante firma con la clave pública como secreto HMAC. PyJWKClient con cache de claves evita un fetch de JWKS por request. El modo fichero hace el test suite autocontenido: genera su par RSA, publica el JWKS y firma tokens reales, cubriendo los 401 de firma ajena, expiración y audience incorrecta por la misma ruta de código que producción.

## Limitaciones conocidas

Sin autorización por proyecto/rol (cualquier token válido puede todo), sin refresh del JWKS ante rotación de claves con `kid` desconocido, y sin scopes/claims de permisos — primera parada del ROADMAP de seguridad.
