"""Friction and fixes API (docs/api.md, "Friction and fixes")."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hindcast import fix_drafts, friction
from hindcast.jobs import submit
from hindcast.store.schema import core_db
from hindcast.types import JsonObject, JsonValue

router = APIRouter(prefix="/api")


def ensure_schema(conn: sqlite3.Connection) -> None:
    fix_drafts.ensure_fix_schema(conn)


class JobRef(BaseModel):
    job_id: int


class DraftIn(BaseModel):
    group_id: int
    fix_type: Literal["rule", "skill"] = "rule"


class EditIn(BaseModel):
    content: str


class InstallIn(BaseModel):
    target: str = fix_drafts.DEFAULT_TARGET
    confirm: bool = False


class PreviewOut(BaseModel):
    target: str
    diff: str


class InstallOut(BaseModel):
    target: str
    applied: bool


def _build_job(progress: Callable[[str], None]) -> JsonObject:
    # Progress writes to the jobs table, so report outside the write transaction.
    progress("rule pass and grouping")
    with core_db() as conn:
        ensure_schema(conn)
        counts = friction.build_groups(conn)
    return dict(counts.items())


@router.post("/groups/build")
def build_groups() -> JobRef:
    return JobRef(job_id=submit("groups_build", _build_job))


@router.get("/groups")
def list_groups() -> list[dict[str, JsonValue]]:
    with core_db() as conn:
        ensure_schema(conn)
        return friction.list_groups(conn)


@router.get("/groups/{group_id}")
def get_group(group_id: int) -> dict[str, JsonValue]:
    with core_db() as conn:
        ensure_schema(conn)
        g = friction.get_group(conn, group_id)
    if g is None:
        raise HTTPException(404, "group not found")
    return g


@router.post("/fixes/draft")
def draft_fix(body: DraftIn) -> JobRef:
    with core_db() as conn:
        ensure_schema(conn)
        if friction.get_group(conn, body.group_id) is None:
            raise HTTPException(404, "group not found")

    def job(progress: Callable[[str], None]) -> JsonObject:
        progress(f"drafting {body.fix_type} with claude -p")
        with core_db() as conn:
            fix_id = fix_drafts.draft_fix(conn, body.group_id, fix_type=body.fix_type)
        return {"fix_id": fix_id}

    return JobRef(job_id=submit("fix_draft", job))


@router.get("/fixes")
def list_fixes() -> list[dict[str, JsonValue]]:
    with core_db() as conn:
        return fix_drafts.list_fixes(conn)


def _fix_or_404(conn: sqlite3.Connection, fix_id: int) -> dict[str, JsonValue]:
    f = fix_drafts.get_fix(conn, fix_id)
    if f is None:
        raise HTTPException(404, "fix not found")
    return f


@router.get("/fixes/{fix_id}")
def get_fix(fix_id: int) -> dict[str, JsonValue]:
    with core_db() as conn:
        return _fix_or_404(conn, fix_id)


@router.put("/fixes/{fix_id}")
def edit_fix(fix_id: int, body: EditIn) -> dict[str, JsonValue]:
    with core_db() as conn:
        _fix_or_404(conn, fix_id)
        try:
            fix_drafts.add_version(conn, fix_id, body.content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return _fix_or_404(conn, fix_id)


def _rule(fix_id: int) -> str:
    with core_db() as conn:
        _fix_or_404(conn, fix_id)
        content = fix_drafts.latest_content(conn, fix_id)
    if content is None:
        raise HTTPException(404, "fix has no versions")
    return content


def _check_target(target: str) -> str:
    if not Path(target).expanduser().name.endswith(".md"):
        raise HTTPException(422, "target must be a markdown file")
    return target


@router.get("/fixes/{fix_id}/install-preview")
def install_preview(fix_id: int, target: str = fix_drafts.DEFAULT_TARGET) -> PreviewOut:
    rule = _rule(fix_id)
    return PreviewOut(target=target, diff=fix_drafts.install_preview(_check_target(target), rule))


@router.post("/fixes/{fix_id}/install")
def install(fix_id: int, body: InstallIn) -> InstallOut:
    rule = _rule(fix_id)
    target = _check_target(body.target)
    if not body.confirm:
        return InstallOut(target=target, applied=False)
    fix_drafts.install(target, rule)
    return InstallOut(target=target, applied=True)
