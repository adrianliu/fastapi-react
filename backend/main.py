import os
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DB_PATH = Path(os.environ.get("APP_DB", Path(__file__).parent / "app.db"))


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    with get_db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notes"
            " (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL)"
        )
    yield


app = FastAPI(lifespan=lifespan)


class NoteIn(BaseModel):
    text: str


class Note(NoteIn):
    id: int


@app.get("/api/notes")
def list_notes() -> list[Note]:
    with get_db() as conn:
        rows = conn.execute("SELECT id, text FROM notes ORDER BY id").fetchall()
    return [Note(id=r["id"], text=r["text"]) for r in rows]


@app.post("/api/notes", status_code=201)
def create_note(note: NoteIn) -> Note:
    with get_db() as conn:
        cur = conn.execute("INSERT INTO notes (text) VALUES (?)", (note.text,))
    assert cur.lastrowid is not None
    return Note(id=cur.lastrowid, text=note.text)


@app.delete("/api/notes/{note_id}", status_code=204)
def delete_note(note_id: int) -> None:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Note not found")
