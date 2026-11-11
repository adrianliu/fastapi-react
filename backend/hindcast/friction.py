"""Rule pass over human reactions (spec 4.2, simplified) and theme grouping (spec 5.1, MVP).

Every human user step that opens a turn after the first is a reaction to the previous turn.
Reactions with friction signals become corrections; corrections are grouped into themes by
keyword families. No LLM is used here.
"""

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

from hindcast.types import JsonValue

Progress = Callable[[str], None]

QUOTE_CHARS = 400
AGENT_CHARS = 400
MIN_SESSIONS = 3

CORRECTION_RE = re.compile(
    r"(^\s*no\b[,.!]?|\bdon'?t\b|\bdo not\b|\bi said\b|\bwhy did you\b|\bstop\b|\bnever\b|"
    r"\bagain\b|\bnot what i\b|\binstead\b|\bwrong\b|\bundo\b|\brevert\b)",
    re.IGNORECASE,
)
DONE_RE = re.compile(
    r"\b(done|fixed|works|working|complete[d]?|all set|passes|passing|resolved)\b", re.IGNORECASE
)
ACCEPT_RE = re.compile(
    r"^\s*(thanks|thank you|great|perfect|nice|lgtm|looks good|awesome|ok(ay)?|cool|good)\b",
    re.IGNORECASE,
)
REJECT_CLASSES = {"user_rejected", "hook_denied"}

KEEP_IT_SIMPLE = "keep-it-simple"


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    lesson: str
    pattern: re.Pattern[str]


THEMES: list[Theme] = [
    Theme(
        KEEP_IT_SIMPLE,
        "Keep it simple",
        "Do the simplest thing that solves the request; do not add flags, config, fallbacks, "
        "backfills or abstractions nobody asked for.",
        re.compile(
            r"(over[- ]?engineer|overkill|too complex|too complicated|\bsimpl(e|est|er|ify)\b|"
            r"keep it simple|no need for (a |an )?(flag|config|backfill|canary|fallback|"
            r"abstraction|wrapper|option)|\byagni\b|\bunnecessary\b|\bjust do\b|"
            r"\bjust use\b|don'?t need (a |an )?(flag|config|backfill|fallback|abstraction))",
            re.IGNORECASE,
        ),
    ),
    Theme(
        "verify-before-done",
        "Verify before claiming done",
        "Run the change and check the result yourself before saying it is done or fixed.",
        re.compile(
            r"(still (doesn'?t|not|broken|failing|fails|wrong|the same|see)|doesn'?t work|"
            r"didn'?t work|not working|did you (test|check|run|verify)|still (an )?error|"
            r"nothing changed|same (error|issue|problem))",
            re.IGNORECASE,
        ),
    ),
    Theme(
        "follow-instructions",
        "Follow the instruction as given",
        "Re-read the user's instruction and do exactly what it says before doing anything else.",
        re.compile(
            r"(\bi said\b|\bi told you\b|\bi asked\b|not what i (asked|wanted|said|meant)|"
            r"\bread (the|my)\b|\bas i said\b|\bi already\b)",
            re.IGNORECASE,
        ),
    ),
    Theme(
        "scope-creep",
        "Stay inside the requested scope",
        "Change only what was asked; do not edit unrelated files or behaviour without asking.",
        re.compile(
            r"(\bdon'?t (touch|change|modify|edit|delete|remove)\b|\bonly (change|touch|edit)\b|"
            r"\bwhy did you (change|delete|remove|add|touch|modify)\b|\bundo\b|\brevert\b|"
            r"\bleave .{0,20} alone\b|\bunrelated\b)",
            re.IGNORECASE,
        ),
    ),
    Theme(
        "ask-dont-guess",
        "Ask instead of guessing",
        "When the request is ambiguous or a choice is costly, ask one short question first.",
        re.compile(
            r"(\bask me\b|\bwhy did you\b|\bwho told you\b|\bdon'?t assume\b|\bguess(ing|ed)?\b|"
            r"\bmade (that|it) up\b|\bhallucinat)",
            re.IGNORECASE,
        ),
    ),
    Theme(
        "stop-and-wait",
        "Stop when told to stop",
        "When the user says stop or wait, stop acting and answer before doing more work.",
        re.compile(r"(\bstop\b|\bwait\b|\bhold on\b|\bpause\b|\bdon'?t do\b)", re.IGNORECASE),
    ),
]

THEMES_BY_KEY = {t.key: t for t in THEMES}

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
    r"(?i:(api[_-]?key|token|secret|password)\s*[:=]\s*)\S+)"
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def redact(text: str) -> str:
    text = _SECRET_RE.sub("[REDACTED]", text)
    return _EMAIL_RE.sub("[EMAIL]", text)


def trim(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def message_text(message: str) -> str:
    """Plain text of a step message; content-part arrays keep only their text parts."""
    if not message.lstrip().startswith("[{"):
        return message
    try:
        parts: JsonValue = json.loads(message)
    except json.JSONDecodeError:
        return message
    out: list[str] = []
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "text":
                t = part.get("text")
                if isinstance(t, str):
                    out.append(t)
    return "\n".join(out)


def is_human(text: str) -> bool:
    s = text.strip()
    if not s:
        return False
    noise = (
        "<",
        "[Request interrupted",
        "Caveat:",
        "This session is being continued",
        "New comment on",
    )
    return not s.startswith(noise)


SCHEMA = """
CREATE TABLE IF NOT EXISTS ff_corrections (
  id            INTEGER PRIMARY KEY,
  trajectory_id TEXT NOT NULL,
  session_id    TEXT NOT NULL,
  step_id       INTEGER NOT NULL,
  project_path  TEXT,
  timestamp     TEXT,
  quote         TEXT NOT NULL,
  agent_before  TEXT NOT NULL,
  signals_json  TEXT NOT NULL,
  UNIQUE (trajectory_id, step_id)
);
CREATE TABLE IF NOT EXISTS ff_groups (
  id        INTEGER PRIMARY KEY,
  theme     TEXT NOT NULL UNIQUE,
  name      TEXT NOT NULL,
  lesson    TEXT NOT NULL,
  sessions  INTEGER NOT NULL,
  projects  INTEGER NOT NULL,
  score     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ff_group_members (
  group_id      INTEGER NOT NULL REFERENCES ff_groups(id) ON DELETE CASCADE,
  correction_id INTEGER NOT NULL REFERENCES ff_corrections(id) ON DELETE CASCADE,
  PRIMARY KEY (group_id, correction_id)
);
"""


def ensure_friction_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


@dataclass
class Turn:
    index: int
    agent_last: str = ""
    tool_errors: int = 0
    rejections: int = 0
    human: list[tuple[int, str, str | None]] = field(default_factory=list)


def score_reaction(reaction: str, prev: Turn) -> dict[str, float]:
    signals: dict[str, float] = {}
    if CORRECTION_RE.search(reaction):
        signals["correction"] = 1.0
    accepted = bool(ACCEPT_RE.search(reaction))
    if DONE_RE.search(prev.agent_last) and not accepted:
        signals["reopened"] = 1.0
    if prev.tool_errors:
        signals["tool_errors"] = round(0.3 * min(prev.tool_errors, 10), 2)
    if prev.rejections:
        signals["rejections"] = float(prev.rejections)
    return signals


def _turns(conn: sqlite3.Connection, trajectory_id: str) -> list[Turn]:
    turns: dict[int, Turn] = {}
    errors: dict[int, tuple[int, int]] = {}
    for r in conn.execute(
        "SELECT step_id, SUM(is_error) AS e, "
        "SUM(CASE WHEN error_class IN ('user_rejected','hook_denied') THEN 1 ELSE 0 END) AS rj "
        "FROM tool_calls WHERE trajectory_id = ? GROUP BY step_id",
        (trajectory_id,),
    ):
        errors[int(r["step_id"])] = (int(r["e"] or 0), int(r["rj"] or 0))
    for r in conn.execute(
        "SELECT step_id, timestamp, source, message, turn_index FROM steps "
        "WHERE trajectory_id = ? ORDER BY step_id",
        (trajectory_id,),
    ):
        ti = int(r["turn_index"])
        turn = turns.setdefault(ti, Turn(ti))
        text = message_text(str(r["message"]))
        if r["source"] == "agent":
            if text.strip():
                turn.agent_last = text
            e, rj = errors.get(int(r["step_id"]), (0, 0))
            turn.tool_errors += e
            turn.rejections += rj
        elif r["source"] == "user" and is_human(text):
            turn.human.append((int(r["step_id"]), text, r["timestamp"]))
    return [turns[k] for k in sorted(turns)]


def rule_pass(conn: sqlite3.Connection, progress: Progress | None = None) -> int:
    """Score every reaction in every root trajectory; store those with signals. Returns count."""
    ensure_friction_schema(conn)
    conn.execute("DELETE FROM ff_corrections")
    roots = conn.execute(
        "SELECT trajectory_id, session_id, project_path FROM trajectories "
        "WHERE parent_trajectory_id IS NULL AND COALESCE(origin, 'organic') = 'organic'"
    ).fetchall()
    n = 0
    for i, root in enumerate(roots):
        if progress and i % 50 == 0:
            progress(f"rule pass {i}/{len(roots)}")
        turns = _turns(conn, str(root["trajectory_id"]))
        prev: Turn | None = None
        for turn in turns:
            if prev is not None and turn.human and turn.index > 0:
                step_id, text, ts = turn.human[0]
                signals = score_reaction(text, prev)
                if signals:
                    conn.execute(
                        "INSERT OR IGNORE INTO ff_corrections (trajectory_id, session_id, step_id, "
                        "project_path, timestamp, quote, agent_before, signals_json) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (
                            root["trajectory_id"],
                            root["session_id"],
                            step_id,
                            root["project_path"],
                            ts,
                            trim(redact(text), QUOTE_CHARS),
                            trim(redact(prev.agent_last), AGENT_CHARS),
                            json.dumps(signals),
                        ),
                    )
                    n += 1
            prev = turn
    return n


def build_groups(conn: sqlite3.Connection, progress: Progress | None = None) -> dict[str, int]:
    """Run the rule pass, then group corrections into themes. Returns counts for the job result."""
    n = rule_pass(conn, progress)
    conn.execute("DELETE FROM ff_group_members")
    conn.execute("DELETE FROM ff_groups")
    rows = conn.execute("SELECT id, session_id, project_path, quote FROM ff_corrections").fetchall()
    shown = 0
    for theme in THEMES:
        members = [r for r in rows if theme.pattern.search(str(r["quote"]))]
        sessions = len({r["session_id"] for r in members})
        projects = len({r["project_path"] for r in members if r["project_path"]}) or 1
        if sessions < MIN_SESSIONS:
            continue
        cur = conn.execute(
            "INSERT INTO ff_groups (theme, name, lesson, sessions, projects, score) "
            "VALUES (?,?,?,?,?,?)",
            (theme.key, theme.name, theme.lesson, sessions, projects, sessions * projects),
        )
        gid = cur.lastrowid
        conn.executemany(
            "INSERT INTO ff_group_members (group_id, correction_id) VALUES (?,?)",
            [(gid, r["id"]) for r in members],
        )
        shown += 1
    if progress:
        progress("groups built")
    return {"corrections": n, "groups": shown}


def correction_dict(r: sqlite3.Row) -> dict[str, JsonValue]:
    signals: JsonValue = json.loads(str(r["signals_json"]))
    return {
        "id": int(r["id"]),
        "trajectory_id": str(r["trajectory_id"]),
        "step_id": int(r["step_id"]),
        "project_path": r["project_path"],
        "timestamp": r["timestamp"],
        "quote": str(r["quote"]),
        "agent_before": str(r["agent_before"]),
        "signals": signals,
    }


def group_dict(conn: sqlite3.Connection, g: sqlite3.Row) -> dict[str, JsonValue]:
    items = [
        correction_dict(r)
        for r in conn.execute(
            "SELECT c.* FROM ff_corrections c JOIN ff_group_members m ON m.correction_id = c.id "
            "WHERE m.group_id = ? ORDER BY c.timestamp DESC",
            (g["id"],),
        )
    ]
    return {
        "id": int(g["id"]),
        "name": str(g["name"]),
        "lesson": str(g["lesson"]),
        "n_items": len(items),
        "sessions": int(g["sessions"]),
        "projects": int(g["projects"]),
        "score": int(g["score"]),
        "items": list[JsonValue](items),
    }


def list_groups(conn: sqlite3.Connection) -> list[dict[str, JsonValue]]:
    ensure_friction_schema(conn)
    gs = conn.execute("SELECT * FROM ff_groups ORDER BY score DESC, sessions DESC").fetchall()
    return [group_dict(conn, g) for g in gs]


def get_group(conn: sqlite3.Connection, group_id: int) -> dict[str, JsonValue] | None:
    ensure_friction_schema(conn)
    g = conn.execute("SELECT * FROM ff_groups WHERE id = ?", (group_id,)).fetchone()
    return group_dict(conn, g) if g else None
