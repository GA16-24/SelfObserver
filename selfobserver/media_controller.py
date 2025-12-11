"""Cross-platform media bridge for the dashboard music widget.

This module aims for a "best effort" approach: when platform-native bridges are
available (``winsdk`` on Windows, AppleScript on macOS) we surface now-playing
metadata and transport controls. On unsupported platforms we return descriptive
warnings so the UI can render graceful fallbacks instead of crashing.
"""
from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class NowPlaying:
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    position_seconds: Optional[float] = None
    duration_seconds: Optional[float] = None
    is_playing: bool = False
    warnings: list[str] = None  # type: ignore

    def to_dict(self):
        return asdict(self)


class MediaController:
    def __init__(self):
        self.platform = platform.system().lower()
        self._warning: Optional[str] = None
        self._win_manager = None
        self._initialize_backend()

    # ---------------------- platform setup ----------------------
    def _initialize_backend(self):
        if self.platform == "windows":
            try:
                from winsdk.windows.media.control import (  # type: ignore
                    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
                )

                self._win_manager = MediaManager.request_async().get()
            except Exception as exc:  # pragma: no cover - runtime-only path
                self._warning = f"Windows media session unavailable: {exc}"
        elif self.platform == "darwin":
            # AppleScript is available without additional dependencies
            pass
        else:
            self._warning = "Media controls are not supported on this platform"

    # ---------------------- helpers ----------------------
    def _default_now_playing(self, warnings: Optional[list[str]] = None) -> NowPlaying:
        warn = []
        if self._warning:
            warn.append(self._warning)
        if warnings:
            warn.extend(warnings)
        return NowPlaying(warnings=warn)

    # ---------------------- public API ----------------------
    def now_playing(self) -> dict:
        if self.platform == "windows" and self._win_manager:
            try:
                session = self._win_manager.get_current_session()
                if not session:
                    return self._default_now_playing(["No active media session"]).to_dict()
                info = session.try_get_media_properties_async().get()
                timeline = session.get_timeline_properties()
                return NowPlaying(
                    title=str(info.title or ""),
                    artist=str(info.artist or ""),
                    album=str(info.album_title or ""),
                    position_seconds=float(timeline.position.total_seconds()),
                    duration_seconds=float(timeline.end_time.total_seconds()),
                    is_playing=str(session.get_playback_info().playback_status).endswith("playing"),
                    warnings=[] if not self._warning else [self._warning],
                ).to_dict()
            except Exception as exc:  # pragma: no cover - runtime-only path
                return self._default_now_playing([str(exc)]).to_dict()

        if self.platform == "darwin":
            try:
                script = (
                    'tell application "Music" to if player state is playing then '  # noqa: E501
                    '{ name of current track, artist of current track, album of current track, player position, duration, true } '
                    'else { "", "", "", 0, 0, false }'
                )
                result = subprocess.check_output(["osascript", "-e", script], text=True)
                parts = [p.strip() for p in result.split(",")]
                return NowPlaying(
                    title=parts[0] or None,
                    artist=parts[1] or None,
                    album=parts[2] or None,
                    position_seconds=float(parts[3] or 0),
                    duration_seconds=float(parts[4] or 0),
                    is_playing=parts[5].lower() == "true",
                    warnings=[] if not self._warning else [self._warning],
                ).to_dict()
            except Exception as exc:  # pragma: no cover - runtime-only path
                return self._default_now_playing([str(exc)]).to_dict()

        return self._default_now_playing().to_dict()

    def play_pause(self) -> bool:
        if self.platform == "windows" and self._win_manager:
            try:
                session = self._win_manager.get_current_session()
                if session:
                    session.try_toggle_play_pause_async().get()
                    return True
            except Exception:
                return False
        elif self.platform == "darwin":
            return self._run_applescript('tell application "Music" to playpause')
        return False

    def next_track(self) -> bool:
        if self.platform == "windows" and self._win_manager:
            try:
                session = self._win_manager.get_current_session()
                if session:
                    session.try_skip_next_async().get()
                    return True
            except Exception:
                return False
        elif self.platform == "darwin":
            return self._run_applescript('tell application "Music" to next track')
        return False

    def previous_track(self) -> bool:
        if self.platform == "windows" and self._win_manager:
            try:
                session = self._win_manager.get_current_session()
                if session:
                    session.try_skip_previous_async().get()
                    return True
            except Exception:
                return False
        elif self.platform == "darwin":
            return self._run_applescript('tell application "Music" to previous track')
        return False

    # ---------------------- private helpers ----------------------
    def _run_applescript(self, script: str) -> bool:
        try:
            subprocess.check_call(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:  # pragma: no cover - runtime-only path
            return False
