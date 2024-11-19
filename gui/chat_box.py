import uuid
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal, QTimer, QByteArray, QBuffer, QIODevice, QThread
from PyQt6.QtGui import QImage, QIcon
import os
import json
import base64
from datetime import datetime
from gui.settings import get_base_model_name, load_svg_button_icon
from utils.provider_utils import check_provider_status
from utils.settings_manager import get_default_model
from utils.chat_storage import ChatStorage
from collections import OrderedDict
from utils.provider_utils import ProviderRequest
import re

DEBUG = "-debug" in __import__('sys').argv

class Message:
    def __init__(self, role, content=None, model=None, message_id=None):
        self.role = role
        self.content = content or []
        self.model = model
        self.id = message_id or str(uuid.uuid4())
        self.parent_chat = None  # Reference to parent chat box
        self.timestamp = datetime.now()
        self.child_message = None  # Reference to the assistant's response message
        self.is_editing = False
        self.original_content = None  # Store original content during edits

    def submit(self):
        """Submit this message and generate a response."""
        if not self.parent_chat:
            print("Warning: Message not associated with a ChatBox")
            return

        if DEBUG:
            print("\n=== Submitting message ===")
            print(f"Message ID: {self.id}")

        # Store original IDs before regenerating
        original_id = self.id
        original_child_id = self.child_message.id if self.child_message else None

        # Remove all messages after this one
        if self.role == "user":
            self.parent_chat.remove_subsequent_messages(original_id)
            
        # Ensure we keep the same ID when regenerating
        self.id = original_id
        self.parent_chat.messages[original_id] = self

        # Create or update child message for assistant response
        if not self.child_message and self.role == "user":
            self.child_message = Message("assistant", model=self.parent_chat.active_model)
            self.child_message.parent_chat = self.parent_chat
        elif original_child_id:  # Preserve child message ID if it exists
            self.child_message.id = original_child_id
            
        self.parent_chat.messages[self.child_message.id] = self.child_message

        # Get messages up to this point
        messages_to_send = self.parent_chat.get_messages_for_request(self.id)
        
        # Start the provider request
        self.parent_chat.start_provider_request(
            messages_to_send,
            self.get_images(),
            message_id=self.child_message.id if self.child_message else None
        )

    def regenerate(self):
        """Regenerate this message's response."""
        if self.role == "assistant":
            # Clear content and find parent to resubmit
            self.content = []
            parent = self._find_parent_message()
            if parent:
                parent.submit()
        else:
            # For user messages, just resubmit
            self.submit()

    def _find_parent_message(self):
        """Find the parent message that generated this response."""
        if self.role != "assistant":
            return None
        
        for msg in self.parent_chat.messages.values():
            if msg.child_message and msg.child_message.id == self.id:
                return msg
        return None

    def get_content(self):
        """Get the content of the message"""
        return self.content
    
    def set_text(self, text):
        """Set the text content of the message"""
        self.content = [{"type": "text", "text": text}]

    def get_text(self):
        """Get the text content of the message"""
        return next((item["text"] for item in self.content if item["type"] == "text"), "")
    
    def get_images(self):
        """Extract images from message content."""
        screenshots = []
        for item in self.content:
            if item.get("type") == "image" and "image_url" in item:
                try:
                    img_url = item["image_url"]["url"]
                    base64_data = img_url.split(",")[1]
                    img_data = base64.b64decode(base64_data)
                    qimage = QImage()
                    qimage.loadFromData(img_data)
                    screenshots.append(qimage)
                except Exception as e:
                    print(f"Error extracting screenshot: {e}")
        return screenshots

    def handle_response_chunk(self, chunk):
        """Handle incoming response chunk for this message."""
        if isinstance(chunk, str) and chunk.startswith("Error:"):
            self.content = [{"type": "text", "text": f"⚠️ {chunk}"}]
            self.model = self.parent_chat.active_model or get_default_model()
            return

        try:
            # If this is an existing message being edited, append the chunk
            if self.content and self.content[0]["type"] == "text":
                current_text = self.content[0]["text"]
                self.content = [{"type": "text", "text": current_text + chunk}]
            else:
                # For new messages, set the content directly
                self.content = [{"type": "text", "text": chunk}]
                
            self.model = self.parent_chat.active_model or get_default_model()
            
            # Update the chat display
            if self.parent_chat:
                self.parent_chat.rebuild_chat_content()
                self.parent_chat.update_chat_display()
                
        except Exception as e:
            print(f"Error in handle_response_chunk: {str(e)}")
            if DEBUG:
                import traceback
                traceback.print_exc()

    def to_dict(self):
        """Convert message to dictionary format."""
        return {
            "role": self.role,
            "content": self.content,
            "model": self.model,
            "id": self.id
        }

    @classmethod
    def from_dict(cls, data, parent_chat=None):
        """Create a Message instance from dictionary data."""
        msg = cls(
            role=data.get("role"),
            content=data.get("content"),
            model=data.get("model"),
            message_id=data.get("id")
        )
        msg.parent_chat = parent_chat  # Set the parent_chat reference
        return msg

    def start_edit(self):
        """Start editing this message."""
        if self.role != "user":
            return False
            
        self.is_editing = True
        self.original_content = self.content.copy()  # Backup content
        
        # Signal chat box to update UI
        if self.parent_chat:
            self.parent_chat.handle_edit_start(self)
        return True

    def cancel_edit(self):
        """Cancel editing and restore original content."""
        if not self.is_editing:
            return
            
        self.content = self.original_content
        self.is_editing = False
        self.original_content = None
        
        if self.parent_chat:
            self.parent_chat.handle_edit_end(self)
            self.parent_chat.rebuild_chat_content()

    def prepare_content_with_images(self):
        """Prepare message content including properly formatted images."""
        content = []
        
        # Add text content if exists
        text = self.get_text()
        if text:
            content.append({"type": "text", "text": text})
        
        # Add images if any
        for image in self.get_images():
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            image_base64 = byte_array.toBase64().data().decode()
            content.append({
                "type": "image",
                "image_url": {"url": f"data:image/png;base64,{image_base64}"}
            })
        
        return content

    def submit_edit(self, new_content=None):
        """Submit edited content and regenerate response."""
        if not self.is_editing:
            return
            
        if new_content is not None:
            if isinstance(new_content, str):
                self.set_text(new_content)
            else:
                self.content = new_content

        # Ensure images are properly formatted in content
        self.content = self.prepare_content_with_images()

        self.is_editing = False
        self.original_content = None
        
        if self.parent_chat:
            self.parent_chat.handle_edit_end(self)
            
        # Store the existing child message reference and ID
        existing_child = self.child_message
        child_id = existing_child.id if existing_child else None
        
        # Clear the child message's content but preserve its ID
        if existing_child:
            existing_child.content = []
            self.child_message = existing_child  # Ensure the reference is maintained
            
        # Submit to regenerate response
        self.submit()

class Bridge(QObject):
    def __init__(self, parent_chat):
        super().__init__()
        self.parent_chat = parent_chat

    @pyqtSlot(str)
    def regenerateMessage(self, message_id):
        print("regenerateMessage", message_id)
        self.parent_chat.messages[message_id].regenerate()

    @pyqtSlot(str)
    def editMessage(self, message_id):
        print("editMessage", message_id)
        self.parent_chat.messages[message_id].start_edit()

class ProviderStatusThread(QThread):
    status_changed = pyqtSignal(bool, str)
    
    def __init__(self, chat_instance):
        super().__init__()
        self.chat_instance = chat_instance
    
    def run(self):
        is_online, provider = check_provider_status()
        self.status_changed.emit(is_online, provider)
        self.chat_instance.status_thread = None

class ChatBox(QWidget):
    def __init__(self, parent=None, chat_instance=None):
        super().__init__(parent)
        self.parent = parent
        self.chat_instance = chat_instance
        # Initialize state
        self.chat_content = []
        self.current_response = ""
        self.is_receiving = False
        self.current_editing_message = None
        self.chat_instance.provider_online = False
        self.provider_status_displayed = False
        self.chat_storage = ChatStorage()
        self.active_model = None
        self.messages = OrderedDict()  # Single source of truth
        
        self.initUI()
        
        # Load chat history into ordered dict
        history = self.chat_storage.load_chat_history()
        previous_user_msg = None
        for msg_data in history:
            msg = Message.from_dict(msg_data, self)
            self.messages[msg.id] = msg
            # Update active_model to the last assistant's model
            if msg.role == "assistant" and msg.model:
                self.active_model = msg.model
                # Link assistant message to previous user message
                if previous_user_msg:
                    previous_user_msg.child_message = msg
            elif msg.role == "user":
                previous_user_msg = msg
        
        # Add provider status check timer
        self.provider_check_timer = QTimer(self)
        self.provider_check_timer.timeout.connect(self.check_provider_status)
        self.provider_check_timer.start(5000)

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Chat display
        self.chat_display = QWebEngineView()
        
        layout.addWidget(self.chat_display, 1)
        self.initialize_chat_display()

        # Set up the bridge
        self.channel = QWebChannel()
        self.bridge = Bridge(self)
        self.channel.registerObject("bridge", self.bridge)
        self.chat_display.page().setWebChannel(self.channel)

        # Connect the JavaScript bridge
        self.chat_display.page().loadFinished.connect(self.onLoadFinished)

    def initialize_chat_display(self):
        """Initializes the chat display with HTML template and app icon"""
        html_path = os.path.join(os.path.dirname(__file__), "..\\html\\chat_template.html")
        with open(html_path, "r") as file:
            initial_html = file.read()

        # Read and encode the app icon
        icon_path = os.path.join(os.path.dirname(__file__), "..\\icons\\background.png")
        with open(icon_path, "rb") as icon_file:
            icon_data = icon_file.read()
            icon_base64 = base64.b64encode(icon_data).decode("utf-8")

        # Replace the placeholder with the base64-encoded image
        initial_html = initial_html.replace("{{APP_ICON_BASE64}}", icon_base64)

        self.chat_display.setHtml(initial_html)
        
        # Wait for page to load before updating colors
        self.chat_display.loadFinished.connect(lambda: self.update_webview_colors())

    def extract_color(self, widget_selector, property_name, style=None):
        """Extract color value from QSS for given widget and property."""
        if not style:
            return None
            
        try:
            match = re.search(
                f'{widget_selector}\\s*{{[^}}]*{property_name}:\\s*([^;}}\\s]+)', 
                style
            )
            return match.group(1) if match else None
        except Exception as e:
            print(f"Error extracting color: {e}")
            return None

    def update_webview_colors(self):
        """Updates all theme colors in the webview to match QSS"""
        main_widget = self.parent
        if not main_widget or not main_widget.styleSheet():
            return

        style = main_widget.styleSheet()
        
        colors = {
            'backgroundColor': self.extract_color('QWidget#mainWidget', 'background-color', style),
            'messageBackgroundColor': self.extract_color('QWidget#chatMessage', 'background-color', style) or '#333333',
            'assistantBackgroundColor': self.extract_color('QWidget#chatMessageAssistant', 'background-color', style) or '#222222',
            'messageFontColor': self.extract_color('QWidget#chatMessage', 'color', style) or '#D4D4D4',
            'userBorderColor': self.extract_color('QWidget#chatMessageUser', 'border-color', style) or '#7289DA',
            'assistantBorderColor': self.extract_color('QWidget#chatMessageAssistant', 'border-color', style) or '#53629b'
        }

        # Convert the colors dict to a JavaScript object string
        js = f'if (typeof updateThemeColors === "function") {{ updateThemeColors({json.dumps(colors)}); }}'
        self.chat_display.page().runJavaScript(js)

    def remove_subsequent_messages(self, message_id):
        """Remove all messages that come after the specified message."""
        if message_id not in self.messages:
            return
            
        # Convert to list for iteration since we'll modify the dict
        message_ids = list(self.messages.keys())
        found_message = False
        
        for msg_id in message_ids:
            if found_message:
                del self.messages[msg_id]
            if msg_id == message_id:
                found_message = True

    def handle_response_chunk(self, chunk, message_id):
        """Route response chunks to appropriate message."""
        if DEBUG:
            print("\n=== handle_response_chunk ===")
            print(f"Incoming chunk for message ID: {message_id}")

        if message_id and message_id in self.messages:
            # Route to existing message
            self.messages[message_id].handle_response_chunk(chunk)
        else:
            # Create new message or update last message
            if not self.current_response:
                self.current_response = chunk
                new_msg = Message("assistant", [{"type": "text", "text": chunk}], 
                                self.active_model or get_default_model())
                new_msg.parent_chat = self
                self.messages[new_msg.id] = new_msg
            else:
                self.current_response = chunk
                last_msg = next(reversed(self.messages.values()))
                last_msg.handle_response_chunk(self.current_response)

    def handle_response_complete(self):
        """Handle completion of Ollama response."""
        if not self.current_response:
            self.current_response = "No response received from Assistant."

        # Get the current model being used
        current_model = self.active_model or get_default_model()            

        # Get the last message
        last_msg = next(reversed(self.messages.values()), None)

        # Update model if it's an assistant message
        if last_msg and last_msg.role == "assistant":
            last_msg.model = current_model

        # Reset state
        self.current_response = ""
        self.is_receiving = False
        self.chat_instance.update_gradient_state()
        load_svg_button_icon(self.chat_instance.send_btn, ".\\icons\\send.svg")
        self.chat_instance.send_btn.setObjectName("sendButton")                

    def rebuild_chat_content(self):
        """Reconstruct chat_content based on messages."""
        DEBUG = False
        if DEBUG:
            print("\n=== rebuild_chat_content ===")
            print("Current messages:")
            for msg_id, msg in self.messages.items():
                print(f"ID: {msg_id}")
                print(f"Role: {msg.role}")
                print(f"Content: {msg.get_text()[:100]}...")
    
        self.chat_content = []
        
        for message in self.messages.values():
            if message.role == "system":
                continue
            
            # Ensure parent_chat reference is set
            message.parent_chat = self
            
            try:
                sender = "user" if message.role == "user" else message.model
                text_content = message.get_text()
                images_html = ""

                # Process images if any
                for item in message.content:
                    if item.get("type") == "image" and "image_url" in item:
                        img_url = item["image_url"]["url"]
                        images_html += f'<img src="{img_url}" alt="Screenshot" style="max-width: 100%; height: auto; margin: 10px 0; border-radius: 8px;">'

                self.chat_content.append((sender, text_content, images_html))
                
            except Exception as e:
                if DEBUG:
                    print(f"Error processing message: {str(e)}")
                    print(f"Message content: {message}")

        if DEBUG:
            print("\nFinal chat_content length:", len(self.chat_content))
            
        self.update_chat_display()

    def handle_edit_start(self, message):
        """Handle when a message starts being edited."""
        self.current_editing_message = message
        
        # Update UI to show editing state
        self.chat_instance.send_btn.setIcon(QIcon("icons/edit.png"))
        self.chat_instance.input_field.setText(message.get_text())
        
        # Add any images from the message being edited
        self.chat_instance.selected_screenshots = message.get_images()
        self.chat_instance.update_thumbnails()

    def handle_edit_end(self, message):
        """Handle when message editing ends."""
        self.current_editing_message = None
        self.chat_instance.send_btn.setIcon(QIcon("icons/send.png"))
        self.chat_instance.input_field.clear()
        self.chat_instance.selected_screenshots.clear()
        self.chat_instance.update_thumbnails()

    def handle_message_action(self, message_id, action):
        """Handle message actions (edit, regenerate, etc.)."""
        if message_id not in self.messages:
            return
            
        message = self.messages[message_id]
        
        if action == "edit":
            message.start_edit()
        elif action == "regenerate":
            message.regenerate()
        elif action == "cancel_edit":
            message.cancel_edit()
             
    def send_message(self, content, model=None):
        """Handle sending a new message or submitting an edit."""
        if self.current_editing_message:
            self.current_editing_message.submit_edit(content)
            return
        
        # Update active model if one is specified
        if model:
            self.active_model = model
        
        # Create new message with the specified model
        new_message = Message("user", content, self.active_model)
        new_message.parent_chat = self
        self.messages[new_message.id] = new_message
        
        # Update display and submit
        self.rebuild_chat_content()
        self.save_chat_history()
        new_message.submit()

    def clear_chat(self):
        self.chat_content.clear()
        self.messages.clear()
        self.current_editing_message = None
        self.update_chat_display()
        self.chat_instance.input_field.clear()
        self.selected_screenshot = None
        self.chat_instance.screenshot_btn.setStyleSheet(self.chat_instance.original_button_style)
        self.active_model = None
        # Save empty chat history
        self.save_chat_history()

    def handle_js_console(self, level, message, line, source):
        """Handle JavaScript console messages."""
        if DEBUG:
            print(f"JS Console ({level}): {message} [line {line}] {source}")



    def check_provider_status(self):
        """Check provider status and update UI accordingly."""
        # Create and start the status check thread
        if self.chat_instance.status_thread is None:
            self.chat_instance.status_thread = ProviderStatusThread(self.chat_instance)
            self.chat_instance.status_thread.status_changed.connect(self.handle_provider_status)
            self.chat_instance.status_thread.start()

    def handle_provider_status(self, is_online, provider):
        """Handle the provider status results from the thread."""
        # Adjust timer interval based on status

        if is_online != self.chat_instance.provider_online:  # Only update if state changed
            self.chat_instance.provider_online = is_online
            self.chat_instance.update_gradient_state()  # Update gradient
            
            # Force an immediate gradient update
            self.chat_instance.update_gradient()

            # If we just came online and have messages, display them
            if is_online and len(self.messages) > 0:
                self.rebuild_chat_content()

        # Update status in UI
        status_message = {
            "provider": provider,
            "online": is_online
        }

        self.chat_display.page().runJavaScript(f"updateProviderStatus({json.dumps(status_message)})")        
        self.chat_instance.send_btn.setEnabled(self.chat_instance.provider_online)

    def onLoadFinished(self, ok):
        if ok:
            js = """
            new QWebChannel(qt.webChannelTransport, function(channel) {
                window.bridge = channel.objects.bridge;
                window.qt_bridge = {
                    regenerateMessage: function(messageId) {
                        if (window.bridge) {
                            window.bridge.regenerateMessage(messageId);
                        } else {
                            console.error('Bridge not initialized');
                        }
                    },
                    editMessage: function(messageId) {
                        if (window.bridge) {
                            window.bridge.editMessage(messageId);
                        } else {
                            console.error('Bridge not initialized');
                        }
                    }
                };
            });
            """
            self.chat_display.page().runJavaScript(js)

    def regenerate_message(self, message_id):
        """Regenerate a specific message in the chat history."""
        if message_id in self.messages:
            message = self.messages[message_id]
            message.parent_chat = self  # Ensure the message is linked to this chat box
            message.regenerate()
        else:
            print(f"Warning: Message {message_id} not found in chat history")

    def edit_message(self, message_id):
        """Start editing a message with the given ID."""
        print(f"\n=== edit_message ===")
        print(f"Starting edit for message ID: {message_id}")
        
        if message_id not in self.messages:
            print(f"Warning: Message {message_id} not found in chat history")
            return
        
        message = self.messages[message_id]
        if message.role != "user":
            print("Can only edit user messages")
            return
        
        message.start_edit()

    def save_chat_history(self):
        """Save the current chat history"""
        try:
            # Convert all messages to dictionaries using to_dict()
            history_data = [
                msg.to_dict() if isinstance(msg, Message) else Message.from_dict(msg).to_dict()
                for msg in self.messages.values()
            ]
            self.chat_storage.save_chat_history(history_data)
        except Exception as e:
            print(f"Error saving chat history: {str(e)}")
            if DEBUG:
                import traceback
                traceback.print_exc()

    def update_chat_display(self):
        """Update the chat display with current content."""
        DEBUG = False
        if DEBUG:
            print("\n=== update_chat_display ===")
            
        chat_content = []
        
        # Check if messages is empty
        if not self.messages:
            if DEBUG:
                print("Empty messages, clearing display")
            self.chat_display.page().runJavaScript(
                """
                try {
                    updateChatContent([]);
                } catch (error) {
                    console.error('Error updating chat content:', error);
                }
                """
            )
            return

        # Process messages if there are any
        for idx, message in enumerate(self.messages.values()):
            try:
                # Skip system messages
                if message.role == "system":
                    continue
                    
                sender = "user" if message.role == "user" else message.model
                message_id = message.id
                
                if DEBUG:
                    print(f"\nProcessing message {idx}:")
                    print(f"Sender: {sender}")
                    print(f"Content: {message.content}")
                
                text_content = message.get_text()
                images_html = ""
                
                # Process images if any
                for item in message.content:
                    if item.get("type") == "image" and "image_url" in item:
                        img_url = item["image_url"]["url"]
                        images_html += f'<img src="{img_url}" alt="Screenshot" style="max-width: 128px; height: auto; margin: 10px 0; border-radius: 8px;">'
                
                chat_content.append({
                    "sender": sender,
                    "content": text_content,
                    "images": images_html,
                    "id": message_id
                })
                
                if DEBUG:
                    print(f"Added to chat_content - Text: {text_content[:50]}...")
                    print(f"Has images: {'Yes' if images_html else 'No'}")
                    
            except Exception as e:
                if DEBUG:
                    print(f"Error processing message {idx}: {str(e)}")
                    print(f"Message content: {message}")

        # Update the chat container content
        self.chat_display.page().runJavaScript(
            f"""
            try {{
                updateChatContent({json.dumps(chat_content)});
            }} catch (error) {{
                console.error('Error updating chat content:', error);
            }}
            """
        )

    def get_messages_for_request(self, up_to_message_id=None):
        """Get messages formatted for provider request, optionally up to a specific message."""
        messages_to_send = []

        for msg_id, msg in self.messages.items():
            # Create a copy of the message content
            message_data = msg.to_dict()
            messages_to_send.append(message_data)
            if msg_id == up_to_message_id:
                break

        return messages_to_send

    def start_provider_request(self, messages, screenshots=None, message_id=None):
        """Unified method to start a provider request."""
        try:
            model = self.active_model or get_default_model()
            print(f"Starting provider request with model: {model}")
            
            # Check if current model supports vision
            base_model = get_base_model_name(model)
            is_vision_model = base_model in self.chat_instance.settings_interface.vision_capable_models
            
            # If not a vision model, remove all image content from messages
            if not is_vision_model:
                for message in messages:
                    message['content'] = [item for item in message['content'] if item.get('type') != 'image']
                screenshots = []  # Clear images for non-vision models

            self.chat_instance.provider_request_thread = ProviderRequest(
                messages,
                screenshots,
                model,
                message_id=message_id,
                temperature=self.chat_instance.settings_interface.temperature,
                context_size=self.chat_instance.settings_interface.context_size,
            )

            thread = self.chat_instance.provider_request_thread
            thread.response_chunk_ready.connect(self.handle_response_chunk)
            thread.response_complete.connect(self.handle_response_complete)
            thread.start()

            # Update UI state
            self.is_receiving = True
            self.chat_instance.update_gradient_state()
            load_svg_button_icon(self.chat_instance.send_btn, ".\\icons\\stop.svg")
            self.chat_instance.send_btn.setObjectName("stopButton")

        except Exception as e:
            print(f"Error in start_provider_request: {str(e)}")
            if DEBUG:
                import traceback
                traceback.print_exc()