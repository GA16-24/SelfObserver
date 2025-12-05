import os
import threading
import time
from datetime import datetime

from selfobserver.categories import load_categories
from selfobserver.config import HEURISTICS_FILE, log_path_for_date
from selfobserver.heuristics import load_heuristics, maybe_reload_heuristics
from selfobserver.classifier import stable_classification
from selfobserver.logger import pretty_print, write_log
from selfobserver.reporting import schedule_daily_report


def run_loop():
    cat_map = load_categories()
    heuristics_rules = load_heuristics()
    heuristics_mtime = os.path.getmtime(HEURISTICS_FILE) if os.path.exists(HEURISTICS_FILE) else None
    current_day = datetime.now().date()
    log_path = log_path_for_date(current_day)

    while True:
        heuristics_rules, heuristics_mtime = maybe_reload_heuristics(heuristics_rules, heuristics_mtime)
        snap = stable_classification(cat_map, heuristics_rules)

        if snap is None:
            time.sleep(2)
            continue

        now = datetime.now()
        if now.date() != current_day:
            current_day = now.date()
            log_path = log_path_for_date(current_day)

        entry = {
            "ts": now.isoformat(timespec="seconds"),
            **snap
        }

        pretty_print(entry)
        write_log(entry, log_path)

        time.sleep(2)


def main():
    print("[SelfObserver v10] Vision + OCR + Text Fusion (simplified)")
    threading.Thread(target=schedule_daily_report, daemon=True).start()
    run_loop()


if __name__ == "__main__":
    main()
