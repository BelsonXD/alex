# Changelog

## 1.1.1

- When an update is available, ALEX opens a dialog with the new version, a short changelog, Update now, and Later. Later hides the dialog until the next time ALEX is opened. An Update available badge stays in the header.
- The updater looks at BelsonXD/alex by default, so that repository does not have to be typed in.

## 1.1.0

- Windows setup prefers Python 3.12, then 3.13, then 3.11 through the `py` launcher. Python 3.14 and 3.15 are refused with a link to the 3.12 installer, because those builds try to compile PyYAML and ask for Visual C++. A `.venv` created with the wrong Python is deleted and recreated. Packages install with `pip --only-binary=:all:`. `uvicorn[standard]` was removed so PyYAML is not a dependency.
- One-click update. ALEX checks a GitHub release named `alex.zip`, or a manifest URL, on startup and every 30 minutes. The button downloads the zip, replaces the app, reinstalls changed dependencies, rebuilds the interface, and restarts. If that fails, the previous files are restored. Keys, the database, memories, and projects stay in the user data folder (`%LOCALAPPDATA%\ALEX` on Windows).
- Screen control. A vision model can see the desktop and move the mouse, click, drag, scroll, and type. Ctrl+Alt+Esc and the Stop button halt it. Starting a task, and steps that look like passwords, purchases, sending messages, or deletes, ask for approval. The Screen page shows the latest screenshot and each action. Windows DPI scaling is mapped into the same coordinates as the screenshot.
- Word documents (DOCX) are read alongside PDF, text, and images.
- Reminders raise a Windows balloon notification when they fire.
- Wake phrase and interruption: say the phrase to send a command, and talking over ALEX stops speech.
- Re-running `start.bat` skips package installs and the interface build when nothing changed.

## 1.0.0

- First install: chat, memory, voice, approvals, projects, tasks, and settings.
