"""Core API: home stats, import, sessions, jobs (docs/api.md "Core")."""

import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException

from hindcast.adapters.claude_code import KNOWN_RECORD_TYPES
from hindcast.adapters.importer import import_all
from hindcast.jobs import submit
from hindcast.store.schema import core_db
from hindcast.types import JsonObject, JsonValue

router = APIRouter(prefix="/api")


_SUMMARY_SQL = """
SELECT t.trajectory_id, t.session_id, t.agent_name, t.project_path, t.model_name,
  t.started_at, t.ended_at, t.total_steps, t.total_prompt_tokens, t.total_completion_tokens,
  t.total_cost_usd,
  (SELECT COUNT(*) FROM tool_calls c WHERE c.trajectory_id = t.trajectory_id AND c.is_error = 1)
    AS n_errors,
  (SELECT COUNT(*) FROM trajectories k WHERE k.parent_trajectory_id = t.trajectory_id)
    AS n_subagents,
  COALESCE((SELECT substr(s.message, 1, 300) FROM steps s WHERE s.trajectory_id = t.trajectory_id
    AND s.source = 'user' ORDER BY s.step_id LIMIT 1), '') AS first_prompt
FROM trajectories t
"""


def _friction(conn: sqlite3.Connection, ids: list[str]) -> dict[str, float]:
    if not ids:
        return {}
    try:
        marks = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT trajectory_id, MAX(friction_score) FROM episodes"
            f" WHERE trajectory_id IN ({marks}) GROUP BY trajectory_id",
            ids,
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(r[0]): float(r[1]) for r in rows if r[1] is not None}


def _summaries(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[JsonObject]:
    items: list[JsonObject] = []
    for r in rows:
        d: JsonObject = dict(zip(r.keys(), r, strict=True))
        items.append(d)
    fr = _friction(conn, [str(d["trajectory_id"]) for d in items])
    for d in items:
        d["friction_score"] = fr.get(str(d["trajectory_id"]))
    return items


@router.get("/home")
def home() -> JsonObject:
    with core_db() as conn:
        one = conn.execute(
            "SELECT COUNT(DISTINCT session_id), COUNT(*), COUNT(DISTINCT project_path),"
            " MIN(started_at), MAX(ended_at), SUM(total_steps) FROM trajectories"
        ).fetchone()
        harn = conn.execute(
            "SELECT agent_name, COUNT(*) FROM trajectories"
            " WHERE parent_trajectory_id IS NULL GROUP BY agent_name"
        ).fetchall()
        unknown: dict[str, JsonValue] = {}
        for r in conn.execute("SELECT agent_name, record_type, n FROM raw_record_counts"):
            name, rtype, n = str(r[0]), str(r[1]), int(r[2])
            base = rtype.split("/")[0]
            if name == "claude-code" and base not in KNOWN_RECORD_TYPES:
                prev = unknown.get(name, 0)
                unknown[name] = (prev if isinstance(prev, int) else 0) + n
    first_at, last_at = one[3], one[4]
    weeks = 0
    if first_at and last_at:
        from datetime import datetime

        a = datetime.fromisoformat(str(first_at).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(last_at).replace("Z", "+00:00"))
        weeks = max(1, (b - a).days // 7 + 1)
    return {
        "sessions": int(one[0] or 0),
        "trajectories": int(one[1] or 0),
        "steps": int(one[5] or 0),
        "harnesses": {str(r[0]): int(r[1]) for r in harn},
        "projects": int(one[2] or 0),
        "first_at": first_at,
        "last_at": last_at,
        "weeks": weeks,
        "unknown_records": unknown,
    }


@router.post("/import")
def start_import() -> dict[str, int]:
    return {"job_id": submit("import", lambda progress: import_all(progress))}


_SORTS = {
    "started_at": "t.started_at DESC",
    "cost": "t.total_cost_usd DESC",
    "steps": "t.total_steps DESC",
}


@router.get("/sessions")
def sessions(
    q: str = "",
    harness: str = "",
    project: str = "",
    sort: Literal["started_at", "cost", "steps", "friction"] = "started_at",
    limit: int = 50,
    offset: int = 0,
) -> JsonObject:
    where = ["t.parent_trajectory_id IS NULL"]
    args: list[str | int] = []
    if harness:
        where.append("t.agent_name = ?")
        args.append(harness)
    if project:
        where.append("t.project_path LIKE ?")
        args.append(f"%{project}%")
    if q:
        where.append(
            "t.trajectory_id IN (SELECT trajectory_id FROM steps_fts WHERE steps_fts MATCH ?)"
        )
        args.append('"' + q.replace('"', '""') + '"')
    clause = " WHERE " + " AND ".join(where)
    order = _SORTS.get(sort, "t.started_at DESC")
    if sort == "friction":
        order = (
            "(SELECT MAX(friction_score) FROM episodes e WHERE e.trajectory_id = t.trajectory_id)"
            " DESC"
        )
    limit = max(1, min(limit, 500))
    with core_db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM trajectories t{clause}", args).fetchone()[0]
        try:
            rows = conn.execute(
                f"{_SUMMARY_SQL}{clause} ORDER BY {order} NULLS LAST LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                f"{_SUMMARY_SQL}{clause} ORDER BY t.started_at DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        items = _summaries(conn, rows)
    return {"total": int(total), "items": list(items)}


@router.get("/sessions/{trajectory_id}")
def session_detail(trajectory_id: str) -> JsonObject:
    with core_db() as conn:
        row = conn.execute(f"{_SUMMARY_SQL} WHERE t.trajectory_id = ?", (trajectory_id,)).fetchall()
        if not row:
            raise HTTPException(404, "trajectory not found")
        summary = _summaries(conn, row)[0]
        kids = conn.execute(
            f"{_SUMMARY_SQL} WHERE t.parent_trajectory_id = ? ORDER BY t.started_at",
            (trajectory_id,),
        ).fetchall()
        sub_by_call: dict[str, str] = {}
        for r in conn.execute(
            "SELECT trajectory_id, parent_tool_call_id FROM trajectories"
            " WHERE parent_trajectory_id = ?",
            (trajectory_id,),
        ):
            if r[1]:
                sub_by_call[str(r[1])] = str(r[0])
        calls: dict[int, list[JsonObject]] = {}
        for c in conn.execute(
            "SELECT step_id, tool_call_id, function_name, arguments, content, is_error,"
            " error_class, duration_ms, extra FROM tool_calls WHERE trajectory_id = ?"
            " ORDER BY rowid",
            (trajectory_id,),
        ):
            sub = sub_by_call.get(str(c["tool_call_id"]))
            if sub is None and c["extra"]:
                ex = json.loads(c["extra"])
                if isinstance(ex, dict) and isinstance(ex.get("agent_id"), str):
                    sub = f"{trajectory_id}:{ex['agent_id']}"
            calls.setdefault(int(c["step_id"]), []).append(
                {
                    "tool_call_id": c["tool_call_id"],
                    "function_name": c["function_name"],
                    "arguments": c["arguments"],
                    "content": c["content"] or "",
                    "is_error": bool(c["is_error"]),
                    "error_class": c["error_class"],
                    "duration_ms": c["duration_ms"],
                    "subagent_trajectory_id": sub,
                }
            )
        steps: list[JsonValue] = []
        for s in conn.execute(
            "SELECT * FROM steps WHERE trajectory_id = ? ORDER BY step_id", (trajectory_id,)
        ):
            extra = json.loads(s["extra"]) if s["extra"] else {}
            kind = extra.get("claude_kind") or extra.get("codex_kind")
            steps.append(
                {
                    "step_id": s["step_id"],
                    "timestamp": s["timestamp"],
                    "source": s["source"],
                    "message": s["message"],
                    "reasoning_content": s["reasoning_content"],
                    "model_name": s["model_name"],
                    "prompt_tokens": s["prompt_tokens"],
                    "completion_tokens": s["completion_tokens"],
                    "cost_usd": s["cost_usd"],
                    "turn_index": s["turn_index"],
                    "kind": kind if isinstance(kind, str) else None,
                    "tool_calls": list(calls.get(int(s["step_id"]), [])),
                }
            )
        subagents = _summaries(conn, kids)
    return {"summary": summary, "steps": steps, "subagents": list(subagents)}


def _job(r: sqlite3.Row) -> JsonObject:
    return {
        "id": r["id"],
        "kind": r["kind"],
        "status": r["status"],
        "progress": r["progress"],
        "result": json.loads(r["result"]) if r["result"] else None,
        "error": r["error"],
        "created_at": r["created_at"],
        "finished_at": r["finished_at"],
    }


@router.get("/jobs")
def list_jobs() -> list[JsonObject]:
    with core_db() as conn:
        return [_job(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 20")]


@router.get("/jobs/{job_id}")
def get_job(job_id: int) -> JsonObject:
    with core_db() as conn:
        r = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "job not found")
    return _job(r)
