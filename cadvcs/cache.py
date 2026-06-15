"""Cache de renders en Redis.

Un render SVG (versión única o diff visual entre dos versiones) es
**inmutable**: depende solo del/los SHA(s) de contenido, que son
content-addressed. Por tanto un par de SHAs identifica un diff visual
para siempre y se puede cachear sin invalidación. Eso es justo lo que
pide ARCHITECTURE.md: renders SVG cacheados en Redis con el par de SHAs
como clave.

Degradación: si no hay `CADVCS_REDIS_URL` o Redis no responde, el cache
es un no-op silencioso (get→None, set→nada). El sistema funciona igual,
solo recomputa el render. Nunca un fallo de Redis tumba una petición.
"""
from __future__ import annotations

import os


class RenderCache:
    """Cache get/set de SVG por clave determinista. No-op si no hay Redis."""

    PREFIX = "cadvcs:render:"
    TTL = None  # inmutable: sin expiración por defecto

    def __init__(self, url: str | None = None):
        self.client = None
        url = url or os.environ.get("CADVCS_REDIS_URL")
        if not url:
            return
        try:
            import redis
            self.client = redis.Redis.from_url(
                url, socket_connect_timeout=1, socket_timeout=1)
            self.client.ping()
        except Exception:
            # Redis configurado pero inalcanzable: degradar a no-op
            self.client = None

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @staticmethod
    def version_key(repo: str, sha: str) -> str:
        return f"{RenderCache.PREFIX}v:{repo}:{sha}"

    @staticmethod
    def diff_key(repo: str, sha_a: str, sha_b: str) -> str:
        # El orden importa (a→b no es b→a): no se normaliza.
        return f"{RenderCache.PREFIX}d:{repo}:{sha_a}:{sha_b}"

    def get(self, key: str) -> str | None:
        if not self.client:
            return None
        try:
            val = self.client.get(key)
            return val.decode() if val else None
        except Exception:
            return None  # fallo de Redis nunca propaga

    def set(self, key: str, svg: str) -> None:
        if not self.client:
            return
        try:
            if self.TTL:
                self.client.set(key, svg, ex=self.TTL)
            else:
                self.client.set(key, svg)
        except Exception:
            pass

    def stats(self) -> dict:
        if not self.client:
            return {"enabled": False}
        try:
            n = 0
            for _ in self.client.scan_iter(match=self.PREFIX + "*", count=500):
                n += 1
            return {"enabled": True, "cached_renders": n}
        except Exception:
            return {"enabled": False}


_cache: RenderCache | None = None


def render_cache() -> RenderCache:
    """Singleton perezoso (re-evalúa el entorno la primera vez)."""
    global _cache
    if _cache is None:
        _cache = RenderCache()
    return _cache
