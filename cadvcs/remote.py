"""Remote configuration for local repositories.

Stores remote server URLs in .cadvcs/config.json, similar to git remotes.
Each remote has a name (default 'origin') and a server URL + repo name.

Example config:
  {"remotes": {"origin": {"url": "http://localhost:8000", "repo": "proyecto-1"}}}
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILE = "config.json"


def _config_path(vcs_dir: Path) -> Path:
    return vcs_dir / CONFIG_FILE


def _load(vcs_dir: Path) -> dict:
    path = _config_path(vcs_dir)
    if not path.exists():
        return {"remotes": {}}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"remotes": {}}


def _save(vcs_dir: Path, data: dict) -> None:
    _config_path(vcs_dir).write_text(json.dumps(data, indent=2))


def add_remote(vcs_dir: Path, name: str, url: str, repo: str) -> None:
    data = _load(vcs_dir)
    if name in data["remotes"]:
        raise ValueError(f"Remote '{name}' already exists")
    data["remotes"][name] = {"url": url.rstrip("/"), "repo": repo}
    _save(vcs_dir, data)


def remove_remote(vcs_dir: Path, name: str) -> None:
    data = _load(vcs_dir)
    if name not in data["remotes"]:
        raise ValueError(f"Remote '{name}' does not exist")
    del data["remotes"][name]
    _save(vcs_dir, data)


def get_remote(vcs_dir: Path, name: str = "origin") -> dict | None:
    data = _load(vcs_dir)
    return data["remotes"].get(name)


def list_remotes(vcs_dir: Path) -> dict[str, dict]:
    return _load(vcs_dir).get("remotes", {})


def set_remote_url(vcs_dir: Path, name: str, url: str) -> None:
    data = _load(vcs_dir)
    if name not in data["remotes"]:
        raise ValueError(f"Remote '{name}' does not exist")
    data["remotes"][name]["url"] = url.rstrip("/")
    _save(vcs_dir, data)
