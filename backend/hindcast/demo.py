"""Demo dataset for the UI until the importers (spec phase 1) exist.

Sessions are generated deterministically by a small builder, so step ids, timestamps, tokens,
cost and errors are internally consistent and every number in the UI is computed from steps.
"""

import hashlib
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cache

from .friction import score_episode
from .models import (
    CandidateSet,
    Criterion,
    Dataset,
    Dependency,
    Episode,
    ErrorClass,
    EvalRun,
    EvalTask,
    Fact,
    FixImpact,
    FrictionItem,
    FrictionType,
    Harness,
    Label,
    LeaderboardEntry,
    Origin,
    Outcome,
    RubricItem,
    SessionDetail,
    Span,
    SpanRole,
    Step,
    StopReason,
    SubagentTrajectory,
    TaskCandidate,
    TaskType,
    ToolCall,
    ToolKind,
    Trial,
    TrialStatus,
    TurnRef,
)
from .stats import item_rates, paired_bootstrap, variant_stats

# Pinned price table, USD per million tokens: (input, cache read, output). Costs are estimates.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-sonnet-5-5": (3.0, 0.3, 15.0),
    "claude-opus-5-5": (5.0, 0.5, 25.0),
    "claude-haiku-5-5": (1.0, 0.1, 5.0),
    "gpt-5.3-codex": (1.25, 0.125, 10.0),
}

CLAUDE_FN: dict[ToolKind, str] = {
    "read": "Read",
    "edit": "Edit",
    "shell": "Bash",
    "search": "Grep",
    "web": "WebFetch",
    "subagent": "Agent",
    "skill": "Skill",
    "mcp": "mcp",
    "other": "Other",
}
CODEX_FN: dict[ToolKind, str] = {
    **CLAUDE_FN,
    "read": "exec_command",
    "edit": "apply_patch",
    "shell": "exec_command",
    "search": "exec_command",
    "web": "web_search",
    "subagent": "spawn_agent",
}
MS_RANGE: dict[ToolKind, tuple[int, int]] = {
    "read": (18, 90),
    "edit": (10, 45),
    "shell": (700, 6500),
    "search": (40, 220),
    "web": (600, 2200),
    "skill": (20, 60),
    "mcp": (200, 900),
    "subagent": (0, 0),
    "other": (20, 200),
}


@dataclass(frozen=True)
class C:
    """A tool call to generate."""

    kind: ToolKind
    summary: str
    error: ErrorClass | None = None
    content: str | None = None
    ms: int | None = None
    sub: "Sub | None" = None


@dataclass(frozen=True)
class Sub:
    task: str
    calls: tuple[C, ...]
    answer: str


@dataclass(frozen=True)
class Pools:
    files: tuple[str, ...]
    commands: tuple[str, ...]
    searches: tuple[str, ...]


class Builder:
    def __init__(
        self,
        trajectory_id: str,
        harness: Harness,
        model: str,
        start: datetime,
        pools: Pools,
        seed: int,
        ctx: int = 18_000,
    ) -> None:
        self.tid = trajectory_id
        self.harness = harness
        self.model = model
        self.t = start
        self.pools = pools
        self.rng = random.Random(seed)
        self.ctx = ctx
        self.turn = -1
        self.steps: list[Step] = []
        self.subagents: list[SubagentTrajectory] = []
        self.keys: dict[str, int] = {}
        self.prompts: dict[int, int] = {}
        self._calls = 0

    # -- helpers -------------------------------------------------------------------------
    def _advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)

    def _key(self, key: str | None) -> int:
        step_id = len(self.steps) + 1
        if key:
            self.keys[key] = step_id
        return step_id

    def _fn(self, kind: ToolKind) -> str:
        return (CODEX_FN if self.harness == "codex" else CLAUDE_FN)[kind]

    def _cost(self, prompt: int, cached: int, completion: int) -> float:
        p_in, p_cache, p_out = PRICES[self.model]
        return round(((prompt - cached) * p_in + cached * p_cache + completion * p_out) / 1e6, 5)

    def random_call(self, kind: ToolKind) -> C:
        r = self.rng
        if kind == "read":
            f = r.choice(self.pools.files)
            return C("read", f"sed -n 1,120p {f}" if self.harness == "codex" else f"Read {f}")
        if kind == "edit":
            return C("edit", f"Edit {r.choice(self.pools.files)}")
        if kind == "search":
            return C("search", f'Grep "{r.choice(self.pools.searches)}"')
        if kind == "web":
            return C("web", "WebFetch docs")
        return C("shell", f'Bash "{r.choice(self.pools.commands)}"')

    # -- steps ---------------------------------------------------------------------------
    def user(self, text: str, *, key: str | None = None, gap_s: float | None = None) -> int:
        self.turn += 1
        if self.steps:
            self._advance(gap_s if gap_s is not None else self.rng.uniform(40, 240))
        step_id = self._key(key)
        self.prompts[self.turn] = step_id
        self.steps.append(
            Step(
                step_id=step_id,
                timestamp=self.t,
                source="user",
                message=text,
                turn_index=self.turn,
                duration_ms=0,
            )
        )
        self._advance(2)
        return step_id

    def agent(
        self,
        message: str = "",
        calls: tuple[C, ...] = (),
        *,
        reasoning: str | None = None,
        stop: StopReason | None = None,
        key: str | None = None,
        completion: int | None = None,
    ) -> int:
        r = self.rng
        step_id = self._key(key)
        ts = self.t
        think_ms = r.randint(2500, 11_000)
        self.ctx += r.randint(300, 2600)
        prompt = self.ctx
        cached = int(prompt * r.uniform(0.86, 0.97))
        out = completion or r.randint(90, 900)
        self._advance(think_ms / 1000)
        tool_calls: list[ToolCall] = []
        for c in calls:
            self._calls += 1
            call_id = f"{self.tid[:6]}_{self._calls:04d}"
            lo, hi = MS_RANGE[c.kind]
            ms = c.ms if c.ms is not None else r.randint(lo, hi)
            sub_id = None
            if c.sub:
                sub_id, ms = self._subagent(c.sub, call_id)
            tool_calls.append(
                ToolCall(
                    tool_call_id=call_id,
                    function_name=self._fn(c.kind),
                    tool_kind=c.kind,
                    summary=c.summary,
                    content=c.content,
                    is_error=c.error is not None,
                    error_class=c.error,
                    started_at=self.t,
                    duration_ms=ms,
                    subagent_trajectory_id=sub_id,
                )
            )
            self._advance(ms / 1000 + 0.3)
            self.ctx += r.randint(200, 1500)
        self.steps.append(
            Step(
                step_id=step_id,
                timestamp=ts,
                source="agent",
                message=message,
                reasoning_content=reasoning,
                model_name=self.model,
                stop_reason=stop or ("tool_use" if calls else "end_turn"),
                turn_index=self.turn,
                prompt_tokens=prompt,
                cached_tokens=cached,
                completion_tokens=out,
                cost_usd=self._cost(prompt, cached, out),
                duration_ms=think_ms,
                tool_calls=tool_calls,
            )
        )
        return step_id

    def _subagent(self, sub: Sub, parent_call_id: str) -> tuple[str, int]:
        sub_id = f"{self.tid}:a{len(self.subagents) + 1:x}{self.rng.randint(256, 4095):03x}"
        child = Builder(
            sub_id, self.harness, self.model, self.t, self.pools, self.rng.randint(0, 10**6), 9000
        )
        child.turn = 0
        for c in sub.calls:
            child.agent("", (c,))
        child.agent(sub.answer)
        self.subagents.append(
            SubagentTrajectory(
                trajectory_id=sub_id,
                parent_tool_call_id=parent_call_id,
                subagent_kind="agent",
                task=sub.task,
                steps=child.steps,
                total_cost_usd=round(sum(s.cost_usd or 0 for s in child.steps), 4),
                tool_errors=sum(1 for s in child.steps for c in s.tool_calls if c.is_error),
            )
        )
        return sub_id, int((child.t - self.t).total_seconds() * 1000)

    def filler(
        self,
        n: int,
        *,
        errors: int = 0,
        kinds: tuple[ToolKind, ...] = ("read", "read", "search", "edit", "edit", "shell", "shell"),
        error_content: str = "Exit code 1",
    ) -> None:
        bad = set(self.rng.sample(range(n), min(errors, n)))
        for i in range(n):
            call = self.random_call(self.rng.choice(kinds))
            if i in bad:
                call = C(
                    "shell",
                    f'Bash "{self.rng.choice(self.pools.commands)}"',
                    error="nonzero_exit",
                    content=error_content,
                )
            self.agent("", (call,))

    def fail_run(self, k: int, call: C) -> None:
        for _ in range(k):
            self.agent("", (call,))

    def compact(self) -> None:
        step_id = self._key(None)
        self.steps.append(
            Step(
                step_id=step_id,
                timestamp=self.t,
                source="system",
                message=f"Conversation compacted. Summary of {step_id - 1} earlier steps.",
                turn_index=self.turn,
                duration_ms=18_000,
                is_compaction=True,
            )
        )
        self.ctx = 30_000
        self._advance(18)

    def turn_range(self, turn: int) -> tuple[int, int]:
        ids = [s.step_id for s in self.steps if s.turn_index == turn]
        return ids[0], ids[-1]


# -- labels ------------------------------------------------------------------------------
@dataclass(frozen=True)
class FrictionSpec:
    type: FrictionType
    severity: int
    user_corrected: bool
    evidence: tuple[str, ...]
    resolution: tuple[str, ...]
    explanation: str
    quote: str | None = None


@dataclass(frozen=True)
class LabelSpec:
    turn: int
    intent: str
    task_type: TaskType
    outcome: Outcome
    outcome_reason: str
    friction: tuple[FrictionSpec, ...]


@dataclass(frozen=True)
class Meta:
    tid: str
    title: str
    project: str
    harness: Harness
    version: str
    model: str
    start: datetime
    origin: Origin = "organic"
    branch: str | None = "main"
    commit: str | None = None
    dirty: bool = False


@dataclass
class Built:
    meta: Meta
    b: Builder
    labels: list[LabelSpec] = field(default_factory=list)


def _builder(meta: Meta, pools: Pools, seed: int) -> Builder:
    return Builder(meta.tid, meta.harness, meta.model, meta.start, pools, seed)


def _ts(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


NOTES_POOLS = Pools(
    files=(
        "backend/main.py",
        "backend/config.py",
        "backend/tests/test_api.py",
        "frontend/src/App.tsx",
        "README.md",
    ),
    commands=(
        "cd backend && .venv/bin/pytest -q",
        "cd backend && .venv/bin/ruff check .",
        "cd backend && .venv/bin/mypy .",
        "git status --short",
        "cd frontend && npm run build",
    ),
    searches=("@app.get", "get_db", "Note(", "limiter", "cursor"),
)
CLOUD_POOLS = Pools(
    files=("deploy/pipeline.yaml", "deploy/promote.sh", "e2e/login.spec.ts", "docker-compose.yml"),
    commands=(
        "npx playwright test e2e/login.spec.ts",
        "./deploy/promote.sh --dry-run",
        "gh run view",
    ),
    searches=("promote", "waitForURL", "retry"),
)
HINDCAST_POOLS = Pools(
    files=(
        "hindcast/jobs.py",
        "hindcast/store/schema.sql",
        "hindcast/settings.py",
        "tests/test_jobs.py",
    ),
    commands=(
        "uv run pytest -q",
        "uv run mypy hindcast",
        "sqlite3 ~/.hindcast/hindcast.db .schema",
    ),
    searches=("from hindcast.settings", "queue", "jobs"),
)
LYNX_POOLS = Pools(
    files=(".github/pull_request_template.md", "scripts/report.py", "README.md"),
    commands=("python scripts/report.py --dry-run", "git diff --stat"),
    searches=("## Testing", "report"),
)


# -- sessions ----------------------------------------------------------------------------
def _rate_limit() -> Built:
    m = Meta(
        "5c0e2a91-b71d",
        "Add rate limiting and pagination to the notes API",
        "fastapi-react",
        "claude-code",
        "2.1.4",
        "claude-sonnet-5-5",
        _ts(9, 14, 2),
        branch="feat/notes-limits",
        commit="3e1c9a2",
        dirty=True,
    )
    b = _builder(m, NOTES_POOLS, 1)
    b.user("Look around the notes app and tell me how the API is laid out.")
    b.filler(6, kinds=("read", "search"))
    b.agent("One FastAPI module with three /api/notes routes over stdlib sqlite3; tests in tests/.")

    b.user("Add a created_at column to notes and return it from the API.")
    b.filler(9, errors=1)
    b.agent("created_at is stored as UTC ISO text and returned on every note.")

    b.user("Now add cursor pagination to GET /api/notes, 20 per page.")
    b.filler(5)
    b.agent(
        "",
        (
            C(
                "subagent",
                "Agent: survey cursor pagination patterns",
                sub=Sub(
                    "Survey cursor pagination patterns for FastAPI + sqlite3",
                    (C("web", "WebFetch fastapi.tiangolo.com/tutorial"), C("read", "Read main.py")),
                    "Use the last id as the cursor; LIMIT 21 detects a next page.",
                ),
            ),
        ),
    )
    b.filler(8)
    b.agent("Pagination is in: GET /api/notes takes ?cursor= and returns next_cursor.")

    b.user("Add rate limiting to POST /api/notes. 10 requests per minute per IP is fine.")
    b.agent(
        "I'll add slowapi with a per-IP limit on the create endpoint. "
        "First I'll look at how the app is configured.",
        (C("read", "Read backend/main.py"), C("read", "Read backend/config.py")),
        reasoning="There's no limiter yet. slowapi fits FastAPI. To be safe I'll gate it behind a "
        "setting so it can be rolled out gradually without breaking existing clients.",
    )
    b.agent("", (C("edit", "Edit backend/main.py", content="+ limiter = Limiter(key_func=...)"),))
    b.agent(
        "",
        (
            C(
                "edit",
                "Edit backend/config.py",
                content='+    enable_rate_limit: bool = Field(False, alias="ENABLE_RATE_LIMIT")\n'
                "+    rate_limit_per_minute: int = 10",
            ),
        ),
        key="flag",
    )
    fail = (
        "Exit code 1\nFAILED tests/test_api.py::test_create_list_delete - FastAPIError:\n"
        "  slowapi requires a `request: Request` argument on create_note\n"
        "1 failed, 11 passed in 1.84s"
    )
    for cmd in ("pytest -q", "pytest -q tests/test_api.py", "pytest -q -x"):
        b.agent(
            "",
            (C("shell", f'Bash "cd backend && .venv/bin/{cmd}"', "nonzero_exit", fail),),
        )
    b.agent(
        "",
        (
            C(
                "subagent",
                "Agent: why slowapi rejects create_note",
                sub=Sub(
                    "Find why slowapi rejects create_note in tests",
                    (
                        C("search", 'Grep "limiter.limit" backend/'),
                        C("read", "Read backend/main.py (lines 40-92)"),
                        C("web", "WebFetch slowapi.readthedocs.io/en/latest/"),
                    ),
                    "The decorated endpoint must take request: Request. Add it to create_note.",
                ),
            ),
        ),
    )
    b.filler(7, kinds=("edit", "edit", "shell", "read"))
    b.agent(
        "Done. Rate limiting is in place on POST /api/notes, behind ENABLE_RATE_LIMIT so you can "
        "roll it out gradually. I also added RATE_LIMIT_PER_MINUTE to the config. "
        "All 12 tests pass.",
        key="claim",
    )

    b.user(
        "no need for a flag. just add the limit, simplest solution. and drop the config var",
        key="reaction",
    )
    b.agent(
        "",
        (C("edit", "Edit backend/config.py", content="- enable_rate_limit ...\n- rate_limit_..."),),
        key="resolved",
    )
    b.filler(4, kinds=("edit", "shell"))
    b.agent("Removed the flag and RATE_LIMIT_PER_MINUTE; the limit is always on at 10/min.")

    b.user("Write tests for the limiter: the 11th request in a minute gets a 429.")
    b.filler(10)
    b.fail_run(
        4,
        C(
            "shell",
            'Bash "cd backend && .venv/bin/pytest -q tests/test_limits.py"',
            "nonzero_exit",
            "Exit code 1\nassert 201 == 429",
        ),
    )
    b.compact()
    b.agent(
        "",
        (
            C(
                "subagent",
                "Agent: why the 429 test is flaky",
                sub=Sub(
                    "Find why the 429 test passes alone and fails in the suite",
                    (C("search", 'Grep "limiter" backend/tests'), C("read", "Read conftest.py")),
                    "The limiter's storage is shared between tests; reset it in a fixture.",
                ),
            ),
        ),
    )
    b.filler(8, kinds=("edit", "shell", "read"))
    b.agent("Added tests/test_limits.py with a fixture that resets the limiter; it passes.")

    b.user("Update the README with the new limits.")
    b.filler(3, kinds=("read", "edit"))
    b.agent("README now documents the 10/min limit and cursor pagination.")
    b.user("Commit this.")
    b.filler(2, kinds=("shell",))
    b.agent("Committed as two commits: pagination, then rate limiting.")
    b.user("Push and open a PR.")
    b.filler(3, kinds=("shell",))
    b.agent("Pushed feat/notes-limits and opened a PR.")

    label = LabelSpec(
        turn=3,
        intent="Rate-limit note creation at 10 requests per minute per IP.",
        task_type="feature",
        outcome="partial",
        outcome_reason="The limit works but shipped behind a flag that was off by default.",
        friction=(
            FrictionSpec(
                "overreach",
                2,
                True,
                ("flag", "claim", "reaction"),
                ("resolved",),
                "Added an ENABLE_RATE_LIMIT feature flag and a config variable nobody asked "
                "for. The user removed both.",
            ),
            FrictionSpec(
                "false_completion",
                1,
                False,
                ("claim",),
                ("resolved",),
                "Claimed done while the requested behaviour was off by default.",
            ),
        ),
    )
    return Built(m, b, [label])


def _jobs_migration() -> Built:
    m = Meta(
        "9a41d3e0-77c2",
        "Migrate the worker queue to the new jobs table",
        "hindcast",
        "claude-code",
        "2.1.4",
        "claude-opus-5-5",
        _ts(8, 9, 40),
        commit="b01c7f3",
    )
    b = _builder(m, HINDCAST_POOLS, 2)
    b.user(
        "Migrate the worker queue to the new jobs table. Keep the old queue table until I say so.",
        key="instruction",
    )
    b.filler(24, errors=3)
    b.compact()
    b.filler(18, errors=2)
    b.compact()
    b.agent(
        "",
        (C("edit", "Edit hindcast/store/schema.sql", content="- CREATE TABLE queue"),),
        key="drop",
    )
    b.filler(6)
    b.agent("Migrated the worker to jobs and dropped the old queue table. Tests pass.", key="claim")
    b.user("I said keep the old table until I say so. Restore it.", key="reaction")
    b.filler(8)
    b.agent("Restored the queue table from the migration and left it in place.")
    b.user("Thanks.")
    b.agent("You're welcome.")
    label = LabelSpec(
        turn=0,
        intent="Move the worker to the jobs table without dropping the old queue table yet.",
        task_type="refactor",
        outcome="partial",
        outcome_reason="The migration worked but the old table was dropped against instructions.",
        friction=(
            FrictionSpec(
                "context_loss",
                3,
                True,
                ("instruction", "drop", "reaction"),
                (),
                "The instruction to keep the queue table was lost after the second compaction.",
                quote="Keep the old queue table until I say so.",
            ),
        ),
    )
    return Built(m, b, [label])


def _flaky_e2e() -> Built:
    m = Meta(
        "019a5b62-e4f1",
        "Fix flaky e2e login test on CI",
        "cloud-bot",
        "codex",
        "0.161.0",
        "gpt-5.3-codex",
        _ts(7, 16, 15),
        commit="77de2a0",
    )
    b = _builder(m, CLOUD_POOLS, 3)
    b.user("Fix the flaky e2e login test on CI.")
    b.filler(6, kinds=("read", "search"))
    flaky = C(
        "shell",
        'exec_command "npx playwright test e2e/login.spec.ts"',
        "nonzero_exit",
        "Exit code 1\nTimeoutError: page.waitForURL: Timeout 5000ms exceeded.",
    )
    b.fail_run(4, flaky)
    b.agent("", (C("edit", "apply_patch e2e/login.spec.ts (retry click)"),))
    b.fail_run(3, flaky)
    b.agent("", (C("shell", 'exec_command "gh run rerun --failed"', "timeout", "timed out"),))
    b.filler(5)
    b.agent("Fixed: added a retry around the login click. Verified locally 5/5.", key="claim")
    b.user("that's not a fix, it still fails on CI. why did you add a retry?", key="reaction")
    b.filler(9)
    b.agent("The redirect waits on /api/session; I now wait for that response instead.")
    label = LabelSpec(
        turn=0,
        intent="Make the e2e login test pass reliably on CI.",
        task_type="bugfix",
        outcome="failed",
        outcome_reason="The retry hid the race locally; CI still failed.",
        friction=(
            FrictionSpec(
                "retry_loop",
                2,
                True,
                ("claim",),
                (),
                "Re-ran the same failing test 7 times with no new information between runs.",
            ),
            FrictionSpec(
                "false_completion",
                2,
                True,
                ("claim", "reaction"),
                (),
                "Claimed verified based on local runs only.",
            ),
        ),
    )
    return Built(m, b, [label])


def _canary() -> Built:
    m = Meta(
        "c2d8f6aa-1b09",
        "Add a canary deploy step before promoting the build",
        "cloud-bot",
        "claude-code",
        "2.1.3",
        "claude-sonnet-5-5",
        _ts(6, 11, 3),
        commit="5f2e9b1",
    )
    b = _builder(m, CLOUD_POOLS, 4)
    b.user("Add a canary deploy step before promoting the build.")
    b.filler(10)
    b.agent("", (C("edit", "Edit deploy/canary.yaml (new file)"),), key="config")
    b.filler(6, errors=1)
    b.agent(
        "Done. The canary step is added with a CANARY_ENABLED flag and a canary.yaml config.",
        key="claim",
    )
    b.user("no need for a flag or a new config file. keep it simple.", key="reaction")
    b.filler(5)
    b.agent("The canary step now runs unconditionally with its settings inline.")
    label = LabelSpec(
        turn=0,
        intent="Run a canary deploy before promotion.",
        task_type="ops",
        outcome="partial",
        outcome_reason="Worked, with an unrequested flag and config file.",
        friction=(
            FrictionSpec(
                "overreach",
                2,
                True,
                ("config", "claim", "reaction"),
                (),
                "Added a CANARY_ENABLED flag and a separate config file.",
            ),
        ),
    )
    return Built(m, b, [label])


def _backfill() -> Built:
    m = Meta(
        "019a4c11-0d3b",
        "Add tags to notes",
        "fastapi-react",
        "codex",
        "0.161.0",
        "gpt-5.3-codex",
        _ts(5, 18, 22),
        commit="2a7d0e4",
    )
    b = _builder(m, NOTES_POOLS, 5)
    b.user("Add tags to notes.")
    b.filler(12, errors=1)
    b.agent("", (C("edit", "apply_patch backend/backfill_tags.py (new file)"),), key="backfill")
    b.filler(3)
    b.agent("Tags work, and I wrote a backfill that tags existing notes.", key="claim")
    b.user("no backfill, simplest solution. existing notes can have no tags.", key="reaction")
    b.filler(4)
    b.agent("Removed the backfill; untagged notes return tags: [].")
    label = LabelSpec(
        turn=0,
        intent="Let notes carry tags.",
        task_type="feature",
        outcome="partial",
        outcome_reason="Tags work; an unrequested backfill was added.",
        friction=(
            FrictionSpec(
                "overreach",
                2,
                True,
                ("backfill", "reaction"),
                (),
                "Wrote a backfill script for existing notes that nobody asked for.",
            ),
        ),
    )
    return Built(m, b, [label])


def _eval_report() -> Built:
    m = Meta(
        "e7f3a0c4-5d62",
        "Wire the eval report into the PR template",
        "lynx-eval",
        "claude-code",
        "2.1.3",
        "claude-sonnet-5-5",
        _ts(4, 10, 51),
        commit="c93b114",
    )
    b = _builder(m, LYNX_POOLS, 6)
    b.user("Wire the eval report into the PR template.")
    b.filler(5, kinds=("read",))
    b.fail_run(
        4,
        C(
            "edit",
            "Edit .github/pull_request_template.md",
            "edit_mismatch",
            "<tool_use_error>String to replace not found in file.</tool_use_error>",
        ),
    )
    b.agent("", (C("read", "Read .github/pull_request_template.md"),), key="reread")
    b.filler(4, kinds=("edit", "shell"))
    b.agent("Updated the PR template with a report section.")
    b.user("ok thanks")
    b.agent("Anytime.")
    label = LabelSpec(
        turn=0,
        intent="Add the eval report to the PR template.",
        task_type="feature",
        outcome="success",
        outcome_reason="Template updated and accepted.",
        friction=(
            FrictionSpec(
                "tool_misuse",
                1,
                False,
                ("reread",),
                ("reread",),
                "Four edits with a stale old_string before re-reading the file.",
            ),
        ),
    )
    return Built(m, b, [label])


def _rename() -> Built:
    m = Meta(
        "4be81c77-a3f0",
        "Rename the settings module and update imports",
        "hindcast",
        "claude-code",
        "2.1.2",
        "claude-haiku-5-5",
        _ts(3, 15, 30),
        commit="91aa0d2",
    )
    b = _builder(m, HINDCAST_POOLS, 7)
    b.user("Rename hindcast/settings.py to config.py and update imports.")
    b.filler(86, kinds=("read", "edit", "edit", "search"))
    b.agent("Renamed settings to config and updated 41 imports.")
    b.user("great")
    b.agent("Glad it helps.")
    label = LabelSpec(
        turn=0,
        intent="Rename a module and fix its imports.",
        task_type="refactor",
        outcome="success",
        outcome_reason="Accepted.",
        friction=(
            FrictionSpec(
                "inefficiency",
                1,
                False,
                (),
                (),
                "Edited imports one file at a time; one search-and-replace would do.",
            ),
        ),
    )
    return Built(m, b, [label])


def _auth() -> Built:
    m = Meta(
        "a8c1f0d2-6e44",
        "Auth, Docker and password reset",
        "fastapi-react",
        "claude-code",
        "2.1.4",
        "claude-sonnet-5-5",
        _ts(10, 9, 12),
        branch="feat/auth",
        commit="3e1c9a2",
    )
    b = _builder(m, NOTES_POOLS, 8)
    b.user("Add login with sessions to the API. Protected routes should return 401.")
    b.agent("", (C("read", "Read backend/main.py", content="CREATE TABLE users ..."),), key="users")
    b.filler(11)
    b.user("tests can't reach postgres, fix the compose file first")
    b.fail_run(
        3,
        C(
            "shell",
            'Bash "docker compose up -d db && pytest -q"',
            "nonzero_exit",
            "Exit code 1\npsycopg.OperationalError: connection refused",
        ),
    )
    b.filler(6, kinds=("read", "edit"))
    b.agent("Postgres is healthy now; its healthcheck passes and tests can connect.")
    b.user("ok the db is up. back to the login")
    b.filler(9)
    b.agent("Login sets a session token; protected routes return 401 without one.")
    b.user(
        "use an httpOnly cookie, not localStorage. and you can just use itsdangerous for signing"
    )
    b.filler(10)
    b.agent("The session now lives in a signed httpOnly cookie.")
    b.user("migration 0007 runs before 0006 on a fresh db")
    b.filler(9, errors=1)
    b.agent("Renumbered the migration so the order is stable on a fresh database.")
    b.user("now password reset by email, link valid for 30 min")
    b.filler(14)
    b.agent("Password reset sends a 30-minute link and sets a new password.")
    b.user(
        "no, the login from earlier doesn't expire sessions. they should expire after 7 days idle",
        key="reaction",
    )
    b.filler(10)
    b.agent("Sessions now expire after 7 days idle. 24 tests pass.")
    b.user("great, commit it all")
    b.filler(2, kinds=("shell",))
    b.agent("Committed on feat/auth.")
    label = LabelSpec(
        turn=5,
        intent="Add password reset by email with a 30-minute link.",
        task_type="feature",
        outcome="success",
        outcome_reason="Reset works; the reaction concerns the earlier login task.",
        friction=(
            FrictionSpec(
                "requirement_missed",
                2,
                True,
                ("reaction",),
                (),
                "Sessions from the login task never expired; the user had to ask.",
            ),
        ),
    )
    return Built(m, b, [label])


def _bench(tid: str, variant: str, start: datetime, flag: bool) -> Built:
    m = Meta(
        tid,
        f"keep-it-simple/rate-limit - {variant} - r1",
        "-app",
        "claude-code",
        "2.1.4",
        "claude-sonnet-5-5",
        start,
        origin="benchmark",
        branch=None,
        commit="3e1c9a2",
    )
    b = _builder(m, NOTES_POOLS, 9 if flag else 10)
    b.user(
        "Add rate limiting to POST /api/notes. 10 requests per minute per IP is fine.",
        gap_s=0,
    )
    b.filler(6, kinds=("read", "search"))
    if flag:
        b.agent("", (C("edit", "Edit backend/config.py", content="+ ENABLE_RATE_LIMIT ..."),))
        b.filler(7, kinds=("edit", "shell"))
        b.agent("Rate limiting is in, behind ENABLE_RATE_LIMIT. All tests pass.")
    else:
        b.filler(4, kinds=("edit", "shell"))
        b.agent("Added a 10/min per-IP limit on POST /api/notes (12-line diff). Tests pass.")
    return Built(m, b)


def _clean(tid: str, title: str, project: str, harness: Harness, model: str, day: int) -> Built:
    m = Meta(tid, title, project, harness, "2.1.4", model, _ts(day, 13, 5), commit="6d2f81e")
    b = _builder(m, NOTES_POOLS, day)
    b.user(title + ".")
    b.filler(9, kinds=("read", "edit", "shell"))
    b.agent("That's in place.")
    b.user("thanks")
    b.agent("Sure.")
    return Built(m, b)


@cache
def _built() -> dict[str, Built]:
    sessions = [
        _rate_limit(),
        _jobs_migration(),
        _flaky_e2e(),
        _canary(),
        _backfill(),
        _eval_report(),
        _rename(),
        _auth(),
        _bench("bench-rl-base-r1", "baseline", _ts(11, 7, 12), True),
        _bench("bench-rl-rule-r1", "baseline + rule v1", _ts(11, 7, 14), False),
        _clean(
            "61f0be3c-92d7",
            "Bump vite and fix the type errors",
            "fastapi-react",
            "claude-code",
            "claude-sonnet-5-5",
            2,
        ),
        _clean(
            "019a3e70-aa18",
            "Add a /healthz endpoint",
            "cloud-bot",
            "codex",
            "gpt-5.3-codex",
            1,
        ),
    ]
    return {s.meta.tid: s for s in sessions}


def _label(built: Built, spec: LabelSpec) -> Label:
    keys = built.b.keys

    def ids(names: tuple[str, ...]) -> list[int]:
        return [keys[n] for n in names]

    digest = hashlib.sha256(f"{built.meta.tid}:{spec.turn}".encode()).hexdigest()
    return Label(
        label_id=f"{built.meta.tid}:t{spec.turn}",
        intent=spec.intent,
        task_type=spec.task_type,
        outcome=spec.outcome,
        outcome_reason=spec.outcome_reason,
        friction=[
            FrictionItem(
                type=f.type,
                severity=f.severity,
                user_corrected=f.user_corrected,
                evidence_step_ids=ids(f.evidence),
                resolution_step_ids=ids(f.resolution),
                explanation=f.explanation,
                instruction_quote=f.quote,
            )
            for f in spec.friction
        ],
        review_state="pending",
        model="claude-sonnet-5-5",
        prompt_version="label@v3",
        condenser_version="c2",
        input_sha256=digest,
        input_chars=12_000 + len(built.b.steps) * 90,
        cost_usd=round(0.004 + len(built.b.steps) * 0.0002, 4),
    )


def _episodes(built: Built) -> list[Episode]:
    steps = built.b.steps
    labels = {spec.turn: _label(built, spec) for spec in built.labels}
    turns = sorted({s.turn_index for s in steps})
    episodes = []
    for t in turns:
        turn_steps = [s for s in steps if s.turn_index == t]
        nxt = built.b.prompts.get(t + 1)
        reaction = steps[nxt - 1] if nxt else None
        sig = score_episode(turn_steps, reaction)
        episodes.append(
            Episode(
                turn_index=t,
                first_step_id=turn_steps[0].step_id,
                last_step_id=turn_steps[-1].step_id,
                reaction_step_id=nxt,
                prompt=turn_steps[0].message,
                score=sig.score,
                signals=sig.signals,
                cost_usd=round(sum(s.cost_usd or 0 for s in turn_steps), 4),
                tool_errors=sum(1 for s in turn_steps for c in s.tool_calls if c.is_error),
                label=labels.get(t),
            )
        )
    return episodes


@cache
def session_details() -> dict[str, SessionDetail]:
    out: dict[str, SessionDetail] = {}
    for tid, built in _built().items():
        b, m = built.b, built.meta
        tree = b.steps + [s for sub in b.subagents for s in sub.steps]
        episodes = _episodes(built)
        labelled = [e.label for e in episodes if e.label]
        out[tid] = SessionDetail(
            trajectory_id=tid,
            title=m.title,
            project_path=m.project,
            agent_name=m.harness,
            agent_version=m.version,
            model_name=m.model,
            origin=m.origin,
            git_branch=m.branch,
            git_commit=m.commit,
            git_dirty=m.dirty,
            started_at=b.steps[0].timestamp,
            ended_at=b.t,
            total_steps=len(tree),
            subagent_count=len(b.subagents),
            total_prompt_tokens=sum(s.prompt_tokens or 0 for s in tree),
            total_cached_tokens=sum(s.cached_tokens or 0 for s in tree),
            total_completion_tokens=sum(s.completion_tokens or 0 for s in tree),
            total_cost_usd=round(sum(s.cost_usd or 0 for s in tree), 4),
            tool_errors=sum(1 for s in tree for c in s.tool_calls if c.is_error),
            turns=len(episodes),
            friction_score=max((e.score for e in episodes), default=0.0),
            friction_types=sorted({f.type for lab in labelled for f in lab.friction}),
            has_friction_label=bool(labelled),
            has_candidates=tid in _candidate_specs(),
            steps=b.steps,
            subagents=b.subagents,
            episodes=episodes,
        )
    return out


# -- task candidates (spec 4.4) ------------------------------------------------------------
@cache
def _candidate_specs() -> frozenset[str]:
    return frozenset({"a8c1f0d2-6e44"})


def candidate_set(trajectory_id: str) -> CandidateSet | None:
    if trajectory_id not in _candidate_specs():
        return None
    built = _built()[trajectory_id]
    b = built.b
    detail = session_details()[trajectory_id]

    def p(turn: int) -> int:
        return b.prompts[turn]

    def work(turn: int) -> tuple[int, int]:
        first, last = b.turn_range(turn)
        return first + 1, last

    def span(role: SpanRole, rng: tuple[int, int] | int, excerpt: str | None = None) -> Span:
        lo, hi = (rng, rng) if isinstance(rng, int) else rng
        return Span(
            role=role, trajectory_id=trajectory_id, from_step=lo, to_step=hi, excerpt=excerpt
        )

    commit = detail.git_commit or "unknown"
    t6_last = b.turn_range(6)[1]
    c1 = [
        span("request", p(0)),
        span("attempt", work(0)),
        span("attempt", work(2)),
        span("requirement", p(3), "Use an httpOnly cookie, not localStorage."),
        span("solution_hint", p(3), "You can just use itsdangerous for signing."),
        span("attempt", work(3)),
        span("correction", p(6)),
        span("requirement", p(6), "Sessions should expire after 7 days idle."),
        span("attempt", (work(6)[0], t6_last - 1)),
        span("outcome", (t6_last, p(7))),
    ]
    candidates = [
        TaskCandidate(
            candidate_id="C1",
            revision=4,
            title="Session-cookie authentication with idle expiry",
            objective="Add login and logout to the API with a signed session in an httpOnly "
            "cookie. Protected routes return 401 without a valid session. Sessions expire after "
            "7 days idle.",
            readiness="ready_for_task_build",
            blocked_reasons=[],
            criteria=[
                Criterion(text="POST /login sets an httpOnly session cookie", step_ids=[p(3)]),
                Criterion(text="Protected routes return 401 without a session", step_ids=[p(0)]),
                Criterion(text="A session idle for 7 days is rejected", step_ids=[p(6)]),
            ],
            spans=c1,
            starting_state=[
                Fact(fact=f"base commit {commit} (git_commit)", status="known", step_ids=[p(0)]),
                Fact(fact="users table exists", status="known", step_ids=[b.keys["users"]]),
            ],
            depends_on=[
                Dependency(
                    candidate_id="C2",
                    reason="Tests could not reach Postgres until the compose file was fixed.",
                    step_ids=[p(1), p(2)],
                )
            ],
            open_questions=[],
            instruction="",
        ),
        TaskCandidate(
            candidate_id="C2",
            revision=2,
            title="Repair the Postgres healthcheck in docker-compose",
            objective="Make the db service healthy so the backend tests can connect.",
            readiness="ready_for_task_build",
            blocked_reasons=[],
            criteria=[
                Criterion(text="The db container passes its healthcheck", step_ids=[work(1)[1]]),
                Criterion(text="Backend tests can connect to Postgres", step_ids=[p(2)]),
            ],
            spans=[
                span("request", p(1)),
                span("attempt", work(1)),
                span("outcome", p(2), "ok the db is up"),
            ],
            starting_state=[
                Fact(fact=f"base commit {commit} (git_commit)", status="known", step_ids=[p(0)])
            ],
            depends_on=[],
            open_questions=[],
            instruction="",
        ),
        TaskCandidate(
            candidate_id="C3",
            revision=1,
            title="Fix migration ordering on a fresh database",
            objective="Migrations apply in numeric order on an empty database.",
            readiness="needs_review",
            blocked_reasons=[],
            criteria=[Criterion(text="A fresh database applies 0006 before 0007", step_ids=[p(4)])],
            spans=[span("request", p(4)), span("attempt", work(4))],
            starting_state=[],
            depends_on=[],
            open_questions=["Did the renumbering also change the table C4 uses for reset tokens?"],
            instruction="",
        ),
        TaskCandidate(
            candidate_id="C4",
            revision=1,
            title="Password reset by email, 30-minute link",
            objective="Users can request a reset link by email; it is valid for 30 minutes.",
            readiness="blocked",
            blocked_reasons=[
                "Starting state unknown: SMTP settings never appear in the session.",
                "Prerequisite C1 is not built yet.",
            ],
            criteria=[
                Criterion(text="A reset link older than 30 minutes is rejected", step_ids=[p(5)])
            ],
            spans=[span("request", p(5)), span("attempt", work(5))],
            starting_state=[Fact(fact="SMTP settings", status="unknown", step_ids=[])],
            depends_on=[
                Dependency(
                    candidate_id="C1",
                    reason="Reset changes the password used by the session login.",
                    step_ids=[p(5)],
                )
            ],
            open_questions=[],
            instruction="",
        ),
    ]
    by_id = {s.step_id: s for s in b.steps}
    for cand in candidates:
        parts = [
            s.excerpt or by_id[s.from_step].message
            for s in sorted(cand.spans, key=lambda s: s.from_step)
            if s.role in ("request", "requirement")
        ]
        cand.instruction = "\n".join(parts)
    turns = [
        TurnRef(
            turn_index=e.turn_index,
            first_step_id=e.first_step_id,
            last_step_id=e.last_step_id,
            prompt=e.prompt,
        )
        for e in detail.episodes
    ]
    return CandidateSet(
        trajectory_id=trajectory_id,
        session_title=detail.title,
        proposal_set=2,
        model="claude-sonnet-5-5",
        prompt_version="extract@v1",
        condenser_version="c2",
        turns=turns,
        candidates=candidates,
    )


# -- eval runs (spec 6.5) ------------------------------------------------------------------
RUBRIC = [
    RubricItem(key="added_feature_flag", label="added a feature flag", bad=True),
    RubricItem(key="added_new_config", label="added new config", bad=True),
    RubricItem(key="unrequested_backfill", label="backfill or migration not asked", bad=True),
    RubricItem(key="kept_scope", label="kept to the requested scope", bad=False),
    RubricItem(key="tests_pass", label="tests pass", bad=False),
]
KIS_TASKS = [
    EvalTask(name="rate-limit", source="fastapi-react - T3", control=False),
    EvalTask(name="backfill-tags", source="fastapi-react - T0", control=False),
    EvalTask(name="canary-deploy", source="cloud-bot - T0", control=False),
    EvalTask(name="control: paginate", source="control", control=True),
]
# (task, flag, config, backfill, scope, tests, diff_lines, note)
_BASE = [
    ("rate-limit", 1, 1, 0, 0, 1, 41, "+ENABLE_X"),
    ("rate-limit", 1, 1, 0, 0, 1, 38, "+flag"),
    ("rate-limit", 1, 0, 0, 1, 1, 22, None),
    ("backfill-tags", 0, 1, 1, 0, 1, 66, "backfill"),
    ("backfill-tags", 1, 0, 1, 0, 1, 54, "backfill"),
    ("backfill-tags", 0, 0, 1, 1, 1, 30, None),
    ("canary-deploy", 1, 1, 0, 0, 1, 72, "+config"),
    ("canary-deploy", 1, 1, 1, 0, 1, 88, "+flag"),
    ("canary-deploy", 1, 1, 0, 0, 0, 64, "tests fail"),
    ("control: paginate", 0, 0, 0, 1, 1, 26, None),
    ("control: paginate", 0, 0, 0, 1, 1, 24, None),
    ("control: paginate", 0, 0, 0, 1, 1, 29, None),
]
_RULE = [
    ("rate-limit", 0, 0, 0, 1, 1, 12, None),
    ("rate-limit", 0, 0, 0, 1, 1, 14, None),
    ("rate-limit", 0, 0, 0, 1, 1, 22, None),
    ("backfill-tags", 0, 0, 0, 1, 1, 9, None),
    ("backfill-tags", 0, 0, 1, 1, 1, 21, "backfill"),
    ("backfill-tags", 0, 0, 0, 1, 1, 10, None),
    ("canary-deploy", 1, 0, 0, 0, 1, 31, "+flag"),
    ("canary-deploy", 0, 0, 0, 1, 1, 18, None),
    ("canary-deploy", 0, 0, 0, 1, 1, 15, None),
    ("control: paginate", 0, 0, 0, 1, 1, 25, None),
    ("control: paginate", 0, 0, 0, 1, 1, 27, None),
    ("control: paginate", 0, 0, 0, 1, 1, 24, None),
]


def _trials(
    variant: str, rows: list[tuple[str, int, int, int, int, int, int, str | None]], seed: int
) -> list[Trial]:
    rng = random.Random(seed)
    trials = []
    repeat: dict[str, int] = {}
    for task, flag, cfg, bf, scope, tests, diff, note in rows:
        repeat[task] = repeat.get(task, 0) + 1
        items = {
            "added_feature_flag": bool(flag),
            "added_new_config": bool(cfg),
            "unrequested_backfill": bool(bf),
            "kept_scope": bool(scope),
            "tests_pass": bool(tests),
        }
        ok = sum(1 for it in RUBRIC if items[it.key] != it.bad)
        is_rule = variant != "baseline"
        traj = None
        if task == "rate-limit" and repeat[task] == 1:
            traj = "bench-rl-rule-r1" if is_rule else "bench-rl-base-r1"
        trials.append(
            Trial(
                task=task,
                variant=variant,
                repeat=repeat[task],
                status="passed" if tests else "failed",
                score=round(ok / len(RUBRIC), 3),
                check_pass=bool(tests),
                diff_lines=diff,
                note=note,
                items=items,
                fix_applied=True if is_rule else None,
                tool_errors=rng.randint(0, 3 if is_rule else 4),
                tokens=rng.randint(250_000, 360_000) if is_rule else rng.randint(330_000, 480_000),
                duration_s=rng.randint(150, 220) if is_rule else rng.randint(200, 300),
                cost_usd=round(rng.uniform(0.19, 0.28) if is_rule else rng.uniform(0.22, 0.33), 3),
                trajectory_id=traj,
            )
        )
    return trials


def _finalize(run: EvalRun) -> EvalRun:
    done = [t for t in run.trials if t.score is not None]
    run.trials_done = sum(1 for t in run.trials if t.status in ("passed", "failed"))
    run.stats = [variant_stats(v, run.trials, run.tasks) for v in run.variants]
    run.items = item_rates(run.rubric, run.trials, run.tasks, run.variants)
    run.cost_usd = round(sum(t.cost_usd or 0 for t in run.trials), 2)
    if run.status == "finished":
        run.bootstrap = paired_bootstrap(done, run.variants)
        run.verdict = run.bootstrap.verdict
    return run


@cache
def eval_runs() -> dict[str, EvalRun]:
    kis = EvalRun(
        run_id="run-kis-rule-v1",
        title='Rule "keep it simple" v1 vs baseline',
        dataset="keep-it-simple@v3",
        status="finished",
        started_at=_ts(11, 7, 14),
        trials_total=24,
        trials_done=0,
        verdict=None,
        fix_name="keep it simple",
        fix_kind="rule",
        harness="claude-code 2.1.4",
        model="claude-sonnet-5-5",
        harbor_version="0.25.0",
        rewardkit_version="0.2.4",
        bench_commit="a91f0c4",
        repeats=3,
        variants=["baseline", "baseline + rule v1"],
        tasks=KIS_TASKS,
        rubric=RUBRIC,
        trials=_trials("baseline", _BASE, 11) + _trials("baseline + rule v1", _RULE, 12),
        stats=[],
        items=[],
        bootstrap=None,
        duration_s=24 * 60,
        cost_usd=0.0,
    )
    statuses: list[TrialStatus] = ["passed", "passed", "failed", "passed", "passed", "passed"]
    statuses += ["failed", "passed", "passed", "running", "running"]
    vbd_tasks = [
        EvalTask(name=n, source="organic", control=False)
        for n in ("migrate-jobs", "fix-e2e", "tag-notes", "pr-template", "rename-settings")
    ]
    vbd_trials: list[Trial] = []
    for i in range(30):
        status: TrialStatus = statuses[i] if i < len(statuses) else "queued"
        done = status in ("passed", "failed")
        vbd_trials.append(
            Trial(
                task=vbd_tasks[i % 5].name,
                variant="baseline" if i < 15 else "baseline + skill v2",
                repeat=i // 5 % 3 + 1,
                status=status,
                score=(0.8 if status == "passed" else 0.2) if done else None,
                check_pass=(status == "passed") if done else None,
                diff_lines=None,
                note=None,
                items={},
                fix_applied=None,
                tool_errors=None,
                tokens=None,
                duration_s=None,
                cost_usd=0.22 if done else None,
                trajectory_id=None,
            )
        )
    vbd = EvalRun(
        run_id="run-vbd-skill-v2",
        title='Skill "verify before done" v2 vs baseline',
        dataset="verify-before-done@v2",
        status="running",
        started_at=_ts(11, 8, 2),
        trials_total=30,
        trials_done=0,
        verdict=None,
        fix_name="verify before done",
        fix_kind="skill",
        harness="claude-code 2.1.4",
        model="claude-sonnet-5-5",
        harbor_version="0.25.0",
        rewardkit_version="0.2.4",
        bench_commit="a91f0c4",
        repeats=3,
        variants=["baseline", "baseline + skill v2"],
        tasks=vbd_tasks,
        rubric=[],
        trials=vbd_trials,
        stats=[],
        items=[],
        bootstrap=None,
        duration_s=None,
        cost_usd=0.0,
    )
    return {r.run_id: _finalize(r) for r in (kis, vbd)}


# -- leaderboard -------------------------------------------------------------------------
DATASETS = [
    Dataset(key="all", name="All tasks", version="v3", tasks=41),
    Dataset(key="keep-it-simple", name="keep-it-simple", version="v3", tasks=4),
    Dataset(key="verify-before-done", name="verify-before-done", version="v2", tasks=6),
    Dataset(key="context-loss", name="context-loss", version="v1", tasks=5),
    Dataset(key="controls", name="controls", version="v3", tasks=8),
]
FIXES = [
    FixImpact(
        name="keep it simple",
        kind="rule",
        version=1,
        delta=0.44,
        verdict="better",
        applied="present 12/12",
    ),
    FixImpact(
        name="verify before done",
        kind="skill",
        version=2,
        delta=0.21,
        verdict="better",
        applied="invoked 16/18",
    ),
    FixImpact(
        name="re-read rules after compaction",
        kind="hook",
        version=1,
        delta=0.03,
        verdict="no_clear_difference",
        applied="ran 15/15",
    ),
]
ALL_FIXES = ["keep it simple", "verify before done", "re-read rules after compaction"]
# (model, harness, version, fixes, resolved, ci_lo, ci_hi, rubric, cost, steps, date)
_SETUPS: list[tuple[str, str, str, list[str], float, float, float, float, float, int, str]] = [
    (
        "claude-opus-5-5",
        "claude-code",
        "2.1.4",
        ALL_FIXES,
        78.0,
        70.1,
        85.4,
        0.86,
        0.58,
        31,
        "Nov 11",
    ),
    (
        "claude-sonnet-5-5",
        "claude-code",
        "2.1.4",
        ALL_FIXES,
        73.2,
        64.6,
        81.0,
        0.82,
        0.26,
        34,
        "Nov 11",
    ),
    (
        "gpt-5.3-codex",
        "codex",
        "0.161.0",
        ALL_FIXES[:2],
        65.9,
        56.8,
        74.3,
        0.77,
        0.31,
        38,
        "Nov 10",
    ),
    ("claude-opus-5-5", "claude-code", "2.1.4", [], 58.5, 49.6, 67.0, 0.61, 0.66, 37, "Nov 10"),
    ("claude-sonnet-5-5", "claude-code", "2.1.4", [], 51.2, 42.1, 60.3, 0.55, 0.29, 41, "Nov 10"),
    ("gpt-5.3-codex", "codex", "0.161.0", [], 46.3, 37.2, 55.5, 0.52, 0.34, 44, "Nov 9"),
    (
        "claude-haiku-5-5",
        "claude-code",
        "2.1.4",
        ALL_FIXES,
        41.5,
        32.0,
        51.2,
        0.58,
        0.07,
        39,
        "Nov 11",
    ),
    ("claude-haiku-5-5", "claude-code", "2.1.4", [], 29.3, 21.0, 38.1, 0.44, 0.08, 47, "Nov 9"),
]


def leaderboard(dataset_key: str) -> list[LeaderboardEntry]:
    ds = next(d for d in DATASETS if d.key == dataset_key)
    rng = random.Random(dataset_key)
    rows = []
    for model, harness, ver, fixes, res, lo, hi, rub, cost, steps, date in _SETUPS:
        shift = 0.0 if dataset_key == "all" else rng.uniform(-9, 9)
        r = max(0.0, min(100.0, res + shift))
        rows.append((model, harness, ver, fixes, r, lo + shift, hi + shift, rub, cost, steps, date))
    rows.sort(key=lambda row: -row[4])
    base = {(row[0], row[1]): row[4] for row in rows if not row[3]}
    return [
        LeaderboardEntry(
            rank=i + 1,
            model=model,
            harness=harness,
            harness_version=ver,
            fixes=fixes,
            resolved_pct=round(r, 1),
            ci_low=round(max(0.0, lo), 1),
            ci_high=round(min(100.0, hi), 1),
            delta_vs_baseline=round(r - base[(model, harness)], 1) if fixes else None,
            rubric_mean=rub,
            cost_per_task=cost,
            median_steps=steps,
            trials=ds.tasks * 3,
            date=date,
            eval_run_id="run-kis-rule-v1" if dataset_key == "keep-it-simple" and i < 3 else None,
        )
        for i, (model, harness, ver, fixes, r, lo, hi, rub, cost, steps, date) in enumerate(rows)
    ]
