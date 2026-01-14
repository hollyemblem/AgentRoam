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
from opentelemetry import trace
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor

import patch_pydantic  # noqa: F401

from langfuse.openai import openai
from google import genai
from google.genai import types
import anthropic  # Claude
from groq import Groq  # Llama via Groq

from pynput.keyboard import Controller, Key, KeyCode

load_dotenv(dotenv_path=Path.cwd().parent / ".env")


class FreeRoamAgent:
    def __init__(self):
        # --------------------------------------
        # CONFIG
        # --------------------------------------
        self.logger = logging.getLogger(__name__)
        logging.basicConfig(
            filename=os.getenv("LOGGER_NAME"),
            encoding="utf-8",
            level=logging.DEBUG,
            format="%(levelname)s:%(message)s",
        )

        # Agent timing / capture config
        self.SAVE_INTERVAL = 1
        self.PHOTO_COOLDOWN = 20

        # Directories
        self.CAPTURE_DIR = os.getenv("CAPTURE_DIRECTORY") or "./captures"
        os.makedirs(self.CAPTURE_DIR, exist_ok=True)

        # Running state
        self.last_save_time = 0.0
        self.last_photo_time = 0.0
        self.last_image_bytes = None
        self.list_of_actions = []
        self.current_move_key = None
        self.smooth_roam = False

        # Keyboard controller
        self.keyboard = Controller()

    print("""\

 █████╗  ██████╗  ███████╗ ███╗   ██╗ ████████╗ ██████╗  ██████╗  █████╗  ███╗   ███╗
██╔══██╗ ██╔════╝ ██╔════╝ ████╗  ██║ ╚══██╔══╝ ██╔══██╗ ██╔═══██╗ ██╔══██╗ ████╗ ████║
███████║ ██║  ███╗█████╗   ██╔██╗ ██║    ██║    ██████╔╝ ██║   ██║ ███████║ ██╔████╔██║
██╔══██║ ██║   ██║██╔══╝   ██║╚██╗██║    ██║    ██╔══██╗ ██║   ██║ ██╔══██║ ██║╚██╔╝██║
██║  ██║ ╚██████╔╝███████╗ ██║ ╚████║    ██║    ██║  ██║ ╚██████╔╝ ██║  ██║ ██║ ╚═╝ ██║
╚═╝  ╚═╝  ╚═════╝ ╚══════╝ ╚═╝  ╚═══╝    ╚═╝    ╚═╝  ╚═╝  ╚═════╝  ╚═╝  ╚═╝ ╚═╝     ╚═╝


            :: AGENTROAM ONLINE ::
     [ Autonomous navigation engaged ]
     [ Selfie smile activated     ]
     [ Awaiting vector instructions  ]

    """)
    # -------------------------
    # HELPERS
    # -------------------------

    def get_latest_image(self, folder_name):
        files = glob.glob(folder_name)
        return max(files, key=os.path.getctime) if files else None

    def extract_direction(self, text):
        m = re.search(
            r"\b(MOVE_UP|MOVE_DOWN|MOVE_LEFT|MOVE_RIGHT|CAMERA_UP|CAMERA_DOWN|CAMERA_LEFT|CAMERA_RIGHT|TAKE_PHOTO)\b",
            text,
            flags=re.IGNORECASE,
        )
        return m.group(1).upper() if m else None

    def extract_length(self, text, default=1.0):
        try:
            return float(text)
        except (ValueError, TypeError):
            return default

    def tap_char(self, ch, n=1, hold=0.06, gap=0.08):
        kc = KeyCode.from_char(ch.lower())
        for _ in range(n):
            self.keyboard.press(kc)
            time.sleep(hold)
            self.keyboard.release(kc)
            time.sleep(gap)

    def tap_key(self, key, hold=0.06, gap=0.08):
        self.keyboard.press(key)
        time.sleep(hold)
        self.keyboard.release(key)
        time.sleep(gap)

    def hold_char(self, ch, duration):
        kc = KeyCode.from_char(ch.lower())
        self.keyboard.press(kc)
        time.sleep(duration)
        self.keyboard.release(kc)

    def press_move_key(self, ch):
        kc = KeyCode.from_char(ch.lower())
        self.keyboard.press(kc)

    def release_move_keys(self):
        for ch in ("w", "a", "s", "d"):
            try:
                self.keyboard.release(KeyCode.from_char(ch))
            except Exception:
                pass
        self.current_move_key = None

    def directions_executor(self, direction, length=0, smooth_roam=False):
        d = direction.strip().upper()
        self.keyboard.release(Key.shift)
        self.keyboard.release(Key.ctrl)
        self.keyboard.release(Key.alt)

        if d == "MOVE_UP":
            if smooth_roam:
                self.press_move_key("w")
                self.current_move_key = "w"
            else:
                self.hold_char("w", length)
        elif d == "MOVE_DOWN":
            if smooth_roam:
                self.press_move_key("s")
                self.current_move_key = "s"
            else:
                self.hold_char("s", length)
        elif d == "MOVE_LEFT":
            if smooth_roam:
                self.press_move_key("a")
                self.current_move_key = "a"
            else:
                self.hold_char("a", length)
        elif d == "MOVE_RIGHT":
            if smooth_roam:
                self.press_move_key("d")
                self.current_move_key = "d"
            else:
                self.hold_char("d", length)
        elif d == "CAMERA_UP":
            self.tap_char("j", int(length))
        elif d == "CAMERA_DOWN":
            self.tap_char("u", int(length))
        elif d == "CAMERA_LEFT":
            self.tap_char("h", int(length))
        elif d == "CAMERA_RIGHT":
            self.tap_char("k", int(length))
        elif d == "TAKE_PHOTO":
            self.take_photo()

    def take_photo(self):
        self.tap_key(Key.enter)
        self.tap_key(Key.down)
        self.tap_key(Key.down)
        self.tap_key(Key.down)
        self.tap_key(Key.space,hold=1, gap=0.4)
        self.tap_key(Key.space,hold=1, gap=0.4)
        img = self.grab_screenshot()
        self.tap_char('c', 1)
        self.tap_char('j',1)
        ts = time.strftime("%Y%m%d_%H%M%S")
        out = os.path.join(os.getenv("SELFIE_CAPTURES") , f"freeroam_agent{ts}.png")
        cv2.imwrite(out, img)
        self.last_save_time = time.time()

    # -------------------------
    # LLM / Prompt
    # -------------------------

    def build_agent_prompt(self, base_prompt):
        return (
            base_prompt
            + "\n\n"
            + "### LATEST_INPUTS\n"
            + f"Your most recent 5 actions were: {self.list_of_actions[-5:]}\n"
            + "Use these to determine whether you are stuck or progressing."
        )
    
    def write_reasoning_to_file(self,direction_text: str,filepath: str = "../obs_exports/obs_reasoning.txt"):
        with open(filepath, "w", encoding="utf-8") as f: 
            f.write(direction_text)

    def call_llm(self,folder_name, llm_value, token, prompt):
        image_path = self.get_latest_image(os.path.join(folder_name, "*.png"))
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

            elif "gpt" in llm_value.lower():
                client = openai.OpenAI(api_key=token)
                content = [
                    {
                        "type": "input_text",
                        "text": (
                            prompt
                            + "\n\n ### IMAGE COMPARISON OF RECENT MOVEMENT"
                            + "You are given two images. "
                            + "The first is the PREVIOUS frame. "
                            + "The second is the CURRENT frame. "
                            + "Compare them to determine whether movement occurred."
                        ),
                    }
                ]

                # ---- previous image (if available) ----
                if self.last_image_bytes is not None:
                    prev_b64 = base64.b64encode(self.last_image_bytes).decode("utf-8")
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
                self.last_image_bytes = image_bytes

            # ---------- Claude ----------
            elif llm_value == "claude-sonnet-4-5":
                AnthropicInstrumentor().instrument()
                client = anthropic.Anthropic(api_key=token)

                content = [
                    {
                        "type": "text",
                        "text": (
                            prompt
                            + "\n\n ### IMAGE COMPARISON OF RECENT MOVEMENT"
                            + "You are given two images.\n"
                            + "The first image is the PREVIOUS frame.\n"
                            + "The second image is the CURRENT frame.\n"
                            + "Compare them and determine whether movement occurred."
                        ),
                    }
                ]

                # ---- previous image (if available) ----
                if self.last_image_bytes is not None:
                    prev_b64 = base64.b64encode(self.last_image_bytes).decode("utf-8")
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": PNG_MIME,
                            "data": prev_b64,
                        },
                    })

                # ---- current image ----
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": PNG_MIME,
                        "data": image_b64,
                    },
                })

                resp = client.messages.create(
                    model="claude-sonnet-4-5",
                    max_tokens=1024,
                    messages=[{
                        "role": "user",
                        "content": content,
                    }],
                )

                result = "".join(
                    block.text for block in resp.content if block.type == "text"
                ).strip()

                # ---- update memory ----
                self.last_image_bytes = image_bytes


            # ---------- Llama ----------
            elif llm_value == "llama-4-maverick-17b-128e-instruct":
                client = Groq(api_key=token)

                content = [
                    {
                        "type": "text",
                        "text": (
                            prompt
                            + "\n\n### IMAGE COMPARISON OF RECENT MOVEMENT\n"
                            + "You are given two images.\n"
                            + "The first image is the PREVIOUS frame.\n"
                            + "The second image is the CURRENT frame.\n"
                            + "Compare them to determine whether movement occurred."
                        ),
                    }
                ]

                # ---- previous image (if available) ----
                if self.last_image_bytes is not None:
                    prev_b64 = base64.b64encode(self.last_image_bytes).decode("utf-8")
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{PNG_MIME};base64,{prev_b64}"
                        },
                    })

                # ---- current image ----
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{PNG_MIME};base64,{image_b64}"
                    },
                })

                resp = client.chat.completions.create(
                    model="meta-llama/llama-4-maverick-17b-128e-instruct",
                    messages=[{
                        "role": "user",
                        "content": content,
                    }],
                    max_completion_tokens=1024,
                    stream=False,
                )

                result = resp.choices[0].message.content.strip()

                # ---- update memory ----
                self.last_image_bytes = image_bytes

            else:
                raise ValueError(f"Unsupported llm_value: {llm_value}")
            return result



    # -------------------------
    # SCREENSHOT
    # -------------------------

    def grab_screenshot(self):
        with mss.mss() as sct:
            monitor = sct.monitors[2]
            screenshot = sct.grab(monitor)

        img = np.array(screenshot)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    # -------------------------
    # RUN LOOP
    # -------------------------
    def run(self):
        LLM_ROTATION = [
        #("fake", 'xummy', 'TAKE_PHOTO:0:Looks nice')
        #("gpt-5.2-2025-12-11", os.getenv("OPEN_AI_TOKEN"), os.getenv("WD_FREEROAM_PROMPT")) #,
        #("claude-sonnet-4-5", os.getenv("CLAUDE_API_KEY"), os.getenv("WD_FREEROAM_PROMPT")) #,
        #("llama-4-maverick-17b-128e-instruct", os.getenv("GROQ_API_KEY"), os.getenv("WD_LLAMA_FREEROAM_PROMPT")) #
        ("gpt-5-mini-2025-08-07", os.getenv("OPEN_AI_TOKEN"), os.getenv("WD_FREEROAM_PROMPT")) 
        ]


        while True:
            if time.time() - self.last_save_time >= self.SAVE_INTERVAL:
                sharp = self.grab_screenshot()
                ts = time.strftime("%Y%m%d_%H%M%S")
                out = os.path.join(self.CAPTURE_DIR, f"minimap_{ts}.png")
                cv2.imwrite(out, sharp)
                self.last_save_time = time.time()

            for llm_name, key, prompt in LLM_ROTATION:
                print(f"\n Roaming with: {llm_name}")
                prompt = self.build_agent_prompt(prompt)
                direction_text = self.call_llm(self.CAPTURE_DIR, llm_name, key, prompt)
                print(direction_text)
                parts = direction_text.split(":", 2)
                direction = self.extract_direction(parts[0]) or "UNKNOWN"
                length = self.extract_length(parts[1] if len(parts) > 1 else "")
                reasoning     = parts[2] if len(parts) > 2 else ""
                self.list_of_actions.append(direction_text)

                print(f"🧭 {llm_name} → {direction}")
                reasoning_outputs = (f"Latest Output: {direction} : {reasoning} ")
                print(reasoning)

                self.write_reasoning_to_file(direction_text=reasoning_outputs)

                if self.smooth_roam and self.current_move_key:
                    self.release_move_keys()

                now = time.time()
                if direction == "TAKE_PHOTO" and now - self.last_photo_time < self.PHOTO_COOLDOWN:
                    print("📸 Photo on cooldown — ignoring TAKE_PHOTO")
                    continue

                if direction != "UNKNOWN":
                    if self.smooth_roam and direction in {"MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"}:
                        length = length / 2.0
                    self.directions_executor(direction, length, smooth_roam=self.smooth_roam)
                    if direction == "TAKE_PHOTO":
                        self.last_photo_time = now
                        print("📸 TAKE_PHOTO executed")


if __name__ == "__main__":
    time.sleep(15) ##allow for warmup and setup
    try:
        agent = FreeRoamAgent()
        agent.run()
    except KeyboardInterrupt:
        print("\n🛑 Exiting program (Ctrl+C)")
