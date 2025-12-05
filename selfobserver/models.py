import base64
import json
import subprocess
from typing import Optional

from .config import ALLOWED_MODES, MODEL_TEXT, MODEL_VISION, OLLAMA
from .categories import normalize_category


PROMPT_HEADER = (
    "You are a strict classifier. Only respond with JSON in the form {\"mode\": \"<mode>\", "
    "\"confidence\": <0-1>}. Allowed modes: " + ', '.join(ALLOWED_MODES) + ". If unsure, return {\"mode\":\"unknown\",\"confidence\":0}."
)


def parse_model_json(raw: str, fallback_mode: str = "unknown"):
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end]) if start != -1 and end != 0 else {}
    except Exception:
        data = {}

    mode = normalize_category(data.get("mode")) if isinstance(data, dict) else "unknown"
    conf = data.get("confidence", 0.0) if isinstance(data, dict) else 0.0

    try:
        conf = max(0.0, min(1.0, float(conf)))
    except Exception:
        conf = 0.0

    if mode == "unknown":
        mode = fallback_mode

    return {"mode": mode, "confidence": conf}


def ollama_text(prompt: str):
    prompt = f"{PROMPT_HEADER}\n\nContext:\n{prompt}"
    try:
        result = subprocess.run(
            [OLLAMA, "run", MODEL_TEXT],
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=20
        )
        raw = result.stdout.decode("utf-8", "ignore")
        return parse_model_json(raw)
    except Exception:
        return {"mode": "unknown", "confidence": 0.0}


def vision_infer(image_path: str, prompt_text: str = "Describe this image") -> Optional[str]:
    try:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        vision_prompt = f"{{\"image\": \"{img_b64}\"}}\n{prompt_text}"

        result = subprocess.run(
            [OLLAMA, "run", MODEL_VISION],
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


def ollama_vision(prompt: str, base64_img: Optional[str]):
    if not base64_img:
        return {"mode": "unknown", "confidence": 0.0}

    payload = {
        "prompt": f"{PROMPT_HEADER}\n\nContext:\n{prompt}",
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
        return parse_model_json(raw)
    except Exception:
        return {"mode": "unknown", "confidence": 0.0}
