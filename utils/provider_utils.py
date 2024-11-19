from typing import Tuple
import requests
import json
from datetime import datetime
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QImage
from utils.settings_manager import get_ollama_url, get_system_prompt, get_openai_key, get_openai_url, get_provider


class ProviderRequest(QThread):
    response_chunk_ready = pyqtSignal(str, str)
    response_complete = pyqtSignal(str)
    request_screenshot = pyqtSignal()
    debug_screenshot_ready = pyqtSignal(QImage)

    def __init__(self, messages, screenshots, model, temperature=None, context_size=None, message_id=None):
        super().__init__()
        self.messages = messages
        self.screenshots = screenshots if screenshots else []
        self.model = model
        self.temperature = temperature
        self.context_size = context_size
        self.provider = get_provider()
        self.message_id = message_id
        
        # Add system prompt to messages
        system_prompt = get_system_prompt()
        if system_prompt and (not messages or messages[0]["role"] != "system"):
            self.messages = [{"role": "system", "content": system_prompt}] + self.messages

        # Provider-specific settings
        self.MIN_IMAGE_SIZE = 256
        self.MAX_IMAGE_SIZE = 1280
        self.api_key = get_openai_key() if self.provider == "openai" else None
        self.api_url = get_openai_url() if self.provider == "openai" else get_ollama_url()

    def run(self):
        try:
            if self.provider == "ollama":
                self._run_ollama_request()
            elif self.provider == "openai":
                self._run_openai_request()
            else:
                raise ValueError(f"Unsupported provider: {self.provider}")
        except Exception as e:
            self.response_chunk_ready.emit(f"Error: {str(e)}", self.message_id)
            self.response_complete.emit(self.message_id)

    def _run_ollama_request(self):
        try:
            # Format messages for Ollama's specific requirements
            formatted_messages = []
            for msg in self.messages:
                content = msg["content"]
                if isinstance(content, list):
                    # Extract text content and handle images
                    text_parts = []
                    images = []
                    
                    for item in content:
                        if item["type"] == "text":
                            text_parts.append(item["text"])
                        elif item["type"] == "image":
                            # For Ollama, we need the base64 image data
                            if "image_url" in item and "url" in item["image_url"]:
                                # Extract base64 data from data URL
                                url = item["image_url"]["url"]
                                if url.startswith("data:image/"):
                                    # Extract base64 part after the comma
                                    base64_data = url.split(",", 1)[1]
                                    images.append(base64_data)

                    # Create formatted message
                    formatted_msg = {
                        "role": msg["role"],
                        "content": " ".join(text_parts)
                    }
                    
                    # Add images if present
                    if images:
                        formatted_msg["images"] = images
                    
                    formatted_messages.append(formatted_msg)
                else:
                    # Handle string content (like system messages)
                    formatted_messages.append({
                        "role": msg["role"],
                        "content": content
                    })

            # Build request parameters
            request_params = {
                "model": self.model,
                "messages": formatted_messages,
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
                f"{ollama_url}/api/chat", 
                json=request_params, 
                stream=True
            )
            response.raise_for_status()

            full_response = ""
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if "message" in chunk and "content" in chunk["message"]:
                        content = chunk["message"]["content"]
                        full_response += content
                        self.response_chunk_ready.emit(content, self.message_id)

            if not full_response:
                self.response_chunk_ready.emit("No response received from Ollama.", self.message_id)

            self.response_complete.emit(self.message_id)

        except Exception as e:
            self.response_chunk_ready.emit(f"Error: {str(e)}", self.message_id)
            self.response_complete.emit(self.message_id)

    def _run_openai_request(self):
        try:
            if not self.api_key:
                self.response_chunk_ready.emit("Error: OpenAI API key not configured", self.message_id)
                self.response_complete.emit(self.message_id)
                return

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream"
            }

            # Format messages for OpenAI's specific requirements
            formatted_messages = []
            for msg in self.messages:
                content = msg["content"]
                if isinstance(content, list):
                    # Convert our format to OpenAI's format
                    openai_content = []
                    for item in content:
                        if item["type"] == "text":
                            openai_content.append({
                                "type": "text",
                                "text": item["text"]
                            })
                        elif item["type"] == "image":
                            openai_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": item["image_url"]["url"]
                                }
                            })
                    formatted_messages.append({
                        "role": msg["role"],
                        "content": openai_content
                    })
                else:
                    # Handle string content (like system messages)
                    formatted_messages.append({
                        "role": msg["role"],
                        "content": content
                    })

            data = {
                "model": self.model,
                "messages": formatted_messages,
                "stream": True
            }

            if self.temperature is not None:
                data["temperature"] = self.temperature

            # Debug print the request
            print("OpenAI Request:")
            print(f"URL: {self.api_url}/chat/completions")
            print("Messages structure:", json.dumps(data["messages"], indent=2))

            response = requests.post(
                f"{self.api_url}/chat/completions",
                headers=headers,
                json=data,
                stream=True
            )

            if response.status_code != 200:
                error_msg = response.json().get("error", {}).get("message", "Unknown error")
                self.response_chunk_ready.emit(f"Error: {error_msg}", self.message_id)
                self.response_complete.emit(self.message_id)
                return

            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith("data: "):
                        if line == "data: [DONE]":
                            break
                        
                        try:
                            json_data = json.loads(line[6:])  # Skip "data: " prefix
                            content = json_data["choices"][0]["delta"].get("content", "")
                            if content:
                                self.response_chunk_ready.emit(content, self.message_id)
                        except json.JSONDecodeError:
                            continue

            self.response_complete.emit(self.message_id)

        except Exception as e:
            self.response_chunk_ready.emit(f"Error: {str(e)}", self.message_id)
            self.response_complete.emit(self.message_id)

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


# Add a new class for provider signals
class ProviderSignals(QObject):
    provider_changed = pyqtSignal()

# Create a global instance
provider_signals = ProviderSignals()


def check_provider_status() -> Tuple[bool, str]:
    """
    Check if the selected provider (Ollama or OpenAI) is online.
    
    Returns:
        Tuple of (is_online: bool, provider: str)
    """
    provider = get_provider()
    is_online = False

    try:
        if provider == "ollama":
            # Check Ollama status
            ollama_url = get_ollama_url()
            if ollama_url:
                try:
                    response = requests.get(f"{ollama_url}/api/tags", timeout=0.1)
                    is_online = (response.status_code == 200)
                except (requests.ConnectionError, requests.Timeout):
                    is_online = False
        elif provider == "openai":
            # Check OpenAI status by making a test API call
            openai_api_key = get_openai_key()
            openai_url = get_openai_url()
            if openai_api_key and openai_url:
                try:
                    response = requests.get(
                        f"{openai_url}/models",
                        headers={
                            "Authorization": f"Bearer {openai_api_key}",
                            "Content-Type": "application/json"
                        },
                        timeout=0.1
                    )
                    is_online = (response.status_code == 200)
                except (requests.ConnectionError, requests.Timeout):
                    is_online = False
        
        return is_online, provider

    except Exception as e:
        print(f"Error checking provider status: {e}")  # Add logging
        return False, provider

def request_models(provider=None):
    """Get available models based on the current provider from settings"""
    if provider is None:
        provider = get_provider()
    
    # Add debug print
    print(f"Requesting models for provider: {provider}")
    
    if provider == "ollama":
        try:
            start_time = datetime.now()
            ollama_url = get_ollama_url()
            
            if not ollama_url:
                return ["Please configure Ollama URL"]
                
            response = requests.get(
                f"{ollama_url}/api/tags",
                timeout=1.0,
                headers={
                    "Connection": "close",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            
            if not response.json().get("models"):
                return ["No models found"]
                
            models = [model["name"] for model in response.json()["models"]]
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"Loading models took {elapsed:.2f} seconds")
            return models if models else ["No models found"]
            
        except requests.Timeout:
            print("Timeout loading models")
            return ["Timeout loading models"]
        except requests.ConnectionError:
            print("Connection error loading models")
            return ["Cannot connect to Ollama"]
        except Exception as e:
            print(f"Error loading models: {e}")
            return ["Error loading models"]
            
    elif provider == "openai":
        try:
            api_key = get_openai_key()
            api_url = get_openai_url()
            
            if not api_key:
                return ["Please configure OpenAI API key"]
            if not api_url:
                return ["Please configure OpenAI URL"]

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                f"{api_url}/models",
                headers=headers,
                timeout=1.0
            )

            response.raise_for_status()
            
            # Remove duplicate models assignment and status check
            models = response.json().get("data", [])      
            chat_models = [model["id"] for model in models]

            print(models)  # Debug print
            return sorted(chat_models) if chat_models else ["No compatible models found"]
                
        except requests.ConnectionError:
            return ["Cannot connect to OpenAI API"]
        except Exception as e:
            print(f"Error loading OpenAI models: {e}")
            return ["Error loading OpenAI models"]
    else:
        return [f"Invalid provider: {provider}"]
