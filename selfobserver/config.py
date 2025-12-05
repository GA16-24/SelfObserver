import os
from typing import List

ALLOWED_MODES: List[str] = [
    "coding",
    "gaming",
    "video",
    "chatting",
    "ai_chat",
    "browsing",
    "reading",
    "writing",
    "system",
    "file_management",
    "unknown",
]

LOG_DIR = "logs"
CATEGORIES_FILE = "categories.json"
HEURISTICS_FILE = "heuristics.json"

OLLAMA = os.environ.get("OLLAMA_EXE", r"C:\\Users\\x1sci\\AppData\\Local\\Programs\\Ollama\\ollama.exe")
MODEL_TEXT = os.environ.get("SELFOB_TEXT_MODEL", "qwen2.5:7b")
MODEL_VISION = os.environ.get("SELFOB_VISION_MODEL", "qwen2.5-vl:7b")

IGNORED_PROCESSES = {"lockapp.exe"}
IGNORED_TITLE_KEYWORDS = ["windows default lock screen"]

DEFAULT_HEURISTICS = [
    {"mode": "coding", "confidence": 0.8, "exe_contains": ["antigravity"]},
    {"mode": "coding", "confidence": 0.7, "title_contains": ["antigravity"]},

    {"mode": "ai_chat", "confidence": 0.85, "url_contains": ["kimi.moonshot", "kimi.ai", "kimi.chat"]},
    {"mode": "ai_chat", "confidence": 0.75, "title_contains": ["kimi"], "url_contains": ["kimi"]},

    {"mode": "video", "confidence": 0.9, "url_contains": ["youtube", "bilibili", "tiktok", "youku", "netflix"]},
    {"mode": "video", "confidence": 0.7, "title_contains": ["youtube", "video"]},
    {"mode": "video", "confidence": 0.7, "exe_contains": ["obs64", "vlc", "mpv", "potplayer"]},

    {"mode": "ai_chat", "confidence": 0.8, "exe_exact": ["chrome.exe"], "url_contains": ["openai", "chatgpt", "poe.com", "claude.ai"]},
    {"mode": "chatting", "confidence": 0.7, "exe_contains": ["wechat", "weixin", "qq", "discord", "slack", "teams"]},

    {"mode": "gaming", "confidence": 0.6, "label_contains": ["game", "play", "hp", "health", "inventory"]},
]


def log_path_for_date(day):
    return os.path.join(LOG_DIR, f"screen_log_{day.isoformat()}.jsonl")
