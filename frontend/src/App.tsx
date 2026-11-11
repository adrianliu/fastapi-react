import { useEffect, useState, type SubmitEvent } from "react";

interface Note {
  id: number;
  text: string;
}

export default function App() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  async function request<T>(url: string, options?: RequestInit): Promise<T> {
    const res = await fetch(url, options);
    if (!res.ok) throw new Error("Request failed");
    return (res.status === 204 ? null : await res.json()) as T;
  }

  useEffect(() => {
    request<Note[]>("/api/notes")
      .then(setNotes)
      .catch(() => {
        setError("Could not load notes. Reload to retry.");
      });
  }, []);

  async function addNote(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!text.trim()) return;
    setError("");
    try {
      const note = await request<Note>("/api/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      setNotes((prev) => [...prev, note]);
      setText("");
    } catch {
      setError("Could not add note. Try again.");
    }
  }

  async function deleteNote(id: number) {
    setError("");
    try {
      await request<null>(`/api/notes/${String(id)}`, { method: "DELETE" });
      setNotes((prev) => prev.filter((n) => n.id !== id));
    } catch {
      setError("Could not delete note. Try again.");
    }
  }

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 480, margin: "40px auto" }}>
      <h1>Notes</h1>
      <form onSubmit={(e) => void addNote(e)}>
        <input
          value={text}
          onChange={(e) => {
            setText(e.target.value);
          }}
          placeholder="New note"
        />
        <button type="submit">Add</button>
      </form>
      {error && <p role="alert">{error}</p>}
      <ul>
        {notes.map((n) => (
          <li key={n.id}>
            {n.text} <button onClick={() => void deleteNote(n.id)}>×</button>
          </li>
        ))}
      </ul>
    </main>
  );
}
