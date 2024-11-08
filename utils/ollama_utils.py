import requests
import json
import base64
from datetime import datetime
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QImage
from utils.screenshot_utils import process_image
from utils.settings_manager import get_ollama_url, get_system_prompt


class OllamaThread(QThread):
    response_chunk_ready = pyqtSignal(str)
    response_complete = pyqtSignal()
    request_screenshot = pyqtSignal()
    debug_screenshot_ready = pyqtSignal(QImage)

    def __init__(
        self, messages, screenshots, model, temperature=None, context_size=None
    ):
        super().__init__()
        self.messages = messages
        self.screenshots = screenshots if screenshots else []  # List of screenshots
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

            if self.screenshots:  # Check if we have any screenshots
                # Process all screenshots
                processed_images = []
                for screenshot in self.screenshots:
                    processed_image = self.process_image(screenshot)
                    self.debug_screenshot_ready.emit(processed_image)

                    # Save image to bytes using PNG format
                    buffer = QByteArray()
                    buffer_io = QBuffer(buffer)
                    buffer_io.open(QIODevice.OpenModeFlag.WriteOnly)
                    success = processed_image.save(buffer_io, "PNG")
                    buffer_io.close()  # Make sure to close the buffer
                    
                    if not success:
                        raise Exception("Failed to save image to buffer")
                    
                    img_bytes = buffer.data()
                    img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                    processed_images.append(img_base64)

                if len(self.messages) > 1:
                    # Get the last user message
                    last_message = self.messages[-1]
                    
                    # Add image placeholders to the content
                    original_content = last_message["content"].strip()
                    last_message["content"] = f"{original_content}".strip()
                    
                    # Add the base64 images
                    last_message["images"] = processed_images
                    
                    print(f"Sending message with {len(processed_images)} images")  # Debug print
                    print(f"Message content: {last_message['content']}")  # Debug print
                else:
                    print("Warning: No user message to attach images to")

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

            # Debug print the request
            print("Request to Ollama:")
            print(f"URL: {ollama_url}/api/chat")
            print("Messages structure:", json.dumps(request_params["messages"], indent=2))

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
        """Process image to ensure it meets Ollama's requirements."""
        if isinstance(image, QImage):
            # Convert QImage to the right format if needed
            if image.format() != QImage.Format.Format_RGB32:
                image = image.convertToFormat(QImage.Format.Format_RGB32)
            
            # Scale image if needed while maintaining aspect ratio
            current_size = max(image.width(), image.height())
            if current_size > self.MAX_IMAGE_SIZE:
                image = image.scaled(
                    self.MAX_IMAGE_SIZE,
                    self.MAX_IMAGE_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            elif current_size < self.MIN_IMAGE_SIZE:
                image = image.scaled(
                    self.MIN_IMAGE_SIZE,
                    self.MIN_IMAGE_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            
            print(f"Processed image size: {image.width()}x{image.height()}")  # Debug print
            return image
        else:
            raise ValueError("Input must be a QImage")


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


# Add this new function
def reload_model_list():
    return load_ollama_models()
