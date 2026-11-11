"""API models for the Hindcast UI. Field names follow ATIF and spec 3.2 where they exist."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Harness = Literal["claude-code", "codex"]
Origin = Literal["organic", "benchmark"]
Source = Literal["system", "user", "agent"]
ToolKind = Literal["shell", "read", "edit", "search", "web", "mcp", "subagent", "skill", "other"]
ErrorClass = Literal[
    "nonzero_exit",
    "invalid_input",
    "hook_denied",
    "user_rejected",
    "interrupted",
    "edit_mismatch",
    "timeout",
    "not_found",
    "permission_denied",
    "other",
]
StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "error", "interrupted"]
FrictionType = Literal[
    "environment",
    "instruction_ignored",
    "context_loss",
    "false_completion",
    "requirement_missed",
    "wrong_assumption",
    "overreach",
    "tool_misuse",
    "retry_loop",
    "inefficiency",
]
TaskType = Literal[
    "feature",
    "bugfix",
    "refactor",
    "setup_integration",
    "debugging",
    "research",
    "review",
    "ops",
    "other",
]
Outcome = Literal["success", "partial", "failed", "abandoned", "unclear"]
ReviewState = Literal["pending", "confirmed", "rejected", "edited"]
SpanRole = Literal["request", "requirement", "attempt", "correction", "outcome", "solution_hint"]
Readiness = Literal["needs_review", "blocked", "ready_for_task_build"]
Verdict = Literal["better", "worse", "no_clear_difference", "too_few_tasks"]
TrialStatus = Literal["queued", "running", "passed", "failed"]


class ToolCall(BaseModel):
    tool_call_id: str
    function_name: str
    tool_kind: ToolKind
    summary: str
    content: str | None
    is_error: bool
    error_class: ErrorClass | None
    started_at: datetime
    duration_ms: int
    subagent_trajectory_id: str | None = None


class Step(BaseModel):
    step_id: int
    timestamp: datetime
    source: Source
    message: str
    reasoning_content: str | None = None
    model_name: str | None = None
    stop_reason: StopReason | None = None
    turn_index: int
    prompt_tokens: int | None = None
    cached_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    duration_ms: int
    is_compaction: bool = False
    tool_calls: list[ToolCall] = []


class SubagentTrajectory(BaseModel):
    trajectory_id: str
    parent_tool_call_id: str
    subagent_kind: Literal["agent", "fork", "workflow"]
    task: str
    steps: list[Step]
    total_cost_usd: float
    tool_errors: int


class Signal(BaseModel):
    name: str
    count: int
    weight: float
    points: float


class FrictionItem(BaseModel):
    type: FrictionType
    severity: int
    user_corrected: bool
    evidence_step_ids: list[int]
    resolution_step_ids: list[int]
    explanation: str
    instruction_quote: str | None = None


class Label(BaseModel):
    label_id: str
    intent: str
    task_type: TaskType
    outcome: Outcome
    outcome_reason: str
    friction: list[FrictionItem]
    review_state: ReviewState
    model: str
    prompt_version: str
    condenser_version: str
    input_sha256: str
    input_chars: int
    cost_usd: float


class Episode(BaseModel):
    turn_index: int
    first_step_id: int
    last_step_id: int
    reaction_step_id: int | None
    prompt: str
    score: float
    signals: list[Signal]
    cost_usd: float
    tool_errors: int
    label: Label | None


class SessionSummary(BaseModel):
    trajectory_id: str
    title: str
    project_path: str
    agent_name: Harness
    agent_version: str
    model_name: str
    origin: Origin
    git_branch: str | None
    git_commit: str | None
    git_dirty: bool
    started_at: datetime
    ended_at: datetime
    total_steps: int
    subagent_count: int
    total_prompt_tokens: int
    total_cached_tokens: int
    total_completion_tokens: int
    total_cost_usd: float
    tool_errors: int
    turns: int
    friction_score: float
    friction_types: list[FrictionType]
    has_friction_label: bool
    has_candidates: bool


class SessionDetail(SessionSummary):
    steps: list[Step]
    subagents: list[SubagentTrajectory]
    episodes: list[Episode]


class Meta(BaseModel):
    data_source: Literal["demo"]
    sessions: int
    by_harness: dict[str, int]
    projects: int
    first_started_at: datetime
    last_started_at: datetime


class ReviewIn(BaseModel):
    state: Literal["pending", "confirmed", "rejected"]


class Criterion(BaseModel):
    text: str
    step_ids: list[int]


class Span(BaseModel):
    role: SpanRole
    trajectory_id: str
    from_step: int
    to_step: int
    excerpt: str | None = None


class Fact(BaseModel):
    fact: str
    status: Literal["known", "unknown"]
    step_ids: list[int]


class Dependency(BaseModel):
    candidate_id: str
    reason: str
    step_ids: list[int]


class TaskCandidate(BaseModel):
    candidate_id: str
    revision: int
    title: str
    objective: str
    readiness: Readiness
    blocked_reasons: list[str]
    criteria: list[Criterion]
    spans: list[Span]
    starting_state: list[Fact]
    depends_on: list[Dependency]
    open_questions: list[str]
    instruction: str


class TurnRef(BaseModel):
    turn_index: int
    first_step_id: int
    last_step_id: int
    prompt: str


class CandidateSet(BaseModel):
    trajectory_id: str
    session_title: str
    proposal_set: int
    model: str
    prompt_version: str
    condenser_version: str
    turns: list[TurnRef]
    candidates: list[TaskCandidate]


class RubricItem(BaseModel):
    key: str
    label: str
    bad: bool


class Trial(BaseModel):
    task: str
    variant: str
    repeat: int
    status: TrialStatus
    score: float | None
    check_pass: bool | None
    diff_lines: int | None
    note: str | None
    items: dict[str, bool]
    fix_applied: bool | None
    tool_errors: int | None
    tokens: int | None
    duration_s: int | None
    cost_usd: float | None
    trajectory_id: str | None


class EvalTask(BaseModel):
    name: str
    source: str
    control: bool


class VariantStats(BaseModel):
    variant: str
    trials: int
    check_pass: int
    rubric_mean: float
    median_diff_lines: float
    new_config: int
    item_trials: int
    mean_tool_errors: float
    mean_tokens: float
    mean_duration_s: float
    mean_cost_usd: float
    fix_applied: int | None


class ItemRate(BaseModel):
    key: str
    label: str
    bad: bool
    baseline: int
    candidate: int
    n: int


class Bootstrap(BaseModel):
    verdict: Verdict
    delta: float
    ci_low: float
    ci_high: float
    margin: float
    resamples: int
    paired_tasks: int
    histogram: list[int]
    hist_min: float
    hist_max: float


class EvalRunSummary(BaseModel):
    run_id: str
    title: str
    dataset: str
    status: Literal["running", "finished"]
    started_at: datetime
    trials_total: int
    trials_done: int
    verdict: Verdict | None


class EvalRun(EvalRunSummary):
    fix_name: str
    fix_kind: Literal["skill", "rule", "hook"]
    harness: str
    model: str
    harbor_version: str
    rewardkit_version: str
    bench_commit: str
    repeats: int
    variants: list[str]
    tasks: list[EvalTask]
    rubric: list[RubricItem]
    trials: list[Trial]
    stats: list[VariantStats]
    items: list[ItemRate]
    bootstrap: Bootstrap | None
    duration_s: int | None
    cost_usd: float


class Dataset(BaseModel):
    key: str
    name: str
    version: str
    tasks: int


class LeaderboardEntry(BaseModel):
    rank: int
    model: str
    harness: str
    harness_version: str
    fixes: list[str]
    resolved_pct: float
    ci_low: float
    ci_high: float
    delta_vs_baseline: float | None
    rubric_mean: float
    cost_per_task: float
    median_steps: int
    trials: int
    date: str
    eval_run_id: str | None


class FixImpact(BaseModel):
    name: str
    kind: Literal["skill", "rule", "hook"]
    version: int
    delta: float
    verdict: Verdict
    applied: str


class Leaderboard(BaseModel):
    dataset: Dataset
    datasets: list[Dataset]
    entries: list[LeaderboardEntry]
    fixes: list[FixImpact]
