"""Bench: load Harbor job dirs from disk and compare a baseline and a candidate.

Lives in the ``hindcast.bench`` package (a ``hindcast/bench.py`` module would be
shadowed by this package directory).
"""

from __future__ import annotations

import glob
import json
import os
import random
import re
import statistics
import subprocess
import tomllib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TypedDict

HOME = Path.home()
SPIKE_JOBS = Path(
    "/private/tmp/claude-501/-Users-zhen-Development-fastapi-react/"
    "473ba78f-b740-4ec3-8e49-9eb772019357/scratchpad/spike/jobs"
)
DEFAULT_RUNS: list[tuple[str, Path, str, str]] = [
    ("demo", HOME / ".hindcast/demo-run/jobs", "demo-baseline", "demo-rule"),
    ("spike", SPIKE_JOBS, "spike-baseline", "spike-rule"),
    ("phase0", HOME / ".hindcast/fixtures/phase0/jobs", "cc-noskill", "cc-skill"),
]
DATASETS_ROOT = HOME / ".hindcast/fixtures/spike-bench/datasets"
DEFAULT_DATASETS = ["changelog", "changelog+house-style-rule@v1"]
CHECK_KEYS = ("has_entry", "check")
RUBRIC_KEYS = ("rubric", "house_style")
IGNORED_METRICS = ("traj_readable", "guard_flag")

JSONValue = dict[str, "JSONValue"] | list["JSONValue"] | str | int | float | bool | None


def _obj(v: JSONValue) -> dict[str, JSONValue]:
    return v if isinstance(v, dict) else {}


def _num(v: JSONValue) -> float | None:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, int | float):
        return float(v)
    return None


def _load_json(p: Path) -> JSONValue:
    try:
        with p.open() as f:
            data: JSONValue = json.load(f)
        return data
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- runs


@dataclass
class RunDef:
    id: str
    root: Path
    baseline: str
    candidate: str

    @property
    def variants(self) -> list[str]:
        return [self.baseline, self.candidate]


def run_defs() -> list[RunDef]:
    """Runs from HINDCAST_RUNS ("name=root:baseline:candidate;...") or defaults."""
    env = os.environ.get("HINDCAST_RUNS")
    if env:
        out: list[RunDef] = []
        for part in env.split(";"):
            if "=" not in part:
                continue
            name, rest = part.split("=", 1)
            bits = rest.rsplit(":", 2)
            if len(bits) == 3:
                out.append(RunDef(name.strip(), Path(bits[0]), bits[1], bits[2]))
        return out
    return [RunDef(n, r, b, c) for n, r, b, c in DEFAULT_RUNS]


def get_run(run_id: str) -> RunDef | None:
    return next((r for r in run_defs() if r.id == run_id), None)


# ---------------------------------------------------------------- trials


@dataclass
class Trial:
    trial_id: str
    variant: str
    task: str
    path: Path
    finished: bool
    reward: dict[str, float] = field(default_factory=dict)
    criteria: dict[str, tuple[float, str]] = field(default_factory=dict)
    diff: str = ""
    diff_lines: int = 0
    cost_usd: float | None = None
    tokens: float | None = None
    duration_s: float | None = None
    started_at: str | None = None
    exception: str | None = None


def count_diff_lines(diff: str) -> int:
    n = 0
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            n += 1
    return n


def _duration(r: dict[str, JSONValue]) -> float | None:
    a, b = r.get("started_at"), r.get("finished_at")
    if not isinstance(a, str) or not isinstance(b, str):
        return None
    try:
        da = datetime.fromisoformat(a.replace("Z", "+00:00"))
        db = datetime.fromisoformat(b.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (db - da).total_seconds()


def _read_diff(tdir: Path) -> str:
    for cand in [tdir / "verifier/diff.patch", *sorted(tdir.glob("artifacts/**/*.patch"))]:
        if cand.is_file():
            try:
                return cand.read_text(errors="replace")
            except OSError:
                return ""
    return ""


def load_trial(tdir: Path, variant: str) -> Trial:
    raw = _load_json(tdir / "result.json")
    r = _obj(raw)
    task = tdir.name.split("__", 1)[0]
    tn = r.get("task_name")
    if isinstance(tn, str):
        task = tn.split("/")[-1]
    vr = _obj(r.get("verifier_result"))
    rewards = _obj(vr.get("rewards"))
    t = Trial(
        trial_id=f"{tdir.parent.name}~{tdir.name}",
        variant=variant,
        task=task,
        path=tdir,
        finished=bool(raw is not None and rewards),
    )
    for k, v in rewards.items():
        n = _num(v)
        if n is not None:
            t.reward[k] = n
    details = _obj(_obj(_load_json(tdir / "verifier/reward-details.json")).get("judge"))
    crit = details.get("criteria")
    if isinstance(crit, list):
        for c in crit:
            co = _obj(c)
            name, val = co.get("name"), _num(co.get("value"))
            desc = co.get("description")
            if isinstance(name, str) and val is not None:
                t.criteria[name] = (val, desc if isinstance(desc, str) else name)
    ar = _obj(r.get("agent_result"))
    t.cost_usd = _num(ar.get("cost_usd"))
    toks = [_num(ar.get(k)) for k in ("n_input_tokens", "n_output_tokens")]
    if any(x is not None for x in toks):
        t.tokens = sum(x for x in toks if x is not None)
    t.duration_s = _duration(r)
    sa = r.get("started_at")
    t.started_at = sa if isinstance(sa, str) else None
    exc = r.get("exception_info")
    if exc is not None:
        t.exception = json.dumps(exc)[:500]
    t.diff = _read_diff(tdir)
    t.diff_lines = count_diff_lines(t.diff)
    return t


def load_job(root: Path, job: str) -> list[Trial]:
    jdir = root / job
    if not jdir.is_dir():
        return []
    return [load_trial(d, job) for d in sorted(jdir.iterdir()) if d.is_dir() and "__" in d.name]


def find_trial(trial_id: str) -> Trial | None:
    if "~" not in trial_id:
        return None
    job, name = trial_id.split("~", 1)
    if "/" in job or "/" in name or ".." in (job + name):
        return None
    for rd in run_defs():
        if job in rd.variants and (rd.root / job / name).is_dir():
            return load_trial(rd.root / job / name, job)
    return None


def rule_present(trials: list[Trial]) -> str:
    """Whether /app/CLAUDE.md was loaded as instructions in the agent session."""
    seen_session = False
    for t in trials:
        for f in glob.glob(str(t.path / "agent/sessions/**/*.jsonl"), recursive=True):
            seen_session = True
            try:
                text = Path(f).read_text(errors="replace")
            except OSError:
                continue
            if '"path":"/app/CLAUDE.md"' in text.replace(" ", ""):
                return "yes: /app/CLAUDE.md loaded"
    return "no" if seen_session else "unknown"


# ---------------------------------------------------------------- comparison


class Rate(TypedDict):
    passed: int
    n: int


class VariantStats(TypedDict):
    name: str
    n_trials: int
    check_pass_rate: float | None
    rubric_mean: float | None
    metrics: dict[str, float]
    median_diff_lines: float | None
    cost_usd_mean: float | None
    tokens_mean: float | None
    duration_s_mean: float | None
    rule_present: str


class ItemRate(TypedDict):
    id: str
    text: str
    rates: dict[str, Rate]


class Cell(TypedDict):
    variant: str
    trial_id: str
    reward: dict[str, float]
    diff_lines: int


class TaskRow(TypedDict):
    task: str
    cells: list[Cell]


class Comparison(TypedDict):
    run: str
    variants: list[VariantStats]
    items: list[ItemRate]
    tasks: list[TaskRow]
    verdict: str
    verdict_detail: str


def _mean(xs: list[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def check_value(t: Trial) -> float | None:
    for k in CHECK_KEYS:
        if k in t.reward:
            return 1.0 if t.reward[k] >= 1.0 else 0.0
    return None


def score(t: Trial) -> float | None:
    """Per-trial score used for the verdict: rubric if present, else check."""
    for k in RUBRIC_KEYS:
        if k in t.reward:
            return t.reward[k]
    return check_value(t)


def variant_stats(name: str, trials: list[Trial]) -> VariantStats:
    checks = [c for t in trials if (c := check_value(t)) is not None]
    rub = [t.reward[k] for t in trials for k in RUBRIC_KEYS[:1] if k in t.reward]
    if not rub:
        rub = [t.reward[k] for t in trials for k in RUBRIC_KEYS[1:] if k in t.reward]
    keys = sorted({k for t in trials for k in t.reward})
    metrics: dict[str, float] = {}
    for k in keys:
        if k in IGNORED_METRICS:
            continue
        m = _mean([t.reward[k] for t in trials if k in t.reward])
        if m is not None:
            metrics[k] = m
    return VariantStats(
        name=name,
        n_trials=len(trials),
        check_pass_rate=_mean(checks),
        rubric_mean=_mean(rub),
        metrics=metrics,
        median_diff_lines=(
            float(statistics.median([t.diff_lines for t in trials])) if trials else None
        ),
        cost_usd_mean=_mean([t.cost_usd for t in trials if t.cost_usd is not None]),
        tokens_mean=_mean([t.tokens for t in trials if t.tokens is not None]),
        duration_s_mean=_mean([t.duration_s for t in trials if t.duration_s is not None]),
        rule_present=rule_present(trials),
    )


def item_rates(by_variant: dict[str, list[Trial]]) -> list[ItemRate]:
    items: dict[str, ItemRate] = {}
    for v, trials in by_variant.items():
        for t in trials:
            for k, val in t.reward.items():
                if k in IGNORED_METRICS:
                    continue
                it = items.setdefault(k, ItemRate(id=k, text=k, rates={}))
                rate = it["rates"].setdefault(v, Rate(passed=0, n=0))
                rate["n"] += 1
                rate["passed"] += 1 if val >= 1.0 else 0
            for cname, (cval, desc) in t.criteria.items():
                cid = f"criterion:{cname}"
                it = items.setdefault(cid, ItemRate(id=cid, text=desc, rates={}))
                rate = it["rates"].setdefault(v, Rate(passed=0, n=0))
                rate["n"] += 1
                rate["passed"] += 1 if cval >= 1.0 else 0
    for it in items.values():
        for v in by_variant:
            it["rates"].setdefault(v, Rate(passed=0, n=0))
    return list(items.values())


def paired_bootstrap(
    diffs: list[float], resamples: int = 5000, seed: int = 0
) -> tuple[float, float, float]:
    """Mean of per-task (candidate - baseline) and a 95% bootstrap interval."""
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(statistics.fmean(rng.choices(diffs, k=n)) for _ in range(resamples))
    lo = means[int(0.025 * resamples)]
    hi = means[min(resamples - 1, int(0.975 * resamples))]
    return statistics.fmean(diffs), lo, hi


def verdict(base: list[Trial], cand: list[Trial], margin: float = 0.05) -> tuple[str, str]:
    def per_task(ts: list[Trial]) -> dict[str, float]:
        groups: dict[str, list[float]] = {}
        for t in ts:
            s = score(t)
            if s is not None:
                groups.setdefault(t.task, []).append(s)
        return {k: statistics.fmean(v) for k, v in groups.items()}

    pb, pc = per_task(base), per_task(cand)
    paired = sorted(set(pb) & set(pc))
    if len(paired) < 3:
        return "too few tasks", (
            f"{len(paired)} paired task(s); need at least 3 for a paired bootstrap."
        )
    diffs = [pc[k] - pb[k] for k in paired]
    m, lo, hi = paired_bootstrap(diffs)
    detail = (
        f"{len(paired)} paired tasks; mean diff {m:+.3f}, 95% CI [{lo:+.3f}, {hi:+.3f}],"
        f" margin {margin}."
    )
    if lo > margin:
        return "better", detail
    if hi < -margin:
        return "worse", detail
    return "no clear difference", detail


def compare(rd: RunDef) -> Comparison:
    all_by_v = {v: load_job(rd.root, v) for v in rd.variants}
    by_v = {v: [t for t in ts if t.finished] for v, ts in all_by_v.items()}
    skipped = sum(len(all_by_v[v]) - len(by_v[v]) for v in rd.variants)
    tasks: dict[str, TaskRow] = {}
    for v in rd.variants:
        for t in by_v[v]:
            row = tasks.setdefault(t.task, TaskRow(task=t.task, cells=[]))
            row["cells"].append(
                Cell(
                    variant=v,
                    trial_id=t.trial_id,
                    reward=t.reward,
                    diff_lines=t.diff_lines,
                )
            )
    v, detail = verdict(by_v[rd.baseline], by_v[rd.candidate])
    if skipped:
        detail += f" {skipped} trial(s) still running or unfinished were skipped."
    detail += " Scores use rubric (else check); cost is Harbor's estimate."
    return Comparison(
        run=rd.id,
        variants=[variant_stats(n, by_v[n]) for n in rd.variants],
        items=item_rates(by_v),
        tasks=list(tasks.values()),
        verdict=v,
        verdict_detail=detail,
    )


class RunInfo(TypedDict):
    id: str
    name: str
    variants: list[str]
    n_trials: int
    started_at: str | None
    status: str


def list_runs() -> list[RunInfo]:
    out: list[RunInfo] = []
    for rd in run_defs():
        trials = [t for v in rd.variants for t in load_job(rd.root, v)]
        if not trials and not any((rd.root / v).is_dir() for v in rd.variants):
            continue
        done = all(
            (rd.root / v / "result.json").is_file()
            and _obj(_load_json(rd.root / v / "result.json")).get("finished_at")
            for v in rd.variants
        )
        starts = [t.started_at for t in trials if t.started_at]
        out.append(
            RunInfo(
                id=rd.id,
                name=f"{rd.id}: {rd.baseline} vs {rd.candidate}",
                variants=rd.variants,
                n_trials=len(trials),
                started_at=min(starts) if starts else None,
                status="done" if done else "running",
            )
        )
    return out


# ---------------------------------------------------------------- trial detail


class ToolCall(TypedDict):
    function_name: str
    arguments: str


class Step(TypedDict):
    step_id: int
    source: str
    message: str
    tool_calls: list[ToolCall]


def condensed_steps(tdir: Path, limit: int = 400) -> list[Step]:
    traj = _obj(_load_json(tdir / "agent/trajectory.json"))
    steps = traj.get("steps")
    out: list[Step] = []
    if not isinstance(steps, list):
        return out
    for i, s in enumerate(steps):
        so = _obj(s)
        sid = so.get("step_id")
        msg = so.get("message")
        calls: list[ToolCall] = []
        tc = so.get("tool_calls")
        if isinstance(tc, list):
            for c in tc:
                co = _obj(c)
                fn = co.get("function_name")
                calls.append(
                    ToolCall(
                        function_name=fn if isinstance(fn, str) else "?",
                        arguments=json.dumps(co.get("arguments"))[:limit],
                    )
                )
        src = so.get("source")
        out.append(
            Step(
                step_id=sid if isinstance(sid, int) else i,
                source=src if isinstance(src, str) else "?",
                message=(msg if isinstance(msg, str) else json.dumps(msg))[:limit],
                tool_calls=calls,
            )
        )
    return out


# ---------------------------------------------------------------- tasks


class RubricItem(TypedDict):
    id: str
    text: str
    kind: str
    weight: float


class Checks(TypedDict):
    nop: str
    oracle: str
    install: str


class TaskInfo(TypedDict):
    name: str
    dataset: str
    kind: str
    instruction: str
    rubric: list[RubricItem]
    checks: Checks


def _check_status(jobs_dir: Path, prefix: str, expect_pass: bool) -> str:
    """nop must fail the check; oracle must pass it. pass = behaved as expected."""
    vals: list[float] = []
    for f in glob.glob(str(jobs_dir / f"{prefix}*" / "*__*" / "result.json")):
        t = load_trial(Path(f).parent, "")
        c = check_value(t)
        if c is not None:
            vals.append(c)
    if not vals:
        return "unknown"
    ok = all((v >= 1.0) == expect_pass for v in vals)
    return "pass" if ok else "fail"


def _rubric(task_dir: Path) -> list[RubricItem]:
    out: list[RubricItem] = []
    for f in sorted((task_dir / "tests").glob("**/*.toml")):
        try:
            data = tomllib.loads(f.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            continue
        crit = data.get("criterion", [])
        if not isinstance(crit, list):
            continue
        for c in crit:
            if not isinstance(c, dict):
                continue
            w = c.get("weight", 1.0)
            out.append(
                RubricItem(
                    id=str(c.get("name", "")),
                    text=str(c.get("description", "")),
                    kind=str(c.get("type", "binary")),
                    weight=float(w) if isinstance(w, int | float) else 1.0,
                )
            )
    return out


def list_tasks(
    datasets_root: Path | None = None,
    datasets: list[str] | None = None,
    checks_dir: Path | None = None,
) -> list[TaskInfo]:
    root = datasets_root or Path(os.environ.get("HINDCAST_DATASETS", str(DATASETS_ROOT)))
    cdir = checks_dir or SPIKE_JOBS
    checks = Checks(
        nop=_check_status(cdir, "t-nop", expect_pass=False),
        oracle=_check_status(cdir, "t-oracle", expect_pass=True),
        install=_check_status(cdir, "t-install", expect_pass=False),
    )
    out: list[TaskInfo] = []
    for ds in datasets or DEFAULT_DATASETS:
        ddir = root / ds
        if not ddir.is_dir():
            continue
        for tdir in sorted(p for p in ddir.iterdir() if (p / "task.toml").is_file()):
            kind = "reconstructed"
            try:
                meta = tomllib.loads((tdir / "task.toml").read_text()).get("metadata", {})
                if isinstance(meta, dict) and meta.get("kind") == "control":
                    kind = "control"
            except (OSError, tomllib.TOMLDecodeError):
                pass
            instr = tdir / "instruction.md"
            out.append(
                TaskInfo(
                    name=tdir.name,
                    dataset=ds,
                    kind=kind,
                    instruction=instr.read_text() if instr.is_file() else "",
                    rubric=_rubric(tdir),
                    checks=checks,
                )
            )
    return out


# ---------------------------------------------------------------- estimate / run


class Estimate(TypedDict):
    trials: int
    minutes: float
    cost_usd: float


def estimate(variants: int, tasks: int, repeats: int, concurrency: int = 2) -> Estimate:
    trials = max(0, variants) * max(0, tasks) * max(0, repeats)
    return Estimate(
        trials=trials,
        minutes=round(trials * 1.2 / concurrency, 1),
        cost_usd=round(trials * 0.15, 2),
    )


_SAFE_CFG = re.compile(r"^[\w./@+~-]+\.ya?ml$")


def launch(baseline_config: str, candidate_config: str) -> str:
    """Start ``harbor run`` for both configs in the background. Returns a job id."""
    procs: list[subprocess.Popen[bytes]] = []
    secrets = HOME / ".hindcast/secrets.env"
    env = {
        "PATH": f"{HOME}/.local/bin:{HOME}/.docker/bin:/opt/homebrew/bin:/usr/bin:/bin",
        "HOME": str(HOME),
    }
    for cfg in (baseline_config, candidate_config):
        p = Path(cfg).expanduser().resolve()
        if not _SAFE_CFG.match(str(p)) or not p.is_file():
            raise ValueError(f"config not found: {cfg}")
        log = (p.parent / f"{p.stem}.harbor.log").open("ab")
        procs.append(
            subprocess.Popen(
                ["harbor", "run", "-c", str(p), "--env-file", str(secrets), "-y"],
                cwd=str(p.parent),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        )
    try:
        from hindcast import jobs as jobs_mod

        submit = getattr(jobs_mod, "submit", None)
        if callable(submit):
            res = submit("bench.run", {"pids": [p.pid for p in procs]})
            if isinstance(res, str):
                return res
            if isinstance(res, int):
                return str(res)
    except ImportError:
        pass
    return "bench-" + uuid.uuid4().hex[:8]
