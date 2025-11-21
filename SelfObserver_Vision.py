import time
import os
import json
import base64
import requests
from datetime import datetime

# ===== CONFIG =====
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5vl:7b"
SCREENSHOT_PATH = "screen.png"
LOG_PATH = "vision_logs.jsonl"
INTERVAL = 15   # 每 15 秒检测一次


# ===== 截图 =====
def take_screenshot():
    try:
        import mss
        import mss.tools
    except ImportError:
        print("[!] 需要安装 mss： pip install mss")
        exit()

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        img = sct.grab(monitor)
        mss.tools.to_png(img.rgb, img.size, output=SCREENSHOT_PATH)

    return SCREENSHOT_PATH


# ===== Vision 推理 =====
def vision_understand(image_path):
    # base64
    with open(image_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode()

    # ⚠ 重点：把图片嵌入 Markdown，Ollama Vision 官方支持的唯一格式
    md_prompt = f"""
![screenshot](data:image/png;base64,{img_base64})

你是一个“全局屏幕理解”模型。基于截图，请输出严格 JSON：

{{
  "activity": "",
  "sub_activity": "",
  "apps": [],
  "focus_window": "",
  "evidence": "",
  "confidence": 0.0
}}
"""

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": md_prompt
            }
        ],
        "stream": False
    }

    r = requests.post(OLLAMA_URL, json=payload)

    if r.status_code != 200:
        print("[ERROR] Vision API failed:", r.text)
        return None

    try:
        data = r.json()
        # qwen2.5-vl 返回格式：data["message"]["content"]
        return data["message"]["content"]
    except Exception as e:
        print("[ERROR] parse failed", e)
        print(r.text)
        return None


# ===== 保存日志 =====
def save_log(result_json):
    with open(LOG_PATH, "a", encoding="utf8") as f:
        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "result": result_json
        }
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ===== 主循环 =====
def main():
    print("\n=== SelfObserver Vision (Ollama Vision Compatible Edition) 启动 ===\n")

    while True:
        try:
            # 1. 截图
            path = take_screenshot()

            # 2. 推理
            print("[+] 推理中...")
            out = vision_understand(path)

            if out:
                print("\n=== 推理结果 ===")
                print(out)
                print()
                save_log(out)

        except Exception as e:
            print("[ERROR]", e)

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
