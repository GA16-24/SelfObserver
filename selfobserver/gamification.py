"""Gamification rule engine for XP, levels, and badges.

The engine observes log entries and increments XP based on focused duration. It
runs lightweight heuristics (inbox zero, focus streaks) and persists state so
UI widgets can display current badges and XP progress.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional

from .config import LOG_DIR

GAMIFICATION_STATE_PATH = os.path.join(LOG_DIR, "gamification_state.json")


@dataclass
class GamificationState:
    level: int = 1
    xp: float = 0.0
    xp_to_next: float = 120.0
    badges: Dict[str, bool] = field(default_factory=dict)
    focus_minutes: float = 0.0
    inbox_zero_streak: int = 0
    last_event_ts: Optional[str] = None

    def to_dict(self):
        return asdict(self)


class GamificationEngine:
    def __init__(self, state_path: str = GAMIFICATION_STATE_PATH):
        self.state_path = state_path
        self.state = self._load_state()
        self._last_ts: Optional[datetime] = None

    # ---------------------- persistence ----------------------
    def _load_state(self) -> GamificationState:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                return GamificationState(**data)
            except Exception:
                pass
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        return GamificationState(badges={})

    def _save_state(self):
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(self.state.to_dict(), fh, ensure_ascii=False, indent=2)

    # ---------------------- rule helpers ----------------------
    def _award_badge(self, name: str):
        self.state.badges[name] = True

    def _gain_xp(self, minutes: float, mode: str):
        multiplier = 1.5 if mode in {"coding", "writing", "reading"} else 1.0
        xp_gain = minutes * multiplier
        self.state.xp += xp_gain
        while self.state.xp >= self.state.xp_to_next:
            self.state.xp -= self.state.xp_to_next
            self.state.level += 1
            # Slightly raise the threshold each level to keep progress engaging
            self.state.xp_to_next = round(self.state.xp_to_next * 1.08, 2)

    def _check_inbox_zero(self, entry: dict, minutes: float):
        if minutes == 0:
            return
        title = (entry.get("title") or "").lower()
        exe = (entry.get("exe") or "").lower()
        is_email = "outlook" in exe or "gmail" in title or entry.get("mode") == "email"
        if is_email and minutes <= 30:
            self._award_badge("Inbox Zero")
            self.state.inbox_zero_streak += 1

    def _check_focus_streak(self, mode: str, minutes: float):
        if mode in {"coding", "writing", "reading"}:
            self.state.focus_minutes += minutes
            if self.state.focus_minutes >= 45:
                self._award_badge("Deep Work")
        else:
            self.state.focus_minutes = 0.0

    # ---------------------- public API ----------------------
    def process_entry(self, entry: dict):
        ts_raw = entry.get("ts")
        if not ts_raw:
            return
        try:
            ts = datetime.fromisoformat(ts_raw)
        except Exception:
            return

        minutes = 0.0
        if self._last_ts:
            delta = (ts - self._last_ts).total_seconds()
            minutes = max(delta, 0) / 60.0
        self._last_ts = ts

        mode = entry.get("mode") or "unknown"
        self._gain_xp(minutes, mode)
        self._check_focus_streak(mode, minutes)
        self._check_inbox_zero(entry, minutes)

        self.state.last_event_ts = ts_raw
        self._save_state()

    def get_state(self) -> dict:
        return self.state.to_dict()


_singleton: Optional[GamificationEngine] = None


def get_gamification_engine() -> GamificationEngine:
    global _singleton
    if _singleton is None:
        _singleton = GamificationEngine()
    return _singleton
