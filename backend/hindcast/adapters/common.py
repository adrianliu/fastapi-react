"""Shared adapter output types, redaction and pricing."""

import re
from dataclasses import dataclass, field

from hindcast.types import JsonObject, JsonValue


@dataclass
class ToolCallRow:
    tool_call_id: str
    function_name: str
    arguments: str
    content: str = ""
    is_error: bool = False
    error_class: str | None = None
    tool_kind: str | None = None
    duration_ms: int | None = None
    extra: JsonObject = field(default_factory=dict)


@dataclass
class StepRow:
    step_id: int
    timestamp: str | None
    source: str
    message: str
    turn_index: int
    reasoning_content: str | None = None
    model_name: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: float | None = None
    stop_reason: str | None = None
    extra: JsonObject = field(default_factory=dict)
    tool_calls: list[ToolCallRow] = field(default_factory=list)


@dataclass
class TrajectoryRow:
    trajectory_id: str
    session_id: str
    agent_name: str
    parent_trajectory_id: str | None = None
    parent_tool_call_id: str | None = None
    agent_version: str | None = None
    model_name: str | None = None
    project_path: str | None = None
    git_branch: str | None = None
    steps: list[StepRow] = field(default_factory=list)
    extra: JsonObject = field(default_factory=dict)
    record_counts: dict[str, int] = field(default_factory=dict)


# USD per million tokens: (input, output, cache read, cache write). Pinned 2026-11; estimate only.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "opus": (5.0, 25.0, 0.5, 6.25),
    "sonnet": (3.0, 15.0, 0.3, 3.75),
    "haiku": (1.0, 5.0, 0.1, 1.25),
    "gpt-5": (1.25, 10.0, 0.125, 1.25),
    "gpt": (1.25, 10.0, 0.125, 1.25),
}


def estimate_cost(
    model: str | None, prompt: int, completion: int, cache_read: int, cache_write: int
) -> float | None:
    if not model:
        return None
    m = model.lower()
    for key, (pin, pout, pread, pwrite) in PRICES.items():
        if key in m:
            return (
                prompt * pin + completion * pout + cache_read * pread + cache_write * pwrite
            ) / 1e6
    return None


_SECRET_RES = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk-[REDACTED]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"), r"\1[REDACTED]"),
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,})"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (
        re.compile(
            r"(?m)^(\s*(?:export\s+)?[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS)[A-Z0-9_]*\s*=\s*)"
            r"['\"]?[^\s'\"]{6,}['\"]?"
        ),
        r"\1[REDACTED]",
    ),
]


def redact(text: str) -> str:
    for pattern, repl in _SECRET_RES:
        text = pattern.sub(repl, text)
    return text


def as_text(value: JsonValue) -> str:
    """Flatten a content value (string or list of blocks) to text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                t = item.get("type")
                if t == "text" and isinstance(item.get("text"), str):
                    parts.append(str(item["text"]))
                elif t == "image":
                    parts.append("[image]")
                elif t == "tool_reference":
                    parts.append(f"[tool: {item.get('tool_name')}]")
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(value)


def classify_error(text: str) -> str:
    t = text.lower()
    rules = [
        ("user_rejected", ("user doesn't want", "rejected", "user denied", "permission")),
        ("interrupted", ("interrupted",)),
        ("file_not_found", ("no such file", "does not exist", "not found")),
        ("not_read_first", ("has not been read", "read it first")),
        ("edit_mismatch", ("string to replace not found", "old_string", "no match")),
        ("timeout", ("timed out", "timeout")),
        ("test_failure", ("failed", "assertionerror", "error:")),
    ]
    for name, needles in rules:
        if any(n in t for n in needles):
            return name
    return "other"


def tool_kind(name: str) -> str:
    n = name.lower()
    if n in ("read", "glob", "grep", "ls", "webfetch", "websearch"):
        return "read"
    if n in ("edit", "write", "multiedit", "notebookedit", "apply_patch"):
        return "edit"
    if n in ("bash", "shell", "exec_command", "local_shell"):
        return "shell"
    if n in ("task", "agent"):
        return "subagent"
    if n.startswith("mcp__"):
        return "mcp"
    return "other"
