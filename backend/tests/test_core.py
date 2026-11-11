import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hindcast.adapters.claude_code import parse_claude_lines
from hindcast.adapters.common import redact
from hindcast.adapters.importer import import_all
from hindcast.jobs import submit, wait_idle

SID = "sess-1"


def _line(**kw: object) -> str:
    base: dict[str, object] = {"sessionId": SID, "cwd": "/repo", "version": "2.0.0"}
    base.update(kw)
    return json.dumps(base)


def _usage(out: int) -> dict[str, int]:
    return {"input_tokens": 10, "output_tokens": out, "cache_read_input_tokens": 100}


FIXTURE = [
    _line(
        type="user",
        timestamp="2026-01-01T00:00:00Z",
        message={"role": "user", "content": "fix the bug"},
    ),
    _line(
        type="assistant",
        timestamp="2026-01-01T00:00:01Z",
        message={
            "id": "m1",
            "model": "claude-opus-4",
            "content": [{"type": "text", "text": "Looking"}],
            "usage": _usage(1),
        },
    ),
    _line(
        type="assistant",
        timestamp="2026-01-01T00:00:02Z",
        message={
            "id": "m1",
            "model": "claude-opus-4",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/x"}}
            ],
            "usage": _usage(50),
        },
    ),
    _line(
        type="user",
        timestamp="2026-01-01T00:00:03Z",
        message={
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "is_error": True,
                    "content": "File does not exist.",
                }
            ],
        },
    ),
    _line(
        type="user",
        isMeta=True,
        timestamp="2026-01-01T00:00:04Z",
        message={"role": "user", "content": "<local-command-stdout>x</local-command-stdout>"},
    ),
    _line(type="system", subtype="compact_boundary", timestamp="2026-01-01T00:00:05Z"),
    _line(
        type="user",
        timestamp="2026-01-01T00:00:06Z",
        message={"role": "user", "content": "key is sk-abcdefghijklmnopqrstuvwx"},
    ),
]


def test_parse_groups_and_classifies() -> None:
    t = parse_claude_lines(FIXTURE)
    assert t is not None
    assert [s.source for s in t.steps] == ["user", "agent", "system", "system", "user"]
    agent = t.steps[1]
    assert agent.message == "Looking"
    assert agent.completion_tokens == 50  # usage from the last line
    assert agent.prompt_tokens == 110
    assert agent.cached_tokens == 100
    assert agent.cost_usd is not None
    assert agent.cost_usd > 0
    tc = agent.tool_calls[0]
    assert tc.is_error
    assert tc.error_class == "file_not_found"
    assert tc.duration_ms == 1000
    assert t.steps[2].extra["claude_kind"] == "meta"
    assert t.steps[3].extra["claude_kind"] == "compaction"
    assert t.steps[4].turn_index == 1
    assert "sk-abcdefghijklmnop" not in t.steps[4].message


def test_redact_env_and_bearer() -> None:
    out = redact("OPENAI_API_KEY=abc123456789\nAuthorization: Bearer abcdefghijklmnopqrstu")
    assert "abc123456789" not in out
    assert "abcdefghijklmnopqrstu" not in out


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("HINDCAST_DB", str(tmp_path / "h.db"))
    proj = tmp_path / "projects" / "-repo"
    (proj / SID / "subagents").mkdir(parents=True)
    (proj / f"{SID}.jsonl").write_text("\n".join(FIXTURE) + "\n")
    sub = [
        _line(
            type="user",
            timestamp="2026-01-01T00:00:02Z",
            message={"role": "user", "content": "sub task"},
        )
    ]
    (proj / SID / "subagents" / "agent-abc.jsonl").write_text("\n".join(sub) + "\n")
    (proj / SID / "subagents" / "agent-abc.meta.json").write_text(json.dumps({"toolUseId": "t1"}))
    monkeypatch.setenv("HINDCAST_CLAUDE_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("HINDCAST_ARCHIVE", str(tmp_path / "none"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "none"))
    from main import app

    with TestClient(app) as c:
        yield c


def test_import_and_api(client: TestClient) -> None:
    r1 = import_all()
    assert r1["imported"] == 2
    assert r1["failed"] == 0
    assert import_all()["unchanged"] == 2
    home = client.get("/api/home").json()
    assert home["sessions"] == 1
    assert home["trajectories"] == 2
    assert home["harnesses"] == {"claude-code": 1}
    lst = client.get("/api/sessions?limit=1").json()
    assert lst["total"] == 1
    item = lst["items"][0]
    assert item["n_errors"] == 1
    assert item["n_subagents"] == 1
    assert item["first_prompt"] == "fix the bug"
    assert client.get("/api/sessions?q=bug").json()["total"] == 1
    assert client.get("/api/sessions?q=zebra").json()["total"] == 0
    detail = client.get(f"/api/sessions/{SID}").json()
    assert detail["steps"][1]["tool_calls"][0]["subagent_trajectory_id"] == f"{SID}:abc"
    assert detail["subagents"][0]["trajectory_id"] == f"{SID}:abc"
    assert client.get("/api/sessions/nope").status_code == 404


def test_jobs(client: TestClient) -> None:
    ok = submit("t", lambda p: {"x": 1})
    bad = submit("t", lambda p: {"y": 1 // 0})
    wait_idle()
    assert client.get(f"/api/jobs/{ok}").json()["result"] == {"x": 1}
    j = client.get(f"/api/jobs/{bad}").json()
    assert j["status"] == "failed"
    assert "ZeroDivisionError" in j["error"]
    assert len(client.get("/api/jobs").json()) == 2
