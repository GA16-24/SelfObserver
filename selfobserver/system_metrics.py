"""Lightweight system metrics poller used by the UI vitals card.

The poller is intentionally small and dependency-light. When ``psutil`` is
available we record CPU and RAM usage every few seconds so the UI can render
smooth gauges without blocking requests. When the dependency is missing, the
poller still returns placeholder data plus a warning string so callers can
surface actionable feedback instead of failing.
"""
from __future__ import annotations

import datetime as _dt
import threading
from dataclasses import dataclass, field
from typing import List, Optional

try:  # Optional dependency; we keep the module import safe at runtime
    import psutil  # type: ignore
except Exception:  # pragma: no cover - handled gracefully at runtime
    psutil = None


@dataclass
class MetricSample:
    """Single point-in-time CPU/RAM snapshot."""

    timestamp: str
    cpu_percent: Optional[float]
    ram_percent: Optional[float]
    ram_used_gb: Optional[float]
    ram_total_gb: Optional[float]
    warnings: List[str] = field(default_factory=list)


class SystemMetricsPoller:
    """Background poller that keeps a rolling window of system vitals."""

    def __init__(self, interval_seconds: int = 5, history_size: int = 120):
        self.interval_seconds = interval_seconds
        self.history_size = history_size
        self._samples: List[MetricSample] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):  # pragma: no cover - used only in manual runs
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def _run(self):
        while not self._stop.is_set():
            sample = self._collect_sample()
            if sample:
                with self._lock:
                    self._samples.append(sample)
                    self._samples = self._samples[-self.history_size :]
            self._stop.wait(self.interval_seconds)

    def _collect_sample(self) -> Optional[MetricSample]:
        warnings: List[str] = []
        if psutil is None:
            warnings.append("Install psutil to enable live CPU/RAM telemetry")
            return MetricSample(
                timestamp=_dt.datetime.utcnow().isoformat(),
                cpu_percent=None,
                ram_percent=None,
                ram_used_gb=None,
                ram_total_gb=None,
                warnings=warnings,
            )

        try:
            cpu = psutil.cpu_percent(interval=None)
        except Exception:
            cpu = None
            warnings.append("CPU percentage unavailable")

        try:
            mem = psutil.virtual_memory()
            ram_percent = mem.percent
            ram_used_gb = mem.used / (1024**3)
            ram_total_gb = mem.total / (1024**3)
        except Exception:
            ram_percent = ram_used_gb = ram_total_gb = None
            warnings.append("Memory details unavailable")

        return MetricSample(
            timestamp=_dt.datetime.utcnow().isoformat(),
            cpu_percent=cpu,
            ram_percent=ram_percent,
            ram_used_gb=ram_used_gb,
            ram_total_gb=ram_total_gb,
            warnings=warnings,
        )

    def snapshot(self) -> dict:
        with self._lock:
            latest = self._samples[-1].__dict__ if self._samples else None
            history = [s.__dict__ for s in self._samples]
        return {"latest": latest, "history": history}


_singleton: Optional[SystemMetricsPoller] = None


def start_metrics_poller(interval_seconds: int = 5) -> SystemMetricsPoller:
    """Return a running singleton poller so callers can share samples."""

    global _singleton
    if _singleton is None:
        _singleton = SystemMetricsPoller(interval_seconds=interval_seconds)
        _singleton.start()
    return _singleton
