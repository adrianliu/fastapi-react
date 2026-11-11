"""Offline eval of a drafted fix (spec 6.3): export it to the bench repo, write one job
config per variant, and launch both with Harbor.

- skill: the candidate adds ``skills: [<bench>/skills/<name>]`` on the same dataset.
- rule: the candidate runs a generated sibling dataset ``<dataset>+<name>@v<N>`` whose
  ``environment/CLAUDE.md`` has the rule appended.

Runs land in ``<bench>/jobs/runs/<run_id>-baseline`` and ``-candidate``; ``bench.run_defs``
discovers them there, so the comparison view picks them up while they run.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

HOME = Path.home()
DEFAULT_DATASET = HOME / ".hindcast/fixtures/spike-bench/datasets/changelog"
CLAUDE_CODE_VERSION = "2.1.322"
DEFAULT_MODEL = "anthropic/claude-sonnet-5-5"


def bench_root() -> Path:
    return Path(os.environ.get("HINDCAST_BENCH", str(HOME / ".hindcast/bench"))).expanduser()


def runs_dir() -> Path:
    return bench_root() / "jobs/runs"


def dataset_dir() -> Path:
    return Path(os.environ.get("HINDCAST_EVAL_DATASET", str(DEFAULT_DATASET))).expanduser()


@dataclass
class EvalPlan:
    run_id: str
    baseline_config: Path
    candidate_config: Path
    fix_path: Path
    dataset: Path
    candidate_dataset: Path
    trials: int


def _ensure_repo(root: Path) -> None:
    for sub in ("datasets", "skills", "rules", "jobs/configs", "jobs/runs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    gi = root / ".gitignore"
    if not gi.exists():
        gi.write_text("jobs/runs/\n**/repo.tar\n**/agent/sessions/\n.env*\n")
    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=root, check=False)


def _next_run_id(name: str, version: int) -> str:
    base = f"{name}-v{version}"
    n = 1
    while (runs_dir() / f"{base}-{n}-baseline").exists() or (
        bench_root() / "jobs/configs" / f"{base}-{n}-baseline.yaml"
    ).exists():
        n += 1
    return f"{base}-{n}"


def _config(job_name: str, dataset: Path, repeats: int, skill_dir: Path | None) -> str:
    skills = f"\n    skills: [{_q(skill_dir)}]" if skill_dir else ""
    return (
        f"job_name: {job_name}\n"
        f"jobs_dir: {_q(runs_dir())}\n"
        f"datasets: [{{ path: {_q(dataset)} }}]\n"
        "agents:\n"
        "  - name: claude-code\n"
        f"    model_name: {DEFAULT_MODEL}{skills}\n"
        f'    kwargs: {{ version: "{CLAUDE_CODE_VERSION}", reasoning_effort: medium,'
        " max_budget_usd: 2 }\n"
        f"n_attempts: {repeats}\n"
        "n_concurrent_trials: 3\n"
        "environment: { type: docker }\n"
    )


def _q(p: Path) -> str:
    return '"' + str(p).replace('"', '\\"') + '"'


def _rule_sibling(dataset: Path, name: str, version: int, rule: str) -> Path:
    sibling = bench_root() / "datasets" / f"{dataset.name}+{name}@v{version}"
    if sibling.exists():
        shutil.rmtree(sibling)
    shutil.copytree(dataset, sibling)
    for env_dir in sibling.glob("*/environment"):
        md = env_dir / "CLAUDE.md"
        current = md.read_text() if md.exists() else ""
        sep = "" if not current or current.endswith("\n\n") else "\n"
        md.write_text(current + sep + rule.rstrip("\n") + "\n")
    return sibling


def plan_eval(fix_type: str, name: str, version: int, content: str, repeats: int) -> EvalPlan:
    """Export the fix and write both job configs. Does not launch anything."""
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
        raise ValueError(f"bad fix name {name!r}")
    root = bench_root()
    _ensure_repo(root)
    dataset = dataset_dir()
    if not dataset.is_dir():
        raise ValueError(f"eval dataset not found: {dataset}")
    run_id = _next_run_id(name, version)
    skill_dir: Path | None = None
    if fix_type == "skill":
        skill_dir = root / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content)
        fix_path, cand_dataset = skill_dir, dataset
    else:
        fix_path = root / "rules" / f"{name}.md"
        fix_path.write_text(content.rstrip("\n") + "\n")
        cand_dataset = _rule_sibling(dataset, name, version, content)
    cfgs = root / "jobs/configs"
    base_cfg = cfgs / f"{run_id}-baseline.yaml"
    cand_cfg = cfgs / f"{run_id}-candidate.yaml"
    base_cfg.write_text(_config(f"{run_id}-baseline", dataset, repeats, None))
    cand_cfg.write_text(_config(f"{run_id}-candidate", cand_dataset, repeats, skill_dir))
    n_tasks = sum(1 for p in dataset.iterdir() if (p / "task.toml").is_file())
    return EvalPlan(
        run_id=run_id,
        baseline_config=base_cfg,
        candidate_config=cand_cfg,
        fix_path=fix_path,
        dataset=dataset,
        candidate_dataset=cand_dataset,
        trials=2 * n_tasks * repeats,
    )


def discovered_runs() -> list[tuple[str, Path, str, str]]:
    """(run_id, root, baseline job, candidate job) for eval runs in the bench repo, newest first."""
    root = runs_dir()
    cfgs = bench_root() / "jobs/configs"
    if not cfgs.is_dir():
        return []
    found: list[tuple[float, str]] = []
    for cfg in cfgs.glob("*-baseline.yaml"):
        run_id = cfg.name.removesuffix("-baseline.yaml")
        if (cfgs / f"{run_id}-candidate.yaml").is_file():
            found.append((cfg.stat().st_mtime, run_id))
    found.sort(reverse=True)
    return [(r, root, f"{r}-baseline", f"{r}-candidate") for _, r in found]
