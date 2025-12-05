import base64
import time
from typing import Optional

import psutil
import win32gui
import win32process
from PIL import ImageGrab
from pywinauto import Desktop
import requests

from .config import IGNORED_PROCESSES, IGNORED_TITLE_KEYWORDS


def capture_screen_base64() -> Optional[str]:
    try:
        img = ImageGrab.grab()
    except Exception as e:
        print("[SCREENSHOT ERROR]", e)
        return None

    path = "screen_shot_tmp.jpg"
    img.save(path, "JPEG", quality=70)

    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_foreground_window():
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        exe = psutil.Process(pid).name()
        title = win32gui.GetWindowText(hwnd)
        return {"hwnd": hwnd, "exe": exe, "title": title}
    except Exception:
        return None


def get_uia_labels(hwnd):
    try:
        app = Desktop(backend="uia").window(handle=hwnd)
        return [c.window_text() for c in app.children() if c.window_text()]
    except Exception:
        return []


def try_get_chrome_url():
    try:
        tabs = requests.get("http://localhost:9222/json", timeout=2).json()
        for t in tabs:
            url = t.get("url", "")
            if url.startswith("http"):
                return url
    except (requests.RequestException, ValueError):
        return ""
    return ""


def is_ignored_window(window_info):
    if not window_info:
        return False

    exe = (window_info.get("exe") or "").lower()
    title = (window_info.get("title") or "").lower()

    if exe in IGNORED_PROCESSES:
        return True

    return any(keyword in title for keyword in IGNORED_TITLE_KEYWORDS)


def retry_foreground_window(wait: float = 0.3, attempts: int = 2):
    for _ in range(attempts):
        fw = get_foreground_window()
        if fw:
            return fw
        time.sleep(wait)
    return None
