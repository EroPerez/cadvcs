"""Login contra el proveedor OIDC para el CLI.

Obtiene un token de acceso sin que el usuario tenga que copiarlo a mano:

  - Modo directo (`--token`): el usuario pega un JWT una sola vez y se
    guarda en el almacén de credenciales. Útil cuando el token se obtiene
    por otro medio (panel del IdP, CI).
  - Password grant (OAuth2 Resource Owner Password Credentials): con el
    issuer OIDC configurado, intercambia usuario+contraseña por un token
    en el token endpoint del IdP. Pensado para CLIs de confianza y
    entornos donde ese grant está habilitado.

La URL del token endpoint se descubre del documento
`{issuer}/.well-known/openid-configuration`, igual que la API descubre el
JWKS, así no hay que configurarla aparte.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


class LoginError(RuntimeError):
    pass


def _discover(issuer: str) -> dict:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        raise LoginError(f"No se pudo descubrir la configuración OIDC en "
                         f"{url}: {exc}")


def password_grant(username: str, password: str, *,
                   issuer: str | None = None,
                   client_id: str | None = None,
                   client_secret: str | None = None,
                   scope: str = "openid profile") -> str:
    """Intercambia usuario+contraseña por un access token (OAuth2 ROPC).

    Lee issuer/client de variables de entorno si no se pasan:
      CADVCS_OIDC_ISSUER, CADVCS_OIDC_CLIENT_ID, CADVCS_OIDC_CLIENT_SECRET
    Devuelve el access_token (JWT) string.
    """
    issuer = issuer or os.environ.get("CADVCS_OIDC_ISSUER")
    if not issuer:
        raise LoginError(
            "No hay issuer OIDC configurado (CADVCS_OIDC_ISSUER). "
            "Usa 'cadvcs login --token <JWT>' para pegar un token a mano.")
    client_id = client_id or os.environ.get("CADVCS_OIDC_CLIENT_ID", "cadvcs")
    client_secret = client_secret or os.environ.get("CADVCS_OIDC_CLIENT_SECRET")

    conf = _discover(issuer)
    token_endpoint = conf.get("token_endpoint")
    if not token_endpoint:
        raise LoginError("El IdP no anuncia token_endpoint en su configuración")

    form = {
        "grant_type": "password",
        "username": username,
        "password": password,
        "scope": scope,
        "client_id": client_id,
    }
    if client_secret:
        form["client_secret"] = client_secret

    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(
        token_endpoint, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        raise LoginError(f"El IdP rechazó el login ({exc.code}): {body}")
    except Exception as exc:
        raise LoginError(f"Fallo contactando el token endpoint: {exc}")

    token = payload.get("access_token")
    if not token:
        raise LoginError("La respuesta del IdP no incluye access_token")
    return token
