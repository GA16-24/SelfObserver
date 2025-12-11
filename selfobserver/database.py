"""Lightweight persistence helpers for goals and project mappings."""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Dict, List, Optional, Tuple

from .config import LOG_DIR

GOALS_FILE = os.path.join(LOG_DIR, "goals.json")
PROJECTS_FILE = "projects.json"

DEFAULT_PROJECTS = {
    "rules": [
        {
            "name": "Website Redesign",
            "title_contains": ["figma", "website", "landing"],
            "path_contains": ["/Website", "\\Website"],
        },
        {
            "name": "Research",
            "title_contains": ["notion", "paper", "arxiv", "research"],
        },
        {
            "name": "Inbox",
            "title_contains": ["gmail", "outlook", "mail"],
        },
    ],
    "default": "General",
}


# ---------------------- utilities ----------------------
def _ensure_logs_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


# ---------------------- goals ----------------------
def load_goals() -> List[dict]:
    _ensure_logs_dir()
    data = _load_json(GOALS_FILE, [])
    if not isinstance(data, list):
        return []
    return data


def save_goals(goals: List[dict]):
    _ensure_logs_dir()
    with open(GOALS_FILE, "w", encoding="utf-8") as fh:
        json.dump(goals, fh, ensure_ascii=False, indent=2)


def add_goal(title: str, due: Optional[str] = None) -> List[dict]:
    goals = load_goals()
    goals.append(
        {
            "id": str(uuid.uuid4()),
            "title": title,
            "done": False,
            "due": due,
            "created": time.time(),
            "source": "dashboard",
        }
    )
    save_goals(goals)
    return goals


def toggle_goal(goal_id: str, done: bool) -> List[dict]:
    goals = load_goals()
    for goal in goals:
        if goal.get("id") == goal_id:
            goal["done"] = bool(done)
            break
    save_goals(goals)
    return goals


# ---------------------- projects ----------------------
def ensure_default_projects_file():
    if not os.path.exists(PROJECTS_FILE):
        with open(PROJECTS_FILE, "w", encoding="utf-8") as fh:
            json.dump(DEFAULT_PROJECTS, fh, ensure_ascii=False, indent=2)


def load_project_mappings() -> Tuple[Dict, Optional[float]]:
    ensure_default_projects_file()
    mtime = os.path.getmtime(PROJECTS_FILE)
    return _load_json(PROJECTS_FILE, DEFAULT_PROJECTS), mtime


def maybe_reload_project_mappings(current: Optional[Dict], last_mtime: Optional[float]):
    try:
        current_mtime = os.path.getmtime(PROJECTS_FILE)
    except FileNotFoundError:
        ensure_default_projects_file()
        current_mtime = os.path.getmtime(PROJECTS_FILE)

    if current is None or last_mtime is None or current_mtime > last_mtime:
        return load_project_mappings()
    return current, last_mtime


def resolve_project(entry: dict, mapping: Dict | None = None) -> Optional[str]:
    if mapping is None:
        mapping, _ = load_project_mappings()

    rules = mapping.get("rules") or []
    title = (entry.get("title") or "").lower()
    path = (entry.get("path") or "").lower()
    exe = (entry.get("exe") or "").lower()

    for rule in rules:
        name = rule.get("name")
        if not name:
            continue
        title_contains = [t.lower() for t in rule.get("title_contains", [])]
        path_contains = [t.lower() for t in rule.get("path_contains", [])]
        exe_contains = [t.lower() for t in rule.get("exe_contains", [])]

        if any(token in title for token in title_contains):
            return name
        if any(token in path for token in path_contains):
            return name
        if any(token in exe for token in exe_contains):
            return name

    return mapping.get("default")
