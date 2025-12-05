import json

import behavior_digital_twin


def write_log(entry, log_path):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    try:
        behavior_digital_twin.update_state_with_entry(entry)
    except Exception as exc:
        print(f"[DIGITAL TWIN ERROR] {exc}")


def pretty_print(entry):
    title = entry.get("title") or "<no title>"
    if len(title) > 50:
        title = title[:47] + "..."

    exe = entry.get("exe", "<unknown exe>")
    mode = entry.get("mode", "unknown")
    confidence = float(entry.get("confidence", 0.0) or 0.0)
    ts = entry.get("ts", "")

    print(f"[{ts}] {exe:<12} | {mode:<10} | {confidence:.2f} | {title}")
