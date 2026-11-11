import { useEffect, useState } from "react";

export default function App() {
  const [notes, setNotes] = useState([]);
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  async function request(url, options) {
    const res = await fetch(url, options);
    if (!res.ok) throw new Error("Request failed");
    return res.status === 204 ? null : res.json();
  }

  useEffect(() => {
    request("/api/notes").then(setNotes).catch(() => setError("Could not load notes. Reload to retry."));
  }, []);

  async function addNote(e) {
    e.preventDefault();
    if (!text.trim()) return;
    setError("");
    try {
      const note = await request("/api/notes", {
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

  async function deleteNote(id) {
    setError("");
    try {
      await request(`/api/notes/${id}`, { method: "DELETE" });
      setNotes((prev) => prev.filter((n) => n.id !== id));
    } catch {
      setError("Could not delete note. Try again.");
    }
  }

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 480, margin: "40px auto" }}>
      <h1>Notes</h1>
      <form onSubmit={addNote}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="New note" />
        <button type="submit">Add</button>
      </form>
      {error && <p role="alert">{error}</p>}
      <ul>
        {notes.map((n) => (
          <li key={n.id}>
            {n.text} <button onClick={() => deleteNote(n.id)}>×</button>
          </li>
        ))}
      </ul>
    </main>
  );
}
