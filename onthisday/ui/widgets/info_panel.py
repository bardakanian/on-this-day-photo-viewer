from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget


class InfoPanel(QFrame):
    """The viewer's side panel listing one item's details as label/value pairs."""

    WIDTH = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "viewerPanel")
        self.setFixedWidth(self.WIDTH)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Info")
        title.setProperty("role", "panelTitle")
        title.setContentsMargins(18, 16, 18, 4)
        outer.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body = QWidget()
        self._rows = QVBoxLayout(self._body)
        self._rows.setContentsMargins(18, 8, 18, 18)
        self._rows.setSpacing(2)
        self._rows.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._body)
        outer.addWidget(scroll, 1)
        self.rows: list[tuple[str, str]] = []

    def show_message(self, text: str) -> None:
        self._clear()
        message = QLabel(text)
        message.setProperty("muted", True)
        message.setWordWrap(True)
        self._rows.addWidget(message)

    def show_rows(self, rows: list[tuple[str, str]]) -> None:
        self._clear()
        self.rows = rows
        for label, value in rows:
            caption = QLabel(label)
            caption.setProperty("role", "panelCaption")
            caption.setContentsMargins(0, 10, 0, 0)
            text = QLabel(value)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if label == "Path":
                text.setToolTip(value)
            self._rows.addWidget(caption)
            self._rows.addWidget(text)

    def _clear(self) -> None:
        self.rows = []
        while self._rows.count():
            widget = self._rows.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
