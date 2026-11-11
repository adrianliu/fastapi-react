from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hindcast import bench
from hindcast.api_bench import router

FIX = Path(__file__).parent / "fixtures" / "bench" / "jobs"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("HINDCAST_RUNS", f"fx={FIX}:demo-baseline:demo-rule")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c


def test_runs(client: TestClient) -> None:
    runs = client.get("/api/bench/runs").json()
    assert [r["id"] for r in runs] == ["fx"]
    assert runs[0]["n_trials"] == 2


def test_comparison(client: TestClient) -> None:
    c = client.get("/api/bench/comparison", params={"run": "fx"}).json()
    base, cand = c["variants"]
    assert base["check_pass_rate"] == 1.0
    assert cand["check_pass_rate"] == 1.0
    assert base["rubric_mean"] == 0.0
    assert cand["rubric_mean"] == 1.0
    assert base["median_diff_lines"] > 0
    assert c["verdict"] == "too few tasks"
    items = {i["id"]: i for i in c["items"]}
    assert items["criterion:ticket_marker"]["rates"]["demo-rule"] == {
        "passed": 1,
        "n": 1,
    }
    assert c["tasks"][0]["task"] == "changelog-entry"
    assert client.get("/api/bench/comparison", params={"run": "x"}).status_code == 404


def test_trial_detail(client: TestClient) -> None:
    c = client.get("/api/bench/comparison", params={"run": "fx"}).json()
    tid = c["tasks"][0]["cells"][0]["trial_id"]
    t = client.get(f"/api/bench/trials/{tid}").json()
    assert t["diff"].startswith("diff --git")
    assert t["steps"]
    assert "tool_calls" in t["steps"][0]
    assert client.get("/api/bench/trials/nope~x").status_code == 404


def test_estimate(client: TestClient) -> None:
    r = client.post(
        "/api/bench/estimate", json={"fix_id": None, "variants": 2, "tasks": 5, "repeats": 3}
    ).json()
    assert r == {"trials": 30, "minutes": 18.0, "cost_usd": 4.5}


def test_diff_lines_and_bootstrap() -> None:
    assert bench.count_diff_lines("--- a\n+++ b\n+x\n-y\n z") == 2
    trials = [
        bench.Trial(f"t{i}", v, f"task{i}", FIX, True, reward={"check": 1, "rubric": r})
        for i in range(4)
        for v, r in (("b", 0.0), ("c", 1.0))
    ]
    base = [t for t in trials if t.variant == "b"]
    cand = [t for t in trials if t.variant == "c"]
    assert bench.verdict(base, cand)[0] == "better"
    assert bench.verdict(cand, base)[0] == "worse"
    assert bench.verdict(base, base)[0] == "no clear difference"
