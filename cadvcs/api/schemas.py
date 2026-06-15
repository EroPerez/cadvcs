"""Schemas Pydantic de la API REST."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RepoCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
                      description="slug del repositorio")


class RepoInfo(BaseModel):
    name: str
    current_branch: str
    head_commit_id: int | None


class CommitRequest(BaseModel):
    message: str = ""


class CommitInfo(BaseModel):
    commit_id: int
    branch: str
    files: int
    changed: list[str]


class CommitLogEntry(BaseModel):
    id: int
    parent_id: int | None
    parent2_id: int | None
    author: str
    message: str
    created_at: str
    is_merge: bool
    branches: list[str]
    tags: list[str]


class StatusResponse(BaseModel):
    branch: str
    new: list[str]
    modified: list[str]
    deleted: list[str]
    clean: list[str]


class BranchCreate(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,63}$")


class BranchInfo(BaseModel):
    name: str
    head_commit_id: int | None
    current: bool


class SwitchRequest(BaseModel):
    branch: str
    force: bool = False


class TagCreate(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
    ref: str = "HEAD"


class TagInfo(BaseModel):
    name: str
    commit_id: int


class MergeRequest(BaseModel):
    branch: str
    message: str | None = None


class MergeResolveRequest(BaseModel):
    branch: str
    message: str | None = None
    resolutions: dict[str, dict[str, str]] = Field(
        description="repo_path → {handle: 'ours'|'theirs'}; "
                    "clave '__file__' para binarios divergentes completos")


class CherryPickRequest(BaseModel):
    ref: str
    message: str | None = None
    resolutions: dict[str, dict[str, str]] = {}


class MergeResponse(BaseModel):
    result: str                      # merged | fast-forward | already-up-to-date
    commit_id: int | None = None
    details: dict[str, str] | None = None
    author: str | None = None


class EntityConflict(BaseModel):
    handle: str
    dxftype: str
    reason: str                      # modify/modify | modify/delete | add/add
    ours: dict | None
    theirs: dict | None


class MergeConflictResponse(BaseModel):
    detail: str
    conflicts: dict[str, list[EntityConflict] | str]  # 'binary' para no-DXF


class LockRequest(BaseModel):
    path: str


class LockInfo(BaseModel):
    path: str
    owner: str
    expires_at: str


class BlameEntry(BaseModel):
    handle: str
    dxftype: str
    layer: str
    commit_id: int | None = None
    author: str | None = None
    message: str | None = None


class StageRequest(BaseModel):
    sha256: str = Field(min_length=64, max_length=64)
    size: int = Field(ge=0)


class UploadResponse(BaseModel):
    path: str
    sha256: str
    size: int
    tracked: bool
