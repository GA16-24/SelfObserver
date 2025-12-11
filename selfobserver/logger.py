import json
import os

import behavior_digital_twin
from .database import maybe_reload_project_mappings, resolve_project
from .gamification import get_gamification_engine

_GAMIFICATION = get_gamification_engine()
_PROJECT_MAPPING = None
_PROJECT_MTIME = None


def write_log(entry, log_path):
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    global _PROJECT_MAPPING, _PROJECT_MTIME
    _PROJECT_MAPPING, _PROJECT_MTIME = maybe_reload_project_mappings(
        _PROJECT_MAPPING, _PROJECT_MTIME
    )
    project = resolve_project(entry, _PROJECT_MAPPING)
    if project:
        entry.setdefault("project", project)

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    try:
        behavior_digital_twin.update_state_with_entry(entry)
    except Exception as exc:
        print(f"[DIGITAL TWIN ERROR] {exc}")
    try:
        _GAMIFICATION.process_entry(entry)
    except Exception as exc:
        print(f"[GAMIFICATION ERROR] {exc}")


def pretty_print(entry):
    title = entry.get("title") or "<no title>"
    if len(title) > 50:
        title = title[:47] + "..."

    exe = entry.get("exe", "<unknown exe>")
    mode = entry.get("mode", "unknown")
    confidence = float(entry.get("confidence", 0.0) or 0.0)
    ts = entry.get("ts", "")

    print(f"[{ts}] {exe:<12} | {mode:<10} | {confidence:.2f} | {title}")
