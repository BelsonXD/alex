import { useEffect, useState } from "react";
import { api } from "../api";
import type { Settings } from "../types";

const KEYS: { id: string; label: string; help: string; field: string }[] = [
  { id: "openai", label: "OpenAI", help: "openai", field: "openai_api_key" },
  { id: "anthropic", label: "Anthropic", help: "anthropic", field: "anthropic_api_key" },
  { id: "xai", label: "xAI", help: "xai", field: "xai_api_key" },
  { id: "elevenlabs", label: "ElevenLabs", help: "elevenlabs", field: "elevenlabs_api_key" },
  { id: "tavily", label: "Tavily", help: "tavily", field: "tavily_api_key" },
  { id: "brave", label: "Brave Search", help: "brave", field: "brave_search_api_key" },
];

export function SettingsView({
  settings,
  onChange,
  onSpeak,
}: {
  settings: Settings;
  onChange: (next: Settings) => void;
  onSpeak: (text: string) => Promise<void>;
}) {
  const [name, setName] = useState(settings.assistant_name);
  const [persona, setPersona] = useState(settings.persona);
  const [provider, setProvider] = useState(settings.provider);
  const [model, setModel] = useState(settings.model || settings.effective_model);
  const [voiceProvider, setVoiceProvider] = useState(settings.voice_provider);
  const [voiceId, setVoiceId] = useState(settings.voice_id);
  const [autoSpeak, setAutoSpeak] = useState(settings.auto_speak);
  const [searchProvider, setSearchProvider] = useState(settings.search_provider);
  const [wake, setWake] = useState(settings.voice_wake);
  const [wakePhrase, setWakePhrase] = useState(settings.wake_phrase || "alex");
  const [computerUse, setComputerUse] = useState(settings.computer_use_enabled);
  const [maxSteps, setMaxSteps] = useState(String(settings.computer_use_max_steps || 12));
  const [githubRepo, setGithubRepo] = useState(settings.github_repo || "BelsonXD/alex");
  const [manifest, setManifest] = useState(settings.update_manifest || "");
  const [updateToken, setUpdateToken] = useState("");
  const [updateNote, setUpdateNote] = useState("");
  const [folders, setFolders] = useState(settings.safe_folders.join("\n"));
  const [allow, setAllow] = useState(settings.command_allowlist.join("\n"));
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const chosen = settings.providers.find((item) => item.id === provider);

  useEffect(() => {
    const load = () => setVoices(window.speechSynthesis?.getVoices() ?? []);
    load();
    window.speechSynthesis?.addEventListener("voiceschanged", load);
    return () => window.speechSynthesis?.removeEventListener("voiceschanged", load);
  }, []);

  async function saveProfile() {
    setError("");
    try {
      const next = await api<Settings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          assistant_name: name,
          persona,
          provider,
          model,
          voice_provider: voiceProvider,
          voice_id: voiceId,
          auto_speak: autoSpeak,
          voice_wake: wake,
          wake_phrase: wakePhrase,
          computer_use_enabled: computerUse,
          computer_use_max_steps: Number(maxSteps) || 12,
          alex_github_repo: githubRepo,
          alex_update_manifest: manifest,
          search_provider: searchProvider,
          safe_folders: folders.split(/\r?\n/).map((line) => line.trim()).filter(Boolean),
          command_allowlist: allow.split(/\r?\n/).map((line) => line.trim()).filter(Boolean),
        }),
      });
      onChange(next);
      setNotice("Settings saved on this computer.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed.");
    }
  }

  async function saveSecrets() {
    const body: Record<string, string> = {};
    for (const [key, value] of Object.entries(secrets)) {
      if (value.trim()) body[key] = value.trim();
    }
    if (!Object.keys(body).length) {
      setError("Paste at least one key before saving.");
      return;
    }
    try {
      await api("/api/settings/secrets", { method: "POST", body: JSON.stringify(body) });
      const next = await api<Settings>("/api/settings");
      onChange(next);
      setSecrets({});
      setNotice("Keys written to the local .env file. They are not shown again.");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not store keys.");
    }
  }

  async function probe() {
    setError("");
    try {
      const result = await api<{ ok: boolean; detail: string }>("/api/system/probe", { method: "POST" });
      setNotice(result.detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Probe failed.");
    }
  }

  return (
    <section className="panel view settings">
      <header className="view-head">
        <div>
          <p className="eyebrow">Control room</p>
          <h2>Settings</h2>
        </div>
      </header>
      {notice && <p className="ok-line">{notice}</p>}
      {error && <p className="error-line">{error}</p>}

      <div className="setting-grid">
        <label>
          Name
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          Brain
          <select value={provider} onChange={(event) => setProvider(event.target.value)}>
            {settings.providers.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
                {item.configured ? "" : " — not configured"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Search
          <select value={searchProvider} onChange={(event) => setSearchProvider(event.target.value)}>
            <option value="auto">Automatic</option>
            <option value="tavily">Tavily {settings.keys.tavily ? "" : "— key missing"}</option>
            <option value="brave">Brave {settings.keys.brave ? "" : "— key missing"}</option>
            <option value="none">Off</option>
          </select>
        </label>
        <label>
          Model
          <input value={model} onChange={(event) => setModel(event.target.value)} list="model-choices" />
          <datalist id="model-choices">
            {(chosen?.models ?? []).map((item) => (
              <option key={item} value={item} />
            ))}
          </datalist>
        </label>
        <p className="hint">{chosen?.detail}</p>
        <label className="wide">
          Persona
          <textarea value={persona} onChange={(event) => setPersona(event.target.value)} rows={8} />
        </label>
        <div className="wide actions">
          <button className="solid" type="button" onClick={() => void saveProfile()}>
            Save profile
          </button>
          <button className="ghost" type="button" onClick={() => void probe()}>
            Test connection
          </button>
        </div>
      </div>

      <h3>API keys</h3>
      <p className="hint">Optional. ALEX runs on the offline kernel with no keys. One model key, or Ollama, unlocks open-ended chat. Keys stay in .env on this machine.</p>
      <ul className="key-list">
        {KEYS.map((item) => (
          <li key={item.id}>
            <div>
              <strong>{item.label}</strong>
              <span className={settings.keys[item.id] ? "pill ok" : "pill warn"}>
                {settings.keys[item.id] ? "Configured" : "Not configured"}
              </span>
              <a href={settings.key_help[item.help]} target="_blank" rel="noreferrer">
                Get a key
              </a>
            </div>
            <input
              type="password"
              autoComplete="off"
              placeholder="Paste to replace"
              value={secrets[item.field] ?? ""}
              onChange={(event) => setSecrets({ ...secrets, [item.field]: event.target.value })}
            />
          </li>
        ))}
      </ul>
      <label>
        Ollama URL
        <input
          value={secrets.ollama_base_url ?? ""}
          placeholder="http://127.0.0.1:11434"
          onChange={(event) => setSecrets({ ...secrets, ollama_base_url: event.target.value })}
        />
      </label>
      <button className="ghost" type="button" onClick={() => void saveSecrets()}>
        Save keys to .env
      </button>

      <h3>Voice</h3>
      <div className="setting-grid">
        <label>
          Voice engine
          <select value={voiceProvider} onChange={(event) => setVoiceProvider(event.target.value)}>
            <option value="browser">Browser (Windows voices, no key)</option>
            <option value="openai">OpenAI TTS {settings.keys.openai ? "" : "— key missing"}</option>
            <option value="elevenlabs">ElevenLabs {settings.keys.elevenlabs ? "" : "— key missing"}</option>
          </select>
        </label>
        <label>
          Voice id
          {voiceProvider === "browser" ? (
            <select value={voiceId} onChange={(event) => setVoiceId(event.target.value)}>
              <option value="">System default</option>
              {voices.map((voice) => (
                <option key={voice.voiceURI} value={voice.voiceURI}>
                  {voice.name}
                </option>
              ))}
            </select>
          ) : (
            <input value={voiceId} onChange={(event) => setVoiceId(event.target.value)} placeholder={voiceProvider === "openai" ? "nova" : "ElevenLabs voice id"} />
          )}
        </label>
        <label className="check">
          <input type="checkbox" checked={autoSpeak} onChange={(event) => setAutoSpeak(event.target.checked)} />
          Speak replies aloud
        </label>
        <label className="check">
          <input type="checkbox" checked={wake} onChange={(event) => setWake(event.target.checked)} />
          Wake when I say the phrase, and stop speaking if I interrupt
        </label>
        <label>
          Wake phrase
          <input value={wakePhrase} onChange={(event) => setWakePhrase(event.target.value)} />
        </label>
        <button className="ghost" type="button" onClick={() => void onSpeak("ALEX online. Systems nominal, Sahib.")}>
          Test voice
        </button>
      </div>
      <p className="hint">{settings.voice.note}</p>

      <h3>Screen control</h3>
      <p className="hint">Off until you enable it. A task still asks before it starts, and again before passwords, purchases, sending messages, or deletes. Stop is always on screen. Ctrl+Alt+Esc stops it even if ALEX is in another window.</p>
      <label className="check">
        <input type="checkbox" checked={computerUse} onChange={(event) => setComputerUse(event.target.checked)} />
        Allow screen control
      </label>
      <label>
        Maximum steps
        <input value={maxSteps} onChange={(event) => setMaxSteps(event.target.value)} inputMode="numeric" />
      </label>
      <h3>Updates</h3>
      <p className="hint">
        This install updates itself from a GitHub release asset named alex.zip, or from a manifest URL. Keys and memories stay in the user data folder. If an update fails, ALEX puts the previous files back.
      </p>
      <label>
        GitHub repository (owner/name)
        <input value={githubRepo} onChange={(event) => setGithubRepo(event.target.value)} placeholder="BelsonXD/alex" />
      </label>
      <label>
        Or manifest URL
        <input value={manifest} onChange={(event) => setManifest(event.target.value)} placeholder="https://example.com/alex/manifest.json" />
      </label>
      <label>
        Read-only token, only for a private repository
        <input type="password" autoComplete="off" value={updateToken} placeholder={settings.update_token_set ? "Saved. Paste to replace." : "github_pat_..."} onChange={(event) => setUpdateToken(event.target.value)} />
      </label>
      <div className="row">
        <button
          className="ghost"
          type="button"
          onClick={() => {
            void api<{ detail: string; update_available: boolean; latest?: string; notes?: string }>("/api/system/update").then((result) => {
              setUpdateNote(result.detail + (result.notes ? `\n${result.notes}` : ""));
            }).catch((err: unknown) => setError(err instanceof Error ? err.message : "Update check failed."));
          }}
        >
          Check for updates
        </button>
        <button
          className="ghost"
          type="button"
          onClick={() => {
            if (!updateToken.trim()) {
              setError("Paste a token or leave this blank if the repository is public.");
              return;
            }
            void api("/api/settings/secrets", { method: "POST", body: JSON.stringify({ alex_update_token: updateToken }) }).then(() => {
              setUpdateToken("");
              setNotice("Update token saved in the user data folder.");
            });
          }}
        >
          Save token
        </button>
      </div>
      {updateNote && <p className="hint">{updateNote}</p>}
      <h3>Permissions</h3>
      <p className="hint">
        Commands run in {settings.shell}. File tools stay inside these folders. An allowlist entry is only the first token of a command, such as <code>Get-ChildItem</code>, and it skips the approval dialog.
      </p>
      <label>
        Safe folders, one path per line
        <textarea value={folders} onChange={(event) => setFolders(event.target.value)} rows={4} placeholder={"C:\\Users\\Sahib\\Documents\\ALEX"} />
      </label>
      <label>
        Command allowlist, one token per line
        <textarea value={allow} onChange={(event) => setAllow(event.target.value)} rows={3} placeholder={"Get-ChildItem"} />
      </label>
      <button className="solid" type="button" onClick={() => void saveProfile()}>
        Save permissions
      </button>
    </section>
  );
}
