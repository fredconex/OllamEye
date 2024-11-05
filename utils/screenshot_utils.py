from PyQt6.QtWidgets import QWidget, QRubberBand, QApplication
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import (
    QPainter,
    QPen,
    QColor,
    QImage,
    QPixmap,
)


class ScreenshotSelector(QWidget):
    screenshot_taken = pyqtSignal(object)

    def __init__(self, screenshot):
        super().__init__()
        self.screenshot = screenshot
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setGeometry(QApplication.primaryScreen().geometry())
        self.begin = QPoint()
        self.end = QPoint()
        self.rubberband = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self.setWindowOpacity(1.0)  # Increased from 0.3 for better visibility
        self.setCursor(Qt.CursorShape.CrossCursor)  # Set crosshair cursor
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.screenshot)

        # Darker overlay
        overlay = QColor(0, 0, 0, 120)
        painter.fillRect(self.rect(), overlay)

        if not self.rubberband.isHidden():
            selected_rect = self.rubberband.geometry()

            # Draw the original screenshot in the selected area
            painter.setClipRect(selected_rect)
            painter.drawPixmap(self.rect(), self.screenshot)
            painter.setClipRect(self.rect())

            # Draw border around selected area
            painter.setPen(QPen(QColor(255, 0, 255), 2))
            painter.drawRect(selected_rect)

    def mousePressEvent(self, event):
        self.begin = event.pos()
        self.end = event.pos()
        self.rubberband.setGeometry(QRect(self.begin, self.end))
        self.rubberband.show()

    def mouseMoveEvent(self, event):
        self.end = event.pos()
        self.rubberband.setGeometry(QRect(self.begin, self.end).normalized())
        self.update()  # Trigger a repaint

    def mouseReleaseEvent(self, event):
        self.rubberband.hide()
        selected_area = QRect(self.begin, self.end).normalized()

        # Check if selected area is smaller than 8x8
        if selected_area.width() * selected_area.height() < 8:
            screenshot = self.screenshot.copy()  # Use the entire screenshot
        else:
            screenshot = self.screenshot.copy(selected_area)  # Use selected area

        self.screenshot_taken.emit(screenshot)
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


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
