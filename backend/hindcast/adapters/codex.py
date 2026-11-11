"""Basic Codex rollout adapter: messages, function calls joined by call_id, token usage."""

import json
from collections.abc import Iterable

from hindcast.adapters.common import (
    StepRow,
    ToolCallRow,
    TrajectoryRow,
    classify_error,
    estimate_cost,
    redact,
    tool_kind,
)
from hindcast.types import JsonObject, JsonValue

PARSER_VERSION = "codex-1"
AGENT_NAME = "codex"


def _text(content: JsonValue) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text")) for b in content if isinstance(b, dict) and "text" in b)
    return ""


def parse_codex_lines(lines: Iterable[str], fallback_id: str) -> TrajectoryRow | None:
    traj = TrajectoryRow(trajectory_id=fallback_id, session_id=fallback_id, agent_name=AGENT_NAME)
    steps: list[StepRow] = []
    calls: dict[str, ToolCallRow] = {}
    counts: dict[str, int] = {}
    turn = -1
    last_agent: StepRow | None = None
    for line in lines:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        payload = raw.get("payload")
        rtype = str(raw.get("type"))
        p: JsonObject = payload if isinstance(payload, dict) else {}
        ptype = str(p.get("type", ""))
        counts[f"{rtype}/{ptype}"] = counts.get(f"{rtype}/{ptype}", 0) + 1
        ts = raw.get("timestamp") if isinstance(raw.get("timestamp"), str) else None
        tss = str(ts) if ts else None
        if rtype == "session_meta":
            sid = p.get("id")
            if isinstance(sid, str):
                traj.trajectory_id = traj.session_id = sid
            cwd = p.get("cwd")
            traj.project_path = cwd if isinstance(cwd, str) else None
            ver = p.get("cli_version")
            traj.agent_version = ver if isinstance(ver, str) else None
            git = p.get("git")
            if isinstance(git, dict) and isinstance(git.get("branch"), str):
                traj.git_branch = str(git["branch"])
        elif rtype == "turn_context":
            model = p.get("model")
            if isinstance(model, str) and not traj.model_name:
                traj.model_name = model
        elif rtype == "response_item":
            if ptype == "message":
                role = p.get("role")
                text = redact(_text(p.get("content")))
                if role == "user":
                    if text.lstrip().startswith("<"):
                        steps.append(
                            StepRow(
                                len(steps) + 1,
                                tss,
                                "system",
                                text,
                                max(turn, 0),
                                extra={"codex_kind": "context"},
                            )
                        )
                        continue
                    turn += 1
                    steps.append(StepRow(len(steps) + 1, tss, "user", text, turn))
                elif role == "assistant":
                    last_agent = StepRow(
                        len(steps) + 1,
                        tss,
                        "agent",
                        text,
                        max(turn, 0),
                        model_name=traj.model_name,
                    )
                    steps.append(last_agent)
            elif ptype in ("function_call", "custom_tool_call", "local_shell_call"):
                cid = str(p.get("call_id") or f"call-{len(calls)}")
                name = str(p.get("name") or ptype)
                args = p.get("arguments", p.get("input", p.get("action")))
                tc = ToolCallRow(
                    cid,
                    name,
                    redact(args if isinstance(args, str) else json.dumps(args)),
                    tool_kind=tool_kind(name),
                )
                if last_agent is None or last_agent.message:
                    last_agent = StepRow(
                        len(steps) + 1, tss, "agent", "", max(turn, 0), model_name=traj.model_name
                    )
                    steps.append(last_agent)
                last_agent.tool_calls.append(tc)
                calls[cid] = tc
            elif ptype in ("function_call_output", "custom_tool_call_output"):
                tc2 = calls.get(str(p.get("call_id")))
                if tc2 is not None:
                    out = p.get("output")
                    text = out if isinstance(out, str) else json.dumps(out)
                    tc2.content = redact(text)[:20000]
                    low = text[:400].lower()
                    if '"exit_code":1' in low.replace(" ", "") or "exit code: 1" in low:
                        tc2.is_error = True
                        tc2.error_class = classify_error(text)
        elif rtype == "event_msg" and ptype == "token_count":
            info = p.get("info")
            if isinstance(info, dict) and last_agent is not None:
                u = info.get("last_token_usage")
                if isinstance(u, dict):
                    inp = u.get("input_tokens")
                    cached = u.get("cached_input_tokens")
                    out2 = u.get("output_tokens")
                    i = inp if isinstance(inp, int) else 0
                    c = cached if isinstance(cached, int) else 0
                    o = out2 if isinstance(out2, int) else 0
                    last_agent.prompt_tokens = i
                    last_agent.cached_tokens = c
                    last_agent.completion_tokens = o
                    last_agent.cost_usd = estimate_cost(traj.model_name, i - c, o, c, 0)
    if not steps:
        return None
    traj.steps = steps
    traj.record_counts = counts
    return traj
