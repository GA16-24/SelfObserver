# SelfObserver

SelfObserver is a multi-surface activity tracker that blends desktop sensors, a lightweight browser bridge, and local AI models to build a timeline of what you are doing on your machine. The project is designed to run fully locally and feed its results into a simple Flask dashboard or your own Obsidian vault.

## Components
- **Desktop watcher (`self_observer.py`)**: Windows-focused agent that samples the foreground window, captures a screenshot, fuses text + vision classification via local Ollama models, and appends JSONL entries to a per-day file such as `logs/screen_log_2024-09-30.jsonl`.
- **Vision-only loop (`SelfObserver_Vision.py`)**: Periodically screenshots the display with `mss` and asks a vision model for structured activity summaries, writing results to `vision_logs.jsonl`.
- **Behavior embedding & clustering (`behavior_model.py`)**: Builds a 768-dimension embedding per activity (intent, context, cognitive load, emotional tone, dopamine vs. goal orientation, app semantics) and clusters them with HDBSCAN/DBSCAN/K-Means to surface emergent behaviors beyond fixed modes.
- **Time-series forecasting (`time_series_forecasting.py`)**: Uses behavior embeddings, temporal features, and productivity signals to predict the next-hour behavior cluster, productivity, and distraction likelihood via LSTM/TCN/Prophet or a rolling baseline.
- **Behavior digital twin (`behavior_digital_twin.py`)**: Maintains a probabilistic, incrementally updated mirror of the user's habits with Markov-style transitions, contextual factors, and short/long-horizon goal alignment signals.
- **Daily report generator (`daily_report.py`)**: Reads the newest `logs/screen_log_*.jsonl` (or the legacy `screen_log.jsonl`) and writes Markdown summaries to `SelfObserverDaily` inside your Obsidian vault, with time distributions and suggested optimizations.
- **Dashboard (`ui/server.py`)**: Simple Flask app that exposes recent events and time-distribution stats via JSON APIs and renders them with the templates in `ui/templates`.
- **Browser bridge (`service_worker.js` + `browser-extension-manifest.json`)**: Chrome extension service worker that periodically posts the active tab's title and URL to `http://127.0.0.1:8765/ingest` so desktop context includes browser activity.

## Code structure
- `self_observer.py` remains the single entry point; it now delegates to the `selfobserver/` package for configuration, screen capture, heuristics, classification, logging, and daily reporting.
- `selfobserver/config.py` centralizes constants and filesystem paths, while `selfobserver/capture.py`, `selfobserver/classifier.py`, and `selfobserver/logger.py` keep the watcher loop small and readable.

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
   A background thread will generate a daily report at 22:00, and log entries will stream into a daily `logs/screen_log_<date>.jsonl` file that rolls over automatically at midnight.

## Running the dashboard
1. Install the UI dependency bundle (includes Flask):
   ```bash
   pip install -r requirements.txt
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
- Screen activity logs: rolling `logs/screen_log_<date>.jsonl` files (with `screen_log.jsonl` supported as a legacy fallback)
- Vision summaries: `vision_logs.jsonl`
- Temporary screenshot for the watcher: `screen_shot_tmp.jpg`
- Temporary screenshot for the vision loop: `screen.png`
- Behavior embeddings + cluster assignments are stored alongside each log entry under `behavior_embedding`, `behavior_cluster`, and `behavior_label`.
- Time-series forecasts and digital-twin state are derived on the fly from the recorded embeddings and temporal features; daily reports summarize the latest insights.

## Behavior insights pipeline
- **Embedding**: Every captured activity is transformed into a dense 768-d vector by `behavior_model.build_embedding`. Signals include intent tokens, app/window context, cognitive load, emotional tone, and dopamine-vs-goal cues.
- **Clustering**: `behavior_model.cluster_behaviors` groups embeddings with HDBSCAN when available (falling back to DBSCAN/K-Means). The top clusters, transition patterns, flow likelihood, and anomalies appear in the daily report.
- **Forecasting**: `time_series_forecasting.predict_next_hour` ingests embeddings, timestamps (with cyclical features), prior clusters/labels, and productivity to estimate next-hour behavior probabilities, expected productivity, and distraction risk.
- **Digital twin**: `behavior_digital_twin.update_state` incrementally tracks Markov-style transitions and contextual productivity/distraction signals to infer productivity windows, procrastination triggers, stress/cognitive load cues, and short-term behavior transitions.
- **Reporting**: `daily_report.py` stitches the above outputs into Markdown—behavior clusters, transitions, flow/anomaly summaries, forecasting distributions, and digital-twin insights (goal alignment, risky periods, recommended deep-work windows).

## Tuning classification heuristics
The watcher uses a small, ordered list of heuristics before falling back to the text/vision models. To keep labels future-proof
as new apps or window titles appear, you can add or override rules in `heuristics.json` without touching the code. The file
accepts a list of rule objects, checked from top to bottom:

```json
[
  {
    "mode": "writing",
    "confidence": 0.8,
    "exe_contains": ["joplin", "logseq"],
    "title_contains": ["notes"]
  },
  {
    "mode": "coding",
    "confidence": 0.75,
    "exe_exact": ["code.exe"],
    "url_contains": ["github.com"]
  }
]
```

Supported keys per rule: `exe_exact`, `exe_contains`, `title_contains`, `url_contains`, and `label_contains` (for UI Automation
labels). Rules are sanitized automatically, and the watcher hot-reloads them whenever `heuristics.json` changes.

## Notes
- The project currently targets Windows APIs for foreground window detection and may need adaptation for other platforms.
- The Ollama invocations rely on JSON-only responses; if you customize prompts, ensure they remain strictly machine-readable.
