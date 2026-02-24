"""Custom QRangeSlider widget for selecting min/max range values."""

from PyQt5.QtCore import Qt, pyqtSignal, QRect, QPoint
from PyQt5.QtWidgets import QWidget, QStyle, QStyleOptionSlider
from PyQt5.QtGui import QPainter, QColor, QPen


class QRangeSlider(QWidget):
    """A slider widget with two handles for selecting a range (min, max).
    
    Signals:
        rangeChanged(float, float): Emitted when either handle is moved
    """
    
    rangeChanged = pyqtSignal(float, float)
    
    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(parent)
        
        self.orientation = orientation
        self.minimum = 0.0
        self.maximum = 1.0
        self.low_value = 0.0
        self.high_value = 1.0
        self.decimals = 4
        
        self.pressed_control = None  # None, 'low', 'high', or 'bar'
        self.hover_control = None
        self.click_offset = 0
        
        self.setMouseTracking(True)
        self.setMinimumHeight(40)
        
    def setRange(self, minimum: float, maximum: float):
        """Set the valid range for both handles."""
        self.minimum = minimum
        self.maximum = maximum
        self.low_value = max(self.low_value, minimum)
        self.high_value = min(self.high_value, maximum)
        self.update()
        
    def setValues(self, low: float, high: float):
        """Set both handle values."""
        self.low_value = max(self.minimum, min(low, self.maximum))
        self.high_value = max(self.minimum, min(high, self.maximum))
        
        # Ensure low <= high
        if self.low_value > self.high_value:
            self.low_value, self.high_value = self.high_value, self.low_value
            
        self.update()
        self.rangeChanged.emit(self.low_value, self.high_value)
        
    def setDecimals(self, decimals: int):
        """Set number of decimal places for display."""
        self.decimals = decimals
        
    def values(self):
        """Get current (low, high) values."""
        return (self.low_value, self.high_value)
    
    def _value_to_pixel(self, value: float) -> int:
        """Convert value to pixel position."""
        if self.maximum == self.minimum:
            return self._get_groove_rect().left()
        
        groove = self._get_groove_rect()
        ratio = (value - self.minimum) / (self.maximum - self.minimum)
        
        if self.orientation == Qt.Horizontal:
            return int(groove.left() + ratio * groove.width())
        else:
            return int(groove.bottom() - ratio * groove.height())
    
    def _pixel_to_value(self, pixel: int) -> float:
        """Convert pixel position to value."""
        groove = self._get_groove_rect()
        
        if self.orientation == Qt.Horizontal:
            if groove.width() == 0:
                return self.minimum
            ratio = (pixel - groove.left()) / groove.width()
        else:
            if groove.height() == 0:
                return self.minimum
            ratio = (groove.bottom() - pixel) / groove.height()
        
        ratio = max(0.0, min(1.0, ratio))
        value = self.minimum + ratio * (self.maximum - self.minimum)
        return round(value, self.decimals)
    
    def _get_groove_rect(self) -> QRect:
        """Get the rectangle for the slider groove."""
        margin = 15
        if self.orientation == Qt.Horizontal:
            return QRect(margin, self.height() // 2 - 3, 
                        self.width() - 2 * margin, 6)
        else:
            return QRect(self.width() // 2 - 3, margin, 
                        6, self.height() - 2 * margin)
    
    def _get_handle_rect(self, value: float) -> QRect:
        """Get the rectangle for a handle at given value."""
        pixel = self._value_to_pixel(value)
        handle_size = 12
        
        if self.orientation == Qt.Horizontal:
            return QRect(pixel - handle_size // 2, 
                        self.height() // 2 - handle_size // 2,
                        handle_size, handle_size)
        else:
            return QRect(self.width() // 2 - handle_size // 2,
                        pixel - handle_size // 2,
                        handle_size, handle_size)
    
    def _get_bar_rect(self) -> QRect:
        """Get the rectangle for the active range bar."""
        low_pixel = self._value_to_pixel(self.low_value)
        high_pixel = self._value_to_pixel(self.high_value)
        groove = self._get_groove_rect()
        
        if self.orientation == Qt.Horizontal:
            return QRect(low_pixel, groove.top(), 
                        high_pixel - low_pixel, groove.height())
        else:
            return QRect(groove.left(), high_pixel,
                        groove.width(), low_pixel - high_pixel)
    
    def mousePressEvent(self, event):
        """Handle mouse press to start dragging."""
        if event.button() != Qt.LeftButton:
            return
        
        pos = event.pos()
        
        # Check if clicking on handles
        low_rect = self._get_handle_rect(self.low_value)
        high_rect = self._get_handle_rect(self.high_value)
        bar_rect = self._get_bar_rect()
        
        if low_rect.contains(pos):
            self.pressed_control = 'low'
            pixel = self._value_to_pixel(self.low_value)
            self.click_offset = pos.x() - pixel if self.orientation == Qt.Horizontal else pos.y() - pixel
        elif high_rect.contains(pos):
            self.pressed_control = 'high'
            pixel = self._value_to_pixel(self.high_value)
            self.click_offset = pos.x() - pixel if self.orientation == Qt.Horizontal else pos.y() - pixel
        elif bar_rect.contains(pos):
            self.pressed_control = 'bar'
            self.bar_drag_start_low = self.low_value
            self.bar_drag_start_high = self.high_value
            self.bar_drag_start_pixel = pos.x() if self.orientation == Qt.Horizontal else pos.y()
        else:
            # Click on groove - move nearest handle
            click_value = self._pixel_to_value(pos.x() if self.orientation == Qt.Horizontal else pos.y())
            dist_to_low = abs(click_value - self.low_value)
            dist_to_high = abs(click_value - self.high_value)
            
            if dist_to_low < dist_to_high:
                self.low_value = click_value
                self.pressed_control = 'low'
            else:
                self.high_value = click_value
                self.pressed_control = 'high'
            
            self.click_offset = 0
            self.update()
            self.rangeChanged.emit(self.low_value, self.high_value)
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for dragging or hover."""
        pos = event.pos()
        
        if self.pressed_control == 'low':
            pixel = (pos.x() if self.orientation == Qt.Horizontal else pos.y()) - self.click_offset
            new_value = self._pixel_to_value(pixel)
            self.low_value = min(new_value, self.high_value)
            self.update()
            self.rangeChanged.emit(self.low_value, self.high_value)
            
        elif self.pressed_control == 'high':
            pixel = (pos.x() if self.orientation == Qt.Horizontal else pos.y()) - self.click_offset
            new_value = self._pixel_to_value(pixel)
            self.high_value = max(new_value, self.low_value)
            self.update()
            self.rangeChanged.emit(self.low_value, self.high_value)
            
        elif self.pressed_control == 'bar':
            current_pixel = pos.x() if self.orientation == Qt.Horizontal else pos.y()
            delta_pixel = current_pixel - self.bar_drag_start_pixel
            delta_value = self._pixel_to_value(self._value_to_pixel(self.minimum) + delta_pixel) - self.minimum
            
            new_low = self.bar_drag_start_low + delta_value
            new_high = self.bar_drag_start_high + delta_value
            
            # Constrain to bounds
            if new_low < self.minimum:
                offset = self.minimum - new_low
                new_low += offset
                new_high += offset
            if new_high > self.maximum:
                offset = new_high - self.maximum
                new_low -= offset
                new_high -= offset
            
            self.low_value = max(self.minimum, min(new_low, self.maximum))
            self.high_value = max(self.minimum, min(new_high, self.maximum))
            self.update()
            self.rangeChanged.emit(self.low_value, self.high_value)
        else:
            # Update hover state
            low_rect = self._get_handle_rect(self.low_value)
            high_rect = self._get_handle_rect(self.high_value)
            bar_rect = self._get_bar_rect()
            
            if low_rect.contains(pos):
                self.hover_control = 'low'
            elif high_rect.contains(pos):
                self.hover_control = 'high'
            elif bar_rect.contains(pos):
                self.hover_control = 'bar'
            else:
                self.hover_control = None
            
            self.update()
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release to stop dragging."""
        if event.button() == Qt.LeftButton:
            self.pressed_control = None
            self.update()
    
    def paintEvent(self, event):
        """Paint the range slider."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw groove
        groove = self._get_groove_rect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(200, 200, 200))
        painter.drawRoundedRect(groove, 3, 3)
        
        # Draw active range bar
        bar = self._get_bar_rect()
        painter.setBrush(QColor(0, 123, 255))
        painter.drawRoundedRect(bar, 3, 3)
        
        # Draw handles
        low_rect = self._get_handle_rect(self.low_value)
        high_rect = self._get_handle_rect(self.high_value)
        
        for handle_rect, control_name in [(low_rect, 'low'), (high_rect, 'high')]:
            # Handle color based on state
            if self.pressed_control == control_name:
                color = QColor(0, 86, 179)  # Darker blue when pressed
            elif self.hover_control == control_name:
                color = QColor(51, 153, 255)  # Lighter blue when hovering
            else:
                color = QColor(0, 123, 255)  # Normal blue
            
            painter.setBrush(color)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawEllipse(handle_rect)
