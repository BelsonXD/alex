import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ApprovalDialog } from "./components/ApprovalDialog";
import { Markdown } from "./components/Markdown";
import { MemoryView } from "./components/MemoryView";
import { ProjectsView } from "./components/ProjectsView";
import { Reactor } from "./components/Reactor";
import { ScreenView, type ScreenAction } from "./components/ScreenView";
import { SettingsView } from "./components/SettingsView";
import { TasksView } from "./components/TasksView";
import type { Approval, ChatMessage, Conversation, CoreState, ProjectItem, ServerEvent, Settings, SystemStatus, UploadItem, View } from "./types";
import { interruptSpeech, listen, speak } from "./voice";

export function App() {
  const [view, setView] = useState<View>("chat");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Record<string, ChatMessage[]>>({});
  const [draft, setDraft] = useState("");
  const [core, setCore] = useState<CoreState>("idle");
  const [level, setLevel] = useState(0);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [bootError, setBootError] = useState("");
  const [toast, setToast] = useState("");
  const [listening, setListening] = useState(false);
  const [attachments, setAttachments] = useState<UploadItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [activeProject, setActiveProject] = useState<ProjectItem | null>(null);
  const [update, setUpdate] = useState<{ update_available?: boolean; detail?: string; notes?: string; latest?: string; version?: string } | null>(null);
  const [updating, setUpdating] = useState(false);
  const [screenImage, setScreenImage] = useState("");
  const [screenActions, setScreenActions] = useState<ScreenAction[]>([]);
  const [screenRunning, setScreenRunning] = useState(false);
  const [clock, setClock] = useState(() => new Date());
  const socketRef = useRef<WebSocket | null>(null);
  const activeRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const attachmentsRef = useRef(attachments);
  const projectRef = useRef(activeProject);
  const sendRef = useRef<(text: string) => void>(() => undefined);
  attachmentsRef.current = attachments;
  projectRef.current = activeProject;
  const listenStop = useRef<(() => Promise<string>) | null>(null);
  const handlerRef = useRef<(event: ServerEvent) => void>(() => undefined);
  const settingsRef = useRef(settings);
  const approvalRef = useRef(approval);
  settingsRef.current = settings;
  approvalRef.current = approval;

  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  async function boot() {
    try {
      const [nextSettings, nextStatus, nextConversations] = await Promise.all([
        api<Settings>("/api/settings"),
        api<SystemStatus>("/api/system/status"),
        api<Conversation[]>("/api/conversations"),
      ]);
      setSettings(nextSettings);
      setStatus(nextStatus);
      setConversations(nextConversations);
      setBootError("");
    } catch (err) {
      setBootError(err instanceof Error ? err.message : "Backend unreachable.");
    }
  }

  useEffect(() => {
    void api<{ update_available?: boolean; detail?: string; notes?: string; latest?: string; version?: string }>("/api/system/update")
      .then(setUpdate)
      .catch(() => undefined);
    const timer = window.setInterval(() => {
      void api<{ update_available?: boolean; detail?: string; notes?: string; latest?: string; version?: string }>("/api/system/update")
        .then(setUpdate)
        .catch(() => undefined);
    }, 10 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!settings?.voice_wake) return;
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Ctor) {
      setToast("Wake word needs Edge or Chrome, or turn it off in Settings.");
      return;
    }
    const recognition = new Ctor() as unknown as {
      continuous: boolean;
      interimResults: boolean;
      onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
      onend: (() => void) | null;
      start: () => void;
      stop: () => void;
    };
    recognition.continuous = true;
    recognition.interimResults = false;
    const phrase = (settings.wake_phrase || "alex").toLowerCase();
    recognition.onresult = (event) => {
      let text = "";
      for (let index = 0; index < event.results.length; index += 1) text += event.results[index][0].transcript;
      const lower = text.toLowerCase();
      const at = lower.lastIndexOf(phrase);
      if (at < 0) return;
      interruptSpeech();
      const command = text.slice(at + phrase.length).trim();
      if (command) sendRef.current(command);
    };
    recognition.onend = () => {
      try {
        recognition.start();
      } catch {
        /* already started */
      }
    };
    try {
      recognition.start();
    } catch {
      setToast("Wake word could not start. Allow the microphone in the browser.");
    }
    return () => recognition.stop();
  }, [settings?.voice_wake, settings?.wake_phrase]);

  useEffect(() => {
    void boot();
    const poll = window.setInterval(() => {
      void api<SystemStatus>("/api/system/status").then(setStatus).catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(poll);
  }, []);

  useEffect(() => {
    let stop = false;
    let retry = 400;
    let socket: WebSocket | null = null;
    const connect = () => {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${location.host}/ws`);
      socketRef.current = socket;
      socket.onopen = () => {
        setConnected(true);
        retry = 400;
      };
      socket.onclose = () => {
        setConnected(false);
        if (!stop) {
          window.setTimeout(connect, retry);
          retry = Math.min(5000, retry * 2);
        }
      };
      socket.onmessage = (event) => handlerRef.current(JSON.parse(event.data) as ServerEvent);
    };
    connect();
    return () => {
      stop = true;
      socket?.close();
    };
    // The socket lives for the session. onServer reads refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, activeId, busy]);

  function onServer(event: ServerEvent) {
    if (event.type === "computer_frame" && event.image) {
      setScreenImage(String(event.image));
      setScreenRunning(true);
      setCore("thinking");
      return;
    }
    if (event.type === "computer_action") {
      setScreenActions((current) => [
        ...current,
        {
          step: Number(event.step || current.length + 1),
          action: String(event.action || ""),
          reason: String(event.reason || ""),
          summary: String(event.summary || ""),
          ok: event.ok,
        },
      ]);
      return;
    }
    if (event.type === "computer_done") {
      setScreenRunning(false);
      setCore("idle");
      setToast(String(event.summary || "Screen task finished."));
      return;
    }
    if (event.type === "computer_status") {
      setScreenRunning(Boolean(event.running));
      return;
    }
    if (event.type === "notification" && event.notification) {
      setToast(`${event.notification.title}: ${event.notification.body}`);
      return;
    }
    if (event.type === "conversation" && event.conversation_id) {
      const id = event.conversation_id;
      const previous = activeRef.current ?? "draft";
      activeRef.current = id;
      setActiveId(id);
      if (previous !== id) {
        setMessages((current) => {
          const moved = current[previous] ?? [];
          const next = { ...current, [id]: [...(current[id] ?? []), ...moved] };
          if (previous === "draft") delete next.draft;
          return next;
        });
      }
      void api<Conversation[]>("/api/conversations").then(setConversations).catch(() => undefined);
      return;
    }
    if (event.type === "status" && event.state && !approvalRef.current) {
      setCore(event.state);
    }
    if (event.type === "approval_required" && event.approval_id && event.tool) {
      setApproval({
        approval_id: event.approval_id,
        tool: event.tool,
        summary: event.summary || "",
        arguments: event.arguments || {},
        risk: event.risk || "",
      });
      setCore("approval");
      return;
    }
    const cid = event.conversation_id || activeRef.current || "draft";
    if (event.type === "token") {
      setMessages((current) => appendToken(current, cid, event.text || ""));
    } else if (event.type === "tool" && event.call_id) {
      setMessages((current) =>
        append(current, cid, {
          id: event.call_id || crypto.randomUUID(),
          role: "tool",
          toolName: event.name,
          content: "Waiting for the tool…",
          pending: true,
        }),
      );
    } else if (event.type === "tool_result" && event.call_id) {
      setMessages((current) => updateTool(current, cid, event));
    } else if (event.type === "error") {
      setMessages((current) =>
        append(current, cid, { id: crypto.randomUUID(), role: "error", content: event.detail || "Unknown error" }),
      );
      setBusy(false);
      setCore("idle");
    } else if (event.type === "done") {
      setMessages((current) => finish(current, cid));
      setBusy(false);
      setCore("idle");
      if (settingsRef.current?.auto_speak && event.text) void say(event.text);
      void api<Conversation[]>("/api/conversations").then(setConversations).catch(() => undefined);
    }
  }
  handlerRef.current = onServer;

  function send(text: string) {
    const content = text.trim();
    const files = attachmentsRef.current;
    if ((!content && files.length === 0) || busy || !connected) return;
    const key = activeRef.current ?? "draft";
    const shown = [content, ...files.map((file) => `[${file.kind}] ${file.filename}`)].filter(Boolean).join("\n");
    setMessages((current) => append(current, key, { id: crypto.randomUUID(), role: "user", content: shown }));
    setDraft("");
    setAttachments([]);
    setBusy(true);
    setCore("thinking");
    socketRef.current?.send(
      JSON.stringify({
        type: "chat",
        content,
        conversation_id: activeRef.current,
        project_id: activeRef.current ? undefined : projectRef.current?.id,
        attachment_ids: files.map((file) => file.id),
      }),
    );
  }
  sendRef.current = send;

  async function attachFiles(list: FileList | null) {
    if (!list?.length) return;
    setUploading(true);
    setToast("");
    try {
      for (const file of Array.from(list)) {
        const body = new FormData();
        body.append("file", file);
        const saved = await api<UploadItem>("/api/uploads", { method: "POST", body });
        saved.preview = file.type.startsWith("image/") ? URL.createObjectURL(file) : "";
        setAttachments((current) => [...current, saved]);
      }
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function openConversation(id: string) {
    setActiveId(id);
    activeRef.current = id;
    const rows = await api<Array<{ id: string; role: string; content: string; tool_name?: string; ok?: boolean; sources?: ChatMessage["sources"] }>>(
      `/api/conversations/${id}/messages`,
    );
    setMessages((current) => ({
      ...current,
      [id]: rows.map((row) => ({
        id: row.id,
        role: row.role === "tool" ? "tool" : row.role === "user" ? "user" : "assistant",
        content: row.content,
        toolName: row.tool_name,
        ok: row.ok,
        sources: row.sources,
      })),
    }));
  }

  function newChat(project?: ProjectItem | null) {
    setActiveId(null);
    activeRef.current = null;
    setActiveProject(project ?? null);
    setView("chat");
  }

  async function deleteConversation(id: string) {
    await api(`/api/conversations/${id}`, { method: "DELETE" });
    if (activeRef.current === id) newChat();
    setConversations(await api<Conversation[]>("/api/conversations"));
  }

  function decide(approved: boolean) {
    if (!approval) return;
    socketRef.current?.send(JSON.stringify({ type: "approval_decision", approval_id: approval.approval_id, approved }));
    setApproval(null);
    setCore("thinking");
  }

  async function holdStart() {
    if (listening || busy) return;
    interruptSpeech();
    setListening(true);
    setCore("listening");
    setToast("");
    try {
      const session = await listen(settings?.voice.stt || "browser", setLevel, setDraft);
      listenStop.current = session.stop;
    } catch (err) {
      setListening(false);
      setCore("idle");
      setToast(err instanceof Error ? err.message : "Microphone unavailable.");
    }
  }

  async function holdEnd() {
    if (!listenStop.current) {
      setListening(false);
      setCore("idle");
      return;
    }
    const stop = listenStop.current;
    listenStop.current = null;
    try {
      const text = await stop();
      setListening(false);
      setLevel(0);
      if (text) send(text);
      else {
        setCore("idle");
        setToast("No speech detected.");
      }
    } catch (err) {
      setListening(false);
      setLevel(0);
      setCore("idle");
      setToast(err instanceof Error ? err.message : "Transcription failed.");
    }
  }

  async function say(text: string) {
    setCore("speaking");
    try {
      await speak(text, setLevel, settings?.voice_provider === "browser" ? settings.voice_id : "");
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Voice playback failed.");
    } finally {
      setLevel(0);
      setCore((current) => (current === "speaking" ? "idle" : current));
    }
  }

  const thread = messages[activeId ?? "draft"] ?? [];

  if (!settings) {
    return (
      <main className="boot">
        <Reactor state="thinking" level={0.2} />
        <h1>ALEX</h1>
        {bootError ? (
          <>
            <p>{bootError}</p>
            <button className="solid" type="button" onClick={() => void boot()}>
              Retry
            </button>
          </>
        ) : (
          <p>Contacting the local core…</p>
        )}
      </main>
    );
  }

  return (
    <div className="shell">
      <div className="mast">
      <header className="topbar">
        <div className="brand">
          <span>ALEX</span>
          <small>Personal interface</small>
        </div>
        <div className="pills">
          <em className={connected ? "ok" : "warn"}>{connected ? "Link" : "Offline link"}</em>
          <em>{status?.provider_label || settings.provider}</em>
          <em>{status?.provider_configured ? "Model ready" : "Not configured"}</em>
          <em>CPU {Math.round(status?.cpu_percent ?? 0)}%</em>
          <em>RAM {Math.round(status?.memory_percent ?? 0)}%</em>
          <em>{clock.toLocaleTimeString()}</em>
        </div>
        <button
          type="button"
          className={screenRunning ? "stop armed" : "stop"}
          onClick={() => {
            socketRef.current?.send(JSON.stringify({ type: "computer_stop" }));
            void api("/api/computer/stop", { method: "POST" }).catch(() => undefined);
            setScreenRunning(false);
            setCore("idle");
          }}
        >
          Stop
        </button>
      </header>
      {update?.update_available && (
        <div className="update-banner">
          <div>
            <strong>Update available — {update.latest}</strong>
            <p>{update.notes || update.detail}</p>
          </div>
          <button
            type="button"
            className="solid"
            disabled={updating}
            onClick={() => {
              setUpdating(true);
              void api("/api/system/update/apply", { method: "POST" })
                .then(() => setToast("Updating. ALEX will restart itself."))
                .catch((err: unknown) => {
                  setUpdating(false);
                  setToast(err instanceof Error ? err.message : "Update failed and the previous version was restored.");
                });
            }}
          >
            {updating ? "Updating" : "Update now"}
          </button>
        </div>
      )}
      </div>
      <nav className="nav">
        <button type="button" className={view === "chat" ? "on" : ""} onClick={() => setView("chat")}>
          Chat
        </button>
        <button type="button" className={view === "memory" ? "on" : ""} onClick={() => setView("memory")}>
          Memory
        </button>
        <button type="button" className={view === "projects" ? "on" : ""} onClick={() => setView("projects")}>
          Projects
        </button>
        <button type="button" className={view === "tasks" ? "on" : ""} onClick={() => setView("tasks")}>
          Tasks
        </button>
        <button type="button" className={view === "screen" ? "on" : ""} onClick={() => setView("screen")}>
          Screen
        </button>
        <button type="button" className={view === "settings" ? "on" : ""} onClick={() => setView("settings")}>
          Settings
        </button>
        {view === "chat" && (
          <div className="convos">
            <button type="button" className="solid" onClick={() => newChat(null)}>
              New chat
            </button>
            {conversations.map((conversation) => (
              <div key={conversation.id} className={conversation.id === activeId ? "convo on" : "convo"}>
                <button type="button" onClick={() => void openConversation(conversation.id)}>
                  {conversation.title}
                </button>
                <button type="button" className="icon" aria-label="Delete conversation" onClick={() => void deleteConversation(conversation.id)}>
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </nav>
      <main className="stage">
        {view === "chat" && (
          <section className="panel chat">
            <div className="transcript">
              {(activeProject && !activeId) || conversations.find((item) => item.id === activeId)?.project_name ? (
                <p className="project-banner">
                  Project · {conversations.find((item) => item.id === activeId)?.project_name || activeProject?.name}
                </p>
              ) : null}
              {thread.length === 0 && (
                <div className="empty hero-empty">
                  <p>Channel open, Sahib.</p>
                  <p>Ask ALEX something, attach a document or image, or hold the mic. Commands wait for your approval.</p>
                </div>
              )}
              {thread.map((message) => (
                <article key={message.id} className={`bubble ${message.role}`}>
                  <header>{message.role === "tool" ? message.toolName : message.role === "user" ? "Sahib" : settings.assistant_name}</header>
                  {message.role === "assistant" ? <Markdown text={message.content || (message.pending ? "…" : "")} /> : <pre>{message.content}</pre>}
                  {message.sources && message.sources.length > 0 && (
                    <ul className="sources">
                      {message.sources.map((source) => (
                        <li key={source.url}>
                          <a href={source.url} target="_blank" rel="noreferrer">
                            {source.title || source.url}
                          </a>
                        </li>
                      ))}
                    </ul>
                  )}
                </article>
              ))}
              <div ref={bottomRef} />
            </div>
            {attachments.length > 0 && (
              <ul className="attach-list">
                {attachments.map((file) => (
                  <li key={file.id}>
                    {file.preview && <img src={file.preview} alt="" />}
                    <span>
                      {file.filename}
                      <em>{file.kind}</em>
                    </span>
                    <button type="button" className="icon" aria-label="Remove attachment" onClick={() => setAttachments((current) => current.filter((item) => item.id !== file.id))}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <form
              className="composer"
              onSubmit={(event) => {
                event.preventDefault();
                send(draft);
              }}
            >
              <textarea
                value={draft}
                rows={2}
                placeholder={connected ? "Message ALEX. Enter to send." : "Waiting for the local link…"}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    send(draft);
                  }
                }}
              />
              <div className="composer-actions">
                <input
                  ref={fileRef}
                  type="file"
                  hidden
                  multiple
                  accept=".pdf,.txt,.md,.csv,.json,.py,.ts,.tsx,.js,.png,.jpg,.jpeg,.webp,.gif,image/*,application/pdf,text/*"
                  onChange={(event) => void attachFiles(event.target.files)}
                />
                <button type="button" className="ghost" onClick={() => fileRef.current?.click()} disabled={uploading || busy}>
                  {uploading ? "Uploading" : "Attach"}
                </button>
                <button
                  type="button"
                  className={listening ? "mic hot" : "mic"}
                  onPointerDown={() => void holdStart()}
                  onPointerUp={() => void holdEnd()}
                  onPointerLeave={() => {
                    if (listening) void holdEnd();
                  }}
                >
                  {listening ? "Release" : "Hold to talk"}
                  <span className="meter" style={{ width: `${Math.round(level * 100)}%` }} />
                </button>
                <button className="solid" type="submit" disabled={!connected || busy || uploading || (!draft.trim() && attachments.length === 0)}>
                  {busy ? "Working" : "Send"}
                </button>
              </div>
            </form>
          </section>
        )}
        {view === "memory" && <MemoryView />}
        {view === "projects" && <ProjectsView onOpenChat={(project) => newChat(project)} />}
        {view === "tasks" && <TasksView onNotice={setToast} />}
        {view === "screen" && (
          <ScreenView
            enabled={settings.computer_use_enabled}
            running={screenRunning}
            image={screenImage}
            actions={screenActions}
            hotkey="Ctrl+Alt+Esc"
            dpi={1}
            onStart={(goal) => {
              setScreenActions([]);
              setView("screen");
              socketRef.current?.send(JSON.stringify({ type: "computer_task", goal }));
            }}
            onStop={() => {
              socketRef.current?.send(JSON.stringify({ type: "computer_stop" }));
              void api("/api/computer/stop", { method: "POST" }).catch(() => undefined);
              setScreenRunning(false);
            }}
            onPreview={() => {
              void api<{ image: string }>("/api/computer/preview")
                .then((frame) => setScreenImage(frame.image))
                .catch((err: unknown) => setToast(err instanceof Error ? err.message : "Could not capture the screen."));
            }}
          />
        )}
        {view === "settings" && <SettingsView settings={settings} onChange={setSettings} onSpeak={say} />}
      </main>
      <aside className="side">
        <Reactor state={core} level={level} />
        <div className="side-card">
          <p className="eyebrow">Host</p>
          <strong>{status?.system || "…"}</strong>
          <span>{status?.shell} shell</span>
          <span>{status?.platform}</span>
          <span>
            Memory {status?.memory_used_mb ?? "–"} / {status?.memory_total_mb ?? "–"} MB
          </span>
          <span className={status?.provider_configured ? "ok-line" : "warn-line"}>{status?.provider_detail}</span>
          {status?.plugins && status.plugins.length > 0 && <span>Plugins: {status.plugins.join(", ")}</span>}
        </div>
      </aside>
      {toast && <p className="toast global-toast">{toast}</p>}
      {approval && <ApprovalDialog approval={approval} onDecide={decide} />}
    </div>
  );
}

function append(current: Record<string, ChatMessage[]>, id: string, message: ChatMessage) {
  return { ...current, [id]: [...(current[id] ?? []), message] };
}

function appendToken(current: Record<string, ChatMessage[]>, id: string, text: string) {
  const list = [...(current[id] ?? [])];
  const last = list[list.length - 1];
  if (last?.role === "assistant" && last.pending) {
    list[list.length - 1] = { ...last, content: last.content + text };
  } else {
    list.push({ id: crypto.randomUUID(), role: "assistant", content: text, pending: true });
  }
  return { ...current, [id]: list };
}

function updateTool(current: Record<string, ChatMessage[]>, id: string, event: ServerEvent) {
  const list = [...(current[id] ?? [])];
  const index = list.findIndex((item) => item.id === event.call_id);
  const next = {
    id: event.call_id || crypto.randomUUID(),
    role: "tool" as const,
    toolName: event.name,
    content: event.output || "",
    ok: event.ok,
    sources: event.sources,
    pending: false,
  };
  if (index >= 0) list[index] = next;
  else list.push(next);
  return { ...current, [id]: list };
}

function finish(current: Record<string, ChatMessage[]>, id: string) {
  const list = (current[id] ?? []).map((item) => ({ ...item, pending: false }));
  return { ...current, [id]: list };
}
