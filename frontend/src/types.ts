export type View = "chat" | "memory" | "projects" | "tasks" | "screen" | "settings";
export type CoreState = "idle" | "listening" | "thinking" | "speaking" | "approval";

export interface Source {
  title: string;
  url: string;
  snippet?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool" | "error";
  content: string;
  toolName?: string;
  ok?: boolean;
  sources?: Source[];
  pending?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  project_id: string | null;
  project_name: string | null;
  updated_at: string | null;
}

export interface MemoryItem {
  id: string;
  content: string;
  kind: string;
  source: string;
  updated_at: string | null;
}

export interface ProviderInfo {
  id: string;
  label: string;
  configured: boolean;
  detail: string;
  models: string[];
}

export interface Settings {
  assistant_name: string;
  persona: string;
  provider: string;
  model: string;
  effective_model: string;
  voice_provider: string;
  voice_id: string;
  auto_speak: boolean;
  voice_wake: boolean;
  wake_phrase: string;
  computer_use_enabled: boolean;
  computer_use_max_steps: number;
  github_repo: string;
  update_manifest: string;
  update_token_set: boolean;
  search_provider: string;
  safe_folders: string[];
  command_allowlist: string[];
  provider_configured: boolean;
  provider_detail: string;
  providers: ProviderInfo[];
  keys: Record<string, boolean>;
  key_help: Record<string, string>;
  shell: string;
  voice: VoiceCaps;
}

export interface VoiceCaps {
  stt: "openai" | "browser";
  tts: "openai" | "elevenlabs" | "browser";
  openai_voices: string[];
  note: string;
}

export interface SystemStatus {
  ok: boolean;
  platform: string;
  system: string;
  shell: string;
  cpu_percent: number;
  memory_percent: number;
  memory_used_mb: number;
  memory_total_mb: number;
  provider: string;
  provider_label: string;
  provider_configured: boolean;
  provider_detail: string;
  model: string;
  assistant_name: string;
  uptime_seconds: number;
  plugins?: string[];
}

export interface Approval {
  approval_id: string;
  tool: string;
  summary: string;
  arguments: Record<string, unknown>;
  risk: string;
}

export interface ProjectItem {
  id: string;
  name: string;
  description: string;
  folder: string;
  conversation_count: number;
  created_at: string | null;
}

export interface ProjectFile {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
}

export interface ReminderItem {
  id: string;
  title: string;
  notes: string;
  due_at: string | null;
  status: string;
  fired_at: string | null;
}

export interface AutomationItem {
  id: string;
  name: string;
  prompt: string;
  interval_seconds: number;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  last_result: string;
  conversation_id: string | null;
}

export interface UploadItem {
  id: string;
  filename: string;
  mime: string;
  kind: string;
  excerpt?: string;
  preview?: string;
}

export interface ServerEvent {
  type: string;
  conversation_id?: string;
  title?: string;
  text?: string;
  detail?: string;
  state?: CoreState;
  call_id?: string;
  name?: string;
  arguments?: Record<string, unknown>;
  ok?: boolean;
  output?: string;
  sources?: Source[];
  approval_id?: string;
  tool?: string;
  summary?: string;
  risk?: string;
  image?: string;
  step?: number;
  action?: string;
  reason?: string;
  running?: boolean;
  notification?: { title: string; body: string; kind: string };
}
