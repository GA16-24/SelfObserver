# SelfObserver

SelfObserver is a multi-surface activity tracker that blends desktop sensors, a lightweight browser bridge, and local AI models to build a timeline of what you are doing on your machine. The project is designed to run fully locally and feed its results into a simple Flask dashboard or your own Obsidian vault.

## Components
- **Desktop watcher (`self_observer.py`)**: Windows-focused agent that samples the foreground window, captures a screenshot, fuses text + vision classification via local Ollama models, and appends JSONL entries to `logs/screen_log.jsonl`.
- **Vision-only loop (`SelfObserver_Vision.py`)**: Periodically screenshots the display with `mss` and asks a vision model for structured activity summaries, writing results to `vision_logs.jsonl`.
- **Daily report generator (`daily_report.py`)**: Reads `screen_log.jsonl` and writes Markdown summaries to `SelfObserverDaily` inside your Obsidian vault, with time distributions and suggested optimizations.
- **Dashboard (`ui/server.py`)**: Simple Flask app that exposes recent events and time-distribution stats via JSON APIs and renders them with the templates in `ui/templates`.
- **Browser bridge (`service_worker.js` + `browser-extension-manifest.json`)**: Chrome extension service worker that periodically posts the active tab's title and URL to `http://127.0.0.1:8765/ingest` so desktop context includes browser activity.

## Prerequisites
- Python 3.10+
- Windows-only dependencies for the desktop watcher: `pywin32`, `psutil`, `pywinauto`, `Pillow`.
- For the vision loop: `mss` and network access to your local Ollama server with vision models available.
- An Ollama installation with models referenced in `self_observer.py` (defaults to `qwen2.5:7b` and `qwen2.5vl:7b`). Adjust the `OLLAMA` path if Ollama is not on your `PATH`.

## Running the desktop watcher
1. Install dependencies (example):
   ```bash
   pip install pywin32 psutil pywinauto Pillow requests
   ```
2. Ensure Chrome remote debugging is available on port `9222` if you want URLs captured: start Chrome with `--remote-debugging-port=9222`.
3. Start the watcher:
   ```bash
   python self_observer.py
   ```
   A background thread will generate a daily report at 22:00, and log entries will stream into `logs/screen_log.jsonl`.

## Running the dashboard
1. Install Flask:
   ```bash
   pip install flask
   ```
2. From the repository root, launch the server:
   ```bash
   python ui/server.py
   ```
3. Open `http://localhost:5010/` to view the latest 50 events and simple stats endpoints.

## Using the browser extension
1. Load an unpacked extension in Chrome and point it to this folder containing `browser-extension-manifest.json` and `service_worker.js`.
2. Keep the desktop watcher listening on `http://127.0.0.1:8765/ingest` to receive tab updates (implement your own handler for ingestion if needed).
3. The service worker automatically posts the active tab on navigation, activation, and every 5 seconds.

## Generating daily reports manually
If you want to render a report outside the scheduled time:
```bash
python daily_report.py
```
The Markdown file will be placed under `SelfObserverDaily` in your Obsidian vault path configured in `daily_report.py`.

## Logs and data
- Screen activity logs: `logs/screen_log.jsonl`
- Vision summaries: `vision_logs.jsonl`
- Temporary screenshot for the watcher: `screen_shot_tmp.jpg`
- Temporary screenshot for the vision loop: `screen.png`

## Notes
- The project currently targets Windows APIs for foreground window detection and may need adaptation for other platforms.
- The Ollama invocations rely on JSON-only responses; if you customize prompts, ensure they remain strictly machine-readable.
