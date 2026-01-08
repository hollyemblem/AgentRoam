import cv2
import numpy as np
import time
import glob
import os
import base64
import logging
import re
import mss
from dotenv import load_dotenv
from pathlib import Path
from langtrace_python_sdk import langtrace
from opentelemetry import trace

from openai import OpenAI
from google import genai
from google.genai import types
import anthropic              # Claude
from groq import Groq         # Llama via Groq
from pynput.keyboard import Controller
import time

# ------------ CONFIG & SETUP ------------
load_dotenv(dotenv_path=Path.cwd().parent / ".env")
langtrace.init(api_key=os.getenv("LANGTRACE_API_KEY"), write_spans_to_console=False)

logger = logging.getLogger(__name__)
logging.basicConfig(
    filename=os.getenv("LOGGER_NAME"),
    encoding="utf-8",
    level=logging.DEBUG,
    format="%(levelname)s:%(message)s",
)

SAVE_INTERVAL = 10
last_save_time = 0.0
CAPTURE_DIR = os.getenv("CAPTURE_DIRECTORY") or "./captures"
os.makedirs(CAPTURE_DIR, exist_ok=True)
print(f"📁 Saving images to: {CAPTURE_DIR}")


# -----------------------------------------------------------
#                     HELPER FUNCTIONS
# -----------------------------------------------------------

def get_latest_image(folder_name):
    files = glob.glob(folder_name)
    return max(files, key=os.path.getctime) if files else None

def extract_direction(text):
    m = re.search(r"\b(MOVE_UP|MOVE_DOWN|MOVE_LEFT|MOVE_RIGHT|CAMERA_UP|CAMERA_DOWN|CAMERA_LEFT|CAMERA_RIGHT)\b", text, flags=re.IGNORECASE)
    return m.group(1).upper() if m else None

def directions_executor(direction):
    direction = direction.strip().upper()
    keyboard = Controller()

    def tap(key, n, hold=0.05, gap=0.45):
        for _ in range(n):
            keyboard.press(key)
            time.sleep(hold)
            keyboard.release(key)
            time.sleep(gap)

    if direction == "MOVE_UP":
        tap('w', 5)
    elif direction == "MOVE_DOWN":
        tap('s', 5)
    elif direction == "MOVE_LEFT":
        tap('a', 5)
    elif direction == "MOVE_RIGHT":
        tap('d', 5)
    elif direction == "CAMERA_UP":
        tap('j', 2)
    elif direction == "CAMERA_DOWN":
        tap('u', 2)
    elif direction == "CAMERA_LEFT":
        tap('h', 2)
    elif direction == "CAMERA_RIGHT":
        tap('k', 2)
    else:
        print(f"Invalid action: {direction}")



# -----------------------------------------------------------
#                     LLM DISPATCHER
# -----------------------------------------------------------

def call_llm(folder_name, llm_value, token, prompt):
    image_path = get_latest_image(os.path.join(folder_name, "*.png"))
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    PNG_MIME = "image/png"

    tracer = trace.get_tracer("llm_agent_run")
    with tracer.start_as_current_span(llm_value) as span:
        span.set_attribute("ctx.run_id", "1")
        span.set_attribute("ctx.decision_source", "responses-test")

        # ---------- Gemini ----------
        if llm_value == "gemini-2.5-flash":
            client = genai.Client(api_key=token)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Part.from_bytes(data=image_bytes, mime_type=PNG_MIME), prompt],
            )
            result = resp.text.strip()

        # ---------- GPT-5.2----------
        elif llm_value == "gpt-5.2-2025-12-11":
            client = OpenAI(api_key=token)
            data_url = f"data:{PNG_MIME};base64,{image_b64}"
            resp = client.responses.create(
                model="gpt-5-nano",
                input=[{
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }],
            )
            result = resp.output_text

        # ---------- Claude ----------
        elif llm_value == "claude-sonnet-4-5":
            client = anthropic.Anthropic(api_key=token)
            resp = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": PNG_MIME, "data": image_b64}},
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
            result = "".join([b.text for b in resp.content if b.type == "text"]).strip()

        # ---------- Llama ----------
        elif llm_value == "llama-4-scout":
            client = Groq(api_key=token)
            data_url = f"data:{PNG_MIME};base64,{image_b64}"
            resp = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }],
                max_completion_tokens=1024,
                stream=False
            )
            result = resp.choices[0].message.content.strip()

        else:
            raise ValueError(f"Unsupported llm_value: {llm_value}")

        span.set_attribute("ctx.next_action", result)
        return result


# -----------------------------------------------------------
#                    SCREENSHOT SCREEN
# -----------------------------------------------------------
def grab_screenshot():
    with mss.mss() as sct:
        # List monitors
            monitors = sct.monitors
            monitor = monitors[2]  # choose screen
            screenshot = sct.grab(monitor)
            # Convert to NumPy array
            img = np.array(screenshot)
            # mss gives BGRA → convert to BGR for OpenCV
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img



# -----------------------------------------------------------
#                        MAIN LOOP
# -----------------------------------------------------------

def main():
    global  last_save_time
    LLM_ROTATION = [
        ("gpt-5.2-2025-12-11", os.getenv("OPEN_AI_TOKEN"), os.getenv("OPTIMISED_OPENAI_PROMPT")),
        # ("claude-sonnet-4-5", os.getenv("CLAUDE_API_KEY"), os.getenv("CLAUDE_PROMPT")),
        # ("llama-4-scout", os.getenv("GROQ_API_KEY"), os.getenv("LLAMA_PROMPT")),
    ]

    while True:
            # ---- ALWAYS SAVE BEFORE LLM ----
            if time.time() - last_save_time >= SAVE_INTERVAL:
                ts = time.strftime("%Y%m%d_%H%M%S")
                sharp = grab_screenshot()
                out = os.path.join(CAPTURE_DIR, f"minimap_{ts}.png")
                ok = cv2.imwrite(out, sharp)
                print("💾 Save:", out, "OK?", ok, "Shape:", sharp.shape)
                last_save_time = time.time()

            # ---- RUN SELECTED LLMS ----
            for llm_name, key, prompt in LLM_ROTATION:
                print(f"\n🔍 Testing: {llm_name}")
                direction_text = call_llm(CAPTURE_DIR, llm_name, key, prompt)
                parts = direction_text.split(":", 1)
                direction_raw = parts[0] if parts else ""
                direction = extract_direction(direction_raw) or "UNKNOWN"

                logger.info(f"{llm_name} → {direction_text}")
                print(f"🧭 {llm_name} → {direction}")
                print(direction_text)

                if direction != "UNKNOWN":
                    directions_executor(direction)
            time.sleep(0.1)


if __name__ == "__main__":
    main()
