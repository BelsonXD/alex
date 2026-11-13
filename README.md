# ALEX

ALEX is a personal AI that runs on your computer. It keeps conversations and memories in a local SQLite database, streams replies from the model you choose, and can speak, listen, search, and — only after you approve it — run PowerShell and change files.

Windows is the primary target. macOS and Linux use the same app.

## Windows

1. Install **Python 3.12** (3.13 and 3.11 also work): https://www.python.org/downloads/windows/  
   Do not use Python 3.14 or 3.15. Those builds have no Windows wheels for some libraries, so pip tries to compile them and asks for Visual C++. You do not need Visual C++.  
   In the installer, check **py launcher** and **Add python.exe to PATH**. `start.bat` then runs `py -3.12`, then `py -3.13`, then `py -3.11`. If `.venv` was created with another Python, it is deleted and recreated.
2. Install **Node.js 20 LTS or newer**: https://nodejs.org/en/download  
   Node is only used to build the interface. ALEX itself is the Python app plus that built interface.
3. Double-click **`start.bat`**.

The first launch creates a virtual environment, installs dependencies, builds the interface, writes a `.env` file if you do not have one, and opens http://127.0.0.1:8787

You can also run it from PowerShell:

```powershell
cd path\to\ALEX
.\setup.ps1
```

`setup.ps1` does the same work as `start.bat` and then launches ALEX. Close the console window, or press Ctrl+C, to stop it.

If Windows SmartScreen warns you about `start.bat`, choose More info → Run anyway. It is a local script, not an installer from the internet.

## API keys

None are required. With an empty `.env`, ALEX uses the **offline kernel**: it can remember facts, set reminders through the API, list files in its safe folders, do arithmetic, and run commands after you approve them. It will not pretend to be a full language model.

Add one model provider when you want open-ended chat. Put the keys in `.env` in the ALEX folder (copy from `.env.example`), or paste them into Settings. The interface shows whether each key is configured and never displays the key again.

| Key | Required? | What it unlocks | Where to get it |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | Optional | GPT models, Whisper speech-to-text, streamed TTS, the best chat quality | https://platform.openai.com/api-keys |
| `ANTHROPIC_API_KEY` | Optional | Claude models | https://console.anthropic.com/settings/keys |
| `XAI_API_KEY` | Optional | Grok models | https://console.x.ai/ |
| `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` | Optional | Neural text-to-speech | https://elevenlabs.io/app/settings/api-keys |
| `TAVILY_API_KEY` | Optional | Web search | https://tavily.com |
| `BRAVE_SEARCH_API_KEY` | Optional | Web search, used if Tavily is empty | https://api.search.brave.com/app/keys |
| Ollama, no key | Optional | Local models. Install from https://ollama.com/download/windows then `ollama pull llama3.2`, and choose Ollama in Settings | `OLLAMA_BASE_URL` defaults to `http://127.0.0.1:11434` |

Voice with no keys uses the browser. On Windows that is the installed Microsoft voice (Edge and Chrome expose it through `speechSynthesis`). Hold the mic button to talk. Edge or Chrome is the reliable speech-to-text fallback; an OpenAI key switches transcription to Whisper.

## What this version does

- Edit ALEX's name and persona in Settings.
- Stream a reply from OpenAI, Anthropic, xAI, Ollama, or the offline kernel, and switch models in Settings.
- Save every conversation. Say “remember that …” or use the Memory screen to add, search, edit, and delete facts. Relevant memories are retrieved into later chats.
- Push-to-talk with a live microphone meter, browser speech recognition, optional Whisper, and spoken replies (browser voice, OpenAI PCM, or ElevenLabs).
- Tools the model can call: web search (when a search key is set), file list/read, and — after an approval dialog — PowerShell commands, writing, moving, deleting, and organizing files, and opening apps or websites. On Windows, apps open through `Start-Process` and the Start menu. Paths accept drive letters and `%ENV%` variables.
- Safe folders and an optional command allowlist. The sandbox and `Documents\ALEX` are created for you. The action log records approvals and denials.
- A live system strip: link, model, CPU, and memory.

File tools cannot leave the safe folders even after approval. A shell command is different: once you approve it, it runs as your Windows user. The dialog shows the exact command.

## macOS and Linux

```bash
chmod +x start.sh
./start.sh
```

Commands use bash instead of PowerShell. Opening an app uses `open` on macOS and `xdg-open` on Linux. Everything else is the same.

For development, with the backend already running on port 8787:

```bash
cd frontend
npm install
npm run dev
```

The dev server is http://127.0.0.1:47321 and proxies the API.

## Tests

From the ALEX folder, after the virtual environment exists:

```bat
.venv\Scripts\python -m pytest
```

```bash
.venv/bin/python -m pytest
```

The suite covers memory retrieval, the approval flow, Windows PowerShell command construction, provider switching with a mocked model, and the settings API.

## Layout

- `backend/alex` — FastAPI app, providers, memory, tools, voice, chat websocket
- `plugins/` — drop a Python file here with a `register(registry)` function to add a tool
- `frontend/` — React interface
- `data/` — SQLite database, uploads, and the sandbox (created on first run, not committed)
- `.env` — secrets, never commit this

## Updates

This zip is the last copy you install by hand. After that, ALEX can replace itself.

1. Create a GitHub repository and push this project, or download it from the release you publish.
2. For each version, publish a GitHub Release. Attach one file named exactly `alex.zip` (the same kind of archive as this one: source only, no `node_modules`, `.venv`, `.env`, or database). The release notes are the changelog ALEX shows.
3. The repository name is already **BelsonXD/alex**. Change it in Settings → Updates only if the release lives somewhere else. If the repository is private, paste a fine-grained personal access token with **Contents: Read** and click Save token. A public repository needs no token.
4. Alternatively, host a JSON file and set its URL as the manifest:

```json
{"version": "1.2.0", "zip_url": "https://example.com/alex-1.2.0.zip", "sha256": "<sha256 of the zip>", "notes": "What changed"}
```

ALEX checks on startup and every 30 minutes. When a newer version exists, a dialog shows the version, a short changelog, **Update now**, and **Later**. Later closes the dialog until the next time ALEX is opened. The header keeps an **Update available** badge so the dialog can be opened again. Update now downloads the zip, copies it over this folder, runs pip only if `requirements.txt` changed (binary wheels only), rebuilds the interface only if those files changed, and restarts. Your `.env`, database, memories, and projects stay in `%LOCALAPPDATA%\ALEX` and are not inside the zip. If the new version fails to install, the previous files are put back.

I recommend the GitHub Release with an `alex.zip` asset. It works from a Windows PC with no extra server, and a public repository needs no token.

## Also in the interface

- **Projects** create a real folder, list its files, open it in Explorer, and start a chat bound to that folder.
- **Attach** on the composer uploads text, PDF, and images. Text and PDFs are read into the conversation. Images are sent to a vision-capable model; otherwise ALEX says which setting turns vision on.
- **Tasks** stores reminders and scheduled prompts. A due reminder raises a notice. Run now executes an automation immediately. Scheduled runs deny shell and file changes unless you approve them yourself in chat.

Plugins still load from `plugins/`. Drop in a module that exposes `register(registry)`. Run ALEX with `start.bat` on the Windows machine you want it to control. A container would only control itself.
