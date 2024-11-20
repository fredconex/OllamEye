from typing import Tuple
import requests
import json
import sys
from datetime import datetime
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage
from utils.settings_manager import get_ollama_url, get_system_prompt, get_openai_key, get_openai_url, get_provider

DEBUG = "-debug" in sys.argv

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
            if DEBUG:
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

        except requests.ConnectionError:
            self.response_chunk_ready.emit("Error: Cannot connect to Ollama. Please check if Ollama is running.", self.message_id)
            self.response_complete.emit(self.message_id)
        except Exception as e:
            # Simplify generic error messages
            error_msg = str(e)
            if "ConnectionPool" in error_msg or "NewConnectionError" in error_msg:
                error_msg = "Cannot connect to Ollama. Please check if it's running."
            self.response_chunk_ready.emit(f"Error: {error_msg}", self.message_id)
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
            if DEBUG:
                print("OpenAI Request:")
                print(f"URL: {self.api_url}/chat/completions")
                print("Messages structure:", json.dumps(data["messages"], indent=2))

            response = requests.post(
                f"{self.api_url}/chat/completions",
                headers=headers,
                json=data,
                stream=True
            )

            response.raise_for_status()

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

        except requests.ConnectionError:
            self.response_chunk_ready.emit("Error: Cannot connect to OpenAI API. Please check your connection and API endpoint.", self.message_id)
            self.response_complete.emit(self.message_id)
        except Exception as e:
            # Simplify generic error messages
            error_msg = str(e)
            if "ConnectionPool" in error_msg or "NewConnectionError" in error_msg:
                error_msg = "Cannot connect to API endpoint. Please check your connection and settings."
            self.response_chunk_ready.emit(f"Error: {error_msg}", self.message_id)
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

def check_provider_status() -> Tuple[bool, str]:
    """Check if the selected provider (Ollama or OpenAI) is online."""
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
                        timeout=0.5
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
    
    if DEBUG:
        print(f"Requesting models for provider: {provider}")
    
    try:
        start_time = datetime.now()
        
        # Common configuration
        request_config = {
            "timeout": 0.5,
            "headers": {"Accept": "application/json"}
        }
        
        if provider == "ollama":
            base_url = get_ollama_url()
            if not base_url:
                return ["Please configure Ollama URL"]
            
            request_config["url"] = f"{base_url}/api/tags"
            request_config["headers"]["Connection"] = "close"
            
        elif provider == "openai":
            api_key = get_openai_key()
            base_url = get_openai_url()
            
            if not api_key:
                return ["Please configure OpenAI API key"]
            if not base_url:
                return ["Please configure OpenAI URL"]
                
            request_config["url"] = f"{base_url}/models"
            request_config["headers"].update({
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            })
            
        else:
            return [f"Invalid provider: {provider}"]
        
        # Make the request
        response = requests.get(**request_config)
        response.raise_for_status()
        
        # Parse response based on provider
        if provider == "ollama":
            models = [model["name"] for model in response.json().get("models", [])]
        else:  # openai
            models = [model["id"] for model in response.json().get("data", [])]
            models = sorted(models)
        
        if DEBUG:
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"Loading models took {elapsed:.2f} seconds")
            if provider == "openai":
                print(response.json().get("data", []))
        
        return models if models else [f"No {'compatible ' if provider == 'openai' else ''}models found"]
            
    except requests.Timeout:
        if DEBUG:
            print("Timeout loading models")
        return ["Error loading models"]
    except requests.ConnectionError:
        if DEBUG:
            print(f"Cannot connect to {provider.title()} API")
        return [f"Cannot connect to {provider.title()} API"]
    except Exception as e:
        if DEBUG:
            print(f"Error loading {provider} models: {e}")
        return [f"Error loading {provider.title()} models"]