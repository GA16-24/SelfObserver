import os
import time
from datetime import datetime

import daily_report


TARGET_HOUR = 22
TARGET_MIN = 50


def schedule_daily_report():
    last_date = None

    def _maybe_generate_report(tag):
        nonlocal last_date
        try:
            path = daily_report.generate_daily_report()
            last_date = datetime.now().date()
            print(f"[REPORT SAVED][{tag}] {path}")
        except Exception as exc:
            print(f"[REPORT ERROR][{tag}] {exc}")

    while True:
        now = datetime.now()
        target_dt = now.replace(hour=TARGET_HOUR, minute=TARGET_MIN, second=0, microsecond=0)
        report_today_exists = os.path.exists(daily_report.report_path_for_date(now.date()))

        if not report_today_exists and now >= target_dt and last_date != now.date():
            _maybe_generate_report("catchup")
            time.sleep(60)
            continue

        if (
            now.hour == TARGET_HOUR
            and now.minute == TARGET_MIN
            and last_date != now.date()
        ):
            _maybe_generate_report("scheduled")
            time.sleep(70)
        else:
            time.sleep(15)
