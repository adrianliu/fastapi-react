"""Pass 1 of friction labeling (spec 4.2): rule signals per episode, free, no model calls."""

import re
from dataclasses import dataclass

from .models import Signal, Step, ToolCall

CORRECTION_RE = re.compile(
    r"^\s*(no\b|nope\b)|\b(no need|don't|do not|i said|why did you|stop|never|again)\b",
    re.IGNORECASE,
)
COMPLETION_RE = re.compile(r"\b(done|fixed|works|all \d* ?tests pass|verified)\b", re.IGNORECASE)
ACCEPT_RE = re.compile(
    r"^\s*(great|thanks|thank you|perfect|lgtm|nice|looks good|ok\b|okay\b)", re.IGNORECASE
)

WEIGHTS = {
    "correction": 3.0,
    "reopened": 3.0,
    "rejections": 2.0,
    "repeat_failures": 2.0,
    "tool_errors": 0.3,
    "compactions": 1.0,
    "outlier_cost": 2.0,
}
TOOL_ERROR_CAP = 10
REPEAT_MIN = 3
REPEAT_WINDOW = 10
# Fixed defaults for "your norm" until there are 50 organic episodes to take a p90 from.
DEFAULT_COST_NORM = 2.0
DEFAULT_STEP_NORM = 80


@dataclass(frozen=True)
class EpisodeSignals:
    signals: list[Signal]
    score: float


def _errored_calls(steps: list[Step]) -> list[tuple[int, ToolCall]]:
    return [(s.step_id, c) for s in steps for c in s.tool_calls if c.is_error]


def repeat_failure_runs(steps: list[Step]) -> int:
    """Runs of >=3 errored calls with the same function and error class within 10 steps."""
    runs = 0
    key: tuple[str, str | None] | None = None
    start = 0
    count = 0
    for step_id, call in _errored_calls(steps):
        this = (call.function_name, call.error_class)
        if this == key and step_id - start < REPEAT_WINDOW:
            count += 1
            continue
        if count >= REPEAT_MIN:
            runs += 1
        key, start, count = this, step_id, 1
    if count >= REPEAT_MIN:
        runs += 1
    return runs


def score_episode(turn_steps: list[Step], reaction: Step | None) -> EpisodeSignals:
    counts: dict[str, int] = {}
    reaction_text = reaction.message if reaction else ""

    if reaction and CORRECTION_RE.search(reaction_text):
        counts["correction"] = 1

    agent_msgs = [s for s in turn_steps if s.source == "agent" and s.message.strip()]
    if (
        reaction
        and agent_msgs
        and COMPLETION_RE.search(agent_msgs[-1].message)
        and not ACCEPT_RE.search(reaction_text)
    ):
        counts["reopened"] = 1

    calls = [c for s in turn_steps for c in s.tool_calls]
    rejections = sum(1 for c in calls if c.error_class == "user_rejected")
    rejections += sum(1 for s in turn_steps if s.stop_reason == "interrupted")
    if rejections:
        counts["rejections"] = rejections

    if repeats := repeat_failure_runs(turn_steps):
        counts["repeat_failures"] = repeats

    errors = sum(1 for c in calls if c.is_error and c.error_class != "hook_denied")
    if errors:
        counts["tool_errors"] = min(errors, TOOL_ERROR_CAP)

    if compactions := sum(1 for s in turn_steps if s.is_compaction):
        counts["compactions"] = compactions

    cost = sum(s.cost_usd or 0.0 for s in turn_steps)
    if cost > DEFAULT_COST_NORM or len(turn_steps) > DEFAULT_STEP_NORM:
        counts["outlier_cost"] = 1

    signals = [
        Signal(name=name, count=n, weight=WEIGHTS[name], points=round(n * WEIGHTS[name], 2))
        for name, n in counts.items()
    ]
    return EpisodeSignals(signals=signals, score=round(sum(s.points for s in signals), 2))
