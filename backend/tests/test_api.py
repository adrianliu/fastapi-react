import importlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_DB", str(tmp_path / "test.db"))
    import main

    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def test_create_list_delete(client: TestClient) -> None:
    assert client.get("/api/notes").json() == []

    r = client.post("/api/notes", json={"text": "hello"})
    assert r.status_code == 201
    note = r.json()
    assert note["text"] == "hello"

    assert client.get("/api/notes").json() == [note]

    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert client.get("/api/notes").json() == []


def test_delete_missing_returns_404(client: TestClient) -> None:
    assert client.delete("/api/notes/999").status_code == 404


def test_create_requires_text(client: TestClient) -> None:
    assert client.post("/api/notes", json={}).status_code == 422


@pytest.mark.parametrize("fail", [False, True])
def test_db_transaction_closes_connection(client: TestClient, fail: bool) -> None:
    import main

    connections: list[sqlite3.Connection] = []

    def insert() -> None:
        with main.get_db() as conn:
            connections.append(conn)
            conn.execute("INSERT INTO notes (text) VALUES (?)", ("transaction",))
            if fail:
                raise ValueError("rollback")

    if fail:
        with pytest.raises(ValueError, match="rollback"):
            insert()
    else:
        insert()

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")

    assert len(client.get("/api/notes").json()) == (0 if fail else 1)
