import json
import os
from typing import List, Tuple

from .categories import normalize_category
from .config import DEFAULT_HEURISTICS, HEURISTICS_FILE


def _clean_rule(rule):
    if not isinstance(rule, dict):
        return None

    mode = normalize_category(rule.get("mode"))
    if mode == "unknown":
        return None

    try:
        conf = float(rule.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    allowed_keys = {
        "exe_exact", "exe_contains", "title_contains", "url_contains", "label_contains"
    }
    cleaned = {}
    for k, v in rule.items():
        if k in allowed_keys and isinstance(v, (list, tuple)) and v:
            cleaned[k] = [str(x).lower() for x in v]

    if not cleaned:
        return None

    return {
        "mode": mode,
        "confidence": conf,
        **cleaned
    }


def load_heuristics():
    user_rules = []
    if os.path.exists(HEURISTICS_FILE):
        try:
            with open(HEURISTICS_FILE, "r", encoding="utf-8") as fh:
                raw_rules = json.load(fh)
        except (OSError, json.JSONDecodeError):
            raw_rules = []

        if isinstance(raw_rules, list):
            for rule in raw_rules:
                cleaned = _clean_rule(rule)
                if cleaned:
                    user_rules.append(cleaned)

    return user_rules + DEFAULT_HEURISTICS


def heuristic_label(snapshot, rules):
    exe = (snapshot.get("exe") or "").lower()
    title = (snapshot.get("title") or "").lower()
    url = (snapshot.get("url") or "").lower()
    labels = " ".join([x.lower() for x in snapshot.get("uia_labels", [])])

    def matches(rule):
        if "exe_exact" in rule and exe not in [x.lower() for x in rule["exe_exact"]]:
            return False
        if "exe_contains" in rule and not any(k in exe for k in rule["exe_contains"]):
            return False
        if "title_contains" in rule and not any(k in title for k in rule["title_contains"]):
            return False
        if "url_contains" in rule and not any(k in url for k in rule["url_contains"]):
            return False
        if "label_contains" in rule and not any(k in labels for k in rule["label_contains"]):
            return False
        return True

    for rule in rules:
        if matches(rule):
            return {"mode": rule["mode"], "confidence": rule.get("confidence", 0.6)}

    return None


def maybe_reload_heuristics(rules, last_mtime: float) -> Tuple[List[dict], float]:
    if not os.path.exists(HEURISTICS_FILE):
        return rules, last_mtime

    current_mtime = os.path.getmtime(HEURISTICS_FILE)
    if last_mtime is None or current_mtime > last_mtime:
        return load_heuristics(), current_mtime
    return rules, last_mtime
