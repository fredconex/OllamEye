# PixelLama 0.95b - A GUI interface for Ollama
# Created by Alfredo Fernandes
# This software provides a user-friendly interface for interacting with Ollama with screenshot capabilities,
# https://github.com/fredconex/PixelLlama

import os
import sys
from math import cos, sin, radians
from gui.settings import SettingsPage, get_base_model_name, load_svg_button_icon
from gui.prompt_box import PromptBox
from utils.chat_storage import ChatStorage
from gui.chat_box import ChatBox
from utils.settings_manager import load_settings_from_file
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QSizeGrip,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QMenu,
    QMessageBox,
    QWidget,
    QHBoxLayout,
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
)
from PyQt6.QtGui import (
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
    QCursor,
)

from utils.screenshot_utils import ScreenshotSelector, process_image
from utils.provider_utils import ( 
    request_models
)
from utils.settings_manager import get_default_model

DEBUG = "-debug" in sys.argv
   
class PixelChat(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        screen = QApplication.primaryScreen().availableGeometry()

        # Add thumbnail size constants
        self.THUMBNAIL_SIZE = 42  # Main container size
        self.THUMBNAIL_INNER_SIZE = 26  # Actual thumbnail size
        self.THUMBNAIL_BTN_SIZE = 16  # Delete button size
        self.THUMBNAIL_BTN_MARGIN = 0  # Button margin from top-right

        # Add these lines near the start of __init__
        self.provider_online = False
        self.gradient_angle = 0
        self.gradient_color1 = "#1E1E1E" 
        self.gradient_color2 = "#1E1E1E"
        self.gradient_speed = 0

        # Initialize a timer to check model capabilities
        self.model_check_timer = QTimer(self)
        self.model_check_timer.timeout.connect(self.update_screenshot_button_visibility)
        self.model_check_timer.start(1000)  # Check every second

        # Current sizes can change when user resizes the window
        self.compact_size = QSize(400, 800)
        self.expanded_size = QSize(int(screen.width() * 0.5), int(screen.height() * 0.75))

        # Store original sizes
        self.original_compact_size = self.compact_size
        self.original_expanded_size = self.expanded_size

        self.is_expanded = False
        self.selected_screenshot = None
        self.original_button_style = ""
        self.debug_screenshot = None
        self.sidebar_expanded = True
        self.previous_geometry = None
        self.animation = None
        self.selected_model = None # Model used with @model_name
        self.active_model = None
        self.dragging = False
        self.drag_start_position = None
        self.current_response_model = None
        self.status_thread = None

        # Prompt box
        self.input_field = PromptBox(self, chat_instance=self)
        self.input_field.setPlaceholderText("Type your message...")
        self.input_field.textChanged.connect(self.adjust_input_height)

        self.initUI()  # Initialize UI components after input_field is created
        self.settings_interface.load_settings()
        self.add_vertical_button()
        self.position_window()
        self.chat_box.initialize_chat_display()
        self.thumbnail_size = QSize(256, 256)
        self.create_tray_icon()

        # Load chat history
        self.chat_content = []
        self.chat_storage = ChatStorage()

        # Add provider status check timer
        self.provider_check_timer = QTimer(self)
        self.provider_check_timer.timeout.connect(self.chat_box.check_provider_status)
        self.provider_check_timer.start(1000) # 1 second for the initial check
        self.provider_online = False
        self.provider_status_displayed = False

        # Add these new attributes for multiple images
        self.MAX_IMAGES = 3  # Maximum number of allowed images
        self.prompt_images = []  # List to store multiple images
        self.thumbnail_containers = []  # List to store thumbnail containers

        # Create thumbnail containers
        for i in range(self.MAX_IMAGES):
            container = self.create_thumbnail_container()
            self.thumbnail_containers.append(container)
            container.hide()

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
        delete_btn.setObjectName("deleteThumbnailButton")

        delete_btn.setStyleSheet(self.styleSheet())
        load_svg_button_icon(delete_btn, ".\\icons\\clear.svg")
        # Position the delete button
        btn_position = self.THUMBNAIL_INNER_SIZE - self.THUMBNAIL_BTN_SIZE + self.THUMBNAIL_BTN_MARGIN
        delete_btn.move(btn_position, self.THUMBNAIL_BTN_MARGIN)
        delete_btn.raise_()

        # Store references to label and button
        container.thumbnail_label = thumbnail_label
        container.delete_btn = delete_btn

        return container
    


    def initUI(self):
        # Remove border and set window to stay on top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        # Set window to be translucent
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Load the stylesheet
        style_path = os.path.join(os.path.dirname(__file__), f""".\\themes\\{load_settings_from_file().get("theme", "dark")}.qss""")
        with open(style_path, "r") as style_file:
            self.setStyleSheet(style_file.read())

        # Create main layout for the entire widget
        main_layout = QVBoxLayout(self)  # Set directly on self
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create outer widget with gradient background
        outer_widget = QWidget()
        outer_widget.setObjectName("outerWidget")
        outer_widget.setStyleSheet(self.styleSheet())
        main_layout.addWidget(outer_widget)

        # Create layout for outer widget
        outer_layout = QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(2, 2, 2, 2)

        # Create main widget
        main_widget = QWidget()
        main_widget.setObjectName("mainWidget")
        main_widget.setStyleSheet(self.styleSheet())
        widget_layout = QVBoxLayout(main_widget)
        widget_layout.setContentsMargins(20, 20, 20, 20)
        outer_layout.addWidget(main_widget)

        # Chat display
        self.chat_box = ChatBox(self, chat_instance=self)

        # Start the gradient animation
        self.start_gradient_animation()

        # Update references
        self.chat_display = self.chat_box.chat_display
        self.chat_content = self.chat_box.chat_content

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
        self.monitor_btn.setFixedSize(26, 26)
        self.monitor_btn.setToolTip("Switch Monitor")
        self.monitor_btn.setObjectName("monitorButton")
        self.monitor_btn.setStyleSheet(self.styleSheet())
        load_svg_button_icon(self.monitor_btn, ".\\icons\\monitor.svg")
        self.monitor_btn.clicked.connect(self.switch_monitor)
       
        # Hide if there's only one monitor
        if len(QApplication.screens()) > 1:
            self.monitor_btn.show()
        else:
            self.monitor_btn.hide()

        header.addWidget(self.monitor_btn)

        # Add clear button with icon
        self.clear_btn = QPushButton()
        self.clear_btn.setFixedSize(26, 26)  # Make the button smaller
        self.clear_btn.setToolTip("Clear Chat")
        self.clear_btn.setObjectName("clearButton")
        self.clear_btn.setStyleSheet(self.styleSheet())
        self.clear_btn.clicked.connect(self.chat_box.clear_chat)
        load_svg_button_icon(self.clear_btn, ".\\icons\\clear.svg")
        header.addWidget(self.clear_btn)

        # Add settings button
        self.settings_btn = QPushButton()
        self.settings_btn.setFixedSize(26, 26)
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setObjectName("settingsButton")
        self.settings_btn.setStyleSheet(self.styleSheet())
        
        load_svg_button_icon(self.settings_btn, ".\\icons\\settings.svg")

        self.settings_btn.clicked.connect(self.toggle_settings)
        header.addWidget(self.settings_btn)

        # Add close button
        self.close_btn = QPushButton()
        self.close_btn.setFixedSize(26, 26)
        self.close_btn.setToolTip("Close")
        self.close_btn.setObjectName("closeButton")
        self.close_btn.clicked.connect(self.handle_close_button_click)
        self.close_btn.setStyleSheet(self.styleSheet())

        load_svg_button_icon(self.close_btn, ".\\icons\\close.svg")
        header.addWidget(self.close_btn)

        widget_layout.addLayout(header)

        # Updated toggle button creation
        toggle_layout = QHBoxLayout()
        self.toggle_btn = QPushButton()
        button_size = 26
        self.toggle_btn.setFixedSize(button_size, button_size)
        self.toggle_btn.setObjectName("toggleButton")
        self.toggle_btn.clicked.connect(self.toggle_window_size)
        self.toggle_btn.setStyleSheet(self.styleSheet())

        load_svg_button_icon(self.toggle_btn, ".\\icons\\zoom_in.svg")

        # Add App label and version
        app_label_container = QWidget()
        app_label_layout = QVBoxLayout(app_label_container)
        app_label_layout.setContentsMargins(0, 0, 0, 0)
        app_label_layout.setSpacing(0)

        pixelllama_label = QLabel("PixelLlama")
        pixelllama_label.setObjectName("AppLabel")

        version_label = QLabel("v0.95b")
        version_label.setObjectName("VersionLabel")
        version_label.setStyleSheet(self.styleSheet())

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

        chat_layout.addWidget(self.chat_box, 1)

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
        
        # Add camera icon button
        self.screenshot_btn = QPushButton()
        self.screenshot_btn.setFixedSize(30, 30)
        self.screenshot_btn.setToolTip("Take Screenshot")
        self.screenshot_btn.clicked.connect(self.take_screenshot)
        self.screenshot_btn.setStyleSheet(self.styleSheet())
        load_svg_button_icon(self.screenshot_btn, ".\\icons\\camera.svg")
        self.original_button_style = self.screenshot_btn.styleSheet()


        self.send_btn = QPushButton()
        self.send_btn.setFixedSize(30, 30)
        self.send_btn.setText("")
        self.send_btn.setObjectName("sendButton")
        self.send_btn.setStyleSheet(self.styleSheet())
        load_svg_button_icon(self.send_btn, ".\\icons\\send.svg")
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


        # Create and add the settings interface
        self.settings_interface = SettingsPage(self, chat_instance=self)
        self.stacked_widget.addWidget(self.chat_interface)
        self.stacked_widget.addWidget(self.settings_interface)

        # Set size policy for main_widget
        main_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Set layout for self
        self.setLayout(main_layout)
        self.add_vertical_button()

    def start_gradient_animation(self):
        """Initialize and start the gradient animation"""
        self.gradient_angle = 0
        self.gradient_timer = QTimer(self)
        self.gradient_timer.timeout.connect(self.update_gradient)
        self.gradient_timer.start(50)  # Update every 50ms
        self.gradient_speed = 1  # Normal speed
        self.is_loading = False
        self.update_gradient_state()  # Initial state update

    def update_gradient_state(self):
        """Update gradient colors based on current state"""
        if self.chat_box.is_receiving or self.is_loading:
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
            """
        else:
            # Solid color when not rotating
            gradient_style = f"""
                #outerWidget {{
                    background: {self.gradient_color1};
                    border-radius: 20px;
                }}
            """

        self.findChild(QWidget, "outerWidget").setStyleSheet(gradient_style)        

    def update_screenshot_button_visibility(self):
        """Update the visibility of the screenshot button based on the current model's capabilities."""
        if self.active_model is not None:
            if self.active_model is not None:
                base_model = get_base_model_name(self.active_model)
                self.screenshot_btn.setVisible(base_model in self.settings_interface.vision_capable_models)
        else:
            if get_default_model():
                base_model = get_base_model_name(get_default_model())
                self.screenshot_btn.setVisible(base_model in self.settings_interface.vision_capable_models)

    def toggle_settings(self):
        """ Toggle between chat and settings interfaces. """
        if self.stacked_widget.currentWidget() == self.settings_interface:
            #self.stacked_widget.setCurrentWidget(self.chat_interface)
            self.settings_interface.cancel_settings()
            load_svg_button_icon(self.settings_btn, ".\\icons\\settings.svg")
        else:
            self.stacked_widget.setCurrentWidget(self.settings_interface)
            load_svg_button_icon(self.settings_btn, ".\\icons\\go_previous.svg")

            # Load settings
            self.settings_interface.load_settings()


    def send_or_stop_message(self):
        """ Send or stop receiving messages. """
        if self.chat_box.is_receiving:
            self.stop_receiving()
        else:
            self.send_message()

    def send_message(self):
        """Handle sending a message."""
        message = self.input_field.toPlainText().strip()
        
        # Don't send if there's no message and no images
        if not message and not self.prompt_images:
            return

        # Extract model if message starts with @
        model_to_use = None
        if message.startswith("@"):
            parts = message.split(" ", 1)
            model_name = parts[0][1:]
            available_models = request_models()
            if model_name in available_models:
                model_to_use = model_name
                message = parts[1] if len(parts) > 1 else ""
                # Set the active model for this conversation
                self.chat_box.active_model = model_to_use
        
        # If no model was specified with @, use active_model or default
        if model_to_use is None:
            model_to_use = self.chat_box.active_model or get_default_model()

        # Prepare content
        content = []
        if message:
            content.append({"type": "text", "text": message})
        
        # Add images if any
        if self.prompt_images:
            for image in self.prompt_images:
                byte_array = QByteArray()
                buffer = QBuffer(byte_array)
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                image.save(buffer, "PNG")
                image_base64 = byte_array.toBase64().data().decode()
                content.append({
                    "type": "image",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"}
                })

        # Send to chat box with the specified model
        self.chat_box.send_message(content, model_to_use)

        # Clear input and images
        self.reset_input_area()

        # Return focus to input field
        QTimer.singleShot(100, lambda: self.input_field.setFocus(Qt.FocusReason.OtherFocusReason))
        QTimer.singleShot(100, self.activateWindow)

    def remove_image(self):
        self.selected_screenshot = None
        self.thumbnail_container.hide()
        self.screenshot_btn.setStyleSheet("")
        self.input_field.setPlaceholderText("Type your message...")

    def take_screenshot(self):
        self.hide()
        QTimer.singleShot(100, self._delayed_screenshot)

    def _delayed_screenshot(self):
        if DEBUG:
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
            if DEBUG:
                print("Screenshot selector is no longer visible")  # Debug print
            self.check_screenshot_timer.stop()
            QTimer.singleShot(100, self.show)  # Delay showing the main window

    def handle_screenshot(self, screenshot):
        """Handle new screenshot addition."""
        if len(self.prompt_images) >= self.MAX_IMAGES:
            self.show_error_message("Maximum Screenshots", 
                                  f"Maximum of {self.MAX_IMAGES} screenshots allowed.")
            return

        # Process the screenshot
        processed_screenshot = process_image(screenshot)
        self.prompt_images.append(processed_screenshot)
        
        # Update thumbnails
        self.update_thumbnails()
        
        self.show()
        QTimer.singleShot(200, self._post_screenshot_actions)

    def update_thumbnails(self):
        """Update all thumbnail displays."""
        for i, container in enumerate(self.thumbnail_containers):
            if i < len(self.prompt_images):
                # Show and update container
                self.update_single_thumbnail(container, self.prompt_images[i], i)
                container.show()
                # Connect delete button if not already connected
                if not container.delete_btn.receivers(container.delete_btn.clicked):
                    container.delete_btn.clicked.connect(lambda checked, idx=i: self.remove_image(idx))
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

    def remove_image(self, index):
        """Remove image at specified index."""
        if 0 <= index < len(self.prompt_images):
            del self.prompt_images[index]
            self.update_thumbnails()

        if not self.prompt_images:
            self.input_field.setPlaceholderText("Type your message...")

    def update_input_layout(self):
        """Update input layout with current thumbnails."""
        # Remove existing thumbnails from layout
        for container in self.thumbnail_containers:
            self.input_layout.removeWidget(container)

        # Add visible thumbnails back to layout
        for i, container in enumerate(self.thumbnail_containers):
            if i < len(self.prompt_images):
                self.input_layout.insertWidget(2 + i, container)

    def _post_screenshot_actions(self):
        if DEBUG:
            print("Performing post-screenshot actions")  # Debug print

        # Update the UI to indicate a screenshot was taken
        self.input_field.setPlaceholderText("Screenshot taken. Type your message...")

        # Force focus to input field
        self.input_field.setFocus(Qt.FocusReason.OtherFocusReason)
        self.activateWindow()  # Activate the window to ensure it can receive focus

        if DEBUG:
            print("Post-screenshot actions completed")  # Debug print

    
    def position_window(self):
        screen = QApplication.primaryScreen().availableGeometry()
        padding = 20  # Adjust this value to change the padding
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
            load_svg_button_icon(self.toggle_btn, ".\\icons\\zoom_in.svg")
        else:
            self.compact_size = current_rect.size()
            new_size = self.expanded_size
            load_svg_button_icon(self.toggle_btn, ".\\icons\\zoom_out.svg")
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
        self.update_vertical_button_position() 

    def reset_input_area(self):
        """Reset input area by clearing text and removing all images."""
        self.input_field.clear()
        # Clear all images
        self.prompt_images.clear()
        # Hide all thumbnail containers
        for container in self.thumbnail_containers:
            container.hide()
        # Reset placeholder text
        self.input_field.setPlaceholderText("Type your message...")

    def stop_receiving(self):
        if self.provider_request_thread.isRunning():
            self.provider_request_thread.terminate()
            self.provider_request_thread.wait()
        self.chat_box.handle_response_complete()
        self.chat_box.rebuild_chat_content()
        self.chat_box.is_receiving = False
        self.send_btn.setObjectName("sendButton")
        load_svg_button_icon(self.send_btn, ".\\icons\\send.svg")

    def terminate_application(self):
        self.tray_icon.hide()
        QApplication.quit()

    def create_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icons/app_icon.png"))

        # Create the menu with custom styling
        tray_menu = QMenu()
        tray_menu.setObjectName("trayMenu")
        tray_menu.setStyleSheet(self.styleSheet())
        
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
        self.vertical_button.setStyleSheet(self.styleSheet())

        # Create and set the initial arrow icon
        load_svg_button_icon(self.vertical_button, ".\\icons\\right_arrow.svg")
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
        screen = QApplication.primaryScreen().availableGeometry()

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
            load_svg_button_icon(self.vertical_button, ".\\icons\\left_arrow.svg")

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
            load_svg_button_icon(self.vertical_button, ".\\icons\\right_arrow.svg")

            # Show all controls
            self.chat_display.show()
            self.input_field.show()
            self.screenshot_btn.show()
            self.send_btn.show()
            self.clear_btn.show()
            self.settings_btn.show()
            self.close_btn.show()
            self.toggle_btn.show() 

            # Show monitor button if there are multiple monitors
            if len(QApplication.screens()) > 1:
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

    def eventFilter(self, obj, event):
        if isinstance(obj, QSizeGrip):
            if event.type() == QEvent.Type.MouseButtonDblClick:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.restore_size()
                    return True            
        
        return super().eventFilter(obj, event)

    def handle_pasted_image(self, image):
        """Process and add a pasted or dropped image."""
        if len(self.prompt_images) >= self.MAX_IMAGES:
            self.show_error_message("Maximum Images", 
                                  f"Maximum of {self.MAX_IMAGES} images allowed.")
            return

        # Process the image using the same function as images
        processed_image = process_image(image)
        self.prompt_images.append(processed_image)
        
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

    def handle_close_button_click(self):
        """Handle the close button click event."""
        if QApplication.keyboardModifiers() == Qt.KeyboardModifier.ControlModifier:
            self.chat_box.save_chat_history()
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
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = PixelChat()
    ex.show()
    sys.exit(app.exec())
