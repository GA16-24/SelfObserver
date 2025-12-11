"""Input telemetry tracker for keystrokes and mouse travel.

We intentionally avoid logging any key contents and only maintain counts and
movement distances. The tracker starts background listeners (when ``pynput`` is
available) and exposes ``snapshot()`` for the UI to query the current odometer
values.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Optional

try:  # Optional dependency to remain safe in headless environments
    from pynput import keyboard, mouse  # type: ignore
except Exception:  # pragma: no cover - handled at runtime
    keyboard = None
    mouse = None


@dataclass
class InputSnapshot:
    keys_pressed: int
    mouse_distance_px: float
    started_at: float
    warnings: list[str]


class InputTelemetry:
    def __init__(self):
        self.keys_pressed = 0
        self.mouse_distance = 0.0
        self.started_at = time.time()
        self._last_mouse_pos: Optional[tuple[int, int]] = None
        self._lock = threading.Lock()
        self._kb_listener = None
        self._mouse_listener = None
        self._warnings: list[str] = []

    # ---------------------- listeners ----------------------
    def start(self):
        if keyboard is None or mouse is None:
            self._warnings.append(
                "Install pynput to enable keystroke/mouse telemetry; falling back to zeros"
            )
            return

        if not self._kb_listener:
            self._kb_listener = keyboard.Listener(on_press=self._on_key_press)
            self._kb_listener.daemon = True
            self._kb_listener.start()

        if not self._mouse_listener:
            self._mouse_listener = mouse.Listener(on_move=self._on_mouse_move)
            self._mouse_listener.daemon = True
            self._mouse_listener.start()

    # ---------------------- event handlers ----------------------
    def _on_key_press(self, _key):  # pragma: no cover - listener callback
        with self._lock:
            self.keys_pressed += 1

    def _on_mouse_move(self, x, y):  # pragma: no cover - listener callback
        with self._lock:
            if self._last_mouse_pos is not None:
                last_x, last_y = self._last_mouse_pos
                self.mouse_distance += math.dist((last_x, last_y), (x, y))
            self._last_mouse_pos = (x, y)

    # ---------------------- API ----------------------
    def snapshot(self, reset: bool = False) -> InputSnapshot:
        with self._lock:
            snap = InputSnapshot(
                keys_pressed=self.keys_pressed,
                mouse_distance_px=self.mouse_distance,
                started_at=self.started_at,
                warnings=list(self._warnings),
            )
            if reset:
                self.keys_pressed = 0
                self.mouse_distance = 0.0
                self.started_at = time.time()
                self._warnings.clear()
        return snap


_singleton: Optional[InputTelemetry] = None


def start_input_tracker() -> InputTelemetry:
    global _singleton
    if _singleton is None:
        _singleton = InputTelemetry()
        _singleton.start()
    return _singleton
