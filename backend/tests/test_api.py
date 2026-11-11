import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB", str(tmp_path / "test.db"))
    import main

    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def test_create_list_delete(client):
    assert client.get("/api/notes").json() == []

    r = client.post("/api/notes", json={"text": "hello"})
    assert r.status_code == 201
    note = r.json()
    assert note["text"] == "hello"

    assert client.get("/api/notes").json() == [note]

    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert client.get("/api/notes").json() == []


def test_delete_missing_returns_404(client):
    assert client.delete("/api/notes/999").status_code == 404


def test_create_requires_text(client):
    assert client.post("/api/notes", json={}).status_code == 422
