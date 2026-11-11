"""Hindcast HTTP API: /api/hindcast/*."""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException

from . import demo
from .models import (
    CandidateSet,
    EvalRun,
    EvalRunSummary,
    Harness,
    Leaderboard,
    Meta,
    Origin,
    ReviewIn,
    ReviewState,
    SessionDetail,
    SessionSummary,
)

GetDb = Callable[[], AbstractContextManager[sqlite3.Connection]]

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS label_reviews"
    " (label_id TEXT PRIMARY KEY, state TEXT NOT NULL, reviewed_at TEXT NOT NULL)"
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA)


def _all_label_ids() -> set[str]:
    return {
        e.label.label_id
        for s in demo.session_details().values()
        for e in s.episodes
        if e.label is not None
    }


def make_router(get_db: GetDb) -> APIRouter:
    router = APIRouter(prefix="/api/hindcast", tags=["hindcast"])

    def reviews() -> dict[str, ReviewState]:
        with get_db() as conn:
            rows = conn.execute("SELECT label_id, state FROM label_reviews").fetchall()
        return {r["label_id"]: ReviewIn(state=r["state"]).state for r in rows}

    def with_reviews(detail: SessionDetail) -> SessionDetail:
        states = reviews()
        detail = detail.model_copy(deep=True)
        for ep in detail.episodes:
            if ep.label and ep.label.label_id in states:
                ep.label.review_state = states[ep.label.label_id]
        return detail

    @router.get("/meta")
    def meta() -> Meta:
        sessions = list(demo.session_details().values())
        by_harness: dict[str, int] = {}
        for s in sessions:
            by_harness[s.agent_name] = by_harness.get(s.agent_name, 0) + 1
        starts = [s.started_at for s in sessions]
        return Meta(
            data_source="demo",
            sessions=len(sessions),
            by_harness=by_harness,
            projects=len({s.project_path for s in sessions}),
            first_started_at=min(starts),
            last_started_at=max(starts),
        )

    @router.get("/sessions")
    def list_sessions(
        harness: Harness | None = None,
        project: str | None = None,
        origin: Origin | None = None,
        has_errors: bool = False,
        has_friction_label: bool = False,
        sort: Literal["friction", "cost", "duration", "started"] = "friction",
    ) -> list[SessionSummary]:
        rows = [
            SessionSummary.model_validate(s.model_dump(exclude={"steps", "subagents", "episodes"}))
            for s in demo.session_details().values()
        ]
        rows = [
            s
            for s in rows
            if (harness is None or s.agent_name == harness)
            and (project is None or s.project_path == project)
            and (origin is None or s.origin == origin)
            and (not has_errors or s.tool_errors > 0)
            and (not has_friction_label or s.has_friction_label)
        ]
        keys: dict[str, Callable[[SessionSummary], float]] = {
            "friction": lambda s: s.friction_score,
            "cost": lambda s: s.total_cost_usd,
            "duration": lambda s: (s.ended_at - s.started_at).total_seconds(),
            "started": lambda s: s.started_at.timestamp(),
        }
        return sorted(rows, key=keys[sort], reverse=True)

    @router.get("/sessions/{trajectory_id}")
    def get_session(trajectory_id: str) -> SessionDetail:
        detail = demo.session_details().get(trajectory_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return with_reviews(detail)

    @router.get("/sessions/{trajectory_id}/candidates")
    def get_candidates(trajectory_id: str) -> CandidateSet:
        cset = demo.candidate_set(trajectory_id)
        if cset is None:
            raise HTTPException(status_code=404, detail="No task candidates for this session")
        return cset

    @router.put("/labels/{label_id}/review")
    def review_label(label_id: str, body: ReviewIn) -> ReviewIn:
        if label_id not in _all_label_ids():
            raise HTTPException(status_code=404, detail="Label not found")
        with get_db() as conn:
            conn.execute(
                "INSERT INTO label_reviews (label_id, state, reviewed_at) VALUES (?, ?, ?)"
                " ON CONFLICT(label_id) DO UPDATE SET state = excluded.state,"
                " reviewed_at = excluded.reviewed_at",
                (label_id, body.state, datetime.now(UTC).isoformat()),
            )
        return body

    @router.get("/evals")
    def list_evals() -> list[EvalRunSummary]:
        return [
            EvalRunSummary.model_validate(r.model_dump(include=set(EvalRunSummary.model_fields)))
            for r in sorted(demo.eval_runs().values(), key=lambda r: r.started_at, reverse=True)
        ]

    @router.get("/evals/{run_id}")
    def get_eval(run_id: str) -> EvalRun:
        run = demo.eval_runs().get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Eval run not found")
        return run

    @router.get("/leaderboard")
    def get_leaderboard(dataset: str = "all") -> Leaderboard:
        ds = next((d for d in demo.DATASETS if d.key == dataset), None)
        if ds is None:
            raise HTTPException(status_code=404, detail="Dataset not found")
        return Leaderboard(
            dataset=ds,
            datasets=demo.DATASETS,
            entries=demo.leaderboard(dataset),
            fixes=demo.FIXES,
        )

    return router
