import importlib.util
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import behavior_model


def _module_available(name: str) -> bool:
    """Check whether an optional dependency can be imported without importing it."""

    return importlib.util.find_spec(name) is not None


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
    last_ts: Optional[datetime] = None

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

        time_feats = _cyclical_time_features(ts)
        productivity = _productivity_score(signals)

        features.append(
            {
                "ts": ts,
                "embedding": embedding,
                "time": time_feats,
                "session_len": session_len,
                "cluster": labels[idx] if idx < len(labels) else -1,
                "productivity": productivity,
                "dopamine_score": signals.get("dopamine_score", 0.0),
            }
        )

    return features


def _rolling_probability_baseline(features: List[Dict[str, Any]]):
    if not features:
        return {
            "distribution": {},
            "predicted_cluster": None,
            "productivity": 0.0,
            "distraction": 0.0,
            "algorithm": "baseline",
        }

    last = features[-1]["cluster"]

    transitions = Counter()
    counts = Counter()
    by_hour: Dict[int, Counter] = defaultdict(Counter)

    for prev, nxt in zip(features, features[1:]):
        transitions[(prev["cluster"], nxt["cluster"])] += 1
        counts[nxt["cluster"]] += 1
        by_hour[nxt["ts"].hour][nxt["cluster"]] += 1

    distribution = Counter()

    # Conditional probability from last cluster
    for (a, b), c in transitions.items():
        if a == last:
            distribution[b] += c

    # Blend in overall and hour-of-day priors
    for cluster_id, c in counts.items():
        distribution[cluster_id] += 0.25 * c

    hour_counts = by_hour[features[-1]["ts"].hour]
    for cluster_id, c in hour_counts.items():
        distribution[cluster_id] += 0.5 * c

    if not distribution:
        distribution[last] += 1

    total = sum(distribution.values()) or 1.0
    normalized = {k: v / total for k, v in distribution.items()}

    productivity = sum(f["productivity"] for f in features[-5:]) / min(len(features), 5)
    distraction = sum(f.get("dopamine_score", 0.0) for f in features[-5:]) / min(len(features), 5)

    return {
        "distribution": normalized,
        "predicted_cluster": max(normalized, key=normalized.get),
        "productivity": productivity,
        "distraction": distraction,
        "algorithm": "baseline",
    }


def _forecast_with_prophet(features: List[Dict[str, Any]]):
    if not _module_available("prophet"):
        return None
    # Prophet would require fitting a time-series; for now defer to baseline when unavailable.
    return None


def _forecast_with_sequence_model(features: List[Dict[str, Any]]):
    if not _module_available("torch"):
        return None

    # In constrained environments we fall back to the baseline even when torch is installed
    # to avoid long-running training. Hook exists for future expansion.
    return None


def _forecast_with_tcn(features: List[Dict[str, Any]]):
    if not _module_available("torch"):
        return None
    return None


def forecast_next_hour(entries: List[Dict[str, Any]], analysis: Optional[Dict[str, Any]] = None):
    if not entries:
        return {
            "distribution": {},
            "predicted_cluster": None,
            "productivity": 0.0,
            "distraction": 0.0,
            "algorithm": "baseline",
            "insights": [],
        }

    analysis = analysis or behavior_model.analyze_behaviors(entries)
    labels = analysis.get("labels", [])
    clusters_meta = analysis.get("clusters", {})

    features = _prepare_features(entries, labels)

    forecasters = [
        _forecast_with_sequence_model,
        _forecast_with_tcn,
        _forecast_with_prophet,
        _rolling_probability_baseline,
    ]

    forecast = None
    for fn in forecasters:
        forecast = fn(features)
        if forecast:
            break

    forecast = forecast or _rolling_probability_baseline(features)

    def _cluster_name(lbl):
        info = clusters_meta.get(lbl)
        if info:
            return info.get("label", f"cluster_{lbl}")
        return f"cluster_{lbl}"

    insights = []

    if forecast.get("predicted_cluster") is not None:
        cluster_id = forecast["predicted_cluster"]
        cluster_label = _cluster_name(cluster_id)
        prob = forecast["distribution"].get(cluster_id, 0.0) * 100
        insights.append(
            f"Es besteht eine {prob:.1f}% Wahrscheinlichkeit, in der nächsten Stunde in '{cluster_label}' zu bleiben oder zu wechseln."
        )

    distraction = forecast.get("distraction", 0.0)
    if distraction >= 0.5:
        insights.append("Erhöhte Ablenkungsgefahr: Inhalte mit Dopamin-Fokus dominierten zuletzt.")
    elif distraction <= 0.2:
        insights.append("Geringe Ablenkung: Die letzten Aktivitäten waren zielorientiert.")

    productivity = forecast.get("productivity", 0.0)
    if productivity >= 0.6:
        insights.append("Produktivität vermutlich hoch: Nutze das Zeitfenster für Deep Work.")
    elif productivity <= 0.3:
        insights.append("Produktivität fällt voraussichtlich ab: Kurze Pause einplanen oder Scope reduzieren.")

    # Hourly pattern check for peaks and drops
    hourly_prod: Dict[int, List[float]] = defaultdict(list)
    for f in features:
        hourly_prod[f["ts"].hour].append(f["productivity"])
    hourly_avg = {h: sum(v) / len(v) for h, v in hourly_prod.items()}
    if hourly_avg:
        peak_hour = max(hourly_avg, key=hourly_avg.get)
        low_hour = min(hourly_avg, key=hourly_avg.get)
        insights.append(
            f"Fokus-Peak um ca. {peak_hour:02d}:00; schwächere Phase typischerweise gegen {low_hour:02d}:00."
        )

    forecast["insights"] = insights
    forecast["clusters_meta"] = clusters_meta
    return forecast
