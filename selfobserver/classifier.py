import json
import time
from typing import Dict, Optional, Tuple

import behavior_model

from .capture import (
    capture_screen_base64,
    get_uia_labels,
    is_ignored_window,
    retry_foreground_window,
    try_get_chrome_url,
)
from .categories import normalize_category, save_categories
from .config import ALLOWED_MODES
from .heuristics import heuristic_label
from .models import ollama_text, ollama_vision


TEXT_PROMPT = """
You classify computer activity. Use ONLY this JSON output: {{"mode": "<mode>", "confidence": <0-1>}}.
Allowed modes: {allowed_modes}.

Window data:
{window_data}

Rules:
- Prefer gaming/video/chatting when titles or executables strongly match.
- Treat note-taking apps (Obsidian, Notion, OneNote, Typora) as writing/research, not gaming.
- If the URL suggests AI chat (openai/chatgpt), choose ai_chat.
- When uncertain, respond with unknown and low confidence.
"""

VISION_PROMPT = (
    "Describe the user's activity and classify it. Return only JSON: {\"mode\":\"<mode>\", "
    "\"confidence\":<0-1>}. Focus on whether the view is a video player, a game UI, a chat UI, a document, or browsing."
)


def fused_classification(snapshot: Dict, base64_img: Optional[str], heuristics_rules):
    hints = heuristic_label(snapshot, heuristics_rules)
    if hints:
        return hints

    text_prompt = TEXT_PROMPT.format(
        allowed_modes=', '.join(ALLOWED_MODES),
        window_data=json.dumps(snapshot, indent=2)
    )

    text_out = ollama_text(text_prompt)
    vis_out = ollama_vision(VISION_PROMPT, base64_img)

    strong_keywords = ["video", "gaming", "chatting"]

    if vis_out["mode"] in strong_keywords and vis_out["confidence"] >= 0.4:
        return vis_out

    if text_out["confidence"] + 0.1 >= vis_out["confidence"]:
        return text_out

    return vis_out


def sanity_correct(entry: Dict) -> str:
    exe = (entry.get("exe") or "").lower()
    title = (entry.get("title") or "").lower()
    url = (entry.get("url") or "").lower()
    uia = [x.lower() for x in entry.get("uia_labels", [])]
    mode = entry.get("mode")

    if any(k in title for k in ["bilibili", "哔哩", "youtube", "tiktok", "抖音", "视频"]):
        return "video"
    if any("audio playing" in x for x in uia):
        return "video"

    if exe in ["javaw.exe"] or "minecraft" in title:
        return "gaming"

    if any(x in exe for x in ["wechat", "weixin", "qq", "discord"]):
        return "chatting"

    if "code.exe" in exe:
        return "coding"
    if "obsidian" in exe or "obsidian" in title:
        return "writing"

    if any(k in url for k in ["openai", "chatgpt"]):
        return "ai_chat"

    safe = [
        "coding","gaming","video","chatting","ai_chat",
        "browsing","reading","writing","system","file_management"
    ]
    return mode if mode in safe else "unknown"


def stable_classification(cat_map, heuristics_rules) -> Optional[Dict]:
    modes = []
    confs = []
    snapshot = None

    b64img = capture_screen_base64()

    for _ in range(2):
        fw = retry_foreground_window()
        if not fw:
            continue

        if is_ignored_window(fw):
            return None

        url = ""
        if fw["exe"].lower() == "chrome.exe":
            url = try_get_chrome_url()

        snapshot = {
            "exe": fw["exe"],
            "title": fw["title"],
            "uia_labels": get_uia_labels(fw["hwnd"]),
            "url": url
        }

        fused = fused_classification(snapshot, b64img, heuristics_rules)
        modes.append(fused["mode"])
        confs.append(fused["confidence"])

        time.sleep(0.2)

    if not snapshot:
        return None

    final_mode = max(set(modes), key=modes.count)
    conf = sum(confs)/len(confs)

    final_mode = normalize_category(final_mode)
    final_mode = sanity_correct({**snapshot, "mode": final_mode})

    if final_mode not in cat_map:
        cat_map[final_mode] = []
        save_categories(cat_map)

    snapshot["mode"] = final_mode
    snapshot["confidence"] = conf
    embedding, _ = behavior_model.build_embedding(snapshot)
    snapshot["embedding"] = embedding
    return snapshot
