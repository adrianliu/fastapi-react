from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from hindcast import fix_drafts
from hindcast.api_fixes import ensure_schema, router
from hindcast.jobs import wait_idle
from hindcast.llm.runner import LLMError, Result, Usage
from hindcast.store.schema import core_db, ensure_core_schema

SIMPLE = [
    "no, this is overkill, just do the one-line change",
    "keep it simple, no need for a feature flag",
    "too complex. YAGNI, remove the fallback",
    "why did you add a config option? unnecessary",
]


def _seed() -> None:
    with core_db() as conn:
        ensure_core_schema(conn)
        ensure_schema(conn)
        for i, reaction in enumerate(SIMPLE):
            tid = f"t{i}"
            conn.execute(
                "INSERT INTO trajectories (trajectory_id, session_id, agent_name, project_path) "
                "VALUES (?, ?, 'claude-code', ?)",
                (tid, f"s{i}", f"/p/{i % 2}"),
            )
            rows = [
                (1, "user", "add retries to the client", 0),
                (2, "agent", "Done: added a retry flag, config and a fallback. It works.", 0),
                (3, "user", reaction, 1),
                (4, "agent", "Simplified.", 1),
                (5, "user", "thanks", 2),
            ]
            for step_id, source, msg, turn in rows:
                conn.execute(
                    "INSERT INTO steps (trajectory_id, step_id, timestamp, source, message, "
                    "turn_index) VALUES (?, ?, ?, ?, ?, ?)",
                    (tid, step_id, f"2026-01-0{i + 1}T00:00:0{step_id}Z", source, msg, turn),
                )
            conn.execute(
                "INSERT INTO tool_calls (trajectory_id, step_id, tool_call_id, function_name, "
                "arguments, is_error, error_class) VALUES (?, 2, 'c1', 'Bash', '{}', 1, "
                "'nonzero_exit')",
                (tid,),
            )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("HINDCAST_DB", str(tmp_path / "h.db"))
    _seed()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c


def _fake_result[T: BaseModel](model: type[T], value: T) -> Result[T]:
    return Result(
        value=value,
        model_used="claude-opus",
        duration_ms=1,
        usage=Usage(),
        total_cost_usd=0.0,
        input_sha256="x",
        attempts=1,
        llm_call_id=None,
    )


def _build(client: TestClient) -> int:
    r = client.post("/api/groups/build")
    assert r.status_code == 200
    wait_idle()
    groups = client.get("/api/groups").json()
    simple = [g for g in groups if g["name"] == "Keep it simple"]
    assert simple, groups
    g = simple[0]
    assert g["sessions"] == 4
    assert g["projects"] == 2
    assert g["score"] == 8
    item = g["items"][0]
    assert item["quote"]
    assert "retry flag" in item["agent_before"]
    assert item["signals"]["reopened"] == 1.0
    assert item["signals"]["tool_errors"] == 0.3
    gid = int(g["id"])
    assert client.get(f"/api/groups/{gid}").json()["n_items"] == 4
    return gid


def test_groups_and_fix_flow(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gid = _build(client)
    prompts: list[str] = []

    def fake_run(
        prompt: str, model: type[fix_drafts.RuleFixDraft], **_: object
    ) -> Result[fix_drafts.RuleFixDraft]:
        prompts.append(prompt)
        value = fix_drafts.RuleFixDraft(
            name="keep-it-simple",
            summary="Prefer the smallest change.",
            rule=fix_drafts.RuleBody(text="- Make the smallest change.\n- No flags unasked."),
            rationale=[fix_drafts.RationaleItem(instruction="smallest", correction_ids=[1])],
        )
        return _fake_result(model, value)

    monkeypatch.setattr(fix_drafts, "run_structured", fake_run)
    r = client.post("/api/fixes/draft", json={"group_id": gid})
    assert r.status_code == 200
    wait_idle()
    assert "overkill" in prompts[0]
    fixes = client.get("/api/fixes").json()
    assert len(fixes) == 1
    fid = fixes[0]["id"]
    assert fixes[0]["versions"][0]["author"] == "model"

    bad = client.put(f"/api/fixes/{fid}", json={"content": "\n".join(["x"] * 16)})
    assert bad.status_code == 422
    assert client.put(f"/api/fixes/{fid}", json={"content": "  "}).status_code == 422
    ok = client.put(f"/api/fixes/{fid}", json={"content": "- Keep it simple."})
    assert [v["version"] for v in ok.json()["versions"]] == [1, 2]

    target = tmp_path / "CLAUDE.md"
    target.write_text("# Rules\n")
    prev = client.get(f"/api/fixes/{fid}/install-preview", params={"target": str(target)})
    assert "+- Keep it simple." in prev.json()["diff"]
    assert target.read_text() == "# Rules\n"
    no = client.post(f"/api/fixes/{fid}/install", json={"target": str(target), "confirm": False})
    assert no.json()["applied"] is False
    assert target.read_text() == "# Rules\n"
    yes = client.post(f"/api/fixes/{fid}/install", json={"target": str(target), "confirm": True})
    assert yes.json()["applied"] is True
    assert target.read_text() == "# Rules\n\n- Keep it simple.\n"


def test_draft_fails_when_cli_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    gid = _build(client)

    def boom(prompt: str, model: type[BaseModel], **_: object) -> Result[BaseModel]:
        raise LLMError("cli exploded")

    monkeypatch.setattr(fix_drafts, "run_structured", boom)
    with core_db() as conn, pytest.raises(RuntimeError, match="cli exploded"):
        fix_drafts.draft_fix(conn, gid)
    assert client.get("/api/fixes").json() == []
