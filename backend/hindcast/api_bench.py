"""Bench API: tasks, estimate, run, runs, comparison and trial detail."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hindcast import bench

router = APIRouter(prefix="/api/bench", tags=["bench"])


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Bench reads job dirs straight from disk; no tables needed."""
    del conn


class EstimateIn(BaseModel):
    fix_id: str | int | None = None
    variants: int = 2
    tasks: int = 1
    repeats: int = 3


class RunIn(BaseModel):
    baseline_config: str
    candidate_config: str


class RunOut(BaseModel):
    job_id: str


class TrialDetail(BaseModel):
    trial_id: str
    variant: str
    task: str
    reward: dict[str, float]
    diff: str
    cost_usd: float | None
    steps: list[bench.Step]


@router.get("/tasks")
def get_tasks() -> list[bench.TaskInfo]:
    return bench.list_tasks()


@router.post("/estimate")
def post_estimate(body: EstimateIn) -> bench.Estimate:
    return bench.estimate(body.variants, body.tasks, body.repeats)


@router.post("/run")
def post_run(body: RunIn) -> RunOut:
    try:
        return RunOut(job_id=bench.launch(body.baseline_config, body.candidate_config))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not start harbor: {e}") from e


@router.get("/runs")
def get_runs() -> list[bench.RunInfo]:
    return bench.list_runs()


@router.get("/comparison")
def get_comparison(run: str) -> bench.Comparison:
    rd = bench.get_run(run)
    if rd is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run}")
    return bench.compare(rd)


@router.get("/trials/{trial_id}")
def get_trial(trial_id: str) -> TrialDetail:
    t = bench.find_trial(trial_id)
    if t is None:
        raise HTTPException(status_code=404, detail="trial not found")
    return TrialDetail(
        trial_id=t.trial_id,
        variant=t.variant,
        task=t.task,
        reward=t.reward,
        diff=t.diff,
        cost_usd=t.cost_usd,
        steps=bench.condensed_steps(t.path),
    )
