import hashlib
import math
from collections import Counter, defaultdict
from typing import List, Dict, Any

SEGMENT_SIZE = 128
SEGMENTS = {
    "intention": 0,
    "context": 1,
    "cognitive": 2,
    "emotional": 3,
    "dopamine_goal": 4,
    "app_semantics": 5,
}
EMBEDDING_SIZE = SEGMENT_SIZE * len(SEGMENTS)

DOPAMINE_CUES = {
    "tiktok",
    "youtube",
    "bilibili",
    "netflix",
    "game",
    "gaming",
    "steam",
    "browsing",
    "scroll",
    "feed",
    "reddit",
    "twitter",
    "instagram",
    "video",
    "shorts",
    "discord",
    "chat",
    "ai_chat",
}
GOAL_CUES = {
    "code",
    "coding",
    "ide",
    "vscode",
    "work",
    "project",
    "write",
    "obsidian",
    "notion",
    "note",
    "research",
    "paper",
    "doc",
    "ppt",
    "excel",
    "analysis",
    "debug",
    "terminal",
    "reading",
}
COGNITIVE_HEAVY = {
    "debug",
    "compile",
    "analysis",
    "write",
    "research",
    "solve",
    "problem",
    "refactor",
    "review",
    "deploy",
    "ide",
    "editor",
    "terminal",
    "math",
    "design",
    "architecture",
}
EMOTIONAL_POS = {"win", "completed", "success", "achieved", "great", "good", "yay", "love"}
EMOTIONAL_NEG = {"fail", "error", "lost", "died", "crash", "stuck", "boring", "bad", "angry", "sad"}


def _hash(token: str, segment: int) -> int:
    data = f"{segment}:{token}".encode("utf-8")
    digest = hashlib.sha256(data).digest()
    return int.from_bytes(digest[:4], "big") % SEGMENT_SIZE


def _add_token(vec: List[float], segment: int, token: str, weight: float) -> None:
    base = segment * SEGMENT_SIZE
    idx = base + _hash(token, segment)
    vec[idx] += weight


def _tokenize(text: str) -> List[str]:
    cleaned = []
    for raw in (text or "").replace("/", " ").replace("\\", " ").replace("_", " ").split():
        tok = raw.strip().lower()
        if tok:
            cleaned.append(tok)
    return cleaned


def derive_signals(activity: Dict[str, Any]) -> Dict[str, Any]:
    """Return interpretable signals used for embeddings and labeling."""
    title = activity.get("title") or ""
    exe = activity.get("exe") or ""
    url = activity.get("url") or ""
    uia = " ".join(activity.get("uia_labels", [])) if activity.get("uia_labels") else ""
    mode = activity.get("mode") or ""

    text_blob = f"{title} {exe} {url} {uia} {mode}"
    tokens = _tokenize(text_blob)

    dopamine_hits = sum(1 for t in tokens if t in DOPAMINE_CUES)
    goal_hits = sum(1 for t in tokens if t in GOAL_CUES)
    cog_hits = sum(1 for t in tokens if t in COGNITIVE_HEAVY)
    pos_hits = sum(1 for t in tokens if t in EMOTIONAL_POS)
    neg_hits = sum(1 for t in tokens if t in EMOTIONAL_NEG)

    dopamine_score = dopamine_hits / max(1, len(tokens))
    goal_score = goal_hits / max(1, len(tokens))
    cognitive_load = min(1.0, 0.2 + (cog_hits * 0.15))
    emotional_tone = 0.5 + (pos_hits - neg_hits) * 0.05
    emotional_tone = max(0.0, min(1.0, emotional_tone))

    return {
        "tokens": tokens,
        "dopamine_score": dopamine_score,
        "goal_score": goal_score,
        "cognitive_load": cognitive_load,
        "emotional_tone": emotional_tone,
        "mode": mode.lower(),
        "exe": exe.lower(),
    }


def build_embedding(activity: Dict[str, Any]):
    signals = derive_signals(activity)
    vec: List[float] = [0.0] * EMBEDDING_SIZE

    for tok in signals["tokens"]:
        _add_token(vec, SEGMENTS["intention"], tok, 0.8)
        if tok.startswith("http"):
            _add_token(vec, SEGMENTS["context"], tok, 0.6)
        _add_token(vec, SEGMENTS["app_semantics"], tok, 0.5)

    if signals["exe"]:
        _add_token(vec, SEGMENTS["app_semantics"], signals["exe"], 1.0)

    if activity.get("uia_labels"):
        for label in activity["uia_labels"]:
            _add_token(vec, SEGMENTS["context"], label.lower(), 0.6)

    cognitive_weight = 1.0 + signals["cognitive_load"]
    for tok in signals["tokens"]:
        if tok in COGNITIVE_HEAVY:
            _add_token(vec, SEGMENTS["cognitive"], tok, cognitive_weight)

    _add_token(vec, SEGMENTS["emotional"], "positive", signals["emotional_tone"])
    _add_token(vec, SEGMENTS["emotional"], "negative", 1.0 - signals["emotional_tone"])

    _add_token(vec, SEGMENTS["dopamine_goal"], "dopamine", signals["dopamine_score"])
    _add_token(vec, SEGMENTS["dopamine_goal"], "goal", signals["goal_score"])

    mode = signals.get("mode")
    if mode:
        _add_token(vec, SEGMENTS["intention"], f"mode:{mode}", 0.9)

    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    vec = [x / norm for x in vec]
    return vec, signals


def cluster_embeddings(embeddings: List[List[float]]):
    if not embeddings:
        return {"labels": [], "algorithm": "none"}

    try:
        import hdbscan  # type: ignore

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=max(2, int(len(embeddings) ** 0.5)), metric="euclidean"
        )
        labels = clusterer.fit_predict(embeddings)
        return {"labels": labels.tolist(), "algorithm": "hdbscan"}
    except Exception:
        pass

    try:
        import importlib

        sklearn_cluster = importlib.import_module("sklearn.cluster")
        DBSCAN = getattr(sklearn_cluster, "DBSCAN")

        eps = 0.6 if len(embeddings) > 10 else 0.8
        labels = DBSCAN(eps=eps, min_samples=2).fit_predict(embeddings)
        return {"labels": labels.tolist(), "algorithm": "dbscan"}
    except Exception:
        pass

    try:
        import importlib

        sklearn_cluster = importlib.import_module("sklearn.cluster")
        KMeans = getattr(sklearn_cluster, "KMeans")

        k = min(6, max(2, int(len(embeddings) ** 0.5)))
        labels = KMeans(n_clusters=k, n_init=5, random_state=42).fit_predict(embeddings)
        return {"labels": labels.tolist(), "algorithm": f"kmeans_{k}"}
    except Exception:
        k = 2
        centroids = embeddings[:k]
        labels = []
        for vec in embeddings:
            dists = [sum((a - b) ** 2 for a, b in zip(vec, c)) for c in centroids]
            labels.append(dists.index(min(dists)))
        return {"labels": labels, "algorithm": "simple_kmeans"}


def label_clusters(labels, entries, signals_list):
    cluster_entries = defaultdict(list)
    for lbl, entry, sig in zip(labels, entries, signals_list):
        cluster_entries[lbl].append((entry, sig))

    labeled = {}
    for lbl, data in cluster_entries.items():
        modes = Counter(d[0].get("mode", "unknown") for d in data)
        exes = Counter(d[0].get("exe", "unknown") for d in data)
        avg_cognitive = sum(s["cognitive_load"] for _, s in data) / len(data)
        avg_dopamine = sum(s["dopamine_score"] for _, s in data) / len(data)
        avg_goal = sum(s["goal_score"] for _, s in data) / len(data)

        label = "behavior_cluster"
        if avg_cognitive > 0.6 and avg_goal >= avg_dopamine:
            label = "deep_work"
        elif avg_dopamine > 0.5 and avg_goal < 0.3:
            label = "dopamine_scrolling"
        elif "game" in " ".join(modes.keys()):
            label = "gaming_focus"
        elif len(modes) > 3 and avg_cognitive < 0.5:
            label = "micro_tasking"
        elif avg_goal > 0.5 and avg_dopamine < 0.4:
            label = "research_mode"

        labeled[lbl] = {
            "label": label,
            "top_modes": modes.most_common(3),
            "top_apps": exes.most_common(3),
            "avg_cognitive_load": round(avg_cognitive, 3),
            "avg_dopamine_drive": round(avg_dopamine, 3),
            "avg_goal_focus": round(avg_goal, 3),
            "size": len(data),
        }

    return labeled


def summarize_transitions(labels):
    transitions = Counter()
    for prev, nxt in zip(labels, labels[1:]):
        if prev == nxt:
            continue
        transitions[(prev, nxt)] += 1
    return transitions


def flow_state_likelihood(labels):
    if not labels:
        return 0.0
    dominant = Counter(labels).most_common(1)[0][1]
    return round(dominant / len(labels), 3)


def analyze_behaviors(entries: List[Dict[str, Any]]):
    embeddings = []
    signals = []
    for entry in entries:
        vec = entry.get("embedding")
        sig = None
        if vec and len(vec) == EMBEDDING_SIZE:
            _, sig = build_embedding(entry)
        else:
            vec, sig = build_embedding(entry)
            entry["embedding"] = vec
        embeddings.append(vec)
        signals.append(sig)

    clustering = cluster_embeddings(embeddings)
    labels = clustering["labels"]

    labeled_clusters = label_clusters(labels, entries, signals) if labels else {}
    transitions = summarize_transitions(labels) if labels else {}
    flow = flow_state_likelihood(labels) if labels else 0.0

    anomalies = [i for i, lbl in enumerate(labels) if lbl == -1]

    return {
        "embeddings": embeddings,
        "labels": labels,
        "clusters": labeled_clusters,
        "transitions": transitions,
        "flow_state_likelihood": flow,
        "anomaly_indices": anomalies,
        "algorithm": clustering.get("algorithm", "none"),
    }
