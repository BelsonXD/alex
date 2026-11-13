import { useEffect, useState } from "react";
import { api } from "../api";
import type { MemoryItem } from "../types";

export function MemoryView() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [kind, setKind] = useState("fact");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  async function load(next = query) {
    try {
      const rows = await api<MemoryItem[]>(`/api/memories?q=${encodeURIComponent(next)}`);
      setItems(rows);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load memories.");
    }
  }

  useEffect(() => {
    void load("");
    // Initial load only. Search is explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function add() {
    if (!draft.trim()) return;
    await api("/api/memories", { method: "POST", body: JSON.stringify({ content: draft.trim(), kind }) });
    setDraft("");
    await load(query);
  }

  async function save(id: string) {
    await api(`/api/memories/${id}`, { method: "PUT", body: JSON.stringify({ content: editText }) });
    setEditing(null);
    await load(query);
  }

  async function remove(id: string) {
    await api(`/api/memories/${id}`, { method: "DELETE" });
    await load(query);
  }

  return (
    <section className="panel view">
      <header className="view-head">
        <div>
          <p className="eyebrow">Long-term memory</p>
          <h2>What ALEX keeps</h2>
        </div>
      </header>
      <form
        className="row"
        onSubmit={(event) => {
          event.preventDefault();
          void add();
        }}
      >
        <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Remember that Sahib prefers jasmine tea" />
        <select value={kind} onChange={(event) => setKind(event.target.value)}>
          <option value="fact">Fact</option>
          <option value="preference">Preference</option>
          <option value="explicit">Explicit</option>
        </select>
        <button className="solid" type="submit">
          Store
        </button>
      </form>
      <form
        className="row"
        onSubmit={(event) => {
          event.preventDefault();
          void load(query);
        }}
      >
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search memories" />
        <button className="ghost" type="submit">
          Search
        </button>
      </form>
      {error && <p className="error-line">{error}</p>}
      {items.length === 0 && <p className="empty">No memories yet. Teach ALEX in chat with “remember that …”, or store one here.</p>}
      <ul className="memory-list">
        {items.map((item) => (
          <li key={item.id}>
            <div className="memory-meta">
              <span>{item.kind}</span>
              <span>{item.source}</span>
            </div>
            {editing === item.id ? (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void save(item.id);
                }}
              >
                <textarea value={editText} onChange={(event) => setEditText(event.target.value)} rows={3} />
                <div className="row tight">
                  <button className="solid" type="submit">
                    Save
                  </button>
                  <button className="ghost" type="button" onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <p>{item.content}</p>
            )}
            {editing !== item.id && (
              <div className="row tight">
                <button
                  className="ghost"
                  type="button"
                  onClick={() => {
                    setEditing(item.id);
                    setEditText(item.content);
                  }}
                >
                  Edit
                </button>
                <button className="ghost danger" type="button" onClick={() => void remove(item.id)}>
                  Delete
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
