"""Behavior Digital Twin: probabilistic mirror of user behavior.

This module fuses embeddings, Markov-style transitions, temporal context,
and productivity/distraction signals to build a dynamic behavioral twin.
Each activity log updates the inferred state space and produces
probabilistic forecasts plus interpretable insights.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List

import behavior_model

DEFAULT_STATE_PATH = "logs/digital_twin_state.json"


def _cyclical_time_features(ts: datetime) -> Dict[str, float]:
    hour = ts.hour + ts.minute / 60.0
    dow = ts.weekday()
    return {
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "dow_sin": math.sin(2 * math.pi * dow / 7),
        "dow_cos": math.cos(2 * math.pi * dow / 7),
    }


def _productivity_score(signal: Dict[str, Any]) -> float:
    base = signal.get("goal_score", 0.0) + 0.5 * signal.get("cognitive_load", 0.0)
    base -= 0.4 * signal.get("dopamine_score", 0.0)
    return max(0.0, min(1.0, base))


def _prepare_features(entries: List[Dict[str, Any]], labels: List[int]):
    features = []
    last_ts = None
    for idx, entry in enumerate(entries):
        ts = entry.get("ts")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        embedding = entry.get("embedding")
        signals = None
        if not embedding or len(embedding) != behavior_model.EMBEDDING_SIZE:
            embedding, signals = behavior_model.build_embedding(entry)
            entry["embedding"] = embedding
        else:
            _, signals = behavior_model.build_embedding(entry)

        session_len = 0.0
        if last_ts:
            session_len = (ts - last_ts).total_seconds() / 60.0
        last_ts = ts

        feats = {
            "ts": ts,
            "embedding": embedding,
            "cluster": labels[idx] if idx < len(labels) else -1,
            "productivity": _productivity_score(signals),
            "dopamine_score": signals.get("dopamine_score", 0.0),
            "goal_score": signals.get("goal_score", 0.0),
            "cognitive_load": signals.get("cognitive_load", 0.0),
            "emotional_tone": signals.get("emotional_tone", 0.5),
            "exe": (entry.get("exe") or "").lower(),
            "title": entry.get("title", ""),
            "session_len": session_len,
            "time_features": _cyclical_time_features(ts),
        }
        features.append(feats)
    return features


def _transition_matrix(labels: List[int]):
    transitions = defaultdict(Counter)
    for a, b in zip(labels, labels[1:]):
        if a == -1 or b == -1:
            continue
        transitions[a][b] += 1
    matrix = {}
    for src, dst_counts in transitions.items():
        total = sum(dst_counts.values()) or 1.0
        matrix[src] = {dst: count / total for dst, count in dst_counts.items()}
    return matrix, transitions


def _hourly_cluster_distribution(features: List[Dict[str, Any]]):
    by_hour: Dict[int, Counter] = defaultdict(Counter)
    for f in features:
        by_hour[f["ts"].hour][f["cluster"]] += 1
    return {h: dict(c) for h, c in by_hour.items()}


def _short_term_forecast(features, matrix, hourly_distribution):
    if not features:
        return {"predicted_cluster": None, "distribution": {}, "algorithm": "none"}

    last = features[-1]
    last_cluster = last.get("cluster", -1)
    dist = Counter()

    # Markov transition from last cluster
    if last_cluster in matrix:
        for dst, p in matrix[last_cluster].items():
            dist[dst] += p

    # Blend in hour-of-day prior
    hour_prior = hourly_distribution.get(last["ts"].hour, {})
    for cid, cnt in hour_prior.items():
        dist[cid] += 0.35 * cnt

    # Light recency prior on dopamine/goal to hint distraction vs focus states
    dopamine_bias = last.get("dopamine_score", 0.0) - last.get("goal_score", 0.0)
    if dopamine_bias > 0.25:
        dist["dopamine_prone"] += dopamine_bias
    elif dopamine_bias < -0.15:
        dist["goal_prone"] += -dopamine_bias

    if not dist:
        dist[last_cluster] += 1

    total = sum(dist.values()) or 1.0
    normalized = {k: v / total for k, v in dist.items()}
    predicted = max(normalized, key=normalized.get)

    return {
        "predicted_cluster": predicted,
        "distribution": normalized,
        "algorithm": "markov+context",
    }


def _productivity_windows(features):
    hourly: Dict[int, List[float]] = defaultdict(list)
    for f in features:
        hourly[f["ts"].hour].append(f["productivity"])
    avg = {h: sum(v) / len(v) for h, v in hourly.items() if v}
    if not avg:
        return [], []
    best = sorted(avg.items(), key=lambda kv: kv[1], reverse=True)[:3]
    worst = sorted(avg.items(), key=lambda kv: kv[1])[:3]
    return best, worst


def _procrastination_triggers(features):
    trigger_apps = Counter()
    trigger_context = Counter()
    for f in features:
        if f.get("dopamine_score", 0.0) <= f.get("goal_score", 0.0):
            continue
        exe = f.get("exe")
        if exe:
            trigger_apps[exe] += 1
        title = (f.get("title") or "").lower()
        for cue in behavior_model.DOPAMINE_CUES:
            if cue in title:
                trigger_context[cue] += 1
    return trigger_apps.most_common(5), trigger_context.most_common(5)


def _stress_signals(features, transitions):
    if not features:
        return {"switch_rate": 0.0, "estimate": "niedrig"}
    total_minutes = (features[-1]["ts"] - features[0]["ts"]).total_seconds() / 60.0 or 1.0
    switches = sum(transitions[src][dst] for src in transitions for dst in transitions[src])
    switch_rate = switches / total_minutes
    estimate = "niedrig"
    if switch_rate > 0.8:
        estimate = "hoch"
    elif switch_rate > 0.4:
        estimate = "mittel"
    return {"switch_rate": round(switch_rate, 3), "estimate": estimate}


def _goal_alignment(features):
    if not features:
        return {"alignment": 0.0, "trend": "neutral"}
    goal = sum(f.get("goal_score", 0.0) for f in features) / len(features)
    dopamine = sum(f.get("dopamine_score", 0.0) for f in features) / len(features)
    alignment = max(0.0, min(1.0, 0.5 + goal - dopamine))
    trend = "neutral"
    if alignment >= 0.65:
        trend = "auf Kurs"
    elif alignment <= 0.35:
        trend = "driftet ab"
    return {"alignment": round(alignment, 3), "trend": trend, "goal": goal, "dopamine": dopamine}


def build_digital_twin(entries: List[Dict[str, Any]], analysis: Dict[str, Any] | None = None,
                       forecast: Dict[str, Any] | None = None):
    if not entries:
        return {
            "features": [],
            "transition_matrix": {},
            "hourly_cluster_distribution": {},
            "short_term": {"distribution": {}, "predicted_cluster": None, "algorithm": "none"},
            "productivity_windows": ([], []),
            "procrastination_triggers": ([], []),
            "stress": {"switch_rate": 0.0, "estimate": "niedrig"},
            "goal_alignment": {"alignment": 0.0, "trend": "neutral"},
            "insights": [],
        }

    analysis = analysis or behavior_model.analyze_behaviors(entries)
    labels = analysis.get("labels", [])
    clusters = analysis.get("clusters", {})

    features = _prepare_features(entries, labels)
    matrix, transitions = _transition_matrix(labels)
    hourly_distribution = _hourly_cluster_distribution(features)
    short_term = _short_term_forecast(features, matrix, hourly_distribution)
    productivity_windows = _productivity_windows(features)
    triggers = _procrastination_triggers(features)
    stress = _stress_signals(features, transitions)
    alignment = _goal_alignment(features)

    # Optional one-hour forecast reuse for consistency
    forecast = forecast or {}

    def cluster_name(lbl):
        info = clusters.get(lbl)
        if info:
            return info.get("label", f"cluster_{lbl}")
        return f"cluster_{lbl}"

    insights = []
    if short_term.get("predicted_cluster") is not None:
        cid = short_term["predicted_cluster"]
        prob = short_term["distribution"].get(cid, 0.0) * 100
        insights.append(
            f"Nächste 30 Minuten wahrscheinlich in {cluster_name(cid)} (≈{prob:.1f}%)."
        )
    if forecast.get("predicted_cluster") is not None:
        cid = forecast["predicted_cluster"]
        prob = forecast.get("distribution", {}).get(cid, 0.0) * 100
        insights.append(
            f"Nächste Stunde Prognose: {cluster_name(cid)} (≈{prob:.1f}%)."
        )

    best, worst = productivity_windows
    if best:
        insights.append(
            "Produktivitäts-Peaks rund um "
            + ", ".join([f"{h:02d}:00 ({s:.2f})" for h, s in best])
        )
    if worst:
        insights.append(
            "Produktivitäts-Dip erwartet gegen "
            + ", ".join([f"{h:02d}:00 ({s:.2f})" for h, s in worst])
        )

    if triggers[0]:
        top_app, count = triggers[0][0]
        insights.append(f"Ablenkung häufig durch {top_app} (≈{count} Ereignisse).")

    if stress["estimate"] != "niedrig":
        insights.append(f"Stress-Signal: hoher Wechselrhythmus ({stress['switch_rate']}/Min).")

    if alignment["trend"] == "driftet ab":
        insights.append("Langfristige Ziele in Gefahr: Dopamin-getriebene Muster überwiegen.")
    elif alignment["trend"] == "auf Kurs":
        insights.append("Langfristige Ziele im Blick: zielorientierte Muster dominieren.")

    return {
        "features": features,
        "transition_matrix": matrix,
        "transitions_raw": transitions,
        "hourly_cluster_distribution": hourly_distribution,
        "short_term": short_term,
        "productivity_windows": productivity_windows,
        "procrastination_triggers": triggers,
        "stress": stress,
        "goal_alignment": alignment,
        "clusters": clusters,
        "insights": insights,
    }


def update_state_with_entry(entry: Dict[str, Any], state_path: str = DEFAULT_STATE_PATH) -> None:
    """Incrementally update a persisted twin state with a new log entry.

    The persisted state keeps lightweight counters so every log contributes
    immediately; full clustering is recomputed in the report pipeline.
    """
    try:
        state = json.load(open(state_path, "r", encoding="utf-8"))
    except Exception:
        state = {"events": 0, "hourly_productivity": {}, "last_mode": None}

    ts = entry.get("ts")
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except Exception:
            ts = datetime.now()
    signals = behavior_model.derive_signals(entry)
    prod = _productivity_score(signals)
    hour_key = str(ts.hour)
    hp = state.get("hourly_productivity", {})
    if hour_key not in hp:
        hp[hour_key] = {"sum": 0.0, "count": 0}
    hp[hour_key]["sum"] += prod
    hp[hour_key]["count"] += 1
    state["hourly_productivity"] = hp

    last_mode = state.get("last_mode")
    transitions = state.get("mode_transitions", {})
    cur_mode = entry.get("mode", "unknown")
    if last_mode:
        key = f"{last_mode}->{cur_mode}"
        transitions[key] = transitions.get(key, 0) + 1
    state["mode_transitions"] = transitions
    state["last_mode"] = cur_mode
    state["events"] = state.get("events", 0) + 1

    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        # Swallow write errors to keep logging resilient
        pass


__all__ = ["build_digital_twin", "update_state_with_entry"]
