import { useState } from "react";

export interface ScreenAction {
  step: number;
  action: string;
  reason: string;
  summary: string;
  ok?: boolean;
}

export function ScreenView({
  enabled,
  running,
  image,
  actions,
  hotkey,
  dpi,
  onStart,
  onStop,
  onPreview,
}: {
  enabled: boolean;
  running: boolean;
  image: string;
  actions: ScreenAction[];
  hotkey: string;
  dpi: number;
  onStart: (goal: string) => void;
  onStop: () => void;
  onPreview: () => void;
}) {
  const [goal, setGoal] = useState("");
  return (
    <section className="panel view screen">
      <header className="view-head">
        <div>
          <p className="eyebrow">Desktop</p>
          <h2>Screen control</h2>
        </div>
        <button type="button" className={running ? "stop armed" : "stop"} onClick={onStop}>
          Stop
        </button>
      </header>
      <p className="hint">
        A vision model looks at your screen and moves the mouse and keyboard. Starting a task asks for approval.
        Passwords, purchases, sending messages, and deletes ask again. Press {hotkey} or Stop at any time.
        {dpi > 1 ? ` Windows scale ${dpi.toFixed(2)}x is included in the coordinates.` : ""}
      </p>
      {!enabled && <p className="warn-line">Computer use is off. Turn it on in Settings before starting a task. You can still preview the screen.</p>}
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          if (goal.trim()) onStart(goal.trim());
        }}
      >
        <textarea value={goal} onChange={(event) => setGoal(event.target.value)} rows={3} placeholder="Open Notepad and type today's date" />
        <div className="row">
          <button className="solid" type="submit" disabled={!enabled || running || !goal.trim()}>
            {running ? "Running" : "Start task"}
          </button>
          <button className="ghost" type="button" onClick={onPreview}>
            Refresh screen
          </button>
        </div>
      </form>
      <div className="screen-grid">
        <div className="screen-shot">
          {image ? <img src={`data:image/jpeg;base64,${image}`} alt="Latest desktop screenshot" /> : <p className="empty">No screenshot yet.</p>}
        </div>
        <ol className="action-log">
          {actions.length === 0 && <li className="empty">Actions will appear here.</li>}
          {actions.map((item) => (
            <li key={`${item.step}-${item.summary}`}>
              <strong>
                {item.step}. {item.action}
              </strong>
              <span>{item.ok === false ? "denied or failed" : "done"}</span>
              <p>{item.summary || item.reason}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
