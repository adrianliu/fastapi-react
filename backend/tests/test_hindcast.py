import importlib
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hindcast.friction import repeat_failure_runs, score_episode
from hindcast.models import Step, ToolCall, Trial
from hindcast.stats import paired_bootstrap

RATE_LIMIT = "5c0e2a91-b71d"
AUTH = "a8c1f0d2-6e44"
T0 = datetime(2026, 11, 9, tzinfo=UTC)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_DB", str(db_path))
    import main

    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


# -- API -----------------------------------------------------------------------------------
def test_sessions_sorted_by_friction(client: TestClient) -> None:
    rows = client.get("/api/hindcast/sessions").json()
    scores = [r["friction_score"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert "steps" not in rows[0]


def test_sessions_filters(client: TestClient) -> None:
    codex = client.get("/api/hindcast/sessions", params={"harness": "codex"}).json()
    assert codex
    assert {r["agent_name"] for r in codex} == {"codex"}

    labelled = client.get("/api/hindcast/sessions", params={"has_friction_label": True}).json()
    everything = client.get("/api/hindcast/sessions").json()
    assert all(r["has_friction_label"] for r in labelled)
    assert len(labelled) < len(everything)

    bench = client.get("/api/hindcast/sessions", params={"origin": "benchmark"}).json()
    assert {r["origin"] for r in bench} == {"benchmark"}

    by_cost = client.get("/api/hindcast/sessions", params={"sort": "cost"}).json()
    costs = [r["total_cost_usd"] for r in by_cost]
    assert costs == sorted(costs, reverse=True)

    assert client.get("/api/hindcast/sessions", params={"sort": "nope"}).status_code == 422


def test_session_detail(client: TestClient) -> None:
    assert client.get("/api/hindcast/sessions/missing").status_code == 404
    s = client.get(f"/api/hindcast/sessions/{RATE_LIMIT}").json()
    step_ids = {st["step_id"] for st in s["steps"]}
    assert len(s["episodes"]) == s["turns"]
    # Totals cover the subagent tree.
    sub_steps = sum(len(sub["steps"]) for sub in s["subagents"])
    assert s["total_steps"] == len(s["steps"]) + sub_steps
    labelled = [e for e in s["episodes"] if e["label"]]
    assert labelled
    for ep in labelled:
        for item in ep["label"]["friction"]:
            assert set(item["evidence_step_ids"]) <= step_ids
    # Every subagent hangs off a tool call in the parent.
    call_ids = {c["tool_call_id"] for st in s["steps"] for c in st["tool_calls"]}
    assert {sub["parent_tool_call_id"] for sub in s["subagents"]} <= call_ids


def test_review_label_persists(client: TestClient, db_path: Path) -> None:
    s = client.get(f"/api/hindcast/sessions/{RATE_LIMIT}").json()
    label = next(e["label"] for e in s["episodes"] if e["label"])
    assert label["review_state"] == "pending"

    url = f"/api/hindcast/labels/{label['label_id']}/review"
    assert client.put(url, json={"state": "confirmed"}).json() == {"state": "confirmed"}
    s = client.get(f"/api/hindcast/sessions/{RATE_LIMIT}").json()
    assert next(e["label"] for e in s["episodes"] if e["label"])["review_state"] == "confirmed"

    client.put(url, json={"state": "rejected"})
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT label_id, state FROM label_reviews").fetchall()
    assert rows == [(label["label_id"], "rejected")]


def test_review_label_errors(client: TestClient) -> None:
    assert (
        client.put("/api/hindcast/labels/nope/review", json={"state": "confirmed"}).status_code
        == 404
    )
    s = client.get(f"/api/hindcast/sessions/{RATE_LIMIT}").json()
    label_id = next(e["label"] for e in s["episodes"] if e["label"])["label_id"]
    url = f"/api/hindcast/labels/{label_id}/review"
    assert client.put(url, json={"state": "maybe"}).status_code == 422


def test_candidates(client: TestClient) -> None:
    assert client.get(f"/api/hindcast/sessions/{RATE_LIMIT}/candidates").status_code == 404
    cset = client.get(f"/api/hindcast/sessions/{AUTH}/candidates").json()
    c1 = next(c for c in cset["candidates"] if c["candidate_id"] == "C1")
    hint = next(sp["excerpt"] for sp in c1["spans"] if sp["role"] == "solution_hint")
    assert hint not in c1["instruction"]
    assert "httpOnly cookie" in c1["instruction"]
    ids = {c["candidate_id"] for c in cset["candidates"]}
    for c in cset["candidates"]:
        assert {d["candidate_id"] for d in c["depends_on"]} <= ids - {c["candidate_id"]}


def test_evals(client: TestClient) -> None:
    runs = client.get("/api/hindcast/evals").json()
    assert {r["status"] for r in runs} == {"running", "finished"}
    assert client.get("/api/hindcast/evals/missing").status_code == 404
    run = client.get("/api/hindcast/evals/run-kis-rule-v1").json()
    assert run["verdict"] == "better"
    assert run["bootstrap"]["ci_low"] > run["bootstrap"]["margin"]
    flag = next(i for i in run["items"] if i["key"] == "added_feature_flag")
    assert (flag["baseline"], flag["candidate"], flag["n"]) == (7, 1, 9)
    assert run["trials_done"] == run["trials_total"] == 24


def test_leaderboard(client: TestClient) -> None:
    board = client.get("/api/hindcast/leaderboard").json()
    pct = [e["resolved_pct"] for e in board["entries"]]
    assert pct == sorted(pct, reverse=True)
    assert [e["rank"] for e in board["entries"]] == list(range(1, len(pct) + 1))
    assert all((e["delta_vs_baseline"] is None) == (not e["fixes"]) for e in board["entries"])
    assert client.get("/api/hindcast/leaderboard", params={"dataset": "x"}).status_code == 404
    kis = client.get("/api/hindcast/leaderboard", params={"dataset": "keep-it-simple"}).json()
    assert kis["dataset"]["key"] == "keep-it-simple"


def test_meta(client: TestClient) -> None:
    meta = client.get("/api/hindcast/meta").json()
    assert meta["data_source"] == "demo"
    assert sum(meta["by_harness"].values()) == meta["sessions"]


# -- rule pass (spec 4.2) ------------------------------------------------------------------
def _call(fn: str, error: str | None = None) -> ToolCall:
    return ToolCall(
        tool_call_id=f"c{fn}",
        function_name=fn,
        tool_kind="shell",
        summary=fn,
        content=None,
        is_error=error is not None,
        error_class="nonzero_exit" if error else None,
        started_at=T0,
        duration_ms=10,
    )


def _step(step_id: int, source: str = "agent", message: str = "", *calls: ToolCall) -> Step:
    return Step.model_validate(
        {
            "step_id": step_id,
            "timestamp": T0,
            "source": source,
            "message": message,
            "turn_index": 0,
            "duration_ms": 0,
            "tool_calls": [c.model_dump() for c in calls],
        }
    )


def test_repeat_failure_runs() -> None:
    errs = [_step(i, "agent", "", _call("Bash", "x")) for i in range(1, 4)]
    assert repeat_failure_runs(errs) == 1
    assert repeat_failure_runs(errs[:2]) == 0
    spread = [_step(i, "agent", "", _call("Bash", "x")) for i in (1, 5, 30)]
    assert repeat_failure_runs(spread) == 0


def test_score_episode_correction_and_reopened() -> None:
    turn = [_step(1, "user", "add x"), _step(2, "agent", "Done, all tests pass.")]
    sig = score_episode(turn, _step(3, "user", "no need for a flag"))
    assert {s.name for s in sig.signals} == {"correction", "reopened"}
    assert sig.score == 6.0


def test_score_episode_acceptance_is_not_reopened() -> None:
    turn = [_step(1, "user", "add x"), _step(2, "agent", "Done.")]
    assert score_episode(turn, _step(3, "user", "great, thanks")).score == 0.0
    assert score_episode(turn, None).score == 0.0


def test_bootstrap_too_few_tasks() -> None:
    trials = [
        Trial.model_validate(
            {
                "task": "a",
                "variant": v,
                "repeat": 1,
                "status": "passed",
                "score": s,
                "check_pass": True,
                "diff_lines": 1,
                "note": None,
                "items": {},
                "fix_applied": None,
                "tool_errors": 0,
                "tokens": 0,
                "duration_s": 0,
                "cost_usd": 0.0,
                "trajectory_id": None,
            }
        )
        for v, s in (("base", 0.2), ("cand", 0.9))
    ]
    assert paired_bootstrap(trials, ["base", "cand"]).verdict == "too_few_tasks"
