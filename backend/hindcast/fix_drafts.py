"""Fix drafts (spec 5.2): draft a CLAUDE.md rule from a group's corrections, edit, install.

(Named `fix_drafts` because `hindcast/fixes/` already exists as a package.)
"""

import difflib
import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel, Field

from hindcast.friction import ensure_friction_schema, get_group
from hindcast.llm.runner import LLMError, run_structured
from hindcast.store.db import utc_now
from hindcast.types import JsonValue

MAX_RULE_LINES = 15
MAX_EVIDENCE = 12
DEFAULT_TARGET = "~/.claude/CLAUDE.md"
PROMPT_VERSION = "fix-rule-1"


class RuleBody(BaseModel):
    text: str = Field(description="The rule text, markdown, at most 15 lines.")


class RationaleItem(BaseModel):
    instruction: str
    correction_ids: list[int]


class RuleFixDraft(BaseModel):
    """Schema A3 restricted to fix_type = rule."""

    name: str
    summary: str
    rule: RuleBody
    rationale: list[RationaleItem]


SCHEMA = """
CREATE TABLE IF NOT EXISTS ff_fixes (
  id             INTEGER PRIMARY KEY,
  group_id       INTEGER NOT NULL,
  fix_type       TEXT NOT NULL DEFAULT 'rule',
  name           TEXT NOT NULL,
  summary        TEXT NOT NULL,
  rationale_json TEXT NOT NULL,
  created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ff_fix_versions (
  fix_id     INTEGER NOT NULL REFERENCES ff_fixes(id) ON DELETE CASCADE,
  version    INTEGER NOT NULL,
  content    TEXT NOT NULL,
  author     TEXT NOT NULL CHECK (author IN ('model', 'user')),
  model      TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (fix_id, version)
);
CREATE TABLE IF NOT EXISTS ff_fix_sources (
  fix_id        INTEGER NOT NULL REFERENCES ff_fixes(id) ON DELETE CASCADE,
  correction_id INTEGER NOT NULL,
  PRIMARY KEY (fix_id, correction_id)
);
"""


def ensure_fix_schema(conn: sqlite3.Connection) -> None:
    ensure_friction_schema(conn)
    conn.executescript(SCHEMA)


def validate_rule(content: str) -> str:
    text = content.strip()
    if not text:
        raise ValueError("rule is empty")
    if len(text.splitlines()) > MAX_RULE_LINES:
        raise ValueError(f"rule has more than {MAX_RULE_LINES} lines")
    return text


def build_prompt(group: dict[str, JsonValue]) -> tuple[str, list[int]]:
    items = group.get("items")
    evidence = items[:MAX_EVIDENCE] if isinstance(items, list) else []
    lines = [
        "You write one short rule for a coding agent's CLAUDE.md file.",
        "The user corrected the agent repeatedly in the same way. Each correction below shows",
        "what the agent said just before, then the user's reaction.",
        f"Theme: {group.get('name')}. Lesson so far: {group.get('lesson')}",
        "",
    ]
    ids: list[int] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        cid = item.get("id")
        if isinstance(cid, int):
            ids.append(cid)
        lines.append(f"[correction {cid}]")
        lines.append(f"Agent before: {item.get('agent_before')}")
        lines.append(f"User: {item.get('quote')}")
        lines.append("")
    lines += [
        f"Write rule.text as imperative instructions, at most {MAX_RULE_LINES} lines, general",
        "enough to apply in any project, specific enough to change behaviour. No project names.",
        "In rationale, map each instruction to the correction ids that motivate it.",
        "name: a short kebab-case name. summary: one sentence.",
    ]
    return "\n".join(lines), ids


def draft_fix(conn: sqlite3.Connection, group_id: int, job_id: int | None = None) -> int:
    """Call `claude -p` (opus, then sonnet) and store a new rule fix. Raises on failure."""
    ensure_fix_schema(conn)
    group = get_group(conn, group_id)
    if group is None:
        raise ValueError(f"group {group_id} not found")
    prompt, ids = build_prompt(group)
    errors: list[str] = []
    for llm_model in ("opus", "sonnet"):
        try:
            result = run_structured(
                prompt,
                RuleFixDraft,
                llm_model=llm_model,
                purpose="distill",
                prompt_version=PROMPT_VERSION,
                job_id=job_id,
            )
        except LLMError as exc:
            errors.append(f"{llm_model}: {exc}")
            continue
        draft = result.value
        content = draft.rule.text.strip()
        lines = content.splitlines()
        if len(lines) > MAX_RULE_LINES:
            content = "\n".join(lines[:MAX_RULE_LINES])
        now = utc_now()
        cur = conn.execute(
            "INSERT INTO ff_fixes (group_id, fix_type, name, summary, rationale_json, created_at) "
            "VALUES (?, 'rule', ?, ?, ?, ?)",
            (
                group_id,
                draft.name,
                draft.summary,
                json.dumps([r.model_dump() for r in draft.rationale]),
                now,
            ),
        )
        fix_id = cur.lastrowid
        assert fix_id is not None
        conn.execute(
            "INSERT INTO ff_fix_versions (fix_id, version, content, author, model, created_at) "
            "VALUES (?, 1, ?, 'model', ?, ?)",
            (fix_id, content, result.model_used or llm_model, now),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO ff_fix_sources (fix_id, correction_id) VALUES (?, ?)",
            [(fix_id, i) for i in ids],
        )
        return fix_id
    raise RuntimeError("claude -p failed: " + "; ".join(errors))


def fix_dict(conn: sqlite3.Connection, f: sqlite3.Row) -> dict[str, JsonValue]:
    versions: list[JsonValue] = [
        {
            "version": int(v["version"]),
            "content": str(v["content"]),
            "author": str(v["author"]),
            "model": v["model"],
            "created_at": str(v["created_at"]),
        }
        for v in conn.execute(
            "SELECT * FROM ff_fix_versions WHERE fix_id = ? ORDER BY version", (f["id"],)
        )
    ]
    rationale: JsonValue = json.loads(str(f["rationale_json"]))
    return {
        "id": int(f["id"]),
        "group_id": int(f["group_id"]),
        "fix_type": str(f["fix_type"]),
        "name": str(f["name"]),
        "summary": str(f["summary"]),
        "versions": versions,
        "rationale": rationale,
    }


def list_fixes(conn: sqlite3.Connection) -> list[dict[str, JsonValue]]:
    ensure_fix_schema(conn)
    return [fix_dict(conn, f) for f in conn.execute("SELECT * FROM ff_fixes ORDER BY id DESC")]


def get_fix(conn: sqlite3.Connection, fix_id: int) -> dict[str, JsonValue] | None:
    ensure_fix_schema(conn)
    f = conn.execute("SELECT * FROM ff_fixes WHERE id = ?", (fix_id,)).fetchone()
    return fix_dict(conn, f) if f else None


def add_version(conn: sqlite3.Connection, fix_id: int, content: str) -> None:
    text = validate_rule(content)
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS v FROM ff_fix_versions WHERE fix_id = ?", (fix_id,)
    ).fetchone()
    conn.execute(
        "INSERT INTO ff_fix_versions (fix_id, version, content, author, model, created_at) "
        "VALUES (?, ?, ?, 'user', NULL, ?)",
        (fix_id, int(row["v"]) + 1, text, utc_now()),
    )


def latest_content(conn: sqlite3.Connection, fix_id: int) -> str | None:
    row = conn.execute(
        "SELECT content FROM ff_fix_versions WHERE fix_id = ? ORDER BY version DESC LIMIT 1",
        (fix_id,),
    ).fetchone()
    return str(row["content"]) if row else None


def appended(current: str, rule: str) -> str:
    sep = (
        ""
        if not current or current.endswith("\n\n")
        else ("\n" if current.endswith("\n") else "\n\n")
    )
    return current + sep + rule.rstrip("\n") + "\n"


def install_preview(target: str, rule: str) -> str:
    path = Path(target).expanduser()
    current = path.read_text() if path.exists() else ""
    new = appended(current, rule)
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=target,
            tofile=target,
        )
    )


def install(target: str, rule: str) -> None:
    path = Path(target).expanduser()
    current = path.read_text() if path.exists() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(appended(current, rule))
