"""HTTP client for syncing local repos with a cadvcs server.

Handles blob transfer, commit negotiation, and ref updates for push/pull.
Uses only stdlib (urllib) to avoid adding requests as a dependency.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class ClientError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class Client:
    """HTTP client for a specific remote cadvcs server + repo."""

    def __init__(self, server_url: str, repo_name: str, token: str | None = None):
        self.base = server_url.rstrip("/")
        self.repo = repo_name
        self.token = token

    def _url(self, path: str) -> str:
        return f"{self.base}/repos/{self.repo}/{path}"

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, path: str, data: bytes | None = None,
                 headers: dict | None = None, timeout: int = 30) -> dict | bytes:
        url = self._url(path) if not path.startswith("http") else path
        h = self._headers(headers)
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                ct = resp.headers.get("Content-Type", "")
                if "json" in ct:
                    return json.loads(body)
                return body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:500]
            try:
                detail = json.loads(body).get("detail", body)
            except Exception:
                detail = body
            raise ClientError(f"{exc.code}: {detail}", exc.code)
        except Exception as exc:
            raise ClientError(f"Connection error: {exc}")

    def _get(self, path: str, **kw) -> dict | bytes:
        return self._request("GET", path, **kw)

    def _post(self, path: str, body: dict | None = None, **kw) -> dict | bytes:
        data = json.dumps(body).encode() if body else None
        h = {"Content-Type": "application/json"} if data else {}
        return self._request("POST", path, data=data, headers=h, **kw)

    def _put(self, path: str, data: bytes, content_type: str = "application/octet-stream",
             **kw) -> dict | bytes:
        return self._request("PUT", path, data=data,
                             headers={"Content-Type": content_type}, **kw)

    # ---- High-level sync operations ----

    def get_refs(self) -> dict:
        """Get all branch and tag refs from the remote."""
        return self._get("sync/refs")

    def negotiate(self, local_commit_ids: list[int]) -> dict:
        """Send local commit IDs, get back what the remote needs or has."""
        return self._post("sync/negotiate", {"commit_ids": local_commit_ids})

    def push_pack(self, pack: dict) -> dict:
        """Push a pack of commits and branch updates to the remote."""
        return self._post("sync/push", pack, timeout=120)

    def pull_pack(self, branch: str, since_commit_id: int | None = None) -> dict:
        """Pull commits and blob info for a branch since a given commit."""
        params = {"branch": branch}
        if since_commit_id is not None:
            params["since"] = str(since_commit_id)
        qs = urllib.parse.urlencode(params)
        return self._get(f"sync/pull?{qs}")

    def upload_blob(self, sha: str, data: bytes) -> None:
        """Upload a blob to the remote."""
        self._put(f"sync/blobs/{sha}", data, timeout=120)

    def download_blob(self, sha: str) -> bytes:
        """Download a blob from the remote."""
        return self._get(f"sync/blobs/{sha}", timeout=120)

    def check_blobs(self, shas: list[str]) -> dict:
        """Check which blobs the remote already has."""
        return self._post("sync/blobs/check", {"shas": shas})

    def ensure_repo(self) -> dict:
        """Create the remote repo if it doesn't exist, return info."""
        try:
            return self._request("GET", self._url("")[:-1].rsplit("/", 1)[0]
                                 + "/" + self.repo)
        except ClientError as exc:
            if exc.status == 404:
                url = f"{self.base}/repos"
                data = json.dumps({"name": self.repo}).encode()
                h = self._headers({"Content-Type": "application/json"})
                req = urllib.request.Request(url, data=data, headers=h, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        return json.loads(resp.read())
                except urllib.error.HTTPError as exc2:
                    if exc2.code == 409:
                        return self._get("")
                    raise ClientError(f"{exc2.code}: {exc2.read().decode()[:300]}",
                                      exc2.code)
            raise

    def get_repo_info(self) -> dict:
        """Get repo info from the remote."""
        return self._get("")

    def health(self) -> dict:
        """Check server health."""
        url = f"{self.base}/health"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
