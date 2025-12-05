import json
import os
from typing import Dict, List

from .config import ALLOWED_MODES, CATEGORIES_FILE


def load_categories() -> Dict[str, List[Dict]]:
    if not os.path.exists(CATEGORIES_FILE):
        return {}

    try:
        with open(CATEGORIES_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_categories(cat: Dict[str, List[Dict]]) -> None:
    with open(CATEGORIES_FILE, "w", encoding="utf-8") as fh:
        json.dump(cat, fh, indent=2, ensure_ascii=False)


def normalize_category(cat: str) -> str:
    if not cat:
        return "unknown"
    cleaned = cat.lower().strip().replace(" ", "_").replace("-", "_")
    return cleaned if cleaned in ALLOWED_MODES else "unknown"
