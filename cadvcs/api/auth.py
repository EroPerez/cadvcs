"""Autenticación OIDC para la API.

Valida JWT Bearer (RS256) contra el JWKS del identity provider. El
`author` de commits/merges y el `owner` de locks salen del token, no
del body — el cliente ya no puede suplantar identidad.

Configuración por entorno:
  CADVCS_OIDC_ISSUER     issuer esperado (claim iss). Si hay red, el
                         jwks_uri se descubre vía
                         {issuer}/.well-known/openid-configuration
  CADVCS_OIDC_AUDIENCE   audience esperada (claim aud), default 'cadvcs'
  CADVCS_OIDC_JWKS_URL   override directo del JWKS endpoint
  CADVCS_OIDC_JWKS_FILE  JWKS desde fichero local (tests / air-gapped)

Si no hay issuer ni JWKS configurado, la API arranca en modo dev SIN
auth (principal 'dev') con un warning — nunca usar así en producción.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import urllib.request
from pathlib import Path

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logger = logging.getLogger("cadvcs.auth")

ISSUER = os.environ.get("CADVCS_OIDC_ISSUER")
AUDIENCE = os.environ.get("CADVCS_OIDC_AUDIENCE", "cadvcs")
JWKS_URL = os.environ.get("CADVCS_OIDC_JWKS_URL")
JWKS_FILE = os.environ.get("CADVCS_OIDC_JWKS_FILE")

AUTH_ENABLED = bool(ISSUER or JWKS_URL or JWKS_FILE)
if not AUTH_ENABLED:
    logger.warning("Auth OIDC deshabilitada (sin CADVCS_OIDC_ISSUER): "
                   "modo dev, todas las peticiones como principal 'dev'")

_bearer = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    sub: str
    username: str
    email: str | None = None


@functools.lru_cache(maxsize=1)
def _jwks_url() -> str:
    if JWKS_URL:
        return JWKS_URL
    # Descubrimiento OIDC estándar
    discovery = ISSUER.rstrip("/") + "/.well-known/openid-configuration"
    with urllib.request.urlopen(discovery, timeout=5) as resp:
        return json.load(resp)["jwks_uri"]


@functools.lru_cache(maxsize=1)
def _jwk_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(_jwks_url(), cache_keys=True)


def _signing_key(token: str):
    if JWKS_FILE:
        jwks = json.loads(Path(JWKS_FILE).read_text())
        kid = jwt.get_unverified_header(token).get("kid")
        for k in jwks.get("keys", []):
            if kid is None or k.get("kid") == kid:
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k))
        raise jwt.InvalidKeyError(f"kid {kid} no está en el JWKS")
    return _jwk_client().get_signing_key_from_jwt(token).key


def get_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    """Dependencia FastAPI: valida el Bearer JWT y devuelve el principal."""
    if not AUTH_ENABLED:
        return Principal(sub="dev", username="dev")

    if creds is None:
        raise HTTPException(401, "Falta el header Authorization: Bearer",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        key = _signing_key(creds.credentials)
        claims = jwt.decode(
            creds.credentials, key,
            algorithms=["RS256"],            # nunca aceptar 'none' ni HS256
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"verify_iss": bool(ISSUER), "require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"Token inválido: {exc}",
                            headers={"WWW-Authenticate": "Bearer"})

    username = (claims.get("preferred_username") or claims.get("email")
                or claims["sub"])
    return Principal(sub=claims["sub"], username=username,
                     email=claims.get("email"))
