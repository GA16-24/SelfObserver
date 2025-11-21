import time
import json
import os
import subprocess
import threading
import base64
from datetime import datetime

import win32gui
import win32process
import psutil
from pywinauto import Desktop
import requests
from PIL import ImageGrab

import daily_report


# ===============================================
# CONFIG
# ===============================================

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "screen_log.jsonl")
CATEGORIES_FILE = "categories.json"

OLLAMA = r"C:\Users\x1sci\AppData\Local\Programs\Ollama\ollama.exe"
MODEL_TEXT = "qwen2.5:7b"
MODEL_VISION = "qwen2.5vl:7b"

os.makedirs(LOG_DIR, exist_ok=True)


# ===============================================
# UTILS
# ===============================================

def load_categories():
    if not os.path.exists(CATEGORIES_FILE):
        return {}
    try:
        return json.load(open(CATEGORIES_FILE, "r", encoding="utf-8"))
    except:
        return {}

def save_categories(cat):
    json.dump(cat, open(CATEGORIES_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

def normalize_category(cat):
    if not cat:
        return "unknown"
    return cat.lower().strip().replace(" ", "_").replace("-", "_")


# ===============================================
# Screen capture (A)
# ===============================================

def capture_screen_base64():
    """Capture full screen, encode to base64."""
    img = ImageGrab.grab()
    path = "screen_shot_tmp.jpg"
    img.save(path, "JPEG", quality=70)

    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ===============================================
# Foreground window
# ===============================================

def get_foreground_window():
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        exe = psutil.Process(pid).name()
        title = win32gui.GetWindowText(hwnd)
        return {"hwnd": hwnd, "exe": exe, "title": title}
    except:
        return None


def get_uia_labels(hwnd):
    try:
        app = Desktop(backend="uia").window(handle=hwnd)
        return [c.window_text() for c in app.children() if c.window_text()]
    except:
        return []


# ===============================================
# Chrome URL
# ===============================================

def try_get_chrome_url():
    try:
        tabs = requests.get("http://localhost:9222/json").json()
        for t in tabs:
            url = t.get("url", "")
            if url.startswith("http"):
                return url
    except:
        pass
    return ""


# ===============================================
# Ollama TEXT classify
# ===============================================

def ollama_text(prompt):
    try:
        result = subprocess.run(
            [OLLAMA, "run", MODEL_TEXT],
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=20
        )
        raw = result.stdout.decode("utf-8", "ignore")

        start = raw.find("{")
        end = raw.rfind("}") + 1
        return json.loads(raw[start:end])
    except:
        return {"mode": "unknown", "confidence": 0.0}

# ===============================================
# VISION INFERENCE (VL MODEL RAW OUTPUT)
# ===============================================

def vision_infer(image_path, prompt_text="Describe this image"):
    """
    Run vision model qwen2.5vl:7b
    Show FULL RAW model output for debugging
    Save raw output to vision_raw.log
    """
    try:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        # Correct prompt format for Ollama 0.12.11
        vision_prompt = f"""
{{"image": "{img_b64}"}}
{prompt_text}
"""

        result = subprocess.run(
            [OLLAMA, "run", MODEL_VISION],   # ★ FIXED
            input=vision_prompt.encode("utf-8"),
            capture_output=True,
            timeout=40
        )

        raw = result.stdout.decode("utf-8", "ignore")

        print("\n========== RAW VISION OUTPUT ==========")
        print(raw)
        print("========================================\n")

        with open("vision_raw.log", "a", encoding="utf-8") as f:
            f.write("\n==== RAW VISION OUTPUT ====\n")
            f.write(raw)
            f.write("\n===========================\n")

        return raw

    except Exception as e:
        print("[VISION ERROR]", e)
        return None


# ===============================================
# Ollama VISION classify (B + A)
# ===============================================

def ollama_vision(prompt, base64_img):
    """
    Ollama Vision API — 官方要求 payload 是纯 JSON
    使用 stdin 输入 JSON，而不是 CLI 参数。
    """
    payload = {
        "prompt": prompt,
        "images": [base64_img]
    }

    try:
        result = subprocess.run(
            [OLLAMA, "run", MODEL_VISION],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            timeout=25
        )
        raw = result.stdout.decode("utf-8", "ignore")

        start = raw.find("{")
        end = raw.rfind("}") + 1
        return json.loads(raw[start:end])
    except:
        return {"mode": "unknown", "confidence": 0.0}


# ===============================================
# TEXT + VISION Fusion
# ===============================================

def fused_classification(snapshot, base64_img, known_categories):
    """
    Combine:
    1) TEXT 分析
    2) VISION 分析
    3) OCR from Vision
    """

    text_prompt = f"""
You classify activity based on window data:

{json.dumps(snapshot, indent=2)}

Return only JSON:
{{"mode":"...", "confidence":0.0}}
"""

    vision_prompt = """
Describe the user's activity. Focus on:
- Is this a VIDEO page?
- Is this a GAME screen?
- Is the user chatting?
- Is it a document or browsing?

Return JSON only:
{"mode":"...", "confidence":0.0}
"""

    text_out = ollama_text(text_prompt)
    vis_out = ollama_vision(vision_prompt, base64_img)

    # Fusion rule: Vision wins for video/game/chat UI
    strong_keywords = ["video", "gaming", "chatting"]

    if vis_out["mode"] in strong_keywords:
        return vis_out

    # else text-based dominates
    if text_out["confidence"] >= vis_out["confidence"]:
        return text_out

    return vis_out


# ===============================================
# Sanity correction (same as previous v5)
# ===============================================

def sanity_correct(entry):
    exe = (entry.get("exe") or "").lower()
    title = (entry.get("title") or "").lower()
    url = (entry.get("url") or "").lower()
    uia = [x.lower() for x in entry.get("uia_labels", [])]
    mode = entry.get("mode")

    # VIDEO 强规则
    if any(k in title for k in ["bilibili", "哔哩", "youtube", "tiktok", "抖音", "视频"]):
        return "video"
    if any("audio playing" in x for x in uia):
        return "video"

    # GAMING
    if exe in ["javaw.exe"] or "minecraft" in title:
        return "gaming"

    # CHAT
    if any(x in exe for x in ["wechat", "weixin", "qq", "discord"]):
        return "chatting"

    # AI CHAT
    if any(k in url for k in ["openai", "chatgpt"]):
        return "ai_chat"

    safe = ["coding","gaming","video","chatting","ai_chat",
            "browsing","reading","writing","system","file_management"]
    return mode if mode in safe else "unknown"


# ===============================================
# Stable classification
# ===============================================

def stable_classification(cat_map):
    modes = []
    confs = []
    snapshot = None

    # Capture screen first
    b64img = capture_screen_base64()

    for _ in range(2):  # 2 votes (with vision already heavy)
        fw = get_foreground_window()
        if not fw:
            time.sleep(0.3)
            continue

        url = ""
        if fw["exe"].lower() == "chrome.exe":
            url = try_get_chrome_url()

        snapshot = {
            "exe": fw["exe"],
            "title": fw["title"],
            "uia_labels": get_uia_labels(fw["hwnd"]),
            "url": url
        }

        fused = fused_classification(snapshot, b64img, cat_map)
        modes.append(fused["mode"])
        confs.append(fused["confidence"])

        time.sleep(0.2)

    if not snapshot:
        return {"mode":"unknown","confidence":0.0}

    # vote
    final_mode = max(set(modes), key=modes.count)
    conf = sum(confs)/len(confs)

    final_mode = normalize_category(final_mode)
    final_mode = sanity_correct({
        **snapshot,
        "mode": final_mode
    })

    # save new category
    if final_mode not in cat_map:
        cat_map[final_mode] = []
        save_categories(cat_map)

    snapshot["mode"] = final_mode
    snapshot["confidence"] = conf
    return snapshot


# ===============================================
# Logging
# ===============================================

def write_log(entry):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def pretty_print(e):
    t = e["title"]
    if len(t) > 50:
        t = t[:47] + "..."
    print(f"[{e['ts']}] {e['exe']:<12} | {e['mode']:<10} | {e['confidence']:.2f} | {t}")


# ===============================================
# Daily Report thread
# ===============================================

def schedule_daily_report():
    TARGET_HOUR = 22
    TARGET_MIN = 0
    last_date = None

    while True:
        now = datetime.now()
        if now.hour == TARGET_HOUR and now.minute == TARGET_MIN and last_date != now.date():
            try:
                p = daily_report.generate_daily_report()
                print("[REPORT SAVED]", p)
                last_date = now.date()
            except Exception as e:
                print("[REPORT ERROR]", e)
            time.sleep(70)
        else:
            time.sleep(15)


# ===============================================
# MAIN
# ===============================================

def main():
    print("[SelfObserver v10] Vision + OCR + Text Fusion")

    cat_map = load_categories()

    while True:
        snap = stable_classification(cat_map)

        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            **snap
        }

        pretty_print(entry)
        write_log(entry)

        time.sleep(2)


if __name__ == "__main__":
    threading.Thread(target=schedule_daily_report, daemon=True).start()
    main()
