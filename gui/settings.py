import os
import sys
from utils.settings_manager import load_settings_from_file, save_settings_to_file
from pathlib import Path
from PyQt6.QtCore import (
    Qt,
)
from PyQt6.QtWidgets import (
    QTextEdit,
    QListWidget,
    QWidget,
    QScrollArea,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QHBoxLayout,
    QListWidgetItem,
    QDialog,
    QGridLayout,
    QComboBox,
    QApplication,
)
from PyQt6.QtGui import (
    QDoubleValidator,
    QIntValidator,
    QIcon,
    QPixmap,
    QImage,
)
from utils.provider_utils import (
    get_ollama_url,
    request_models,
    get_openai_url,
)

DEBUG = "-debug" in sys.argv


@staticmethod
def get_base_model_name(model_name):
    """Extract the base model name before the colon."""
    return model_name.split(":")[0] if ":" in model_name else model_name


def load_svg_button_icon(self, path):
    """
    Load an SVG file and replace currentColor with specific color
    :param path: str path to SVG file
    :return: None
    """
    style = self.styleSheet()
    color = "#e8eaed"  # Default color if not found in stylesheet
    if "--icon-color:" in style:
        color = style.split("--icon-color:")[1].split(";")[0].strip()

    with open(path, "r") as file:
        svg_content = file.read()
        svg_content = svg_content.replace('fill="#e8eaed"', f'fill="{color}"')

    self.setIcon(QIcon(QPixmap.fromImage(QImage.fromData(svg_content.encode()))))
    self.icon_path = path


class SettingsPage(QWidget):
    def __init__(self, parent=None, chat_instance=None):
        super().__init__(parent)

        self.ICONS = Path(__file__).parent.parent / "icons"
        # Replace direct settings loading with settings_manager
        self.settings = load_settings_from_file()
        self.chat_instance = chat_instance

        # Update these lines to properly handle provider initialization
        self.ollama_default_model = self.settings.get("ollama_default_model")
        self.openai_default_model = self.settings.get("openai_default_model")
        self.provider = self.settings.get("provider", "openai")  # Add this line
        self.system_prompt = self.settings.get("system_prompt")
        self.ollama_url = self.settings["ollama_url"]
        self.temperature = self.settings.get("temperature")
        self.context_size = self.settings.get("context_size")
        self.vision_capable_models = set(self.settings.get("vision_capable_models", []))
        self.theme = self.settings.get("theme", "dark")
        self.model_names = []

        self.setWindowTitle("Settings")
        self.setGeometry(100, 100, 400, 300)

        settings_layout = QVBoxLayout(self)

        # Create a scroll area for all settings
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )  # Prevent horizontal scroll
        scroll_area.setMinimumWidth(100)  # Set minimum width for scroll area
        scroll_content = QWidget()
        scroll_content.setMinimumWidth(100)
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(10, 10, 10, 10)  # Add some padding
        scroll_content.setObjectName("scrollLayout")
        scroll_content.setStyleSheet(self.styleSheet())

        # Add theme selection inside scroll area
        theme_container = QWidget()
        theme_container.setObjectName("provider_settingsPanel")
        theme_layout = QGridLayout(theme_container)
        theme_layout.setContentsMargins(5, 5, 5, 5)
        theme_layout.setColumnStretch(1, 1)

        # Theme selection combo box
        self.theme_label = QLabel("Theme:")
        self.theme_combo = QComboBox()
        self.theme_combo.currentTextChanged.connect(self.theme_combo_changed)
        self.theme_combo.setMinimumWidth(32)
        self.theme_combo.wheelEvent = lambda event: event.ignore()

        # Load themes from themes folder
        themes_dir = Path(__file__).parent.parent / "themes"
        theme_files = [f.stem for f in themes_dir.glob("*.qss")]
        self.theme_combo.addItems(theme_files)

        # Set current theme
        current_theme = self.settings.get("theme", "dark")
        index = self.theme_combo.findText(current_theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)

        # Add theme selection to layout
        theme_layout.addWidget(self.theme_label, 0, 0)
        theme_layout.addWidget(self.theme_combo, 0, 1)

        scroll_layout.addWidget(theme_container)

        # Create a container widget for provider settings with styling
        provider_container = QWidget()
        provider_container.setObjectName("provider_settingsPanel")
        provider_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )  # Allow horizontal expansion
        provider_container.setStyleSheet(self.styleSheet())

        provider_layout = QGridLayout(provider_container)
        provider_layout.setContentsMargins(15, 15, 15, 15)

        # Make the second column of the grid stretch
        provider_layout.setColumnStretch(1, 1)

        # Provider selection combo box
        self.provider_label = QLabel("AI Provider:")
        self.provider_combo = QComboBox()
        self.provider_combo.setStyleSheet(self.chat_instance.styleSheet())
        self.provider_combo.setMinimumWidth(32)
        self.provider_combo.addItems(["Ollama", "OpenAI"])
        self.provider_combo.wheelEvent = lambda event: event.ignore()
        # Find the matching item ignoring case
        for i in range(self.provider_combo.count()):
            if self.provider_combo.itemText(i).lower() == self.provider:
                self.provider_combo.setCurrentIndex(i)
                break
        self.provider_combo.currentTextChanged.connect(self.on_provider_changed)

        provider_layout.addWidget(self.provider_label, 0, 0)
        provider_layout.addWidget(self.provider_combo, 0, 1)

        # Ollama URL input
        self.ollama_url_label = QLabel("Ollama URL:")
        self.ollama_url_label.setStyleSheet(self.chat_instance.styleSheet())
        self.ollama_url_input = QLineEdit()
        self.ollama_url_input.setText(get_ollama_url())
        self.ollama_url_input.setPlaceholderText("http://localhost:11434")
        self.ollama_url_input.setObjectName("ollamaUrlInput")
        self.ollama_url_input.setStyleSheet(self.chat_instance.styleSheet())
        provider_layout.addWidget(self.ollama_url_label, 1, 0)
        provider_layout.addWidget(self.ollama_url_input, 1, 1)

        # OpenAI settings
        self.openai_url_label = QLabel("OpenAI URL:")
        self.openai_url_label.setStyleSheet(self.chat_instance.styleSheet())
        self.openai_url_input = QLineEdit()
        self.openai_url_input.setText(get_openai_url())
        self.openai_url_input.setPlaceholderText("https://api.openai.com/v1")
        self.openai_url_input.setObjectName("openaiUrlInput")
        self.openai_url_input.setStyleSheet(self.chat_instance.styleSheet())
        provider_layout.addWidget(self.openai_url_label, 2, 0)
        provider_layout.addWidget(self.openai_url_input, 2, 1)

        self.openai_key_label = QLabel("OpenAI API Key:")
        self.openai_key_input = QLineEdit()
        self.openai_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key_input.setText(self.settings.get("openai_key", ""))
        self.openai_key_label.setStyleSheet(self.chat_instance.styleSheet())
        provider_layout.addWidget(self.openai_key_label, 3, 0)
        provider_layout.addWidget(self.openai_key_input, 3, 1)

        # Add provider container to scroll layout
        scroll_layout.addWidget(provider_container)

        # Add model selection
        self.model_label = QLabel("Available Models:")
        scroll_layout.addWidget(self.model_label)

        # Add search bar for models
        # Create container for search and reload button
        search_container = QWidget()
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)

        # Add model search
        self.model_search = QLineEdit()
        self.model_search.setPlaceholderText("Search models...")
        self.model_search.textChanged.connect(self.filter_models)
        search_layout.addWidget(self.model_search)

        # Add model list reload button
        self.model_reload_button = QPushButton()
        self.model_reload_button.setFixedSize(30, 30)
        self.model_reload_button.clicked.connect(
            lambda: self.reload_models(update_ui=True)
        )
        self.model_reload_button.setStyleSheet(self.styleSheet())
        load_svg_button_icon(self.model_reload_button, self.ICONS / "refresh.svg")
        search_layout.addWidget(self.model_reload_button)

        scroll_layout.addWidget(search_container)

        # Model list
        self.model_list = QListWidget()
        self.model_list.setMinimumHeight(100)
        self.model_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.model_list.setObjectName("modelList")
        scroll_layout.addWidget(self.model_list)

        # Add temperature setting
        self.temperature_label = QLabel("Temperature:")
        scroll_layout.addWidget(self.temperature_label)

        self.temperature_input = QLineEdit()
        self.temperature_input.setPlaceholderText("default")
        temperature_validator = QDoubleValidator(0.0, 1.0, 2, self)
        self.temperature_input.setValidator(temperature_validator)
        scroll_layout.addWidget(self.temperature_input)

        # Add context size setting
        self.context_size_label = QLabel("Context Size:")
        scroll_layout.addWidget(self.context_size_label)

        self.context_size_input = QLineEdit()
        self.context_size_input.setPlaceholderText("default")
        context_size_validator = QIntValidator(0, 65536, self)
        self.context_size_input.setValidator(context_size_validator)
        scroll_layout.addWidget(self.context_size_input)

        # Add system prompt setting
        self.system_prompt_label = QLabel("System Prompt:")
        scroll_layout.addWidget(self.system_prompt_label)

        # Create a container for system prompt and button
        system_prompt_container = QWidget()
        system_prompt_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        system_prompt_layout = QVBoxLayout(system_prompt_container)
        system_prompt_layout.setContentsMargins(0, 0, 0, 0)

        # Add system prompt input
        self.system_prompt_input = QTextEdit()
        self.system_prompt_input.setPlaceholderText("Enter system prompt here...")
        self.system_prompt_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.system_prompt_input.setFixedHeight(100)

        # Add prompt selection button
        prompt_button = QPushButton("")
        prompt_button.setFixedSize(24, 24)
        prompt_button.setObjectName("systemPromptButton")
        prompt_button.setStyleSheet(self.chat_instance.styleSheet())
        load_svg_button_icon(prompt_button, self.ICONS / "browse.svg")
        prompt_button.clicked.connect(self.show_prompt_selector)

        prompt_button_container = QWidget()
        prompt_button_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        prompt_button_layout = QHBoxLayout(prompt_button_container)
        prompt_button_layout.setContentsMargins(0, 0, 0, 0)

        prompt_button_layout.addWidget(self.system_prompt_input)
        prompt_button_layout.addWidget(prompt_button)

        system_prompt_layout.addWidget(prompt_button_container)
        scroll_layout.addWidget(system_prompt_container)

        scroll_layout.addStretch(1)
        scroll_content.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_content)
        settings_layout.addWidget(scroll_area)

        # Button layout outside scroll area
        button_layout = QHBoxLayout()
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.apply_settings)
        button_layout.addWidget(self.apply_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.clicked.connect(self.cancel_settings)
        button_layout.addWidget(self.cancel_button)

        settings_layout.addLayout(button_layout)

        # Update visibility based on selected provider
        self.update_provider_fields()

    def filter_models(self, text):
        """Filter the model list based on the search text."""
        search_text = text.lower()
        for index in range(self.model_list.count()):
            item = self.model_list.item(index)
            model_name = self.get_selected_model_name(item)
            if model_name:
                item.setHidden(search_text not in model_name.lower())
            else:
                item.setHidden(True)

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
        self.ollama_default_model = self.settings.get("ollama_default_model")
        self.openai_default_model = self.settings.get("openai_default_model")
        self.temperature = self.settings.get("temperature")
        self.context_size = self.settings.get("context_size")
        self.system_prompt = self.settings.get("system_prompt")
        self.ollama_url = self.settings.get("ollama_url")
        self.vision_capable_models = set(self.settings.get("vision_capable_models", []))

        self.theme_combo.setCurrentText(self.settings.get("theme", "dark"))

        # Update UI elements
        self.temperature_input.setText(
            str(self.temperature) if self.temperature is not None else ""
        )
        self.context_size_input.setText(
            str(self.context_size) if self.context_size is not None else ""
        )
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

        # Get current settings to preserve existing values
        current_settings = load_settings_from_file()

        # Store both providers' settings
        ollama_url = self.ollama_url_input.text()
        openai_url = self.openai_url_input.text()
        openai_key = self.openai_key_input.text()

        # Update the settings dictionary
        save_settings_to_file(
            {
                **current_settings,  # Preserve all existing settings
                "theme": self.theme_combo.currentText(),
                "provider": self.provider_combo.currentText().lower(),
                "openai_url": openai_url,
                "openai_key": openai_key,
                "ollama_url": ollama_url,
                "ollama_default_model": self.ollama_default_model,
                "openai_default_model": self.openai_default_model,
                "temperature": self.temperature,
                "context_size": self.context_size,
                "system_prompt": self.system_prompt,
                "vision_capable_models": sorted(list(self.vision_capable_models)),
            }
        )

        # Force theme update
        self.current_theme = self.theme_combo.currentText()
        self.update_theme(self.current_theme)

        self.load_settings()
        self.chat_instance.toggle_settings()

    def theme_combo_changed(self):
        theme_name = self.theme_combo.currentText()
        self.update_theme(theme_name)

    def update_theme(self, theme_name):
        theme_path = Path(__file__).parent.parent / "themes" / f"{theme_name}.qss"
        if theme_path.exists():
            with open(theme_path, "r") as f:
                stylesheet = f.read()
                self.chat_instance.setStyleSheet(stylesheet)
                # Update style for all child widgets
                for child in self.chat_instance.findChildren(QWidget):
                    child.setStyleSheet(stylesheet)
                    if isinstance(child, QComboBox):
                        # Update the combo box popup/dropdown menu
                        child.view().setStyleSheet(stylesheet)
                    if isinstance(child, QPushButton) and child.icon():
                        if hasattr(child, "icon_path"):
                            load_svg_button_icon(child, child.icon_path)
                    child.style().unpolish(child)
                    child.style().polish(child)
                    child.update()

        self.chat_instance.chat_box.update_webview_colors()

    def reload_models(self, update_ui=False):
        """Reload the model list"""
        try:
            # Force update of the UI
            QApplication.processEvents()

            # Now load new models
            self.model_names = []
            self.model_names = sorted(
                request_models(self.provider_combo.currentText().lower())
            )

            if update_ui:
                self.setCursor(Qt.CursorShape.WaitCursor)

                # Clear existing items and their widgets
                while self.model_list.count() > 0:
                    item = self.model_list.takeItem(0)
                    widget = self.model_list.itemWidget(item)
                    if widget:
                        widget.deleteLater()
                    del item

                self.model_list.clear()  # Ensure list is visually cleared
                self.update_list()
        finally:
            self.chat_instance.provider_online = not self.model_names[0] in [
                "Error loading models"
            ]
            if update_ui:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def update_list(self):
        """Load models based on selected provider"""
        self.model_list.clear()

        # Create items with fixed button positions
        for model_name in self.model_names:
            item = QListWidgetItem(self.model_list)
            base_model = get_base_model_name(model_name)  # Get base model name

            # Create a widget to hold the model name and icons
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(5, 2, 5, 2)
            layout.setSpacing(0)  # Remove spacing between elements

            # Create a fixed-width container for buttons
            button_container = QWidget()
            button_container.setFixedWidth(56)  # Adjust width based on your buttons

            button_layout = QHBoxLayout(button_container)
            button_layout.setContentsMargins(0, 0, 0, 0)
            button_layout.setSpacing(2)
            button_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

            # Add button container first
            layout.addWidget(button_container, 0, Qt.AlignmentFlag.AlignLeft)

            # Add model name label with elision
            label = QLabel(model_name)
            label.setStyleSheet("text-align: left; padding-left: 0px;")
            label.setMinimumWidth(50)
            label.setMaximumWidth(300)
            layout.addWidget(label, 1, Qt.AlignmentFlag.AlignLeft)

            if model_name not in ["Error loading models"]:
                # Add default model button
                default_btn = QPushButton()
                default_btn.setFixedSize(24, 24)
                default_btn.setObjectName("modelDefaultButton")
                default_btn.setProperty("model_name", model_name)
                current_default = (
                    self.ollama_default_model
                    if self.provider_combo.currentText().lower() == "ollama"
                    else self.openai_default_model
                )
                default_btn.setProperty("is_default", model_name == current_default)
                default_btn.setStyleSheet(self.chat_instance.styleSheet())
                load_svg_button_icon(default_btn, self.ICONS / "default.svg")
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
                camera_btn.clicked.connect(
                    lambda checked, m=model_name, b=camera_btn: self.handle_model_camera_click(
                        m, b
                    )
                )
                self.update_camera_button_style(camera_btn)
                button_layout.addWidget(camera_btn)

                # Update default button style
                self.update_default_button_style(default_btn)

            # Set the custom widget as the item's widget
            item.setSizeHint(widget.sizeHint())
            self.model_list.setItemWidget(item, widget)

    def handle_default_model_click(self, model_name, button):
        """Handle clicking the default model button."""
        # Update the default model
        if self.provider_combo.currentText().lower() == "ollama":
            self.ollama_default_model = model_name
        else:
            self.openai_default_model = model_name

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
                    # default_btn.style().unpolish(default_btn)
                    # default_btn.style().polish(default_btn)

    def update_default_button_style(self, button):
        """Update the default button style based on its state."""
        is_default = button.property("is_default")
        button.setObjectName("modelDefaultButton")
        button.setStyleSheet(self.chat_instance.styleSheet())
        button.setProperty("selected", "true" if is_default else "false")
        button.style().unpolish(button)
        button.style().polish(button)

    def handle_model_selection(self, item):
        """Handle double-click to select a model."""
        if item:
            print(f"Selected model: {self.selected_model}")

    def update_camera_button_style(self, button):
        """Update the camera button style based on its enabled state."""
        is_enabled = button.property("enabled_state")
        button.setStyleSheet(self.chat_instance.styleSheet())
        if is_enabled:
            load_svg_button_icon(button, self.ICONS / "vision.svg")
        else:
            load_svg_button_icon(button, self.ICONS / "vision_disabled.svg")

    def handle_model_camera_click(self, model_name, button):
        """Toggle vision capability for a model and all its variants."""
        base_name = get_base_model_name(model_name)
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
                    if get_base_model_name(related_model) == base_name:
                        # Update the button state
                        related_camera_btn.setProperty("enabled_state", new_state)
                        self.update_camera_button_style(related_camera_btn)

    def hide_prompt_selector(self):
        if hasattr(self, "prompt_overlay"):
            # Save all changes when closing
            if hasattr(self, "modified_prompts"):
                settings = load_settings_from_file()
                settings["saved_prompts"] = list(self.modified_prompts.values())
                save_settings_to_file(settings)
            self.prompt_overlay.hide()
            self.prompt_overlay.deleteLater()  # Add this line to properly delete the widget
            delattr(self, "prompt_overlay")  # Remove the reference

    def cancel_settings(self):
        # Close prompt browser if it's open
        if hasattr(self, "prompt_overlay"):
            self.hide_prompt_selector()

        theme = self.settings.get("theme", "dark")
        if theme != self.theme_combo.currentText():
            self.update_theme(theme)
            print(f"Updated theme to {theme}")

        load_svg_button_icon(
            self.chat_instance.settings_btn, self.ICONS / "settings.svg"
        )
        self.hide()

    def hide(self):
        """Hide settings and return to main chat interface."""
        super().hide()
        self.chat_instance.stacked_widget.setCurrentWidget(
            self.chat_instance.chat_interface
        )

    def show_prompt_selector(self):
        if not hasattr(self, "prompt_overlay"):
            self.prompt_overlay = QWidget(self)
            # Store original prompts for comparison when saving
            self.original_prompts = {}
            self.modified_prompts = {}

            overlay_layout = QVBoxLayout(self.prompt_overlay)

            # Scroll area for prompts
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setObjectName(
                "scrollArea"
            )  # Use same object name as settings scroll

            scroll_content = QWidget()
            scroll_content.setObjectName("scrollLayout")
            self.prompt_list_layout = QVBoxLayout(scroll_content)
            self.prompt_list_layout.setSpacing(10)
            self.prompt_list_layout.setContentsMargins(10, 10, 10, 10)
            self.prompt_list_layout.addStretch()

            scroll.setWidget(scroll_content)
            overlay_layout.addWidget(scroll)

            # Bottom buttons
            button_layout = QHBoxLayout()
            add_button = QPushButton("Add New Prompt")
            add_button.clicked.connect(self.add_new_prompt)
            button_layout.addWidget(add_button)

            close_button = QPushButton("Close")
            close_button.setObjectName("cancelButton")
            close_button.clicked.connect(self.hide_prompt_selector)
            button_layout.addWidget(close_button)

            overlay_layout.addLayout(button_layout)

        # Load fresh prompts when showing
        settings = load_settings_from_file()
        self.original_prompts = {p: p for p in settings.get("saved_prompts", [])}
        self.modified_prompts = self.original_prompts.copy()

        self.update_prompt_list()
        self.prompt_overlay.resize(self.size())
        self.prompt_overlay.show()

    def hide_prompt_selector(self):
        if hasattr(self, "prompt_overlay"):
            # Save all changes when closing
            if hasattr(self, "modified_prompts"):
                settings = load_settings_from_file()
                settings["saved_prompts"] = list(self.modified_prompts.values())
                save_settings_to_file(settings)
            self.prompt_overlay.hide()

    def update_prompt_list(self):
        # Clear existing prompts
        while self.prompt_list_layout.count() > 1:
            item = self.prompt_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Add prompts using the in-memory copies
        for original_prompt, current_prompt in self.modified_prompts.items():
            prompt_widget = QWidget()
            prompt_widget.setFixedHeight(100)
            prompt_widget.setObjectName("promptItem")

            layout = QHBoxLayout(prompt_widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)

            # Text container - remove extra margins
            text_container = QWidget()
            text_container.setObjectName("promptTextContainer")
            text_layout = QHBoxLayout(text_container)
            text_layout.setContentsMargins(0, 0, 0, 0)  # Reduced margins

            # Prompt text edit
            preview = QTextEdit()
            preview.setPlainText(current_prompt)
            preview.setObjectName("promptText")
            preview.textChanged.connect(
                lambda p=preview, orig=original_prompt: self.handle_prompt_edit(p, orig)
            )
            text_layout.addWidget(preview)

            layout.addWidget(text_container, stretch=1)  # Add stretch factor

            # Button container
            button_container = QWidget()
            button_container.setFixedWidth(24)
            button_layout = QVBoxLayout(button_container)
            button_layout.setSpacing(0)
            button_layout.setContentsMargins(0, 0, 0, 0)

            # Select button - update to pass original_prompt as key
            select_button = QPushButton("")
            select_button.setFixedSize(24, 24)
            select_button.setObjectName("promptSelectButton")
            select_button.setStyleSheet(self.chat_instance.styleSheet())
            load_svg_button_icon(select_button, self.ICONS / "default.svg")
            select_button.clicked.connect(
                lambda _, key=original_prompt: self.select_prompt(key)
            )

            # Delete button
            delete_button = QPushButton("")
            delete_button.setFixedSize(24, 24)
            delete_button.setObjectName("promptDeleteButton")
            delete_button.setStyleSheet(self.chat_instance.styleSheet())
            load_svg_button_icon(delete_button, self.ICONS / "clear.svg")
            delete_button.clicked.connect(
                lambda _, p=original_prompt, w=preview: self.delete_prompt(
                    p, w.toPlainText()
                )
            )

            button_layout.addWidget(select_button)
            button_layout.addWidget(delete_button)

            layout.addWidget(button_container)

            self.prompt_list_layout.insertWidget(
                self.prompt_list_layout.count() - 1, prompt_widget
            )

    def handle_prompt_edit(self, text_edit, original_prompt):
        """Store prompt changes in memory without saving immediately"""
        new_text = text_edit.toPlainText()
        if original_prompt in self.original_prompts:
            self.modified_prompts[original_prompt] = new_text

    def select_prompt(self, prompt_key):
        """Set the selected prompt as the system prompt using the current modified version"""
        if prompt_key in self.modified_prompts:
            current_text = self.modified_prompts[prompt_key]
            self.system_prompt_input.setPlainText(current_text)
            self.hide_prompt_selector()

    def delete_prompt(self, original_prompt, current_prompt):
        """Remove prompt from in-memory storage"""
        if original_prompt in self.modified_prompts:
            del self.modified_prompts[original_prompt]
            del self.original_prompts[original_prompt]
        self.update_prompt_list()

    def add_new_prompt(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add New Prompt")
        layout = QVBoxLayout(dialog)

        prompt_input = QTextEdit()
        prompt_input.setPlaceholderText("Enter new prompt...")
        layout.addWidget(prompt_input)

        button_box = QHBoxLayout()
        save_button = QPushButton("Save")
        cancel_button = QPushButton("Cancel")

        save_button.clicked.connect(
            lambda: self.save_new_prompt(prompt_input.toPlainText(), dialog)
        )
        cancel_button.clicked.connect(dialog.reject)

        button_box.addWidget(save_button)
        button_box.addWidget(cancel_button)
        layout.addLayout(button_box)

        dialog.exec()

    def save_new_prompt(self, prompt, dialog):
        if prompt.strip():
            # Add to in-memory storage
            self.original_prompts[prompt] = prompt
            self.modified_prompts[prompt] = prompt
            self.update_prompt_list()
            dialog.accept()

    def on_provider_changed(self, provider):
        """Handle provider change in combo box"""
        self.update_provider_fields()

    def update_provider_fields(self):
        """Update visibility of provider-specific fields"""
        is_ollama = self.provider_combo.currentText() == "Ollama"

        # Ollama fields
        self.ollama_url_label.setVisible(is_ollama)
        self.ollama_url_input.setVisible(is_ollama)

        # OpenAI fields
        self.openai_url_label.setVisible(not is_ollama)
        self.openai_url_input.setVisible(not is_ollama)
        self.openai_key_label.setVisible(not is_ollama)
        self.openai_key_input.setVisible(not is_ollama)

        # Reload models
        self.reload_models(update_ui=True)
