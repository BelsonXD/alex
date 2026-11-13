import { useEffect, useState } from "react";
import { api } from "../api";
import type { AutomationItem, ReminderItem } from "../types";

export function TasksView({ onNotice }: { onNotice: (message: string) => void }) {
  const [reminders, setReminders] = useState<ReminderItem[]>([]);
  const [automations, setAutomations] = useState<AutomationItem[]>([]);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [dueSeconds, setDueSeconds] = useState("");
  const [autoName, setAutoName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [everySeconds, setEverySeconds] = useState("3600");
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState("");

  async function load() {
    const [nextReminders, nextAutomations] = await Promise.all([
      api<ReminderItem[]>("/api/reminders"),
      api<AutomationItem[]>("/api/automations"),
    ]);
    setReminders(nextReminders);
    setAutomations(nextAutomations);
  }

  useEffect(() => {
    void load().catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load tasks."));
    const timer = window.setInterval(() => {
      void load().catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  async function addReminder() {
    setError("");
    const body: Record<string, string | number> = { title, notes };
    if (dueSeconds.trim()) body.due_in_seconds = Math.max(1, Number(dueSeconds));
    else if (dueAt) body.due_at = new Date(dueAt).toISOString();
    else {
      setError("Choose a due time or a number of seconds.");
      return;
    }
    try {
      await api("/api/reminders", { method: "POST", body: JSON.stringify(body) });
      setTitle("");
      setNotes("");
      setDueAt("");
      setDueSeconds("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the reminder.");
    }
  }

  async function addAutomation() {
    setError("");
    try {
      await api("/api/automations", {
        method: "POST",
        body: JSON.stringify({
          name: autoName,
          prompt,
          interval_seconds: Math.max(30, Number(everySeconds) || 3600),
          enabled: true,
        }),
      });
      setAutoName("");
      setPrompt("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the automation.");
    }
  }

  async function runNow(item: AutomationItem) {
    setBusyId(item.id);
    setError("");
    try {
      const result = await api<AutomationItem>(`/api/automations/${item.id}/run`, { method: "POST" });
      onNotice(result.last_result.slice(0, 180) || `${item.name} ran.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The automation failed.");
    } finally {
      setBusyId("");
    }
  }

  return (
    <section className="panel view">
      <header className="view-head">
        <div>
          <p className="eyebrow">Schedule</p>
          <h2>Reminders and automations</h2>
        </div>
      </header>
      {error && <p className="error-line">{error}</p>}
      <div className="split">
        <div>
          <h3>Reminders</h3>
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              void addReminder();
            }}
          >
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Inspect the core" required />
            <input value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Notes" />
            <label>
              Due
              <input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} />
            </label>
            <label>
              Or fire after this many seconds
              <input value={dueSeconds} onChange={(event) => setDueSeconds(event.target.value)} inputMode="numeric" placeholder="15" />
            </label>
            <button className="solid" type="submit">
              Save reminder
            </button>
          </form>
          {reminders.length === 0 && <p className="empty">No reminders.</p>}
          <ul className="card-list">
            {reminders.map((item) => (
              <li key={item.id}>
                <div>
                  <strong>{item.title}</strong>
                  <p className="hint">
                    {item.status} · {item.due_at ? new Date(item.due_at).toLocaleString() : "unscheduled"}
                  </p>
                  {item.notes && <p>{item.notes}</p>}
                </div>
                <div className="row tight">
                  {item.status !== "done" && (
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => void api(`/api/reminders/${item.id}/complete`, { method: "POST" }).then(load)}
                    >
                      Complete
                    </button>
                  )}
                  <button type="button" className="ghost danger" onClick={() => void api(`/api/reminders/${item.id}`, { method: "DELETE" }).then(load)}>
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Automations</h3>
          <p className="hint">A scheduled prompt runs on this computer. Sensitive tools are denied unless you run them yourself in chat.</p>
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              void addAutomation();
            }}
          >
            <input value={autoName} onChange={(event) => setAutoName(event.target.value)} placeholder="Clock check" required />
            <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={3} placeholder="what time is it" required />
            <label>
              Repeat every N seconds (minimum 30)
              <input value={everySeconds} onChange={(event) => setEverySeconds(event.target.value)} inputMode="numeric" />
            </label>
            <button className="solid" type="submit">
              Save automation
            </button>
          </form>
          {automations.length === 0 && <p className="empty">No automations.</p>}
          <ul className="card-list">
            {automations.map((item) => (
              <li key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  <p>{item.prompt}</p>
                  <p className="hint">
                    {item.enabled ? "On" : "Off"} · every {item.interval_seconds}s
                    {item.next_run_at ? ` · next ${new Date(item.next_run_at).toLocaleString()}` : ""}
                  </p>
                  {item.last_result && <pre>{item.last_result.slice(0, 500)}</pre>}
                </div>
                <div className="row tight">
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => void api(`/api/automations/${item.id}`, { method: "PUT", body: JSON.stringify({ enabled: !item.enabled }) }).then(load)}
                  >
                    {item.enabled ? "Pause" : "Enable"}
                  </button>
                  <button type="button" className="ghost" disabled={busyId === item.id} onClick={() => void runNow(item)}>
                    {busyId === item.id ? "Running" : "Run now"}
                  </button>
                  <button type="button" className="ghost danger" onClick={() => void api(`/api/automations/${item.id}`, { method: "DELETE" }).then(load)}>
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
