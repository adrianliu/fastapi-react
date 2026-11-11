"""Structured-output contracts: spec Appendix A, schemas A1-A6, as Pydantic models.

These are what `run_structured` (hindcast.llm) passes to `claude -p --json-schema` and validates
the answer against, and what the API returns inside labels, groups, fixes, rubrics and task
candidates. Every object forbids extra keys (`additionalProperties: false`).

The schema enforces shape only. The "code checks" from the spec (cited step ids exist, exactly one
of skill/rule/hook, no dependency cycles, ...) live in the owning area's module.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

KebabName = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64, min_length=1)
]
StepId = Annotated[int, Field(ge=1)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- A1. Label (label.v1) -----------------------------------------------------------------------

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
FRICTION_TYPES: tuple[FrictionType, ...] = (
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
)


class FrictionV1(_Strict):
    type: FrictionType
    severity: Literal[1, 2, 3] = Field(
        description=(
            "1 = minutes lost; 2 = a turn or more lost, or the user had to step in; "
            "3 = wrong or harmful result, or the task failed"
        )
    )
    evidence_step_ids: list[StepId] = Field(min_length=1, max_length=8)
    user_corrected: bool
    instruction_quote: str | None = Field(default=None, max_length=300)
    explanation: str = Field(min_length=1, max_length=400)
    resolution_step_ids: list[StepId] = Field(default_factory=list, max_length=5)


class LabelV1(_Strict):
    intent: str = Field(min_length=1, max_length=400)
    task_type: TaskType
    outcome: Outcome
    outcome_reason: str = Field(min_length=1, max_length=300)
    outcome_evidence_step_ids: list[StepId] = Field(default_factory=list, max_length=5)
    friction: list[FrictionV1] = Field(max_length=10)


# --- A2. Groups (groups.v1) ---------------------------------------------------------------------


class GroupV1(_Strict):
    name: KebabName
    lesson: str = Field(min_length=1, max_length=300)
    friction_ids: list[int] = Field(min_length=2)


class GroupsV1(_Strict):
    groups: list[GroupV1] = Field(max_length=30)


# --- A3. Fix draft (fix_draft.v1) ---------------------------------------------------------------

FixType = Literal["skill", "rule", "hook"]


class SkillFile(_Strict):
    path: Annotated[str, StringConstraints(pattern=r"^references/[a-z0-9-]+\.md$")]
    content: str = Field(max_length=40000)


class SkillContent(_Strict):
    description: str = Field(min_length=1, max_length=1024)
    body: str = Field(min_length=1, max_length=40000)
    files: list[SkillFile] = Field(default_factory=list, max_length=5)


class RuleContent(_Strict):
    scope: Literal["global", "project"]
    project_path: str | None = None
    text: str = Field(min_length=1, max_length=2000)


class HookContent(_Strict):
    event: Literal["PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop"]
    matcher: str = Field(max_length=200)
    script: str = Field(max_length=8000)


class RationaleItem(_Strict):
    instruction: str = Field(max_length=200)
    friction_ids: list[int] = Field(min_length=1)


class FixDraftV1(_Strict):
    fix_type: FixType
    fix_type_reason: str | None = Field(default=None, max_length=300)
    name: KebabName
    summary: str = Field(min_length=1, max_length=200)
    skill: SkillContent | None = None
    rule: RuleContent | None = None
    hook: HookContent | None = None
    rationale: list[RationaleItem] = Field(min_length=1)
    open_questions: list[Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=list, max_length=5
    )


# --- A4. Rubric (rubric.v1) ---------------------------------------------------------------------


class RubricItem(_Strict):
    id: Annotated[str, StringConstraints(pattern=r"^r[0-9]+$")]
    kind: Literal["must", "must_not", "follow_instruction"]
    text: str = Field(min_length=1, max_length=300)
    weight: int = Field(ge=1, le=3)
    critical: bool
    check_by: Literal["diff", "trajectory", "either"]
    source_friction_id: int | None = None


class RubricV1(_Strict):
    version: Literal[1] = 1
    items: list[RubricItem] = Field(min_length=1, max_length=12)


# --- A5. Verdict, host judge (verdict.v1) -------------------------------------------------------

Verdict = Literal["pass", "fail", "not_applicable"]


class VerdictItem(_Strict):
    id: Annotated[str, StringConstraints(pattern=r"^r[0-9]+$")]
    verdict: Verdict
    evidence: str = Field(min_length=1, max_length=400)
    evidence_step_ids: list[StepId] = Field(default_factory=list, max_length=5)
    evidence_files: list[str] = Field(default_factory=list, max_length=5)


class VerdictV1(_Strict):
    items: list[VerdictItem]
    summary: str = Field(max_length=400)


# --- A6. Task candidates (task_candidates.v1) ---------------------------------------------------

CandidateLocalId = Annotated[str, StringConstraints(pattern=r"^c[0-9]+$")]
SpanRole = Literal["request", "requirement", "attempt", "correction", "outcome", "solution_hint"]
CandidateStatus = Literal["needs_review", "blocked", "ready_for_task_build", "rejected"]


class StepRange(_Strict):
    trajectory_id: str
    from_step: StepId
    to_step: StepId


StepRanges = Annotated[list[StepRange], Field(min_length=1, max_length=20)]


class Criterion(_Strict):
    text: str = Field(min_length=1, max_length=300)
    evidence: StepRanges


class Span(_Strict):
    role: SpanRole
    steps: StepRanges
    note: str | None = Field(default=None, max_length=300)


class StartingFact(_Strict):
    fact: str = Field(min_length=1, max_length=300)
    status: Literal["known", "unknown"]
    evidence: StepRanges


class Dependency(_Strict):
    candidate: CandidateLocalId
    reason: str = Field(min_length=1, max_length=300)
    evidence: StepRanges


class CandidateOutcome(_Strict):
    status: Literal["claimed_done", "accepted", "abandoned", "unclear"]
    evidence: StepRanges


class TaskCandidateV1(_Strict):
    id: CandidateLocalId
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=600)
    criteria: list[Criterion] = Field(min_length=1, max_length=12)
    spans: list[Span] = Field(min_length=1)
    starting_state: list[StartingFact] = Field(max_length=12)
    base_commit: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{7,40}$")] | None = None
    depends_on: list[Dependency]
    outcome: CandidateOutcome
    readiness: Literal["needs_review", "blocked"]
    blocking_reasons: list[Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=list, max_length=5
    )


class TaskCandidatesV1(_Strict):
    candidates: list[TaskCandidateV1] = Field(min_length=1, max_length=20)
    open_questions: list[Annotated[str, StringConstraints(max_length=300)]] = Field(max_length=10)
