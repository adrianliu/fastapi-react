import { useEffect, useState } from "react";

export default function App() {
  const [notes, setNotes] = useState([]);
  const [text, setText] = useState("");

  useEffect(() => {
    fetch("/api/notes").then((r) => r.json()).then(setNotes);
  }, []);

  async function addNote(e) {
    e.preventDefault();
    if (!text.trim()) return;
    const res = await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const note = await res.json();
    setNotes((prev) => [...prev, note]);
    setText("");
  }

  async function deleteNote(id) {
    await fetch(`/api/notes/${id}`, { method: "DELETE" });
    setNotes((prev) => prev.filter((n) => n.id !== id));
  }

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 480, margin: "40px auto" }}>
      <h1>Notes</h1>
      <form onSubmit={addNote}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="New note" />
        <button type="submit">Add</button>
      </form>
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
