from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        self.title = QLabel(title)
        self.title.setProperty("role", "title")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setProperty("muted", True)
        text_layout.addWidget(self.title)
        text_layout.addWidget(self.subtitle)
        layout.addLayout(text_layout, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)


class SearchBox(QLineEdit):
    def __init__(self, placeholder: str = "Search", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(240)
        self._search_action = self.addAction(self._search_icon(), QLineEdit.ActionPosition.LeadingPosition)

    def _search_icon(self) -> QIcon:
        pixmap = QPixmap(18, 18)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.palette().color(self.foregroundRole()), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(QRectF(3.2, 3.2, 8.5, 8.5))
        painter.drawLine(10.2, 10.2, 14.5, 14.5)
        painter.end()
        return QIcon(pixmap)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in {QEvent.Type.PaletteChange, QEvent.Type.StyleChange}:
            self._search_action.setIcon(self._search_icon())
        super().changeEvent(event)


class EmptyState(QFrame):
    action_requested = Signal()

    def __init__(self, title: str, message: str, action_text: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("role", "surface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 38, 32, 38)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label = QLabel(title)
        title_label.setProperty("role", "section")
        message_label = QLabel(message)
        message_label.setProperty("muted", True)
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message_label)
        if action_text:
            button = QPushButton(action_text)
            button.setProperty("variant", "primary")
            button.clicked.connect(self.action_requested)
            layout.addSpacing(8)
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignCenter)
