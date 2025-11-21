from flask import Flask, render_template, jsonify
import json
import os
import datetime

# ---------------------------------------------
# Absolute path setup (MUST be above read_logs)
# ---------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))        # ui/
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..")) # SelfObserver/
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LEGACY_LOG = os.path.join(LOG_DIR, "screen_log.jsonl")

# ---------------------------------------------
# Flask App
# ---------------------------------------------
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)

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


def read_logs():
    log_path = latest_log_path()
    if not log_path or not os.path.exists(log_path):
        return []
    out = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except:
                pass
    return out

# ---------------------------------------------
# API: latest logs (UI table)
# ---------------------------------------------
@app.route("/api/latest")
def api_latest():
    logs = read_logs()
    return jsonify(logs[-50:])

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
        ts = datetime.datetime.fromisoformat(entry["ts"])
        if ts.date() != today:
            continue

        if last_ts and last_mode:
            delta = (ts - last_ts).total_seconds()
            durations[last_mode] = durations.get(last_mode, 0) + delta

        last_ts = ts
        last_mode = entry["mode"]

    # Count the time from the last log entry until now so the pie chart
    # reflects the current active segment instead of dropping it.
    if last_ts and last_mode:
        delta = (datetime.datetime.now() - last_ts).total_seconds()
        durations[last_mode] = durations.get(last_mode, 0) + max(delta, 0)

    return jsonify(durations)

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
        ts = datetime.datetime.fromisoformat(entry["ts"])
        if ts >= one_hour_ago:
            timeline.append({
                "ts": entry["ts"],
                "mode": entry["mode"]
            })

    return jsonify(timeline)

# ---------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010, debug=True)
