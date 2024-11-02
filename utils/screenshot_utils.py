from PyQt6.QtWidgets import QWidget, QRubberBand, QApplication
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QImage

class ScreenshotSelector(QWidget):
    screenshot_taken = pyqtSignal(object)

    def __init__(self, screenshot):
        super().__init__()
        self.screenshot = screenshot
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
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

def process_image(image, MIN_IMAGE_SIZE=256, MAX_IMAGE_SIZE=1280):
    width = image.width()
    height = image.height()

    # Ensure dimensions are even
    new_width = width if width % 2 == 0 else width + 1
    new_height = height if height % 2 == 0 else height + 1

    # Create a new image with even dimensions, preserving all content
    even_image = QImage(new_width, new_height, QImage.Format.Format_RGB32)
    even_image.fill(QColor(0, 0, 0))  # Fill with black
    painter = QPainter(even_image)
    painter.drawImage(0, 0, image)
    painter.end()

    aspect_ratio = new_width / new_height

    if new_width < MIN_IMAGE_SIZE and new_height < MIN_IMAGE_SIZE:
        # Both dimensions are smaller than MIN_IMAGE_SIZE
        target_width = target_height = MIN_IMAGE_SIZE
    elif new_width > MAX_IMAGE_SIZE or new_height > MAX_IMAGE_SIZE:
        # At least one dimension is larger than MAX_IMAGE_SIZE
        if aspect_ratio > 1:  # Wider than tall
            target_width = MAX_IMAGE_SIZE
            target_height = int(MAX_IMAGE_SIZE / aspect_ratio)
            if target_height < MIN_IMAGE_SIZE:
                target_height = MIN_IMAGE_SIZE
                target_width = int(MIN_IMAGE_SIZE * aspect_ratio)
        else:  # Taller than wide
            target_height = MAX_IMAGE_SIZE
            target_width = int(MAX_IMAGE_SIZE * aspect_ratio)
            if target_width < MIN_IMAGE_SIZE:
                target_width = MIN_IMAGE_SIZE
                target_height = int(MIN_IMAGE_SIZE / aspect_ratio)
    else:
        # Image is already within bounds
        return even_image

    # Ensure dimensions are within MIN_IMAGE_SIZE and MAX_IMAGE_SIZE
    target_width = max(min(target_width, MAX_IMAGE_SIZE), MIN_IMAGE_SIZE)
    target_height = max(min(target_height, MAX_IMAGE_SIZE), MIN_IMAGE_SIZE)

    # Ensure dimensions are even
    target_width = target_width if target_width % 2 == 0 else target_width - 1
    target_height = target_height if target_height % 2 == 0 else target_height - 1

    return even_image.scaled(
        target_width,
        target_height,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation
    )
