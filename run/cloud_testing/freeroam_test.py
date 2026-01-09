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
from pynput.keyboard import Controller, Key
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


print("""\

   ██████╗ ██╗   ██╗██████╗ ███████╗██████╗ ██████╗ ██╗   ██╗██████╗ ███████╗
  ██╔════╝ ╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗██╔══██╗██║   ██║██╔══██╗██╔════╝
  ██║       ╚████╔╝ ██████╔╝█████╗  ██████╔╝██████╔╝██║   ██║██████╔╝█████╗  
  ██║        ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗██╔══██╗██║   ██║██╔══██╗██╔══╝  
  ╚██████╗    ██║   ██████╔╝███████╗██║  ██║██║  ██║╚██████╔╝██████╔╝███████╗
   ╚═════╝    ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝

              [ CYBERRUBE :: SYSTEM ONLINE ]
              > Putting on walking boots...
              > Getting selfie smile ready...
              > Awaiting instructions...

""")

SAVE_INTERVAL = 2
last_save_time = 0.0
PHOTO_COOLDOWN = 20 # seconds
last_photo_time = 0.0
last_image_bytes = None
CAPTURE_DIR = os.getenv("CAPTURE_DIRECTORY") or "./captures"
os.makedirs(CAPTURE_DIR, exist_ok=True)
print(f"📁 Saving images to specified .env directory")


# -----------------------------------------------------------
#                     HELPER FUNCTIONS
# -----------------------------------------------------------

def get_latest_image(folder_name):
    files = glob.glob(folder_name)
    return max(files, key=os.path.getctime) if files else None

def extract_direction(text):
    m = re.search(r"\b(MOVE_UP|MOVE_DOWN|MOVE_LEFT|MOVE_RIGHT|CAMERA_UP|CAMERA_DOWN|CAMERA_LEFT|CAMERA_RIGHT|TAKE_PHOTO)\b", text, flags=re.IGNORECASE)
    return m.group(1).upper() if m else None

def extract_length(text):
    return int(text)

from pynput.keyboard import Controller, Key, KeyCode
import time

# Create ONE controller (important)
keyboard = Controller()

def tap_char(ch, n=1, hold=0.06, gap=0.08):
    """
    Tap a character key safely (lowercase, no modifiers).
    """
    kc = KeyCode.from_char(ch.lower())
    for _ in range(n):
        keyboard.press(kc)
        time.sleep(hold)
        keyboard.release(kc)
        time.sleep(gap)

def tap_key(key, hold=0.06, gap=0.08):
    """
    Tap a special key (Key.enter, Key.down, etc).
    """
    keyboard.press(key)
    time.sleep(hold)
    keyboard.release(key)
    time.sleep(gap)


def hold_char(ch, duration):
    """
    Hold a character key down continuously for `duration` seconds.
    """
    kc = KeyCode.from_char(ch.lower())
    keyboard.press(kc)
    time.sleep(duration)
    keyboard.release(kc)

def directions_executor(direction,length):
    direction = direction.strip().upper()

    # Clear stuck modifiers before any action (cheap + important)
    keyboard.release(Key.shift)
    keyboard.release(Key.ctrl)
    keyboard.release(Key.alt)

    if direction == "MOVE_UP":
        hold_char('w', length)

    elif direction == "MOVE_DOWN":
        hold_char('s', length)

    elif direction == "MOVE_LEFT":
        hold_char('a', length)

    elif direction == "MOVE_RIGHT":
        hold_char('d', length)

    elif direction == "CAMERA_UP":
        tap_char('j', length)

    elif direction == "CAMERA_DOWN":
        tap_char('u', length)

    elif direction == "CAMERA_LEFT":
        tap_char('h', length)

    elif direction == "CAMERA_RIGHT":
        tap_char('k', length)

    elif direction == "TAKE_PHOTO":
        tap_key(Key.enter)
        tap_key(Key.down)
        tap_key(Key.down)
        tap_key(Key.down)
        tap_key(Key.space,hold=1, gap=0.4)
        tap_key(Key.space,hold=1, gap=0.4)
        img = grab_screenshot()
        tap_char('c', 1)
        tap_char('j',1)
        ts = time.strftime("%Y%m%d_%H%M%S")
        out = os.path.join(os.getenv("SELFIE_CAPTURES") , f"Watchdogs_{ts}.png")
        cv2.imwrite(out, img)
        last_save_time = time.time()

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

        # ---Deterministic approach to test new triggers ---#
        if llm_value == "fake":
        # prompt is treated as the model output directly
         result = prompt

        # ---------- Gemini ----------
        elif llm_value == "gemini-2.5-flash":
            client = genai.Client(api_key=token)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Part.from_bytes(data=image_bytes, mime_type=PNG_MIME), prompt],
            )
            result = resp.text.strip()

        elif llm_value == "gpt-5.2-2025-12-11":
            global last_image_bytes

            client = OpenAI(api_key=token)

            content = [
                {
                    "type": "input_text",
                    "text": (
                        prompt
                        + "\n\n"
                        + "You are given two images. "
                        + "The first is the PREVIOUS frame. "
                        + "The second is the CURRENT frame. "
                        + "Compare them to determine whether movement occurred."
                    ),
                }
            ]

            # ---- previous image (if available) ----
            if last_image_bytes is not None:
                prev_b64 = base64.b64encode(last_image_bytes).decode("utf-8")
                content.append({
                    "type": "input_image",
                    "image_url": f"data:{PNG_MIME};base64,{prev_b64}",
                })

            # ---- current image ----
            content.append({
                "type": "input_image",
                "image_url": f"data:{PNG_MIME};base64,{image_b64}",
            })

            resp = client.responses.create(
                model="gpt-5.2-2025-12-11",
                input=[{
                    "role": "user",
                    "content": content,
                }],
            )

            result = resp.output_text

            # ---- update memory ----
            last_image_bytes = image_bytes

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
    global  last_save_time, last_photo_time
    list_of_actions = list()

    LLM_ROTATION = [
        #("fake", 'xummy', 'TAKE_PHOTO:0:Looks nice')
        ("gpt-5.2-2025-12-11", os.getenv("OPEN_AI_TOKEN"), os.getenv("OPEN_AI_FREE_ROAM_PROMPT")),
        # ("claude-sonnet-4-5", os.getenv("CLAUDE_API_KEY"), os.getenv("CLAUDE_PROMPT")),
        # ("llama-4-scout", os.getenv("GROQ_API_KEY"), os.getenv("LLAMA_PROMPT")),
    ]

    while True:
            # ---- ALWAYS SAVE BEFORE LLM ----
            if time.time() - last_save_time >= SAVE_INTERVAL:
                sharp = grab_screenshot()
                ts = time.strftime("%Y%m%d_%H%M%S")
                out = os.path.join(CAPTURE_DIR, f"minimap_{ts}.png")
                cv2.imwrite(out, sharp)
                last_save_time = time.time()

            # ---- RUN SELECTED LLMS ----
            for llm_name, key, prompt in LLM_ROTATION:
                now = time.time()
                print(f"\n🔍 Roaming with: {llm_name}")
                prompt = (
                        prompt +  f" \n \n ### LATEST_INPUTS: Here are your most recent 5 actions, use these to evaluate if you're getting stuck: {list_of_actions[-5:]}"         
                   )
                direction_text = call_llm(CAPTURE_DIR, llm_name, key, prompt)
                parts = direction_text.split(":", 2)
                print(parts)
                direction_raw = parts[0] if len(parts) > 0 else ""
                length_raw    = parts[1] if len(parts) > 1 else ""
                reasoning     = parts[2] if len(parts) > 2 else ""
                direction = extract_direction(direction_raw) or "UNKNOWN"
                list_of_actions.append(direction_text)
                length = extract_length(length_raw)
                logger.info(f"{llm_name} → {direction_text}")
                print(f"🧭 {llm_name} → {direction}")
                print(reasoning)

                '''
                if direction != "UNKNOWN":
                    directions_executor(direction)
                '''

                if direction == "TAKE_PHOTO" and now - last_photo_time < PHOTO_COOLDOWN:
                    print("📸 Photo on cooldown — ignoring TAKE_PHOTO")
                    continue

                if direction != "UNKNOWN":
                    directions_executor(direction,length)

                    if direction == "TAKE_PHOTO":
                        last_photo_time = now
                        logger.info("📸 TAKE_PHOTO executed")
                        print("📸 TAKE_PHOTO executed")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Exiting program (Ctrl+C)")
