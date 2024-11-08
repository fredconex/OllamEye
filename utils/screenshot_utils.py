from PyQt6.QtWidgets import QWidget, QRubberBand, QApplication
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import (
    QPainter,
    QPen,
    QColor,
    QPixmap,
    QCursor,
)


class ScreenshotSelector(QWidget):
    screenshot_taken = pyqtSignal(object)

    def __init__(self, screenshot):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        # Make widget focusable to receive key events
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # Get all available screens and their screenshots
        self.screens = QApplication.screens()
        self.screen_shots = {}  # Store screenshots for each screen
        
        # Capture initial screenshots for all screens
        for screen in self.screens:
            geometry = screen.geometry()
            self.screen_shots[screen] = screen.grabWindow(
                0,
                0,  # Local coordinates for each screen
                0,
                geometry.width(),
                geometry.height()
            )
        
        self.current_screen = None
        self.screenshot = screenshot  # Initial screenshot
        
        # Selection hasn't started
        self.selection_started = False
        
        self.begin = QPoint()
        self.end = QPoint()
        self.rubberband = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self.setWindowOpacity(1.0)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Fade animation
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self.fade_animation.setDuration(150)  # 150ms duration
        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        # Start timer to track cursor position
        self.cursor_timer = QTimer(self)
        self.cursor_timer.timeout.connect(self.track_cursor)
        self.cursor_timer.start(50)  # Check every 50ms
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)    

    def track_cursor(self):
        if not self.selection_started:
            cursor_pos = QCursor.pos()
            for screen in self.screens:
                if screen.geometry().contains(cursor_pos):
                    if screen != self.current_screen:
                        # Start fade out
                        self.fade_animation.setStartValue(1.0)
                        self.fade_animation.setEndValue(0.0)
                        self.fade_animation.finished.connect(
                            lambda: self.switch_screen(screen)
                        )
                        self.fade_animation.start()
                    break

    def switch_screen(self, new_screen):
        self.current_screen = new_screen
        
        # Capture fresh screenshot of the new screen
        geometry = new_screen.geometry()
        self.screen_shots[new_screen] = new_screen.grabWindow(
            0,
            0,  # Local coordinates for each screen
            0,
            geometry.width(),
            geometry.height()
        )
        self.screenshot = self.screen_shots[new_screen]
        self.setGeometry(new_screen.geometry())
        
        # Start fade in
        self.fade_animation.finished.disconnect()  # Disconnect previous connection
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.start()
        
        self.update()

    def paintEvent(self, event):
        if not self.current_screen:
            return
            
        painter = QPainter(self)
        
        # Draw the screenshot
        screen_rect = self.rect()
        painter.drawPixmap(screen_rect, self.screenshot)

        # Add dark overlay
        overlay = QColor(0, 0, 0, 120)
        painter.fillRect(screen_rect, overlay)

        if self.selection_started and not self.rubberband.isHidden():
            selected_rect = self.rubberband.geometry()
            painter.setClipRect(selected_rect)
            painter.drawPixmap(screen_rect, self.screenshot)
            painter.setClipRect(screen_rect)
            painter.setPen(QPen(QColor(255, 0, 255), 2))
            painter.drawRect(selected_rect)

    def mousePressEvent(self, event):
        if not self.current_screen:
            return
            
        # Only process left mouse button
        if event.button() != Qt.MouseButton.LeftButton:
            self.close()
            return
            
        cursor_pos = event.globalPosition().toPoint()
        if self.current_screen.geometry().contains(cursor_pos):
            self.selection_started = True
            self.begin = event.pos()
            self.end = event.pos()
            self.rubberband.setGeometry(QRect(self.begin, self.end))
            self.rubberband.show()
            self.cursor_timer.stop()  # Stop tracking cursor once selection starts

    def mouseMoveEvent(self, event):
        # Only process if left button is being held
        if not self.selection_started or event.buttons() != Qt.MouseButton.LeftButton:
            return
            
        if self.rubberband.isVisible():
            self.end = event.pos()
            self.rubberband.setGeometry(QRect(self.begin, self.end).normalized())
            self.update()

    def mouseReleaseEvent(self, event):
        # Only process left button release
        if not self.selection_started or event.button() != Qt.MouseButton.LeftButton or not self.rubberband.isVisible():
            return
            
        self.rubberband.hide()
        self.end = event.pos()
        selected_rect = QRect(self.begin, self.end).normalized()

        # Get the device pixel ratio for the current screen
        device_pixel_ratio = self.current_screen.devicePixelRatio()

        # Convert the selected rectangle to screen coordinates
        selected_rect = QRect(
            int(selected_rect.x() * device_pixel_ratio),
            int(selected_rect.y() * device_pixel_ratio),
            int(selected_rect.width() * device_pixel_ratio),
            int(selected_rect.height() * device_pixel_ratio),
        )

        if selected_rect.width() * selected_rect.height() < 64:
            screenshot = self.screenshot.copy()  # Use the entire screenshot
        else:
            screenshot = self.screenshot.copy(selected_rect)  # Use selected area
        
        self.screenshot_taken.emit(screenshot)
        self.close()

    def closeEvent(self, event):
        self.cursor_timer.stop()
        super().closeEvent(event)


def process_image(pixmap, min_size=256, max_size=1280):
    # Convert QPixmap to QImage if it isn't already a QImage
    image = pixmap.toImage() if isinstance(pixmap, QPixmap) else pixmap

    # Get the original size of the image
    original_width = image.width()
    original_height = image.height()

    # Ensure the scaled image fits within our constraints while maintaining aspect ratio
    if original_width <= min_size and original_height <= min_size:
        scale_factor = min(min_size / original_width, min_size / original_height)
    elif original_width >= max_size and original_height >= max_size:
        scale_factor = max(max_size / original_width, max_size / original_height)
    else:
        scale_factor = 1.0

    # Ensure the aspect ratio is maintained
    if original_width > original_height:
        new_width = min(original_width * scale_factor, max_size)
        new_height = int(new_width / original_width * original_height)
    else:  # original_width <= original_height
        new_height = min(original_height * scale_factor, max_size)
        new_width = int(original_width / original_height * new_height)

    # Create a scaled QImage object
    scaled_image = image.scaled(
        int(new_width),
        int(new_height),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    return scaled_image
