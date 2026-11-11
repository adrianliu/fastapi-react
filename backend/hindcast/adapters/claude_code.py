"""Claude Code JSONL adapter (spec 3.1, simplified).

Assistant lines that share `message.id` become one agent step (usage from the last line).
`tool_result` blocks attach to their `tool_use`. Only human prompts become user steps; meta and
harness-injected user lines become system steps with `extra.claude_kind`.
"""

import json
from collections.abc import Iterable
from datetime import datetime

from hindcast.adapters.common import (
    StepRow,
    ToolCallRow,
    TrajectoryRow,
    as_text,
    classify_error,
    estimate_cost,
    redact,
    tool_kind,
)
from hindcast.types import JsonObject, JsonValue

PARSER_VERSION = "cc-2"
AGENT_NAME = "claude-code"

_SKIP_TYPES = {
    "file-history-snapshot",
    "queue-operation",
    "last-prompt",
    "api-request",
    "api-request-blob",
    "api-request-shape",
    "atis-latch",
    "cost-state",
    "summary",
    "custom-title",
    "agent-name",
    "progress",
    "pr-link",
    "permission-mode",
    "ai-title",
    "mode",
    "bridge-session",
    "worktree-state",
    "frame-link",
    "relocated",
    "file-history-delta",
    "artifact-autoreact-ledger",
    "history-suppression",
    "session-owner",
}

KNOWN_RECORD_TYPES = _SKIP_TYPES | {"user", "assistant", "attachment", "system"}

_INTERRUPT = "[Request interrupted by user"


def _system_kind(text: str, obj: JsonObject) -> str | None:
    if obj.get("isCompactSummary"):
        return "compact_summary"
    if obj.get("isMeta"):
        return "meta"
    s = text.lstrip()
    if s.startswith("<task-notification>"):
        return "task_notification"
    if s.startswith(("<local-command", "<command-name>", "<command-message>")):
        return "command"
    if s.startswith(_INTERRUPT):
        return "interrupt"
    if s.startswith("Base directory for this skill:"):
        return "skill"
    if s.startswith("<system-reminder>"):
        return "system_reminder"
    if s.startswith("Caveat: The messages below"):
        return "meta"
    return None


def _int(v: JsonValue) -> int:
    return v if isinstance(v, int) else 0


def _str(v: JsonValue) -> str | None:
    return v if isinstance(v, str) else None


def parse_claude_lines(
    lines: Iterable[str],
    trajectory_id: str | None = None,
    parent_trajectory_id: str | None = None,
    parent_tool_call_id: str | None = None,
) -> TrajectoryRow | None:
    traj: TrajectoryRow | None = None
    steps: list[StepRow] = []
    by_msg_id: dict[str, StepRow] = {}
    usage_by_step: dict[int, JsonObject] = {}
    calls: dict[str, ToolCallRow] = {}
    call_ts: dict[str, str] = {}
    counts: dict[str, int] = {}
    turn = 0
    seen_human = False

    def new_step(ts: str | None, source: str, message: str, extra: JsonObject) -> StepRow:
        step = StepRow(
            step_id=len(steps) + 1,
            timestamp=ts,
            source=source,
            message=redact(message),
            turn_index=turn,
            extra=extra,
        )
        steps.append(step)
        return step

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            counts["invalid_json"] = counts.get("invalid_json", 0) + 1
            continue
        if not isinstance(raw, dict):
            continue
        obj: JsonObject = raw
        rtype = _str(obj.get("type")) or "unknown"
        sub = _str(obj.get("subtype"))
        key = f"{rtype}/{sub}" if sub else rtype
        counts[key] = counts.get(key, 0) + 1
        session_id = _str(obj.get("sessionId"))
        if traj is None and session_id and rtype in ("user", "assistant", "system", "attachment"):
            traj = TrajectoryRow(
                trajectory_id=trajectory_id or session_id,
                session_id=session_id,
                agent_name=AGENT_NAME,
                parent_trajectory_id=parent_trajectory_id,
                parent_tool_call_id=parent_tool_call_id,
            )
        if traj is not None:
            traj.agent_version = traj.agent_version or _str(obj.get("version"))
            traj.project_path = traj.project_path or _str(obj.get("cwd"))
            traj.git_branch = traj.git_branch or _str(obj.get("gitBranch"))
        ts = _str(obj.get("timestamp"))
        msg = obj.get("message")
        if rtype in _SKIP_TYPES or rtype == "attachment":
            continue
        if rtype == "system":
            if sub == "compact_boundary":
                new_step(ts, "system", "[conversation compacted]", {"claude_kind": "compaction"})
            elif sub in ("api_error", "local_command", "informational", "turn_duration"):
                sys_text = _str(obj.get("content")) or ""
                if sub == "api_error":
                    new_step(ts, "system", sys_text or "API error", {"claude_kind": "api_error"})
            continue
        if not isinstance(msg, dict):
            continue
        if rtype == "assistant":
            mid = _str(msg.get("id")) or _str(obj.get("uuid")) or str(len(steps))
            model = _str(msg.get("model"))
            if model == "<synthetic>":
                model = None
            step = by_msg_id.get(mid)
            if step is None:
                step = new_step(ts, "agent", "", {})
                by_msg_id[mid] = step
            step.model_name = step.model_name or model
            if traj is not None and model and not traj.model_name:
                traj.model_name = model
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    bt = block.get("type")
                    if bt == "text":
                        text = redact(_str(block.get("text")) or "")
                        step.message = f"{step.message}\n{text}" if step.message else text
                    elif bt == "thinking":
                        th = _str(block.get("thinking")) or ""
                        if th:
                            prev = step.reasoning_content
                            step.reasoning_content = f"{prev}\n{th}" if prev else th
                    elif bt == "tool_use":
                        cid = _str(block.get("id")) or f"call-{len(calls)}"
                        name = _str(block.get("name")) or "unknown"
                        tc = ToolCallRow(
                            tool_call_id=cid,
                            function_name=name,
                            arguments=redact(json.dumps(block.get("input") or {})),
                            tool_kind=tool_kind(name),
                        )
                        step.tool_calls.append(tc)
                        calls[cid] = tc
                        if ts:
                            call_ts[cid] = ts
            usage = msg.get("usage")
            if isinstance(usage, dict):
                usage_by_step[step.step_id] = usage
            stop = _str(msg.get("stop_reason"))
            if stop:
                step.stop_reason = stop
            continue
        if rtype != "user":
            continue
        content = msg.get("content")
        results: list[JsonObject] = (
            [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
            if isinstance(content, list)
            else []
        )
        if results:
            tur = obj.get("toolUseResult")
            for block in results:
                cid = _str(block.get("tool_use_id")) or ""
                hit = calls.get(cid)
                if hit is None:
                    continue
                text = redact(as_text(block.get("content")))
                hit.content = text[:20000]
                hit.is_error = bool(block.get("is_error"))
                if hit.is_error:
                    hit.error_class = classify_error(text)
                if isinstance(tur, dict) and isinstance(tur.get("agentId"), str):
                    hit.extra["agent_id"] = tur["agentId"]
                start = call_ts.get(cid)
                if start and ts:
                    hit.duration_ms = _ms_between(start, ts)
            continue
        text = as_text(content)
        kind = _system_kind(text, obj)
        if kind is not None:
            if kind == "interrupt":
                for earlier in reversed(steps):
                    if earlier.source == "agent":
                        earlier.stop_reason = "interrupted"
                        break
            new_step(ts, "system", text, {"claude_kind": kind})
            continue
        if seen_human:
            turn += 1
        seen_human = True
        new_step(ts, "user", text, {})
        steps[-1].turn_index = turn

    if traj is None:
        return None
    for step in steps:
        usage = usage_by_step.get(step.step_id)
        if usage is None:
            continue
        pt = _int(usage.get("input_tokens"))
        cr = _int(usage.get("cache_read_input_tokens"))
        cw = _int(usage.get("cache_creation_input_tokens"))
        out = _int(usage.get("output_tokens"))
        step.prompt_tokens = pt + cr + cw
        step.cached_tokens = cr
        step.completion_tokens = out
        step.cost_usd = estimate_cost(step.model_name, pt, out, cr, cw)
    traj.steps = [s for s in steps if s.message or s.tool_calls or s.reasoning_content]
    for i, s in enumerate(traj.steps, start=1):
        s.step_id = i
    traj.record_counts = counts
    return traj


def _ms_between(a: str, b: str) -> int | None:
    try:
        da = datetime.fromisoformat(a.replace("Z", "+00:00"))
        db = datetime.fromisoformat(b.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((db - da).total_seconds() * 1000))
