from PyQt6.QtCore import (
    QEvent, 
    Qt,
    QTimer,
)
from PyQt6.QtWidgets import (     
    QApplication,
    QTextEdit,
    QListWidget,
)
from PyQt6.QtGui import (
    QDropEvent,
    QImage,
    QKeySequence,
)


class PromptBox(QTextEdit):
    def __init__(self, parent=None, chat_instance=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFixedHeight(50)
        self.setAcceptRichText(False)  # Only allow plain text
        self.installEventFilter(self)        
        self.chat_instance = chat_instance  # Store a reference to the chat instance

        # Initialize suggestion list
        self.suggestion_list = QListWidget(self)
        self.suggestion_list.setObjectName("suggestionList")
        self.suggestion_list.setStyleSheet(self.chat_instance.styleSheet())
        self.suggestion_list.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self.suggestion_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.suggestion_list.hide()
        self.suggestion_list.itemClicked.connect(self.insert_suggestion)
        
        # Connect textChanged signal directly
        self.textChanged.connect(self.update_suggestions)

        # Initialize the suggestion timer
        self._suggestion_timer = QTimer()
        self._suggestion_timer.setSingleShot(True)
        self._suggestion_timer.timeout.connect(self._update_suggestion_list)

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
    
    def handle_suggestion_navigation(self, key):
        """Handle keyboard navigation in the suggestion list."""
        suggestion_list = self.suggestion_list
        current_row = suggestion_list.currentRow()
        if key == Qt.Key.Key_Up:
            new_row = (
                max(0, current_row - 1)
                if current_row >= 0
                else suggestion_list.count() - 1
            )
        else:  # Key_Down
            new_row = (
                min(suggestion_list.count() - 1, current_row + 1)
                if current_row >= 0
                else 0
            )

        suggestion_list.setCurrentRow(new_row)
        return True
    
    def eventFilter(self, obj, event):
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

            # Add ESC key handling for message editing
            if event.key() == Qt.Key.Key_Escape:
                if self.chat_instance.chat_box.current_editing_message:
                    self.chat_instance.chat_box.current_editing_message.cancel_edit()
                    return True

            # Handle Image paste
            if event.matches(QKeySequence.StandardKey.Paste):
                clipboard = QApplication.clipboard()
                mime_data = clipboard.mimeData()
                
                if mime_data.hasImage():
                    image = QImage(mime_data.imageData())
                    self.chat_instance.handle_pasted_image(image)
                    return True        

            # Handle Ctrl+Up and Ctrl+Down for message editing
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                if event.key() == Qt.Key.Key_Up:
                    self.chat_instance.show_previous_message()
                    return True
                elif event.key() == Qt.Key.Key_Down:
                    self.chat_instance.show_next_message()
                    return True

            # Regular Enter key handling
            if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
                if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                    cursor = self.textCursor()
                    cursor.insertText("\n")
                    return True
                else:
                    self.chat_instance.send_message()
                    return True
        
        return super().eventFilter(obj, event)
    

    def update_suggestions(self):
        # Get the current text and cursor position
        text = self.toPlainText()
        cursor = self.textCursor()
        current_line = text[:cursor.position()].split('\n')[-1]

        # Only process if line starts with @ and provider is online
        if current_line.startswith("@") and self.chat_instance and self.chat_instance.provider_online:
            # Check if cursor is after a space or model name
            after_at = current_line[1:]
            if " " in after_at:
                self.suggestion_list.hide()
                return

            # Store current search text and start timer
            self._current_search = current_line[1:].lower()
            self._suggestion_timer.start(150)  # Delay of 150ms
        else:
            self.suggestion_list.hide()

    def _update_suggestion_list(self):
        """Actual update of suggestion list with debouncing."""
        if not hasattr(self.chat_instance.settings_interface, 'model_names'):
            return
        
        self.suggestion_list.clear()
        filtered_models = [
            model for model in self.chat_instance.settings_interface.model_names 
            if self._current_search.lower() in model.lower()
        ]

        if filtered_models:
            self.suggestion_list.addItems(filtered_models)
            self.suggestion_list.setCurrentRow(0)  # Select first item
            self.position_suggestion_list()
            self.suggestion_list.show()
        else:
            self.suggestion_list.hide()

    def position_suggestion_list(self):
        """Position the suggestion list below the cursor in the input field."""
        cursor_rect = self.cursorRect()
        global_pos = self.mapToGlobal(cursor_rect.bottomLeft())

        # Calculate the height based on the number of items (with a maximum)
        item_height = 25  # Approximate height per item
        num_items = min(self.suggestion_list.count(), 10)  # Changed from self.chat_instance.suggestion_list
        list_height = num_items * item_height + 4  # Add small padding

        # Set size and position
        suggestion_width = 300  # Fixed width for suggestion list
        self.suggestion_list.setFixedSize(suggestion_width, list_height)  # Changed
        
        # Position the list below the cursor
        self.suggestion_list.move(global_pos.x(), global_pos.y())

        # Ensure the suggestion list stays within screen bounds
        screen = QApplication.primaryScreen().availableGeometry()
        list_rect = self.suggestion_list.geometry()  # Changed
        
        # Adjust horizontal position if needed
        if list_rect.right() > screen.right():
            x_pos = screen.right() - suggestion_width
            self.suggestion_list.move(x_pos, list_rect.y())
        
        # Adjust vertical position if needed
        if list_rect.bottom() > screen.bottom():
            y_pos = global_pos.y() - list_height - cursor_rect.height()
            self.suggestion_list.move(list_rect.x(), y_pos)

    def insert_suggestion(self, item):
        """Insert the selected suggestion into the input field."""
        # Get current text and cursor position
        current_text = self.toPlainText()
        cursor = self.textCursor()
        position = cursor.position()

        # Find the @ before the cursor
        text_before_cursor = current_text[:position]
        at_index = text_before_cursor.rfind("@")

        if at_index != -1:
            # Replace the text from @ to cursor with the suggestion
            new_text = current_text[:at_index] + f"@{item.text()} "
            self.setPlainText(new_text)
            
            # Move cursor to end of inserted text
            cursor = self.textCursor()
            cursor.setPosition(len(new_text))
            self.setTextCursor(cursor)

        self.suggestion_list.hide()
        self.setFocus()