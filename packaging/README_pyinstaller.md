# Building a Windows `.exe` with PyInstaller

These steps package the SelfObserver watcher **and** the Flask dashboard into
a single Windows-friendly bundle. The resulting `SelfObserver` folder contains
a `SelfObserver.exe` that starts the watcher, launches the dashboard on
`http://127.0.0.1:5010`, and opens it in your default browser.

## Prerequisites
- Python 3.10+ on Windows
- All runtime dependencies installed (at minimum: `pywin32`, `psutil`,
  `pywinauto`, `Pillow`, `requests`, `flask`, `mss` if you use the vision loop)
- PyInstaller 6.0+ (`pip install pyinstaller`)

## Build
From the repository root on Windows:

```powershell
pyinstaller packaging/selfobserver.spec
```

Artifacts land under `dist/SelfObserver/`.

## What the bundle includes
- Entry point: `packaging/launcher.py` (starts the watcher + dashboard, then
  opens your browser)
- UI assets: `ui/templates` and `ui/static`
- Config/data: `categories.json`, `observer.config.json`, and browser bridge
  files when present

## Running the EXE
Double-click `dist/SelfObserver/SelfObserver.exe` or run it from PowerShell:

```powershell
./dist/SelfObserver/SelfObserver.exe
```

The watcher writes logs under `logs/` beside the executable, and the dashboard
is available at `http://127.0.0.1:5010` while the app is running.
