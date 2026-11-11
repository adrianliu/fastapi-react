"""Import native session files into the core tables (spec 3.1/3.2).

Unchanged files (same size and first-4KB hash) are skipped. Each file is one transaction.
"""

import gzip
import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from hindcast.adapters import claude_code, codex
from hindcast.adapters.common import TrajectoryRow
from hindcast.config import (
    claude_projects_dir,
    codex_home,
    llm_cwd,
    session_hub_archive,
)
from hindcast.store.schema import connect, ensure_core_schema
from hindcast.types import JsonObject

PARSER_VERSION = f"{claude_code.PARSER_VERSION}+{codex.PARSER_VERSION}"


def _slug(path: Path) -> str:
    return str(path).replace("/", "-").replace(".", "-")


def discover() -> list[Path]:
    files: list[Path] = []
    arch = session_hub_archive()
    if arch.is_dir():
        files.extend(sorted(arch.glob("*.jsonl.gz")))
    cx = codex_home() / "sessions"
    if cx.is_dir():
        files.extend(sorted(cx.rglob("rollout-*.jsonl")))
    projects = claude_projects_dir()
    skip = _slug(llm_cwd())
    if projects.is_dir():
        for proj in sorted(projects.iterdir()):
            if not proj.is_dir() or proj.name == skip:
                continue
            files.extend(sorted(proj.glob("*.jsonl")))
            files.extend(sorted(proj.glob("*/subagents/agent-*.jsonl")))
    return files


def _read_lines(path: Path) -> Iterator[str]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            yield from fh
    else:
        with path.open(encoding="utf-8", errors="replace") as fh:
            yield from fh


def _prefix_hash(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.sha256(fh.read(4096)).hexdigest()


def parse_file(path: Path) -> TrajectoryRow | None:
    lines = list(_read_lines(path))
    head = lines[0] if lines else ""
    if '"session_meta"' in head or ('"payload"' in head and '"sessionId"' not in head):
        return codex.parse_codex_lines(lines, path.name.split(".")[0])
    if path.parent.name == "subagents":
        session_id = path.parent.parent.name
        agent_id = path.stem.removeprefix("agent-")
        parent_call: str | None = None
        meta = path.with_suffix(".meta.json")
        if meta.exists():
            try:
                m = json.loads(meta.read_text())
                if isinstance(m, dict) and isinstance(m.get("toolUseId"), str):
                    parent_call = m["toolUseId"]
            except (OSError, json.JSONDecodeError):
                pass
        return claude_code.parse_claude_lines(
            lines,
            trajectory_id=f"{session_id}:{agent_id}",
            parent_trajectory_id=session_id,
            parent_tool_call_id=parent_call,
        )
    return claude_code.parse_claude_lines(lines)


def write_trajectory(conn: sqlite3.Connection, t: TrajectoryRow, origin_path: str) -> None:
    tid = t.trajectory_id
    conn.execute("DELETE FROM steps WHERE trajectory_id = ?", (tid,))
    conn.execute("DELETE FROM tool_calls WHERE trajectory_id = ?", (tid,))
    conn.execute("DELETE FROM steps_fts WHERE trajectory_id = ?", (tid,))
    conn.execute("DELETE FROM trajectories WHERE trajectory_id = ?", (tid,))
    stamps = [s.timestamp for s in t.steps if s.timestamp]
    extra: JsonObject = {**t.extra, "source_path": origin_path, "cost_source": "estimate"}
    costs = [s.cost_usd for s in t.steps if s.cost_usd is not None]
    conn.execute(
        "INSERT INTO trajectories (trajectory_id, session_id, parent_trajectory_id,"
        " parent_tool_call_id, agent_name, agent_version, model_name, origin, project_path,"
        " git_branch, started_at, ended_at, total_prompt_tokens, total_completion_tokens,"
        " total_cached_tokens, total_cost_usd, total_steps, extra)"
        " VALUES (?,?,?,?,?,?,?,'organic',?,?,?,?,?,?,?,?,?,?)",
        (
            tid,
            t.session_id,
            t.parent_trajectory_id,
            t.parent_tool_call_id,
            t.agent_name,
            t.agent_version,
            t.model_name,
            t.project_path,
            t.git_branch,
            min(stamps) if stamps else None,
            max(stamps) if stamps else None,
            sum(s.prompt_tokens or 0 for s in t.steps),
            sum(s.completion_tokens or 0 for s in t.steps),
            sum(s.cached_tokens or 0 for s in t.steps),
            sum(costs) if costs else None,
            len(t.steps),
            json.dumps(extra),
        ),
    )
    conn.executemany(
        "INSERT INTO steps (trajectory_id, step_id, timestamp, source, message,"
        " reasoning_content, model_name, prompt_tokens, completion_tokens, cached_tokens,"
        " cost_usd, stop_reason, turn_index, extra) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                tid,
                s.step_id,
                s.timestamp,
                s.source,
                s.message,
                s.reasoning_content,
                s.model_name,
                s.prompt_tokens,
                s.completion_tokens,
                s.cached_tokens,
                s.cost_usd,
                s.stop_reason,
                s.turn_index,
                json.dumps(s.extra) if s.extra else None,
            )
            for s in t.steps
        ],
    )
    conn.executemany(
        "INSERT INTO tool_calls (trajectory_id, step_id, tool_call_id, function_name, arguments,"
        " content, is_error, error_class, tool_kind, duration_ms, extra)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                tid,
                s.step_id,
                c.tool_call_id,
                c.function_name,
                c.arguments,
                c.content,
                int(c.is_error),
                c.error_class,
                c.tool_kind,
                c.duration_ms,
                json.dumps(c.extra) if c.extra else None,
            )
            for s in t.steps
            for c in s.tool_calls
        ],
    )
    conn.executemany(
        "INSERT INTO steps_fts (message, trajectory_id, step_id) VALUES (?,?,?)",
        [(s.message, tid, s.step_id) for s in t.steps if s.message and s.source != "system"],
    )
    conn.executemany(
        "INSERT INTO raw_record_counts (agent_name, record_type, n) VALUES (?,?,?)"
        " ON CONFLICT(agent_name, record_type) DO UPDATE SET n = n + excluded.n",
        [(t.agent_name, k, v) for k, v in t.record_counts.items()],
    )


def import_all(
    progress: Callable[[str], None] = lambda _m: None, files: list[Path] | None = None
) -> JsonObject:
    started = time.monotonic()
    paths = files if files is not None else discover()
    conn = connect()
    ensure_core_schema(conn)
    imported = skipped = empty = 0
    failures: list[str] = []
    try:
        for i, path in enumerate(paths):
            if i % 50 == 0:
                progress(f"{i}/{len(paths)} files")
            try:
                size = path.stat().st_size
                phash = _prefix_hash(path)
                row = conn.execute(
                    "SELECT size, prefix_hash, parser_version FROM source_files WHERE path = ?",
                    (str(path),),
                ).fetchone()
                if row and row[0] == size and row[1] == phash and row[2] == PARSER_VERSION:
                    skipped += 1
                    continue
                traj = parse_file(path)
                with conn:
                    if traj is not None:
                        write_trajectory(conn, traj, str(path))
                        imported += 1
                    else:
                        empty += 1
                    conn.execute(
                        "INSERT OR REPLACE INTO source_files"
                        " (path, size, prefix_hash, cursor, parser_version) VALUES (?,?,?,?,?)",
                        (str(path), size, phash, size, PARSER_VERSION),
                    )
            except Exception as exc:
                failures.append(f"{path}: {type(exc).__name__}: {exc}")
    finally:
        conn.close()
    seconds = round(time.monotonic() - started, 1)
    progress(f"done: {imported} imported, {skipped} unchanged, {len(failures)} failed")
    return {
        "files": len(paths),
        "imported": imported,
        "unchanged": skipped,
        "empty": empty,
        "failed": len(failures),
        "failures": list(failures[:20]),
        "seconds": seconds,
    }
