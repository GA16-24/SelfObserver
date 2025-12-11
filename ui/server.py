from flask import Flask, render_template, jsonify, request
import json
import os
import datetime
import platform
import re
import sys
from typing import List

# ---------------------------------------------
# Absolute path setup (MUST be above read_logs)
# ---------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))        # ui/
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..")) # SelfObserver/
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LEGACY_LOG = os.path.join(LOG_DIR, "screen_log.jsonl")

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from selfobserver.database import (
    add_goal,
    load_goals,
    load_project_mappings,
    maybe_reload_project_mappings,
    resolve_project,
    toggle_goal,
)
from selfobserver.gamification import get_gamification_engine
from selfobserver.input_telemetry import start_input_tracker
from selfobserver.media_controller import MediaController
from selfobserver.system_metrics import start_metrics_poller

# Obsidian vault for upcoming goals (env override supported)
OBSIDIAN_VAULT = os.environ.get("OBSIDIAN_VAULT") or os.path.expanduser("~/Obsidian")

# Entries matching these rules are skipped entirely from the UI
IGNORED_PROCESSES = {"lockapp.exe"}
IGNORED_TITLE_KEYWORDS = ["windows default lock screen"]

# Long-lived helpers
METRICS_POLLER = start_metrics_poller()
INPUT_TRACKER = start_input_tracker()
MEDIA = MediaController()
GAMIFICATION = get_gamification_engine()
PROJECT_MAPPING, PROJECT_MTIME = load_project_mappings()

# ---------------------------------------------
# Flask App
# ---------------------------------------------
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)


@app.after_request
def add_no_cache_headers(resp):
    """Force fresh data for the dashboard's live feed endpoints."""
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# ---------------------------------------------
# Latest log lookup + reader
# ---------------------------------------------
def latest_log_path():
    if not os.path.exists(LOG_DIR):
        return LEGACY_LOG if os.path.exists(LEGACY_LOG) else None

    newest = None
    newest_date = None

    for name in os.listdir(LOG_DIR):
        if not (name.startswith("screen_log_") and name.endswith(".jsonl")):
            continue
        date_part = name[len("screen_log_"):-len(".jsonl")]
        try:
            parsed = datetime.date.fromisoformat(date_part)
        except Exception:
            continue
        if not newest_date or parsed > newest_date:
            newest_date = parsed
            newest = os.path.join(LOG_DIR, name)

    if newest:
        return newest

    return LEGACY_LOG if os.path.exists(LEGACY_LOG) else None


def _current_project_mapping():
    global PROJECT_MAPPING, PROJECT_MTIME
    PROJECT_MAPPING, PROJECT_MTIME = maybe_reload_project_mappings(
        PROJECT_MAPPING, PROJECT_MTIME
    )
    return PROJECT_MAPPING


def read_logs():
    log_path = latest_log_path()
    if not log_path or not os.path.exists(log_path):
        return []
    out = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                if not entry.get("ts"):
                    continue
                exe = (entry.get("exe") or "").lower()
                title = (entry.get("title") or "").lower()

                if exe in IGNORED_PROCESSES or any(k in title for k in IGNORED_TITLE_KEYWORDS):
                    continue

                try:
                    mapping = _current_project_mapping()
                    project = resolve_project(entry, mapping)
                    if project:
                        entry.setdefault("project", project)
                except Exception:
                    pass

                out.append(entry)
            except:
                pass
    return out

# ---------------------------------------------
# API: latest logs (UI table)
# ---------------------------------------------
@app.route("/api/latest")
def api_latest():
    logs = read_logs()
    recent = logs[-50:]

    # Ensure newest entry is first so the UI hero card shows the current window
    try:
        recent.sort(
            key=lambda e: datetime.datetime.fromisoformat(e.get("ts", "")),
            reverse=True,
        )
    except Exception:
        recent.reverse()

    for entry in recent:
        try:
            ts = datetime.datetime.fromisoformat(entry.get("ts", ""))
            entry["ts_display"] = ts.strftime("%H:%M")
        except Exception:
            entry["ts_display"] = entry.get("ts")

    return jsonify(recent)

# ---------------------------------------------
# API: today's category durations
# ---------------------------------------------
@app.route("/api/stats/day")
def api_stats_day():
    logs = read_logs()
    today = datetime.date.today()

    durations = {}  # mode → seconds
    last_ts = None
    last_mode = None

    for entry in logs:
        try:
            ts = datetime.datetime.fromisoformat(entry["ts"])
        except Exception:
            continue
        if ts.date() != today:
            continue

        if last_ts and last_mode:
            delta = (ts - last_ts).total_seconds()
            durations[last_mode] = durations.get(last_mode, 0) + delta

        last_ts = ts
        last_mode = entry.get("mode")

    # Count the time from the last log entry until now so the pie chart
    # reflects the current active segment instead of dropping it.
    if last_ts and last_mode:
        delta = (datetime.datetime.now() - last_ts).total_seconds()
        durations[last_mode] = durations.get(last_mode, 0) + max(delta, 0)

    # Convert to minutes for the UI formatter
    durations_minutes = {k: v / 60.0 for k, v in durations.items()}

    return jsonify(durations_minutes)

# ---------------------------------------------
# API: last 1 hour timeline (for line chart)
# ---------------------------------------------
@app.route("/api/stats/hour")
def api_stats_hour():
    logs = read_logs()
    now = datetime.datetime.now()
    one_hour_ago = now - datetime.timedelta(hours=1)

    timeline = []

    for entry in logs:
        try:
            ts = datetime.datetime.fromisoformat(entry["ts"])
        except Exception:
            continue
        if ts >= one_hour_ago:
            timeline.append({
                "ts": entry["ts"],
                "mode": entry.get("mode")
            })

    return jsonify(timeline)


# ---------------------------------------------
# API: today's top applications by active time
# ---------------------------------------------
@app.route("/api/stats/apps")
def api_stats_apps():
    logs = read_logs()
    today = datetime.date.today()

    durations = {}  # exe → seconds
    last_ts = None
    last_exe = None

    for entry in logs:
        try:
            ts = datetime.datetime.fromisoformat(entry["ts"])
        except Exception:
            continue
        if ts.date() != today:
            continue

        if last_ts and last_exe:
            delta = (ts - last_ts).total_seconds()
            if delta > 0:
                durations[last_exe] = durations.get(last_exe, 0) + delta

        last_ts = ts
        last_exe = entry.get("exe") or "Unknown"

    # Count the time from the last log entry until now so the UI reflects
    # the currently active application.
    if last_ts and last_exe:
        delta = (datetime.datetime.now() - last_ts).total_seconds()
        durations[last_exe] = durations.get(last_exe, 0) + max(delta, 0)

    durations_minutes = (
        {name: seconds / 60.0 for name, seconds in durations.items()} if durations else {}
    )

    top = [
        {"exe": name, "minutes": minutes}
        for name, minutes in sorted(
            durations_minutes.items(), key=lambda item: item[1], reverse=True
        )
    ]

    return jsonify(top)

# ---------------------------------------------
# API: today's project breakdown
# ---------------------------------------------
@app.route("/api/stats/projects")
def api_stats_projects():
    logs = read_logs()
    today = datetime.date.today()

    durations = {}
    last_ts = None
    last_project = None

    for entry in logs:
        try:
            ts = datetime.datetime.fromisoformat(entry["ts"])
        except Exception:
            continue
        if ts.date() != today:
            continue

        if last_ts and last_project:
            delta = (ts - last_ts).total_seconds()
            if delta > 0:
                durations[last_project] = durations.get(last_project, 0) + delta

        last_ts = ts
        last_project = entry.get("project") or resolve_project(entry, _current_project_mapping()) or "Uncategorized"

    if last_ts and last_project:
        delta = (datetime.datetime.now() - last_ts).total_seconds()
        durations[last_project] = durations.get(last_project, 0) + max(delta, 0)

    durations_minutes = {name: seconds / 60.0 for name, seconds in durations.items()}

    return jsonify(
        [
            {"project": name, "minutes": minutes}
            for name, minutes in sorted(
                durations_minutes.items(), key=lambda item: item[1], reverse=True
            )
        ]
    )


# ---------------------------------------------
# API: system vitals (CPU / RAM / GPU)
# ---------------------------------------------
def _safe_psutil():
    try:
        import psutil  # type: ignore

        return psutil
    except Exception:
        return None


def _safe_gpu_info():
    try:
        import GPUtil  # type: ignore

        gpus = GPUtil.getGPUs()
        out = []
        for g in gpus:
            out.append(
                {
                    "name": g.name,
                    "load": g.load * 100 if g.load is not None else None,
                    "memory_used_gb": g.memoryUsed / 1024 if g.memoryUsed is not None else None,
                    "memory_total_gb": g.memoryTotal / 1024 if g.memoryTotal is not None else None,
                }
            )
        return out
    except Exception:
        try:
            import pynvml  # type: ignore

            pynvml.nvmlInit()
            device_count = pynvml.nvmlDeviceGetCount()
            gpus = []
            for idx in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
                name = pynvml.nvmlDeviceGetName(handle).decode("utf-8")
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpus.append(
                    {
                        "name": name,
                        "load": getattr(util, "gpu", None),
                        "memory_used_gb": mem.used / (1024 ** 3),
                        "memory_total_gb": mem.total / (1024 ** 3),
                    }
                )
            return gpus
        except Exception:
            return None


def system_snapshot():
    psutil = _safe_psutil()
    warnings: List[str] = []

    cpu_model = platform.processor() or platform.uname().processor or None
    cpu_cores = os.cpu_count() or None
    cpu_load = None
    cpu_freq = None

    ram_used_gb = None
    ram_total_gb = None
    ram_percent = None

    if psutil:
        try:
            cpu_load = psutil.cpu_percent(interval=0.3)
        except Exception:
            cpu_load = None
        try:
            freq = psutil.cpu_freq()
            cpu_freq = freq.current if freq else None
        except Exception:
            cpu_freq = None
        try:
            mem = psutil.virtual_memory()
            ram_used_gb = mem.used / (1024 ** 3)
            ram_total_gb = mem.total / (1024 ** 3)
            ram_percent = mem.percent
        except Exception:
            pass
    else:
        warnings.append("psutil not installed; install psutil for live vitals")

    if not cpu_model:
        try:
            with open("/proc/cpuinfo", "r") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        cpu_model = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass

    gpus = _safe_gpu_info()
    if gpus is None:
        warnings.append("GPU details unavailable; install GPUtil or pynvml for detection")

    return {
        "cpu_model": cpu_model,
        "cpu_load": cpu_load,
        "cpu_cores": cpu_cores,
        "cpu_freq_mhz": cpu_freq,
        "ram_used_gb": ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "ram_percent": ram_percent,
        "gpus": gpus or [],
        "warnings": warnings,
    }


@app.route("/api/system")
def api_system():
    snapshot = system_snapshot()
    try:
        snapshot["live"] = METRICS_POLLER.snapshot() if METRICS_POLLER else {}
    except Exception:
        snapshot["live"] = {}
    return jsonify(snapshot)


# ---------------------------------------------
# API: input odometer (keystrokes / mouse distance)
# ---------------------------------------------
@app.route("/api/input")
def api_input():
    if not INPUT_TRACKER:
        return jsonify({"available": False, "warnings": ["Input tracker unavailable"]})
    snap = INPUT_TRACKER.snapshot()
    return jsonify(
        {
            "available": True,
            "keys": snap.keys_pressed,
            "mouse_px": snap.mouse_distance_px,
            "since": snap.started_at,
            "warnings": snap.warnings,
        }
    )


# ---------------------------------------------
# API: media control + now playing
# ---------------------------------------------
@app.route("/api/media", methods=["GET", "POST"])
def api_media():
    if request.method == "POST":
        payload = request.get_json(silent=True, force=True) or {}
        action = payload.get("action")
        ok = False
        if action == "play_pause":
            ok = MEDIA.play_pause()
        elif action == "next":
            ok = MEDIA.next_track()
        elif action == "previous":
            ok = MEDIA.previous_track()
        return jsonify({"ok": ok})
    return jsonify(MEDIA.now_playing())


# ---------------------------------------------
# API: gamification state (XP / badges)
# ---------------------------------------------
@app.route("/api/gamification")
def api_gamification():
    return jsonify(GAMIFICATION.get_state())


# ---------------------------------------------
# API: upcoming goals from Obsidian vault
# ---------------------------------------------
TASK_RE = re.compile(r"^- \[([ xX])\]\s+(.*)$")
DUE_RE = re.compile(r"(?:due[:\s]|@due\()?([0-9]{4}-[0-9]{2}-[0-9]{2})")


def parse_goals_from_file(path: str) -> List[dict]:
    out: List[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                match = TASK_RE.match(line.strip())
                if not match:
                    continue
                done_flag, body = match.groups()
                done = done_flag.lower() == "x"
                due = None
                due_match = DUE_RE.search(body)
                if due_match:
                    due = due_match.group(1)

                # Remove common markers from the task text
                clean = DUE_RE.sub("", body).strip()
                clean = clean.replace("#task", "").replace("#todo", "").strip("- ")

                out.append(
                    {
                        "title": clean,
                        "done": done,
                        "due": due,
                        "source": os.path.relpath(path, OBSIDIAN_VAULT),
                        "modified": os.path.getmtime(path),
                    }
                )
    except Exception:
        return []
    return out


def collect_obsidian_goals(limit: int = 6) -> List[dict]:
    if not OBSIDIAN_VAULT or not os.path.isdir(OBSIDIAN_VAULT):
        return []

    tasks: List[dict] = []
    for root, _dirs, files in os.walk(OBSIDIAN_VAULT):
        for name in files:
            if not name.lower().endswith(".md"):
                continue
            path = os.path.join(root, name)
            tasks.extend(parse_goals_from_file(path))

    # Only keep incomplete tasks
    tasks = [t for t in tasks if not t.get("done")]

    # Prefer due date, otherwise use last modified time
    def sort_key(task):
        due = task.get("due")
        mtime = task.get("modified") or 0
        try:
            due_dt = datetime.date.fromisoformat(due) if due else None
        except Exception:
            due_dt = None
        return (due_dt or datetime.date.fromtimestamp(mtime), -mtime)

    tasks.sort(key=sort_key)
    return tasks[:limit]


@app.route("/api/goals", methods=["GET", "POST"])
def api_goals():
    if request.method == "POST":
        payload = request.get_json(silent=True, force=True) or {}
        action = payload.get("action")
        goals = load_goals()
        if action == "add" and payload.get("title"):
            goals = add_goal(payload["title"], payload.get("due"))
        elif action == "toggle" and payload.get("id"):
            goals = toggle_goal(payload["id"], payload.get("done"))
        return jsonify({"goals": goals})

    goals = load_goals()
    if goals:
        goals.extend(collect_obsidian_goals(limit=3))
    else:
        goals = collect_obsidian_goals()

    if not goals:
        goals = [
            {"title": "Connect Obsidian vault (set OBSIDIAN_VAULT)", "source": "setup", "due": None},
            {"title": "Capture next actions with '- [ ]' in your notes", "source": "tips", "due": None},
        ]
    return jsonify({"goals": goals})

# ---------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")


def _get_host_port():
    """Resolve the host/port for the Flask dev server.

    Defaults keep the server bound to localhost to avoid Windows firewall
    permission issues, but values can be overridden via env vars.
    """

    host = os.environ.get("UI_HOST") or "127.0.0.1"
    port_env = os.environ.get("UI_PORT")
    try:
        port = int(port_env) if port_env else 5010
    except ValueError:
        port = 5010
    return host, port


if __name__ == "__main__":
    host, port = _get_host_port()
    try:
        app.run(host=host, port=port, debug=True)
    except OSError as exc:
        # Surface a helpful hint when a Windows socket permission error occurs.
        hint = (
            "Socket error starting server. If the port is blocked or reserved, "
            "set UI_PORT to a different value (e.g., 5050) or bind to localhost "
            "with UI_HOST=127.0.0.1."
        )
        print(f"{hint}\nDetails: {exc}")
        raise
