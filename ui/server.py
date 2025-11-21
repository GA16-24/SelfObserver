from flask import Flask, render_template, jsonify
import json
import os
import datetime

# ---------------------------------------------
# Absolute path setup (MUST be above read_logs)
# ---------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))        # ui/
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..")) # SelfObserver/
LOG_PATH = os.path.join(PROJECT_ROOT, "logs", "screen_log.jsonl")

print("DEBUG: BASE_DIR =", BASE_DIR)
print("DEBUG: PROJECT_ROOT =", PROJECT_ROOT)
print("DEBUG: LOG_PATH =", LOG_PATH)
print("DEBUG: LOG_EXISTS =", os.path.exists(LOG_PATH))

# ---------------------------------------------
# Flask App
# ---------------------------------------------
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)

# ---------------------------------------------
# Read logs (now LOG_PATH is already defined)
# ---------------------------------------------
def read_logs():
    if not os.path.exists(LOG_PATH):
        return []
    out = []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
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
