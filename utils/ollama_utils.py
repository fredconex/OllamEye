import requests
import json
import base64
from datetime import datetime
from PyQt6.QtCore import QThread, pyqtSignal, QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QImage
from utils.screenshot_utils import process_image


class OllamaThread(QThread):
    response_chunk_ready = pyqtSignal(str)
    response_complete = pyqtSignal()
    request_screenshot = pyqtSignal()
    debug_screenshot_ready = pyqtSignal(QImage)

    def __init__(
        self, messages, screenshot, model, temperature=None, context_size=None
    ):
        super().__init__()
        self.messages = messages
        self.screenshot = screenshot
        self.screenshot_ready = True
        self.MIN_IMAGE_SIZE = 256
        self.MAX_IMAGE_SIZE = 1280
        self.model = model
        self.temperature = temperature
        self.context_size = context_size

    def run(self):
        try:
            if not self.messages or self.messages[0].get("role") != "system":
                # Insert default system prompt if none exists
                self.messages.insert(
                    0, {"role": "system", "content": get_system_prompt()}
                )

            if self.screenshot is not None:  # Changed condition
                processed_image = self.process_image(
                    self.screenshot
                )  # Directly use the image
                self.debug_screenshot_ready.emit(processed_image)

                buffer = QByteArray()
                buffer_io = QBuffer(buffer)
                buffer_io.open(QIODevice.OpenModeFlag.WriteOnly)
                success = processed_image.save(buffer_io, "PNG")
                if not success:
                    raise Exception("Failed to save image to buffer")
                img_bytes = buffer.data()

                # Convert bytes to base64 string
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")

                if len(self.messages) > 1:
                    self.messages[-1]["images"] = [img_base64]  # Send as base64 string
                else:
                    print("Warning: No user message to attach image to")

            # Build request parameters
            request_params = {
                "model": self.model,
                "messages": self.messages,
                "stream": True,
                "options": {},
            }

            if self.temperature is not None:
                request_params["options"]["temperature"] = self.temperature
            if self.context_size is not None:
                request_params["options"]["context_size"] = self.context_size

            ollama_url = get_ollama_url()

            # Make streaming request to Ollama API
            response = requests.post(
                f"{ollama_url}/api/chat", json=request_params, stream=True
            )
            response.raise_for_status()

            full_response = ""
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if "message" in chunk and "content" in chunk["message"]:
                        content = chunk["message"]["content"]
                        full_response += content
                        self.response_chunk_ready.emit(content)

            if not full_response:
                self.response_chunk_ready.emit("No response received from Ollama.")

            self.response_complete.emit()
        except Exception as e:
            self.response_chunk_ready.emit(f"Error: {str(e)}")
            self.response_complete.emit()

    def process_image(self, image):
        return process_image(image, self.MIN_IMAGE_SIZE, self.MAX_IMAGE_SIZE)


def load_ollama_models():
    try:
        start_time = datetime.now()
        ollama_url = get_ollama_url()
        # Set a timeout to avoid hanging
        response = requests.get(
            f"{ollama_url}/api/tags",
            timeout=0.1,  # 100ms timeout
            headers={
                "Connection": "close",  # Prevent keep-alive connections
                "Accept": "application/json",  # Explicitly request JSON
            },
        )
        response.raise_for_status()
        # Use list comprehension instead of json parsing then list comprehension
        models = [model["name"] for model in response.json()["models"]]
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"Loading models took {elapsed:.2f} seconds")
        return models
    except requests.Timeout:
        print("Timeout loading models")
        return ["Timeout loading models"]
    except Exception as e:
        print(f"Error loading models: {e}")
        return ["Error loading models"]


def get_default_model():
    try:
        with open("config.json", "r") as f:
            settings = json.load(f)
        return settings.get("default_model", "minicpm-v:8b")
    except FileNotFoundError:
        return "minicpm-v:8b"


def get_ollama_url():
    try:
        with open("config.json", "r") as f:
            settings = json.load(f)
        return settings.get("ollama_url", "http://localhost:11434")
    except FileNotFoundError:
        return "http://localhost:11434"


def save_model_setting(model):
    try:
        with open("config.json", "r") as f:
            settings = json.load(f)
    except FileNotFoundError:
        settings = {}

    settings["default_model"] = model
    with open("config.json", "w") as f:
        json.dump(settings, f)


def get_system_prompt():
    try:
        with open("config.json", "r") as f:
            settings = json.load(f)
        return settings.get(
            "system_prompt",
            "You are a helpful AI assistant, answer in same language of question.",
        )
    except FileNotFoundError:
        return "You are a helpful AI assistant, answer in same language of question."


# Add this new function
def reload_model_list():
    return load_ollama_models()
