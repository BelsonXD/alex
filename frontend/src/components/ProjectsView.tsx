import { useEffect, useState } from "react";
import { api } from "../api";
import type { ProjectFile, ProjectItem } from "../types";

export function ProjectsView({ onOpenChat }: { onOpenChat: (project: ProjectItem) => void }) {
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [folder, setFolder] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<ProjectItem | null>(null);
  const [deleteFiles, setDeleteFiles] = useState(false);

  async function load() {
    const rows = await api<ProjectItem[]>("/api/projects");
    setProjects(rows);
    return rows;
  }

  useEffect(() => {
    void load().catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load projects."));
  }, []);

  async function create() {
    setError("");
    try {
      const created = await api<ProjectItem>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ name, description }),
      });
      setName("");
      setDescription("");
      await load();
      await open(created.id);
      setNotice(`Created ${created.name}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the project.");
    }
  }

  async function open(id: string) {
    const payload = await api<{ project: ProjectItem; files: ProjectFile[] }>(`/api/projects/${id}/files`);
    setSelected(id);
    setFiles(payload.files);
    setFolder(payload.project.folder);
  }

  async function reveal(id: string) {
    const result = await api<{ ok: boolean; path: string; detail: string }>(`/api/projects/${id}/open`, { method: "POST" });
    setNotice(result.ok ? `Opened ${result.path}` : `Folder: ${result.path}. ${result.detail}`);
  }

  async function remove() {
    if (!confirmDelete) return;
    await api(`/api/projects/${confirmDelete.id}?delete_files=${deleteFiles ? "true" : "false"}`, { method: "DELETE" });
    if (selected === confirmDelete.id) {
      setSelected(null);
      setFiles([]);
      setFolder("");
    }
    setConfirmDelete(null);
    setDeleteFiles(false);
    await load();
  }

  return (
    <section className="panel view">
      <header className="view-head">
        <div>
          <p className="eyebrow">Workspaces</p>
          <h2>Projects</h2>
        </div>
      </header>
      <p className="hint">A project is a real folder on this computer. Chats started from here can save files into it after you approve the write.</p>
      {notice && <p className="ok-line">{notice}</p>}
      {error && <p className="error-line">{error}</p>}
      <form
        className="setting-grid"
        onSubmit={(event) => {
          event.preventDefault();
          void create();
        }}
      >
        <label>
          Name
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Arc reactor" required />
        </label>
        <label>
          Description
          <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Bench notes and generated code" />
        </label>
        <button className="solid" type="submit">
          Create project
        </button>
      </form>
      {projects.length === 0 && <p className="empty">No projects yet.</p>}
      <ul className="card-list">
        {projects.map((project) => (
          <li key={project.id} className={project.id === selected ? "on" : ""}>
            <div>
              <strong>{project.name}</strong>
              <p>{project.description || "No description"}</p>
              <p className="hint">{project.conversation_count} chats</p>
            </div>
            <div className="row tight">
              <button type="button" className="ghost" onClick={() => void open(project.id)}>
                Files
              </button>
              <button type="button" className="ghost" onClick={() => onOpenChat(project)}>
                New chat
              </button>
              <button type="button" className="ghost" onClick={() => void reveal(project.id)}>
                Open folder
              </button>
              <button type="button" className="ghost danger" onClick={() => setConfirmDelete(project)}>
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>
      {selected && (
        <div className="file-box">
          <p className="eyebrow">Folder</p>
          <p className="path">{folder}</p>
          {files.length === 0 && <p className="empty">The folder is empty.</p>}
          <ul>
            {files.map((file) => (
              <li key={file.path}>
                <span>{file.is_dir ? "dir" : "file"}</span>
                {file.name}
                {!file.is_dir && <em>{file.size} B</em>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {confirmDelete && (
        <div className="modal-back">
          <section className="modal" role="dialog" aria-modal="true">
            <p className="eyebrow">Delete project</p>
            <h2>{confirmDelete.name}</h2>
            <label className="check">
              <input type="checkbox" checked={deleteFiles} onChange={(event) => setDeleteFiles(event.target.checked)} />
              Also delete the folder on disk
            </label>
            <div className="modal-actions">
              <button type="button" className="ghost" onClick={() => setConfirmDelete(null)}>
                Cancel
              </button>
              <button type="button" className="solid" onClick={() => void remove()}>
                Delete
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
