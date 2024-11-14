# PixelLama 0.9a - A GUI interface for Ollama
# Created by Alfredo Fernandes
# This software provides a user-friendly interface for interacting with Ollama with screenshot capabilities,
# https://github.com/fredconex/PixelLlama

import os
import json
import base64
import requests
import sys
from math import cos, sin, radians
from utils.settings_manager import (
    load_settings_from_file, 
    save_settings_to_file, 
    get_ollama_url, 
    get_default_model, 
    get_system_prompt, 
)

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QLabel,
    QSizeGrip,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QMenu,
    QListWidget,
    QScrollArea,
    QMessageBox,
    QListWidgetItem,
    QWidget,
    QHBoxLayout,
    QAbstractItemView,
)
from PyQt6.QtCore import (
    Qt,
    QByteArray,
    QBuffer,
    QIODevice,
    QTimer,
    QSize,
    QRect,
    QPropertyAnimation,
    QEasingCurve,
    QEvent,
    QUrl,
)
from PyQt6.QtGui import (
    QDoubleValidator,
    QIntValidator,
    QKeyEvent,
    QIcon,
    QPainter,
    QPainterPath,
    QImage,
    QColor,
    QPixmap,
    QKeySequence,
    QDropEvent,
    QCursor,
)

from datetime import datetime
from utils.screenshot_utils import ScreenshotSelector, process_image
from utils.ollama_utils import (
    OllamaThread,    
    load_ollama_models
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QObject, pyqtSlot
from PyQt6.QtWebEngineCore import QWebEngineScript

DEBUG = "-debug" in sys.argv


class Bridge(QObject):
    def __init__(self, chat_window):
        super().__init__()
        self.chat_window = chat_window

    @pyqtSlot(int)
    def regenerateMessage(self, index):
        self.chat_window.regenerate_message(index)

    @pyqtSlot(int)
    def editMessage(self, index):
        print("editMessage", index)
        self.chat_window.edit_message(index)

class ImageDropTextEdit(QTextEdit):
    def __init__(self, parent=None, chat_instance=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.chat_instance = chat_instance  # Store a reference to the chat instance

    def dropEvent(self, event: QDropEvent):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            for url in mime_data.urls():
                file_path = url.toLocalFile()
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                    image = QImage(file_path)
                    if not image.isNull() and self.chat_instance:
                        self.chat_instance.handle_pasted_image(image)
            event.acceptProposedAction()
        elif mime_data.hasImage():
            image = QImage(mime_data.imageData())
            if self.chat_instance:
                self.chat_instance.handle_pasted_image(image)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

class OllamaChat(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        screen = QApplication.primaryScreen().availableGeometry()

        # Add thumbnail size constants
        self.THUMBNAIL_SIZE = 42  # Main container size
        self.THUMBNAIL_INNER_SIZE = 26  # Actual thumbnail size
        self.THUMBNAIL_BTN_SIZE = 16  # Delete button size
        self.THUMBNAIL_BTN_MARGIN = 0  # Button margin from top-right

        # Replace direct settings loading with settings_manager
        self.settings = load_settings_from_file()
        
        self.system_prompt = self.settings.get("system_prompt")
        self.ollama_url = self.settings["ollama_url"]
        self.default_model = self.settings.get("default_model")
        self.temperature = self.settings.get("temperature")
        self.context_size = self.settings.get("context_size")
        self.vision_capable_models = set(self.settings.get("vision_capable_models", []))

        # Add these lines near the start of __init__
        self.provider_online = False
        self.is_receiving = False
        self.gradient_angle = 0
        self.gradient_color1 = "#1E1E1E"  # Default blue
        self.gradient_color2 = "#1E1E1E"  # Default dark
        self.gradient_speed = 0

        # Initialize a timer to check model capabilities
        self.model_check_timer = QTimer(self)
        self.model_check_timer.timeout.connect(self.update_screenshot_button_visibility)
        self.model_check_timer.start(1000)  # Check every second

        # Store original sizes
        self.original_compact_size = QSize(400, 800)  
        self.original_expanded_size = QSize(
            int(screen.width() * 0.5), int(screen.height() * 0.75)  
        )

        # Current sizes can change when user resizes the window
        self.compact_size = QSize(400, 800)
        self.expanded_size = QSize(
            int(screen.width() * 0.5), int(screen.height() * 0.75)
        )
        self.message_history = []
        self.chat_content = []
        self.current_response = ""
        self.is_expanded = False
        self.selected_screenshot = None
        self.original_button_style = ""
        self.debug_screenshot = None
        self.is_receiving = False
        self.edit_index = None
        self.system_prompt = get_system_prompt()
        self.sidebar_expanded = True
        self.previous_geometry = None
        self.animation = None
        self.model_names = []
        self.default_model = []
        self.selected_model = None
        self.active_model = None 
        self.vision_capable_models = set()  # Store models with vision capability
        
        # Use the custom ImageDropTextEdit
        self.input_field = ImageDropTextEdit(self, chat_instance=self)
        self.input_field.setPlaceholderText("Type your message...")
        self.input_field.setFixedHeight(50)
        self.input_field.setAcceptRichText(False)  # Only allow plain text
        self.input_field.installEventFilter(self)
        self.input_field.textChanged.connect(self.adjust_input_height)

        self.initUI()  # Initialize UI components after input_field is created
        self.load_settings()
        self.add_vertical_button()
        self.position_window()
        self.initialize_chat_display()
        self.thumbnail_size = QSize(256, 256)
        self.is_settings_visible = False
        self.update_input_position()
        self.create_tray_icon()
        self.dragging = False
        self.drag_start_position = None

        self.suggestion_list = QListWidget(self)  
        self.suggestion_list.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip
        )
        self.suggestion_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.suggestion_list.hide()
        self.suggestion_list.itemClicked.connect(self.insert_suggestion)
        self.input_field.textChanged.connect(
            lambda: self.update_suggestions()
        )  # Use lambda to call without arguments
        self.current_response_model = None

        # Add provider status check timer
        self.provider_check_timer = QTimer(self)
        self.provider_check_timer.timeout.connect(self.check_provider_status)
        self.provider_check_timer.start(5000)  # Check every 5 seconds
        self.provider_online = False
        self.provider_status_displayed = False

        # Add these new attributes for multiple screenshots
        self.selected_screenshots = []  # List to store multiple screenshots
        self.MAX_SCREENSHOTS = 3  # Maximum number of allowed screenshots
        self.thumbnail_containers = []  # List to store thumbnail containers

        # Create thumbnail containers
        for i in range(self.MAX_SCREENSHOTS):
            container = self.create_thumbnail_container()
            self.thumbnail_containers.append(container)
            container.hide()

        self.load_chat_history()

    def create_thumbnail_container(self):
        """Create a new thumbnail container with label and delete button."""
        container = QWidget()
        container.setFixedSize(self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE)
        
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 8, 8, 0)
        layout.setSpacing(0)

        # Create label container
        label_container = QWidget(container)
        label_container.setFixedSize(self.THUMBNAIL_INNER_SIZE, self.THUMBNAIL_INNER_SIZE)
        label_layout = QHBoxLayout(label_container)
        label_layout.setContentsMargins(0, 0, 0, 0)
        label_layout.setSpacing(0)
        label_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Add thumbnail label
        thumbnail_label = QLabel()
        thumbnail_label.setFixedSize(self.THUMBNAIL_INNER_SIZE, self.THUMBNAIL_INNER_SIZE)
        thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumbnail_label.setStyleSheet("background-color: transparent;")
        label_layout.addWidget(thumbnail_label)

        # Add the label container to main layout
        layout.addWidget(label_container)

        # Add delete button
        delete_btn = QPushButton(container)
        delete_btn.setFixedSize(self.THUMBNAIL_BTN_SIZE, self.THUMBNAIL_BTN_SIZE)
        delete_btn.setIcon(QIcon("icons/close.png"))
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #2f3136;
                border: none;
                border-radius: 8px;
                margin: 0;
                padding: 0;
            }
            QPushButton:hover {
                background-color: #ed4245;
            }
        """)
        
        # Position the delete button
        btn_position = self.THUMBNAIL_INNER_SIZE - self.THUMBNAIL_BTN_SIZE + self.THUMBNAIL_BTN_MARGIN
        delete_btn.move(btn_position, self.THUMBNAIL_BTN_MARGIN)
        delete_btn.raise_()

        # Store references to label and button
        container.thumbnail_label = thumbnail_label
        container.delete_btn = delete_btn

        return container

    def initUI(self):

        # Remove the outer_layout creation and setting since we'll use main_layout directly
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Load the stylesheet
        style_path = os.path.join(os.path.dirname(__file__), "styles.qss")
        with open(style_path, "r") as style_file:
            self.setStyleSheet(style_file.read())

        # Create main layout for the entire widget
        main_layout = QVBoxLayout(self)  # Set directly on self
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create outer widget with gradient background
        outer_widget = QWidget()
        outer_widget.setObjectName("outerWidget")
        main_layout.addWidget(outer_widget)

        # Create layout for outer widget
        outer_layout = QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(2, 2, 2, 2)

        # Start the gradient animation
        self.start_gradient_animation()

        # Create main widget
        main_widget = QWidget()
        main_widget.setObjectName("mainWidget")
        widget_layout = QVBoxLayout(main_widget)
        widget_layout.setContentsMargins(20, 20, 20, 20)
        outer_layout.addWidget(main_widget)

        # Add size grip for resizing at the top-left
        size_grip = QSizeGrip(self)
        size_grip.setFixedSize(20, 20)
        size_grip.installEventFilter(
            self
        )  # Install event filter to catch double clicks

        # Create a container for the size grip
        grip_container = QWidget()
        grip_layout = QHBoxLayout(grip_container)
        grip_layout.setContentsMargins(0, 0, 0, 0)
        grip_layout.addWidget(size_grip)
        grip_layout.addStretch(1)

        # Add the grip container to the top of the widget layout
        widget_layout.insertWidget(0, grip_container)

        # Header
        header = QHBoxLayout()
        header.addStretch(1)
        
        # Add monitor switch button
        self.monitor_btn = QPushButton()
        self.monitor_btn.setIcon(QIcon("icons/monitor.png"))
        self.monitor_btn.setFixedSize(26, 26)
        self.monitor_btn.setToolTip("Switch Monitor")
        self.monitor_btn.setObjectName("monitorButton")
        self.monitor_btn.clicked.connect(self.switch_monitor)
        header.addWidget(self.monitor_btn)
        
        # Add clear button with icon
        self.clear_btn = QPushButton()
        self.clear_btn.setIcon(QIcon.fromTheme("edit-delete"))  # Use 'edit-delete' icon
        self.clear_btn.setFixedSize(26, 26)  # Make the button smaller
        self.clear_btn.setToolTip("Clear Chat")
        self.clear_btn.setObjectName("clearButton")
        self.clear_btn.clicked.connect(self.clear_chat)
        header.addWidget(self.clear_btn)

        # Add settings button
        self.settings_btn = QPushButton()
        self.settings_btn.setIcon(QIcon("icons/settings_icon.png"))
        self.settings_btn.setFixedSize(26, 26)
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setObjectName("settingsButton")
        self.settings_btn.clicked.connect(self.toggle_settings)
        header.addWidget(self.settings_btn)

        # Add close button
        self.close_btn = QPushButton()
        self.close_btn.setIcon(QIcon("icons/close.png"))
        self.close_btn.setFixedSize(26, 26)
        self.close_btn.setToolTip("Close")
        self.close_btn.setObjectName("closeButton")
        self.close_btn.clicked.connect(self.handle_close_button_click)
        header.addWidget(self.close_btn)

        

        widget_layout.addLayout(header)

        # Updated toggle button creation
        toggle_layout = QHBoxLayout()
        self.toggle_btn = QPushButton()
        button_size = 26
        self.toggle_btn.setFixedSize(button_size, button_size)
        self.toggle_btn.setIcon(QIcon.fromTheme("zoom-in"))
        self.toggle_btn.setObjectName("toggleButton")
        self.toggle_btn.clicked.connect(self.toggle_window_size)

        # Add App label and version
        app_label_container = QWidget()
        app_label_layout = QVBoxLayout(app_label_container)
        app_label_layout.setContentsMargins(0, 0, 0, 0)
        app_label_layout.setSpacing(0)

        pixelllama_label = QLabel("PixelLlama")
        pixelllama_label.setObjectName("AppLabel")

        version_label = QLabel("v0.92a")
        version_label.setObjectName("VersionLabel")
        version_label.setStyleSheet("""
            QLabel#VersionLabel {
                color: #72767d;
                font-size: 10px;
                padding: 0;
                margin: 0;
            }
        """)

        app_label_layout.addWidget(pixelllama_label)
        app_label_layout.addWidget(version_label)

        toggle_layout.addWidget(self.toggle_btn)
        toggle_layout.addWidget(app_label_container)
        toggle_layout.addStretch(1)  # This will push the button and label to the left

        header.insertLayout(0, toggle_layout)

        # Create a stacked widget to hold both the chat and settings interfaces
        self.stacked_widget = QStackedWidget()
        widget_layout.addWidget(self.stacked_widget, 1)  # Give it a stretch factor

        # Create and add the chat interface
        self.chat_interface = QWidget()
        chat_layout = QVBoxLayout(self.chat_interface)
        chat_layout.setContentsMargins(0, 0, 0, 0)

        # Chat display
        self.chat_display = QWebEngineView()
        self.chat_display.setUrl(QUrl("about:blank"))
        # Update size policy to expand in both directions
        self.chat_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        chat_layout.addWidget(self.chat_display, 1)

        # Modify the input area section:
        input_widget = QWidget()
        self.input_layout = QHBoxLayout(input_widget)
        self.input_layout.setContentsMargins(0, 0, 0, 0)
        self.input_layout.setSpacing(10)

        # Add thumbnail container with adjusted layout
        self.thumbnail_container = QWidget()
        self.thumbnail_container.setFixedSize(self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE)
        self.thumbnail_container.hide()
        thumbnail_layout = QHBoxLayout(self.thumbnail_container)
        thumbnail_layout.setContentsMargins(0, 8, 8, 0)
        thumbnail_layout.setSpacing(0)

        # Create a container for the thumbnail label
        thumbnail_label_container = QWidget(self.thumbnail_container)
        thumbnail_label_container.setFixedSize(self.THUMBNAIL_INNER_SIZE, self.THUMBNAIL_INNER_SIZE)
        thumbnail_label_layout = QHBoxLayout(thumbnail_label_container)
        thumbnail_label_layout.setContentsMargins(0, 0, 0, 0)
        thumbnail_label_layout.setSpacing(0)
        thumbnail_label_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Add thumbnail label to its container
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(self.THUMBNAIL_INNER_SIZE, self.THUMBNAIL_INNER_SIZE)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("background-color: transparent;")
        thumbnail_label_layout.addWidget(self.thumbnail_label)

        # Add the thumbnail label container to the main thumbnail layout
        thumbnail_layout.addWidget(thumbnail_label_container)

        # Add delete button overlay
        self.delete_thumbnail_btn = QPushButton(self.thumbnail_container)
        self.delete_thumbnail_btn.setFixedSize(self.THUMBNAIL_BTN_SIZE, self.THUMBNAIL_BTN_SIZE)
        self.delete_thumbnail_btn.setIcon(QIcon("icons/close.png"))
        self.delete_thumbnail_btn.setStyleSheet("""
            QPushButton {
                background-color: #2f3136;
                border: none;
                border-radius: 8px;
                margin: 0;
                padding: 0;
            }
            QPushButton:hover {
                background-color: #ed4245;
            }
        """)
        self.delete_thumbnail_btn.clicked.connect(self.remove_screenshot)
        
        # Position the delete button in the top-right corner
        btn_position = self.THUMBNAIL_INNER_SIZE - self.THUMBNAIL_BTN_SIZE + self.THUMBNAIL_BTN_MARGIN
        self.delete_thumbnail_btn.move(btn_position, self.THUMBNAIL_BTN_MARGIN)
        self.delete_thumbnail_btn.raise_()

        # Add camera icon button
        self.screenshot_btn = QPushButton()
        self.screenshot_btn.setIcon(QIcon.fromTheme("camera-photo"))
        self.screenshot_btn.setFixedSize(30, 30)
        self.screenshot_btn.setToolTip("Take Screenshot")
        self.screenshot_btn.clicked.connect(self.toggle_screenshot)
        self.original_button_style = self.screenshot_btn.styleSheet()


        self.send_btn = QPushButton()
        self.send_btn.setFixedSize(30, 30)
        self.send_btn.setIcon(QIcon("icons/send.png"))
        self.send_btn.setText("")
        self.send_btn.setObjectName("sendButton")
        self.send_btn.clicked.connect(self.send_or_stop_message)

        # Add components to input layout
        self.input_layout.addWidget(self.screenshot_btn)
        self.input_layout.addWidget(self.thumbnail_container)
        self.input_layout.addWidget(self.input_field, 1)  # Give the input field more space
        self.input_layout.addWidget(self.send_btn)

        # Add the input widget to the chat layout
        chat_layout.addWidget(input_widget, 0, Qt.AlignmentFlag.AlignBottom)

        # Update chat layout stretch factors
        chat_layout.setStretch(0, 1)  # Give chat display stretch priority
        chat_layout.setStretch(1, 0)  # Keep input area at minimum required size

        self.stacked_widget.addWidget(self.chat_interface)

        # Create and add the settings interface
        self.settings_interface = QWidget()
        settings_layout = QVBoxLayout(self.settings_interface)

        # Add a scroll area for settings
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        settings_title = QLabel("Settings")
        settings_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll_layout.addWidget(settings_title)

        # Create an input field for the Ollama URL
        self.ollama_url_label = QLabel("Ollama URL:")
        scroll_layout.addWidget(self.ollama_url_label)

        # Add a QLineEdit widget for entering the Ollama URL
        self.ollama_url_input = QLineEdit()
        self.ollama_url_input.setText(get_ollama_url())        
        self.ollama_url_input.setPlaceholderText("http://localhost:11434")  # Set a placeholder text
        scroll_layout.addWidget(self.ollama_url_input)


        self.model_label = QLabel("Select Ollama Model:")
        scroll_layout.addWidget(self.model_label)

        # Add search bar for models
        self.model_search = QLineEdit()
        self.model_search.setPlaceholderText("Search models...")
        self.model_search.textChanged.connect(self.filter_models)
        scroll_layout.addWidget(self.model_search)

        # Apply the same style to model_list
        self.model_list = QListWidget()
        self.model_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.model_list.setObjectName("modelList")
        self.model_list.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip
        )
        self.model_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.load_models()
        scroll_layout.addWidget(
            self.model_list, 1
        )  # Give it a stretch factor to expand

        # Add temperature setting
        self.temperature_label = QLabel("Temperature:")
        scroll_layout.addWidget(self.temperature_label)

        self.temperature_input = QLineEdit()
        self.temperature_input.setPlaceholderText("default")
        # Add a validator for temperature (float between 0.0 and 1.0)
        temperature_validator = QDoubleValidator(0.0, 1.0, 2, self)
        self.temperature_input.setValidator(temperature_validator)
        scroll_layout.addWidget(self.temperature_input)

        # Add context size setting
        self.context_size_label = QLabel("Context Size:")
        scroll_layout.addWidget(self.context_size_label)

        self.context_size_input = QLineEdit()
        self.context_size_input.setPlaceholderText("default")
        # Add a validator for context size (integer between 0 and 65536)
        context_size_validator = QIntValidator(0, 65536, self)
        self.context_size_input.setValidator(context_size_validator)
        scroll_layout.addWidget(self.context_size_input)

        # Add system prompt setting
        self.system_prompt_label = QLabel("System Prompt:")
        scroll_layout.addWidget(self.system_prompt_label)

        self.system_prompt_input = QTextEdit()
        self.system_prompt_input.setPlaceholderText("Enter system prompt here...")
        self.system_prompt_input.setFixedHeight(
            100
        )  # Set a fixed height for better visibility
        scroll_layout.addWidget(self.system_prompt_input)

        scroll_layout.addStretch(1)

        scroll_content.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_content)
        settings_layout.addWidget(scroll_area)

        # Move button layout outside of scroll area
        button_layout = QHBoxLayout()
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.apply_settings)
        button_layout.addWidget(self.apply_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.clicked.connect(self.cancel_settings)
        button_layout.addWidget(self.cancel_button)

        settings_layout.addLayout(button_layout)

        self.stacked_widget.addWidget(self.settings_interface)

        # Set size policy for main_widget
        main_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Set layout for self
        self.setLayout(main_layout)
        self.update_input_position()  

        # Ensure the vertical button is created after the main layout
        self.add_vertical_button()

        # Set up the bridge
        self.channel = QWebChannel()
        self.bridge = Bridge(self)
        self.channel.registerObject("bridge", self.bridge)
        self.chat_display.page().setWebChannel(self.channel)

        # Connect the JavaScript bridge
        self.chat_display.page().loadFinished.connect(self.onLoadFinished)

    @staticmethod
    def get_base_model_name(model_name):
        """Extract the base model name before the colon."""
        return model_name.split(":")[0] if ":" in model_name else model_name

    def start_gradient_animation(self):
        """Initialize and start the gradient animation"""
        self.gradient_angle = 0
        self.gradient_timer = QTimer(self)
        self.gradient_timer.timeout.connect(self.update_gradient)
        self.gradient_timer.start(50)  # Update every 50ms
        self.gradient_speed = 1  # Normal speed
        self.update_gradient_state()  # Initial state update

    def update_gradient_state(self):
        """Update gradient colors based on current state"""
        if self.is_receiving:
            self.gradient_color1 = "#FFA100"  # Orange
            self.gradient_color2 = "#1E1E1E"
            self.gradient_speed = 20  # Faster rotation when receiving
        elif not self.provider_online:
            self.gradient_color1 = "#FFFFFF"  # white
            self.gradient_color2 = "#1E1E1E"
            self.gradient_speed = 10  # Medium rotation when waiting for provider
        else:
            self.gradient_color1 = "#7289DA"  # Blue
            self.gradient_color2 = "#1E1E1E"
            self.gradient_speed = 0  # No rotation in normal state

    def update_gradient(self):
        """Update the gradient rotation"""
        if self.gradient_speed > 0:
            self.gradient_angle = (self.gradient_angle + self.gradient_speed) % 360

            # Map angle to coordinates in range 0-1
            x1 = (cos(radians(self.gradient_angle)) + 1) / 2
            y1 = (sin(radians(self.gradient_angle)) + 1) / 2
            x2 = (cos(radians(self.gradient_angle + 180)) + 1) / 2
            y2 = (sin(radians(self.gradient_angle + 180)) + 1) / 2

            gradient_style = f"""
                #outerWidget {{
                    background: qlineargradient(spread:pad, x1:{x1}, 
                        y1:{y1}, 
                        x2:{x2}, 
                        y2:{y2},
                        stop:0 {self.gradient_color1}, stop:1 {self.gradient_color2});
                    border-radius: 20px;
                }}
                #mainWidget {{
                    background-color: #1E1E1E;
                    border-radius: 20px;
                    margin: 0px;
                }}
            """
        else:
            # Solid color when not rotating
            gradient_style = f"""
                #outerWidget {{
                    background: {self.gradient_color1};
                    border-radius: 20px;
                }}
                #mainWidget {{
                    background-color: #1E1E1E;
                    border-radius: 20px;
                    margin: 0px;
                }}
            """

        self.findChild(QWidget, "outerWidget").setStyleSheet(gradient_style)

    def update_screenshot_button_visibility(self):
        """Update the visibility of the screenshot button based on the current model's capabilities."""
        if self.active_model:
            base_model = self.get_base_model_name(self.active_model)
            self.screenshot_btn.setVisible(base_model in self.vision_capable_models)
        else:
            base_model = self.get_base_model_name(self.default_model)
            self.screenshot_btn.setVisible(base_model in self.vision_capable_models)

    def onLoadFinished(self, ok):
        if ok:
            js = """
            new QWebChannel(qt.webChannelTransport, function(channel) {
                window.bridge = channel.objects.bridge;
                window.qt_bridge = {
                    regenerateMessage: function(index) {
                        if (window.bridge) {
                            window.bridge.regenerateMessage(index);
                        } else {
                            console.error('Bridge not initialized');
                        }
                    },
                    editMessage: function(index) {
                        if (window.bridge) {
                            window.bridge.editMessage(index);
                        } else {
                            console.error('Bridge not initialized');
                        }
                    }
                };
            });
            """
            self.chat_display.page().runJavaScript(js)

    def load_models(self):
        try:
            self.model_names = sorted(load_ollama_models())
            self.model_list.clear()

            # Create items with fixed button positions
            for model_name in self.model_names:
                item = QListWidgetItem(self.model_list)
                base_model = self.get_base_model_name(model_name)  # Get base model name

                # Create a widget to hold the model name and icons
                widget = QWidget()
                layout = QHBoxLayout(widget)
                layout.setContentsMargins(5, 2, 5, 2)
                layout.setSpacing(0)  # Remove spacing between elements

                # Create a fixed-width container for buttons
                button_container = QWidget()
                button_container.setFixedWidth(60)  # Adjust width based on your buttons

                button_layout = QHBoxLayout(button_container)
                button_layout.setContentsMargins(0, 0, 0, 0)
                button_layout.setSpacing(2)
                button_layout.setAlignment(
                    Qt.AlignmentFlag.AlignLeft
                )  # Align buttons to the left

                # Add button container first
                layout.addWidget(button_container, 0, Qt.AlignmentFlag.AlignLeft)

                # Add model name label with elision
                label = QLabel(model_name)
                label.setStyleSheet(
                    "text-align: left; padding-left: 5px;"
                )  # Add left padding
                label.setMinimumWidth(50)  # Ensure minimum text visibility
                label.setMaximumWidth(300)  # Limit maximum width
                layout.addWidget(
                    label, 1, Qt.AlignmentFlag.AlignLeft
                )  # Use stretch factor 1 to fill remaining space

                # Add default model button
                default_btn = QPushButton()
                default_btn.setFixedSize(24, 24)
                default_btn.setObjectName("modelDefaultButton")
                default_btn.setProperty("model_name", model_name)
                default_btn.setProperty("is_default", model_name == self.default_model)
                default_btn.setIcon(QIcon("icons/default.png"))
                default_btn.clicked.connect(
                    lambda checked, m=model_name, b=default_btn: self.handle_default_model_click(
                        m, b
                    )
                )
                button_layout.addWidget(default_btn)

                # Add camera icon
                camera_btn = QPushButton()
                camera_btn.setFixedSize(24, 24)
                camera_btn.setObjectName("modelCameraButton")
                camera_btn.setProperty("model_name", model_name)
                camera_btn.setProperty(
                    "enabled_state", base_model in self.vision_capable_models
                )
                self.update_camera_button_style(camera_btn)
                camera_btn.clicked.connect(
                    lambda checked, m=model_name, b=camera_btn: self.handle_model_camera_click(
                        m, b
                    )
                )
                button_layout.addWidget(camera_btn)

                # Set the custom widget as the item's widget
                item.setSizeHint(widget.sizeHint())
                self.model_list.setItemWidget(item, widget)

                # Update default button style
                self.update_default_button_style(default_btn)

        except requests.exceptions.ConnectionError:
            self.show_error_message(
                "Connection Error",
                "Unable to connect to the Ollama server. Please make sure Ollama is running and try again.",
            )
        except Exception as e:
            self.show_error_message(
                "Error", f"An error occurred while loading models: {str(e)}"
            )

    def handle_model_selection(self, item):
        """Handle double-click to select a model."""
        if item:
            print(f"Selected model: {self.selected_model}")

    def update_camera_button_style(self, button):
        """Update the camera button style based on its enabled state."""
        is_enabled = button.property("enabled_state")
        if is_enabled:
            button.setIcon(QIcon("icons/vision.png"))
        else:
            button.setIcon(QIcon("icons/vision_disabled.png"))

    def handle_model_camera_click(self, model_name, button):
        """Toggle vision capability for a model and all its variants."""
        base_name = self.get_base_model_name(model_name)
        current_state = button.property("enabled_state")
        new_state = not current_state

        # Update the set of vision-capable models using base name
        if new_state:
            self.vision_capable_models.add(base_name)
        else:
            self.vision_capable_models.discard(base_name)

        # Update all related model buttons
        for index in range(self.model_list.count()):
            item = self.model_list.item(index)
            widget = self.model_list.itemWidget(item)
            if widget:
                related_camera_btn = widget.findChild(QPushButton, "modelCameraButton")
                if related_camera_btn:
                    related_model = related_camera_btn.property("model_name")
                    if self.get_base_model_name(related_model) == base_name:
                        # Update the button state
                        related_camera_btn.setProperty("enabled_state", new_state)
                        self.update_camera_button_style(related_camera_btn)

    def filter_models(self, text):
        """Filter the model list based on the search text."""
        for index in range(self.model_list.count()):
            item = self.model_list.item(index)
            item.setHidden(text.lower() not in item.text().lower())

    def get_selected_model_name(self, item):
        # Retrieve the custom widget associated with the item
        custom_widget = self.model_list.itemWidget(item)
        if not custom_widget:
            return None

        # Find the QLabel within the custom widget
        label = custom_widget.findChild(QLabel)
        if label:
            return label.text()

        return None
    
    def load_settings(self):
        """Load settings using settings_manager"""
        self.settings = load_settings_from_file()
        
        # Update instance variables
        self.default_model = self.settings.get("default_model")
        self.temperature = self.settings.get("temperature")
        self.context_size = self.settings.get("context_size")
        self.system_prompt = self.settings.get("system_prompt")
        self.ollama_url = self.settings.get("ollama_url")
        self.vision_capable_models = set(self.settings.get("vision_capable_models", []))
        
        # Update UI elements
        self.temperature_input.setText(str(self.temperature) if self.temperature is not None else "")
        self.context_size_input.setText(str(self.context_size) if self.context_size is not None else "")
        self.system_prompt_input.setPlainText(self.system_prompt)
        self.ollama_url_input.setText(self.ollama_url)

        return self.settings

    def apply_settings(self):
        """Save settings using settings_manager"""
        # Get values from UI
        temperature = self.temperature_input.text()
        context_size = self.context_size_input.text()
        
        # Validate temperature
        try:
            self.temperature = float(temperature)
            self.temperature = max(0.0, min(self.temperature, 1.0))
        except ValueError:
            self.temperature = None

        # Validate context size
        try:
            self.context_size = int(context_size)
            self.context_size = max(0, min(self.context_size, 65536))
        except ValueError:
            self.context_size = None

        # Update settings
        self.system_prompt = self.system_prompt_input.toPlainText()
        self.ollama_url = self.ollama_url_input.text()

        # Update the vision model list
        self.vision_capable_models = set(self.vision_capable_models)

        # Save settings using settings_manager
        save_settings_to_file({
            "ollama_url": self.ollama_url,
            "default_model": self.selected_model if self.selected_model else self.default_model,
            "temperature": self.temperature,
            "context_size": self.context_size,
            "system_prompt": self.system_prompt,
            "vision_capable_models": list(self.vision_capable_models),
        })

        self.load_settings()
        self.toggle_settings()

    def toggle_settings(self):
        if self.is_settings_visible:
            self.stacked_widget.setCurrentWidget(self.chat_interface)
            self.settings_btn.setIcon(QIcon("icons/settings_icon.png"))
            self.is_settings_visible = False
        else:
            self.stacked_widget.setCurrentWidget(self.settings_interface)
            self.settings_btn.setIcon(QIcon.fromTheme("go-previous"))
            self.is_settings_visible = True

            # Load settings
            self.load_settings()

            # Reload the model list
            self.model_list.clear()
            self.load_models()

    def cancel_settings(self):
        self.toggle_settings()

    def send_or_stop_message(self):
        if self.is_receiving:
            self.stop_receiving()
        else:
            self.send_message()

    def edit_message(self, index):
        """Start editing a message at the given index."""

        # +1 to skip system message
        index += 1

        print(f"Starting edit for message at index {index}")  # Debug print
  
  
        if index >= len(self.message_history):
            print(
                f"Invalid index {index} for message history of length {len(self.message_history)}"
            )
            return

        message = self.message_history[index]
        if message["role"] != "user":
            print(f"Cannot edit non-user message with role {message['role']}")
            return

        # Set the edit index
        self.edit_index = index

        # Set the message content in the input field
        self.input_field.setPlainText(message["content"])

        # Focus the input field
        self.input_field.setFocus()

        # Select all text
        cursor = self.input_field.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.input_field.setTextCursor(cursor)
        # self.input_field.selectAll()

        print(f"Edit mode activated for message: {message['content']}")  # Debug print

    def send_message(self):
        """Handle sending or editing a message."""
        message = self.input_field.toPlainText().strip()
        
        # Handle special commands
        if message.lower() == "/quit":
            self.close()
            return
        elif message.lower() == "/clear":
            self.clear_chat()
            return

        # Don't send if there's no message and no screenshots
        if not message and not self.selected_screenshots:
            return

        if self.edit_index is not None:
            print(f"Submitting edit for message at index {self.edit_index}")
            self.submit_edit(message)
        else:
            print("Adding new message")
            self.add_new_message(message)

        self.reset_input_area()

        # Return focus to input field and activate window
        QTimer.singleShot(100, lambda: self.input_field.setFocus(Qt.FocusReason.OtherFocusReason))
        QTimer.singleShot(100, self.activateWindow)

        # Print the entire message history
        print("\nMessage History:")
        for idx, msg in enumerate(self.message_history):
            print(f"{idx}. Role: {msg['role']}")
            print(f"   Content: {msg['content']}")
            if "model" in msg:
                print(f"   Model: {msg['model']}")
            if "thumbnail_html" in msg and msg["thumbnail_html"]:
                print(f"   Has thumbnail: Yes")
            print()

        # Always send to Ollama for new messages (not edits)
        if self.edit_index is None:
            self.send_to_ollama()

    def submit_edit(self, new_content):
        """Submit the edited message and rebuild the chat content."""
        if self.edit_index is None:
            print("No message selected for editing.")
            return

        print(
            f"Before edit: {len(self.message_history)} messages, {len(self.chat_content)} chat items"
        )

        # Get the original message to preserve its thumbnail_html
        original_message = self.message_history[self.edit_index]
        thumbnail_html = original_message.get("thumbnail_html", "")

        # Replace the content of the message being edited
        self.message_history[self.edit_index] = {
            "role": "user",  # Ensure we set the role
            "content": new_content,
            "thumbnail_html": thumbnail_html,
            "model": original_message.get(
                "model", self.default_model
            ),  # Preserve the model
        }

        # Remove all messages after the edited one
        del self.chat_content[self.edit_index :]  # Also clean up chat_content
        del self.message_history[self.edit_index + 1 :]

        # Update chat_content to match message_history exactly
        self.rebuild_chat_content()  # Use rebuild instead of manually appending

        print(
            f"After edit: {len(self.message_history)} messages, {len(self.chat_content)} chat items"
        )

        # Reset the edit index
        self.edit_index = None

    def rebuild_chat_content(self):
        """Reconstruct chat_content based on message_history."""
        self.chat_content = []  # Clear existing chat content
        if DEBUG:
            print("Rebuilding chat_content from message_history.")  # Debug print

        for idx, message in enumerate(self.message_history):
            # Skip system messages
            if message["role"] == "system":
                continue
                
            if message["role"] == "user":
                sender = "You"
            else:
                # Use the stored model name if available, otherwise use current model
                sender = message.get("model", self.default_model)

            content = message["content"]
            thumbnail_html = message.get("thumbnail_html", "")  # Get thumbnail_html if it exists
            self.chat_content.append((sender, content, thumbnail_html))
            if DEBUG:
                print(f"Added message {idx}: {sender} - {content[:50]}... (Thumbnail: {'Yes' if thumbnail_html else 'No'})")  # Debug print

        # Update the chat display to reflect changes
        self.update_chat_display()
        if DEBUG:
            print("chat_content rebuild complete.")  # Debug print

    def add_new_message(self, message):
        """Add a new user message to the chat."""
        thumbnail_html = ""
        
        # Generate thumbnail HTML for all screenshots
        if self.selected_screenshots and self.screenshot_btn.isVisible():
            for screenshot in self.selected_screenshots:
                thumbnail = screenshot.scaled(
                    self.thumbnail_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                byte_array = QByteArray()
                buffer = QBuffer(byte_array)
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                thumbnail.save(buffer, "PNG")
                thumbnail_base64 = byte_array.toBase64().data().decode()
                thumbnail_html += f'<img src="data:image/png;base64,{thumbnail_base64}" alt="Screenshot thumbnail" style="max-width: 200px; max-height: 200px; margin-right: 10px; vertical-align: middle;">'

        # Extract model if message starts with @
        model_to_use = self.active_model or self.default_model
        if message.startswith("@"):
            parts = message.split(" ", 1)
            if len(parts) > 0:
                model_name = parts[0][1:]  # Remove @ symbol
                if model_name in load_ollama_models():  # Verify it's a valid model
                    model_to_use = model_name
                    self.active_model = model_name  # Set the active model
                    message = parts[1] if len(parts) > 1 else ""

        # Add the message to message_history with the thumbnail_html and model
        self.message_history.append({
            "role": "user",
            "content": message,
            "thumbnail_html": thumbnail_html,
            "model": model_to_use,
        })

        # Add message and thumbnails to chat display in a single entry
        self.add_message_to_chat("You", message, thumbnail_html)

    def send_to_ollama(self, regenerate_index=None):
        """Send message to Ollama."""
        if regenerate_index is not None:
            messages_to_send = self.message_history[:regenerate_index]
        else:
            message = self.input_field.toPlainText().strip()
            #if not message and not self.selected_screenshots:
            #    return

            # Don't add a new message here - it's already handled in add_new_message
            messages_to_send = self.message_history

            # Clear input and screenshots after getting the message
            self.input_field.clear()
            self.selected_screenshots.clear()
            self.update_thumbnails()

        # Get the current model
        model_to_use = self.selected_model if self.selected_model else self.default_model

        # Extract screenshots from the last user message
        screenshots = []
        if not regenerate_index:  # Only for new messages
            for msg in reversed(messages_to_send):
                if msg.get("role") == "user" and msg.get("thumbnail_html"):
                    try:
                        # Extract all base64 image data
                        import re
                        matches = re.finditer(r'src="data:image/png;base64,([^"]+)"', msg["thumbnail_html"])
                        for match in matches:
                            base64_data = match.group(1)
                            img_data = base64.b64decode(base64_data)
                            qimage = QImage()
                            qimage.loadFromData(img_data)
                            screenshots.append(qimage)
                        if screenshots:  # If we found screenshots, break
                            break
                    except Exception as e:
                        print(f"Error processing screenshots: {e}")

        # Create and start Ollama thread
        self.ollama_thread = OllamaThread(
            messages_to_send,
            screenshots,
            model_to_use,
            temperature=self.temperature,
            context_size=self.context_size,
        )

        # Connect signals and start thread
        if regenerate_index is not None:
            self.ollama_thread.response_chunk_ready.connect(
                lambda chunk: self.handle_response_chunk(chunk, regenerate_index)
            )
            self.ollama_thread.response_complete.connect(
                lambda: self.handle_response_complete(regenerate_index)
            )
        else:
            self.ollama_thread.response_chunk_ready.connect(self.handle_response_chunk)
            self.ollama_thread.response_complete.connect(self.handle_response_complete)

        self.ollama_thread.debug_screenshot_ready.connect(self.handle_debug_screenshot)
        self.ollama_thread.start()

        # Update UI state
        self.is_receiving = True
        self.update_gradient_state()
        self.send_btn.setIcon(QIcon("icons/stop.png"))
        self.send_btn.setObjectName("stopButton")

    def add_message_to_chat(self, sender, message, thumbnail_html=""):
        # Use the original model name if it exists in the message history
        if sender == "ollama" and self.message_history:
            # Find the corresponding message in history
            message_index = len(self.chat_content)
            if message_index < len(self.message_history):
                # If this message has a specific model stored in history, use that
                if "model" in self.message_history[message_index]:
                    display_sender = self.message_history[message_index]["model"]
                else:
                    # Otherwise use the current model
                    display_sender = self.default_model
            else:
                display_sender = self.default_model
        else:
            display_sender = sender

        self.chat_content.append((display_sender, message, thumbnail_html))
        self.update_chat_display()

    def update_chat_display(self):
        chat_content = []
        for item in self.chat_content:
            sender = item[0] if item[0] is not None else ""
            message = item[1] if item[1] is not None else ""
            thumbnail_html = item[2] if len(item) > 2 and item[2] is not None else ""
            chat_content.append(
                {"sender": sender, "content": message, "thumbnail": thumbnail_html}
            )

        # Escape the chat content for JavaScript
        escaped_content = json.dumps(chat_content)

        # Update the chat container content
        self.chat_display.page().runJavaScript(
            f"""
            try {{
                updateChatContent({escaped_content});
            }} catch (error) {{
                console.error('Error updating chat content:', error);
            }}
        """
        )

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Up:
            self.show_previous_message()
        elif event.key() == Qt.Key.Key_Down:
            self.show_next_message()
        elif self.suggestion_list.isVisible():
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self.suggestion_list.setFocus()
                self.suggestion_list.keyPressEvent(event)
                return
            elif event.key() == Qt.Key.Key_Enter or event.key() == Qt.Key.Key_Return:
                current_item = self.suggestion_list.currentItem()
                if current_item:
                    self.insert_suggestion(current_item)
                return
        super().keyPressEvent(event)

    def show_previous_message(self):
        """Navigate to the previous user message for editing."""
        if not self.message_history:
            return

        if self.edit_index is None:
            self.edit_index = len(self.message_history) - 1
        elif self.edit_index > 0:
            self.edit_index -= 1

        # Ensure the selected message is from the user
        while (
            self.edit_index >= 0
            and self.message_history[self.edit_index]["role"] != "user"
        ):
            self.edit_index -= 1

        if self.edit_index >= 0:
            message = self.message_history[self.edit_index]
            self.input_field.setPlainText(message["content"])  # Change from setText
            self.input_field.selectAll()
            print(f"Editing message at index {self.edit_index}")  # Debug print
        else:
            # No more user messages to edit
            self.edit_index = None
            self.input_field.clear()
            print("No previous user messages to edit.")  # Debug print

    def show_next_message(self):
        """Navigate to the next user message for editing."""
        if not self.message_history or self.edit_index is None:
            return

        if self.edit_index < len(self.message_history) - 1:
            self.edit_index += 1
            message = self.message_history[self.edit_index]
            if message["role"] == "user":
                self.input_field.setPlainText(message["content"])  # Change from setText
                self.input_field.selectAll()
                print(f"Editing message at index {self.edit_index}")  # Debug print
            else:
                # Skip assistant messages
                print("Cannot edit assistant messages.")  # Debug print
                self.show_next_message()
        else:
            # Reached the end of messages
            self.edit_index = None
            self.input_field.clear()
            print("No more user messages to edit.")  # Debug print

        # Move cursor to end of text
        cursor = self.input_field.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.input_field.setTextCursor(cursor)

    def toggle_screenshot(self):
        if self.selected_screenshot:
            self.remove_screenshot()
        else:
            self.take_screenshot()

    def remove_screenshot(self):
        self.selected_screenshot = None
        self.thumbnail_container.hide()
        self.screenshot_btn.setStyleSheet("")  # Reset to default style
        self.input_field.setPlaceholderText("Type your message...")

    def take_screenshot(self):
        self.hide()
        QTimer.singleShot(100, self._delayed_screenshot)

    def _delayed_screenshot(self):
        print("Starting delayed screenshot process")
        
        # Start with the screen containing the cursor
        cursor_pos = QCursor.pos()
        current_screen = None
        for screen in QApplication.screens():
            if screen.geometry().contains(cursor_pos):
                current_screen = screen
                break
        
        if not current_screen:
            current_screen = QApplication.primaryScreen()
        
        # Take initial screenshot of current screen
        screen_geometry = current_screen.geometry()
        screenshot = current_screen.grabWindow(
            0,
            0,  # Use local coordinates
            0,
            screen_geometry.width(),
            screen_geometry.height()
        )
        
        self.screenshot_selector = ScreenshotSelector(screenshot)
        self.screenshot_selector.screenshot_taken.connect(self.handle_screenshot)
        self.screenshot_selector.setGeometry(screen_geometry)
        self.screenshot_selector.showFullScreen()

        self.check_screenshot_timer = QTimer(self)
        self.check_screenshot_timer.timeout.connect(self._check_screenshot_selector)
        self.check_screenshot_timer.start(100)

    def _check_screenshot_selector(self):
        if not self.screenshot_selector.isVisible():
            print("Screenshot selector is no longer visible")  # Debug print
            self.check_screenshot_timer.stop()
            QTimer.singleShot(100, self.show)  # Delay showing the main window

    def handle_screenshot(self, screenshot):
        """Handle new screenshot addition."""
        if len(self.selected_screenshots) >= self.MAX_SCREENSHOTS:
            self.show_error_message("Maximum Screenshots", 
                                  f"Maximum of {self.MAX_SCREENSHOTS} screenshots allowed.")
            return

        # Process the screenshot
        processed_screenshot = process_image(screenshot)
        self.selected_screenshots.append(processed_screenshot)
        
        # Update thumbnails
        self.update_thumbnails()
        
        self.show()
        QTimer.singleShot(200, self._post_screenshot_actions)

    def update_thumbnails(self):
        """Update all thumbnail displays."""
        for i, container in enumerate(self.thumbnail_containers):
            if i < len(self.selected_screenshots):
                # Show and update container
                self.update_single_thumbnail(container, self.selected_screenshots[i], i)
                container.show()
                # Connect delete button if not already connected
                if not container.delete_btn.receivers(container.delete_btn.clicked):
                    container.delete_btn.clicked.connect(lambda checked, idx=i: self.remove_screenshot(idx))
            else:
                container.hide()

        # Update input layout
        self.update_input_layout()

    def update_single_thumbnail(self, container, screenshot, index):
        """Update a single thumbnail container with the screenshot."""
        max_size = self.THUMBNAIL_INNER_SIZE
        original_size = screenshot.size()
        scaled_size = original_size.scaled(max_size, max_size, Qt.AspectRatioMode.KeepAspectRatio)
        
        thumbnail = screenshot.scaled(
            scaled_size.width(),
            scaled_size.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        display_pixmap = QPixmap(max_size, max_size)
        display_pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(display_pixmap)
        x = (max_size - scaled_size.width()) // 2
        y = (max_size - scaled_size.height()) // 2
        painter.drawImage(x, y, thumbnail)
        painter.end()
        
        container.thumbnail_label.setPixmap(display_pixmap)

    def remove_screenshot(self, index):
        """Remove screenshot at specified index."""
        if 0 <= index < len(self.selected_screenshots):
            del self.selected_screenshots[index]
            self.update_thumbnails()

        if not self.selected_screenshots:
            self.screenshot_btn.setStyleSheet("")
            self.input_field.setPlaceholderText("Type your message...")

    def update_input_layout(self):
        """Update input layout with current thumbnails."""
        # Remove existing thumbnails from layout
        for container in self.thumbnail_containers:
            self.input_layout.removeWidget(container)

        # Add visible thumbnails back to layout
        for i, container in enumerate(self.thumbnail_containers):
            if i < len(self.selected_screenshots):
                self.input_layout.insertWidget(2 + i, container)

    def _post_screenshot_actions(self):
        print("Performing post-screenshot actions")  # Debug print

        # Update the UI to indicate a screenshot was taken
        self.input_field.setPlaceholderText("Screenshot taken. Type your message...")

        # Force focus to input field
        self.input_field.setFocus(Qt.FocusReason.OtherFocusReason)
        self.activateWindow()  # Activate the window to ensure it can receive focus

        print("Post-screenshot actions completed")  # Debug print

    def handle_response_chunk(self, chunk, update_index=None):
        """
        Handle response chunks from Ollama.
        
        Args:
            chunk (str): The response chunk from Ollama
            update_index (int, optional): If provided, updates the message at this index
        """
        self.current_response += chunk
        if self.current_response.strip():
            if update_index is not None:
                # Update specific message for regeneration
                self.message_history[update_index]["content"] = self.current_response
                self.rebuild_chat_content()
            else:
                # Get the current model being used
                current_model = self.active_model or self.default_model
                # Update last message for new responses
                self.update_last_message(current_model, self.current_response)

        # Trigger smooth scroll after updating the content
        self.chat_display.page().runJavaScript("smoothScrollToBottom();")

    def handle_response_complete(self, update_index=None):
        """
        Handle completion of Ollama response.
        
        Args:
            update_index (int, optional): If provided, updates the message at this index
        """
        if not self.current_response:
            self.current_response = "No response received from Ollama."

        # Get the current model being used
        current_model = self.active_model or self.default_model            

        if update_index is not None:
            # Update regenerated message
            self.message_history[update_index].update({
                "content": self.current_response,
                "model": current_model
            })
            self.rebuild_chat_content()
        else:
            # Add new message to history
            self.message_history.append({
                "role": "assistant",
                "content": self.current_response,
                "model": current_model
            })
            # No need to call add_message_to_chat since rebuild_chat_content will handle it
            self.rebuild_chat_content()

        # Reset state
        self.current_response = ""
        self.current_response_model = None
        self.is_receiving = False
        self.update_gradient_state()
        self.send_btn.setIcon(QIcon("icons/send.png"))
        self.send_btn.setObjectName("sendButton")

    def update_last_message(self, sender, content):
        if DEBUG:
            print(f"Updating last message: {sender} - {content}")
        # Only update if we have actual content
        if content.strip():
            if self.chat_content and self.chat_content[-1][0] == sender:
                # Update existing message
                self.chat_content[-1] = (
                    sender,
                    content,
                    self.chat_content[-1][2],
                )  # Preserve thumbnail
            else:
                # Add new message
                self.chat_content.append(
                    (sender, content, "")
                )  # Empty thumbnail for new message
            self.update_chat_display()

    def clear_chat(self):
        """Clear the chat history and saved file."""
        self.message_history = []
        self.chat_content = []
        self.update_chat_display()
        
        # Clear saved chat file
        chat_file = os.path.join(os.path.expanduser("~"), ".pixelllama", "chat_history.json")
        if os.path.exists(chat_file):
            try:
                os.remove(chat_file)
            except Exception as e:
                print(f"Error removing chat history file: {e}")

    def position_window(self):
        screen = QApplication.primaryScreen().availableGeometry()
        padding = 2  # Adjust this value to change the padding
        self.setGeometry(
            screen.width() - self.compact_size.width() - padding,
            screen.height() - self.compact_size.height() - padding,
            self.compact_size.width(),
            self.compact_size.height(),
        )

    def toggle_window_size(self):
        screen = QApplication.primaryScreen().availableGeometry()
        current_rect = self.geometry()

        if self.is_expanded:
            self.expanded_size = current_rect.size()
            new_size = self.compact_size
            self.toggle_btn.setIcon(
                QIcon.fromTheme("zoom-in")
            )  # Change to zoom-in icon when collapsing
        else:
            self.compact_size = current_rect.size()
            new_size = self.expanded_size
            self.toggle_btn.setIcon(
                QIcon.fromTheme("zoom-out")
            )  # Change to zoom-out icon when expanding

        new_x = (
            screen.right() - new_size.width() - (screen.right() - current_rect.right())
        )
        new_y = (
            screen.bottom()
            - new_size.height()
            - (screen.bottom() - current_rect.bottom())
        )

        new_rect = QRect(new_x, new_y, new_size.width() + 1, new_size.height() + 1)
        self.setGeometry(new_rect)
        self.is_expanded = not self.is_expanded

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_input_position()
        self.update_vertical_button_position()  

    def update_input_position(self):
        # Remove the button positioning code since it's handled by the layout
        input_height = 50  # Match the fixed height set in initUI
        new_y = self.height() - input_height - 20  # 20 px padding from bottom

        # Find the widget that contains the input_layout
        input_container = self.findChild(QWidget, "input_container")
        if input_container:
            input_container.setGeometry(20, new_y, self.width() - 40, input_height)

    def reset_input_area(self):
        self.input_field.clear()
        if self.selected_screenshot:
            self.remove_screenshot()

    def handle_debug_screenshot(self, processed_image):
        self.debug_screenshot = processed_image
        if DEBUG:
            self.save_debug_screenshot()

    def save_debug_screenshot(self):
        if self.debug_screenshot:
            debug_folder = "debug_screenshots"
            os.makedirs(debug_folder, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"processed_screenshot_{timestamp}.png"
            filepath = os.path.join(debug_folder, filename)

            self.debug_screenshot.save(filepath, "PNG")
            print(f"Processed debug screenshot saved: {filepath}")
            self.debug_screenshot = None  # Clear the debug screenshot

    def stop_receiving(self):
        if self.ollama_thread.isRunning():
            self.ollama_thread.terminate()
            self.ollama_thread.wait()
        self.handle_response_complete()
        self.is_receiving = False
        self.send_btn.setIcon(QIcon("icons/send.png"))
        self.send_btn.setObjectName("sendButton")

    def initialize_chat_display(self):
        """Initialize the chat display with the HTML template."""
        html_path = os.path.join(os.path.dirname(__file__), "html/chat_template.html")
        with open(html_path, "r") as file:
            initial_html = file.read()

        # Read and encode the app icon
        icon_path = os.path.join(os.path.dirname(__file__), "icons/background.png")
        with open(icon_path, "rb") as icon_file:
            icon_data = icon_file.read()
            icon_base64 = base64.b64encode(icon_data).decode("utf-8")

        # Replace the placeholder with the base64-encoded image
        initial_html = initial_html.replace("{{APP_ICON_BASE64}}", icon_base64)

        # Load the HTML and wait for it to finish before updating chat content
        self.chat_display.loadFinished.connect(self._on_chat_display_loaded)
        self.chat_display.setHtml(initial_html)

    def _on_chat_display_loaded(self, ok):
        """Called when the chat display HTML has finished loading."""
        if ok:
            # Set up the JavaScript bridge
            js = """
            new QWebChannel(qt.webChannelTransport, function(channel) {
                window.bridge = channel.objects.bridge;
                window.qt_bridge = {
                    regenerateMessage: function(index) {
                        if (window.bridge) {
                            window.bridge.regenerateMessage(index);
                        } else {
                            console.error('Bridge not initialized');
                        }
                    },
                    editMessage: function(index) {
                        if (window.bridge) {
                            window.bridge.editMessage(index);
                        } else {
                            console.error('Bridge not initialized');
                        }
                    }
                };
            });
            """
            self.chat_display.page().runJavaScript(js)
            
            # Update the chat display with any existing content
            self.update_chat_display()

    def terminate_application(self):
        """Save chat history and terminate the application."""
        self.save_chat_history()  
        QApplication.quit()

    def create_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icons/app_icon.png"))

        # Create the menu with custom styling
        tray_menu = QMenu()
        tray_menu.setStyleSheet(
            """
            QMenu {
                background-color: #2f3136;
                border: 1px solid #202225;
                border-radius: 4px;
                padding: 4px 0px;
            }
            QMenu::item {
                color: #dcddde;
                padding: 4px 8px;
                font-size: 14px;
                margin: 0px;
            }
            QMenu::item:selected {
                background-color: #7289da;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background: #40444b;
                margin: 4px 0px;
            }
        """
        )

        show_hide_action = tray_menu.addAction("Show/Hide")
        quit_action = tray_menu.addAction("Quit")

        # Connect actions
        show_hide_action.triggered.connect(self.toggle_visibility)
        quit_action.triggered.connect(self.terminate_application)

        # Override the menu's show event to position it above the tray icon
        def show_menu():
            # Get the geometry of the system tray icon
            geometry = self.tray_icon.geometry()
            # Calculate the position to show the menu above the tray icon
            point = geometry.topLeft()
            # Adjust the position to account for menu height
            point.setY(point.y() - tray_menu.sizeHint().height())
            tray_menu.popup(point)

        # Replace the default context menu with our custom positioned one
        self.tray_icon.activated.connect(
            lambda reason: (
                show_menu()
                if reason == QSystemTrayIcon.ActivationReason.Context
                else self.on_tray_icon_activated(reason)
            )
        )

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visibility()

    def add_vertical_button(self):
        # Check if the button already exists
        if hasattr(self, "vertical_button") and self.vertical_button is not None:
            return  # Exit if the button already exists

        self.vertical_button = QPushButton(self)
        self.vertical_button.setFixedWidth(15)  # Set only the width
        # Instead, add object name
        self.vertical_button.setObjectName("verticalButton")

        # Create and set the initial arrow icon
        self.right_arrow_icon = QIcon("icons/right_arrow.png")
        self.left_arrow_icon = QIcon("icons/left_arrow.png")
        self.vertical_button.setIcon(self.right_arrow_icon)
        self.vertical_button.setIconSize(QSize(24, 24))  # Adjust size as needed

        self.vertical_button.clicked.connect(self.toggle_sidebar)

        # Position the button
        self.update_vertical_button_position()

    def update_vertical_button_position(self):
        if self.sidebar_expanded:
            self.vertical_button.setGeometry(
                0, 128, self.vertical_button.width(), self.height() - 256
            )
        else:
            # Set a reduced height for the button when the sidebar is collapsed
            collapsed_height = 96  # Adjust this value as needed
            new_y = (self.height() - collapsed_height) // 2
            self.vertical_button.setGeometry(
                0, new_y, self.vertical_button.width(), collapsed_height
            )
        self.vertical_button.raise_()  # Ensure the button is on top

    def toggle_sidebar(self):
        # Get the current screen's geometry
        current_pos = self.geometry().center()
        current_screen = None
        
        # Find the current screen
        for screen in QApplication.screens():
            if screen.geometry().contains(current_pos):
                current_screen = screen
                break
        
        if not current_screen:
            current_screen = QApplication.primaryScreen()
        
        screen = current_screen.availableGeometry()

        if (
            self.animation
            and self.animation.state() == QPropertyAnimation.State.Running
        ):
            self.animation.stop()

        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(100)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        current_geometry = self.geometry()

        if self.sidebar_expanded:
            self.setMinimumSize(64, 152)
            # Collapse the sidebar - reduce width and height
            self.previous_geometry = current_geometry
            collapsed_width = self.vertical_button.width() + 4
            collapsed_height = 96  # Reduced height when collapsed

            # Calculate new position to center vertically on the current screen
            new_y = screen.y() + (screen.height() - collapsed_height) // 2
            new_x = int(screen.right() - collapsed_width * 0.75)

            new_rect = QRect(new_x, new_y, collapsed_width, collapsed_height)
            self.animation.setEndValue(new_rect)
            self.sidebar_expanded = False
            self.vertical_button.setIcon(self.left_arrow_icon)

            # Hide all controls except the vertical button
            self.chat_display.hide()
            self.input_field.hide()
            self.screenshot_btn.hide()
            self.send_btn.hide()
            self.clear_btn.hide()
            self.settings_btn.hide()
            self.close_btn.hide()
            self.toggle_btn.hide()
            self.monitor_btn.hide()
        else:
            self.setMinimumSize(300, 400)
            # Expand the sidebar - restore previous size and position
            if self.previous_geometry:
                self.animation.setEndValue(self.previous_geometry)
            self.sidebar_expanded = True
            self.vertical_button.setIcon(self.right_arrow_icon)

            # Show all controls
            self.chat_display.show()
            self.input_field.show()
            self.screenshot_btn.show()
            self.send_btn.show()
            self.clear_btn.show()
            self.settings_btn.show()
            self.close_btn.show()
            self.toggle_btn.show()
            self.monitor_btn.show()
            
        self.animation.finished.connect(self.update_vertical_button_position)
        self.animation.start()

    def paintEvent(self, event):
        """Override paintEvent to clip the drawing area to the app's shape."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Get the rectangle dimensions
        rect = self.rect()
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()

        # Define the clipping path to match the app's shape
        path = QPainterPath()
        path.addRoundedRect(x, y, w, h, 20, 20)  # Match the border-radius of the app

        # Set the clipping path
        painter.setClipPath(path)

        # Call the base class paintEvent to ensure default painting
        super().paintEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_start_position = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging:
            new_position = event.globalPosition().toPoint() - self.drag_start_position
            if not self.sidebar_expanded:
                # Only allow vertical movement when sidebar is contracted
                new_position.setX(self.geometry().x())
            self.move(new_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            event.accept()

    def show_error_message(self, title, message):
        error_box = QMessageBox(self)
        error_box.setIcon(QMessageBox.Icon.Critical)
        error_box.setWindowTitle(title)
        error_box.setText(message)
        error_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        error_box.exec()

    def update_suggestions(self):
        # Get the current text and cursor position
        text = self.input_field.toPlainText()
        cursor = self.input_field.textCursor()
        position = cursor.position()

        # Find the current line
        text_before_cursor = text[:position]
        current_line = text_before_cursor.split("\n")[-1]

        # Only process if line starts with @ and provider is online
        if current_line.startswith("@") and self.provider_online:
            # Check if cursor is after a space or model name
            after_at = current_line[1:]
            if " " in after_at:
                self.suggestion_list.hide()
                return

            # Debounce the suggestion update using QTimer
            if hasattr(self, "_suggestion_timer"):
                self._suggestion_timer.stop()
            else:
                self._suggestion_timer = QTimer()
                self._suggestion_timer.setSingleShot(True)
                self._suggestion_timer.timeout.connect(self._update_suggestion_list)

            # Store current search text
            self._current_search = current_line[1:].lower()
            self._suggestion_timer.start(150)  # Delay of 150ms
        else:
            self.suggestion_list.hide()

    def _update_suggestion_list(self):
        """Actual update of suggestion list with debouncing."""
        self.suggestion_list.clear()
        filtered_models = [
            model for model in self.model_names if self._current_search in model.lower()
        ]

        if filtered_models:
            self.suggestion_list.addItems(filtered_models)
            self.suggestion_list.show()
            self.position_suggestion_list()
        else:
            self.suggestion_list.hide()

    def position_suggestion_list(self):
        # Get the input field's geometry in global coordinates
        input_rect = self.input_field.geometry()
        global_pos = self.input_field.mapToGlobal(input_rect.topLeft())

        # Calculate the height based on the number of items (with a maximum)
        item_height = self.suggestion_list.sizeHintForRow(
            0
        )  # Get actual height of an item
        num_items = min(self.suggestion_list.count(), 10)  # Maximum 10 items shown
        list_height = num_items * item_height + 15

        # Position the list above the input field, aligned with its left edge
        # Account for any padding or margins in the input layout
        x_position = global_pos.x()  # + self.input_layout.contentsMargins().left()
        y_position = global_pos.y() - list_height

        # Set size and position
        available_width = (
            self.input_field.width() - self.input_layout.contentsMargins().left()
        )
        self.suggestion_list.setFixedSize(available_width, list_height)
        self.suggestion_list.move(x_position, y_position)

        # Disable horizontal scrollbar and set text elision
        self.suggestion_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.suggestion_list.setTextElideMode(Qt.TextElideMode.ElideRight)

        # Add some styling to make it look better
        self.suggestion_list.setObjectName("suggestionList")

    def insert_suggestion(self, item):
        # Get current text and cursor position
        current_text = self.input_field.toPlainText()
        cursor = self.input_field.textCursor()
        position = cursor.position()

        # Find the @ before the cursor
        text_before_cursor = current_text[:position]
        at_index = text_before_cursor.rfind("@")

        if at_index != -1:
            # Find the next space after the cursor position, or end of text if no space
            text_after_at = current_text[at_index:]
            space_index = text_after_at.find(" ")
            if space_index == -1:
                # No space found, replace until end of text
                new_text = current_text[:at_index] + f"@{item.text()} "
                cursor_position = len(new_text)
            else:
                # Replace only the text between @ and space
                absolute_space_index = at_index + space_index
                new_text = (
                    current_text[:at_index]
                    + f"@{item.text()}"
                    + current_text[absolute_space_index:]
                )
                cursor_position = at_index + len(f"@{item.text()}")

            # Update text and cursor position
            self.input_field.setText(new_text)
            cursor.setPosition(cursor_position)
            self.input_field.setTextCursor(cursor)

        self.suggestion_list.hide()
        self.input_field.setFocus()

    def eventFilter(self, obj, event):
        if obj is self.input_field:
            if event.type() == QEvent.Type.KeyPress:
                if self.suggestion_list.isVisible():
                    if event.key() == Qt.Key.Key_Up:
                        self.handle_suggestion_navigation(event.key())
                        return True
                    elif event.key() == Qt.Key.Key_Down:
                        self.handle_suggestion_navigation(event.key())
                        return True
                    elif event.key() == Qt.Key.Key_Return:
                        if self.suggestion_list.currentItem():
                            self.insert_suggestion(self.suggestion_list.currentItem())
                            return True
                    elif event.key() == Qt.Key.Key_Escape:
                        self.suggestion_list.hide()
                        return True

                # Handle Image paste
                if event.matches(QKeySequence.StandardKey.Paste):
                    clipboard = QApplication.clipboard()
                    mime_data = clipboard.mimeData()
                    
                    if mime_data.hasImage():
                        image = QImage(mime_data.imageData())
                        self.handle_pasted_image(image)
                        return True        

                # Handle Ctrl+Up and Ctrl+Down for message editing
                if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                    if event.key() == Qt.Key.Key_Up:
                        self.show_previous_message()
                        return True
                    elif event.key() == Qt.Key.Key_Down:
                        self.show_next_message()
                        return True

                # Regular Enter key handling
                if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
                    if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                        cursor = self.input_field.textCursor()
                        cursor.insertText("\n")
                        return True
                    else:
                        self.send_message()
                        return True

        elif isinstance(obj, QSizeGrip):
            if event.type() == QEvent.Type.MouseButtonDblClick:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.restore_size()
                    return True            
        
        return super().eventFilter(obj, event)

    def handle_pasted_image(self, image):
        """Process and add a pasted or dropped image."""
        if len(self.selected_screenshots) >= self.MAX_SCREENSHOTS:
            self.show_error_message("Maximum Screenshots", 
                                  f"Maximum of {self.MAX_SCREENSHOTS} screenshots allowed.")
            return

        # Process the image using the same function as screenshots
        processed_image = process_image(image)
        self.selected_screenshots.append(processed_image)
        
        # Update thumbnails
        self.update_thumbnails()
        
        # Update placeholder text
        self.input_field.setPlaceholderText("Image added. Type your message...")
        
        # Force focus back to input field
        self.input_field.setFocus(Qt.FocusReason.OtherFocusReason)
        self.activateWindow()
    

    def restore_size(self):
        """Restore the window to its original size based on expansion state."""
        screen = QApplication.primaryScreen().availableGeometry()
        current_rect = self.geometry()

        if self.is_expanded:
            # If expanded, restore to original expanded size
            new_size = self.original_expanded_size
            # Store current expanded size before restoring
            self.expanded_size = current_rect.size()
        else:
            # If compact, restore to original compact size
            new_size = self.original_compact_size
            # Store current compact size before restoring
            self.compact_size = current_rect.size()

        # Calculate new position to maintain the right edge position
        new_x = (
            screen.right() - new_size.width() - (screen.right() - current_rect.right())
        )
        new_y = (
            screen.bottom()
            - new_size.height()
            - (screen.bottom() - current_rect.bottom())
        )

        # Set the new geometry
        self.setGeometry(new_x, new_y, new_size.width(), new_size.height())

    def handle_suggestion_navigation(self, key):
        """Handle keyboard navigation in the suggestion list."""
        current_row = self.suggestion_list.currentRow()
        if key == Qt.Key.Key_Up:
            new_row = (
                max(0, current_row - 1)
                if current_row >= 0
                else self.suggestion_list.count() - 1
            )
        else:  # Key_Down
            new_row = (
                min(self.suggestion_list.count() - 1, current_row + 1)
                if current_row >= 0
                else 0
            )

        self.suggestion_list.setCurrentRow(new_row)
        return True

    def handle_close_button_click(self):
        """Handle the close button click event."""
        if QApplication.keyboardModifiers() == Qt.KeyboardModifier.ControlModifier:
            self.terminate_application()
        else:
            self.hide()

    def adjust_input_height(self):
        """Adjust input field height based on content."""
        document_height = self.input_field.document().size().height()
        margins = self.input_field.contentsMargins()
        total_margins = margins.top() + margins.bottom()

        # Calculate new height (minimum 50px, maximum 150px)
        new_height = int(min(max(50, document_height + total_margins), 150))

        if new_height != self.input_field.height():
            input_widget = self.input_field.parent()
            input_widget.setFixedHeight(new_height)
            self.input_field.setFixedHeight(new_height)

            # Force layout update without modifying chat display height
            self.chat_interface.layout().update()

    def handle_js_console(self, level, message, line, source):
        """Handle JavaScript console messages."""
        if DEBUG:
            print(f"JS Console ({level}): {message} [line {line}] {source}")

    def regenerate_message(self, index):
        """Regenerate a specific message in the chat history."""
        if index >= len(self.message_history):
            return

        # Call the unified send_to_ollama function with the regeneration index
        self.send_to_ollama(regenerate_index=index+1)

    def handle_default_model_click(self, model_name, button):
        """Handle clicking the default model button."""
        # Update the default model
        self.default_model = model_name
        self.selected_model = model_name

        # Update all default buttons
        for i in range(self.model_list.count()):
            item = self.model_list.item(i)
            widget = self.model_list.itemWidget(item)
            if widget:
                default_btn = widget.findChild(QPushButton, "modelDefaultButton")
                if default_btn:
                    default_btn.setProperty(
                        "is_default", default_btn.property("model_name") == model_name
                    )
                    self.update_default_button_style(default_btn)

    def update_default_button_style(self, button):
        """Update the default button style based on its state."""
        is_default = button.property("is_default")
        button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {'#43b581' if is_default else 'transparent'};
                border: none;
                border-radius: 4px;
                padding: 2px;
            }}
            QPushButton:hover {{
                background-color: {'#3ca374' if is_default else '#2f3136'};
            }}
        """
        )

    def check_provider_status(self):
        """Check if the Ollama provider is online."""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=0.1)
            is_online = response.status_code == 200

            if is_online != self.provider_online:  # Only update if state changed
                self.provider_online = is_online
                self.update_gradient_state()  # Update gradient

            self.chat_display.page().runJavaScript(
                f"updateProviderStatus({str(is_online).lower()})"
            )

        except:
            if self.provider_online:  # Only update if state changed
                self.provider_online = False
                self.update_gradient_state()  # Update gradient
            self.chat_display.page().runJavaScript("updateProviderStatus(false)")

        self.send_btn.setEnabled(self.provider_online)

    def update_provider_status(self, message):
        """Update the chat display with the provider status."""
        # Add status message to chat content if it's empty or update the first message
        if not self.chat_content:
            self.chat_content.append(("System", message, ""))
        else:
            # Check if the first message is a status message
            first_message = self.chat_content[0]
            if first_message[0] == "System" and ("Ollama is" in first_message[1]):
                self.chat_content[0] = ("System", message, "")
            else:
                self.chat_content.insert(0, ("System", message, ""))

        self.update_chat_display()

    def switch_monitor(self):
        """Switch the window to the next available monitor and align to bottom-right corner."""
        screens = QApplication.screens()
        if len(screens) <= 1:
            return  # No other monitors to switch to
            
        # Find current screen
        current_pos = self.geometry().center()
        current_screen_index = -1
        
        for i, screen in enumerate(screens):
            if screen.geometry().contains(current_pos):
                current_screen_index = i
                break
    
        # Switch to next screen (or first if we're on the last)
        next_screen_index = (current_screen_index + 1) % len(screens)
        next_screen = screens[next_screen_index]
        
        # Get current window geometry and available screen geometry
        current_geometry = self.geometry()
        available_geometry = next_screen.availableGeometry()
        
        # Add padding from the edges
        padding = 2
        
        # Calculate new position (bottom-right corner of target screen)
        new_x = available_geometry.right() - current_geometry.width() - padding
        new_y = available_geometry.bottom() - current_geometry.height() - padding
        
        # Move window to new position
        self.setGeometry(new_x, new_y, 
                        current_geometry.width(), 
                        current_geometry.height())

    def save_chat_history(self):
        """Save the current chat history to a file."""
        chat_dir = os.path.join(os.path.expanduser("~"), ".pixelllama")
        if not os.path.exists(chat_dir):
            os.makedirs(chat_dir)
            
        chat_file = os.path.join(chat_dir, "chat_history.json")
        
        # Prepare chat data for saving
        chat_data = {
            "messages": self.message_history,
            "chat_content": self.chat_content,
            "active_model": self.active_model
        }
        
        try:
            with open(chat_file, "w", encoding="utf-8") as f:
                json.dump(chat_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving chat history: {e}")

    def load_chat_history(self):
        """Load chat history from file."""
        chat_file = os.path.join(os.path.expanduser("~"), ".pixelllama", "chat_history.json")
        
        if not os.path.exists(chat_file):
            return
            
        try:
            with open(chat_file, "r", encoding="utf-8") as f:
                chat_data = json.load(f)
                
            self.message_history = chat_data.get("messages", [])
            self.chat_content = chat_data.get("chat_content", [])
            saved_model = chat_data.get("active_model")
            
            if saved_model:
                self.active_model = saved_model
                
            # Instead of calling update_chat_display directly, we'll let the 
            # initialize_chat_display handle it through the loadFinished signal
            if hasattr(self, 'chat_display') and self.chat_display.page().isLoading():
                # If the page is still loading, the _on_chat_display_loaded will handle the update
                pass
            else:
                # If the page is already loaded, update directly
                self.update_chat_display()
                
        except Exception as e:
            print(f"Error loading chat history: {e}")

    def hideEvent(self, event):
        """Save chat history when hiding the window."""
        self.save_chat_history()
        super().hideEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = OllamaChat()
    ex.show()
    sys.exit(app.exec())
