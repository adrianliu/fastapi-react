import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DB_PATH = Path(os.environ.get("APP_DB", Path(__file__).parent / "app.db"))


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL)"
        )
    yield


app = FastAPI(lifespan=lifespan)


class NoteIn(BaseModel):
    text: str


class Note(NoteIn):
    id: int


@app.get("/api/notes", response_model=list[Note])
def list_notes():
    with get_db() as conn:
        rows = conn.execute("SELECT id, text FROM notes ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/notes", response_model=Note, status_code=201)
def create_note(note: NoteIn):
    with get_db() as conn:
        cur = conn.execute("INSERT INTO notes (text) VALUES (?)", (note.text,))
    return {"id": cur.lastrowid, "text": note.text}


@app.delete("/api/notes/{note_id}", status_code=204)
def delete_note(note_id: int):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Note not found")
