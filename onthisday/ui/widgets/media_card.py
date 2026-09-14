from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QCursor, QMouseEvent, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout

from ...core.media import get_cached_thumbnail, thumbnail_cache_path
from ...core.models import MediaRecord


class _ThumbnailSignals(QObject):
    ready = Signal(object)


class _ThumbnailTask(QRunnable):
    def __init__(self, record: MediaRecord):
        super().__init__()
        self.record = record
        self.signals = _ThumbnailSignals()

    def run(self) -> None:
        result = get_cached_thumbnail(
            self.record.path, self.record.media_type, self.record.file_size, self.record.modified_ns
        )
        self.signals.ready.emit(result)


class ClickablePreview(QLabel):
    activated = Signal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
        super().mouseReleaseEvent(event)


class MediaCard(QFrame):
    open_requested = Signal(object)

    def __init__(self, record: MediaRecord, root_folder: Path, pool: QThreadPool, parent=None):
        super().__init__(parent)
        self.record = record
        self._task = None
        self.setProperty("role", "surface")
        self.setFixedWidth(264)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 12)
        layout.setSpacing(5)
        self.preview = ClickablePreview()
        self.preview.setFixedSize(248, 186)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.preview.setProperty("muted", True)
        self.preview.setText("Video preview unavailable" if record.is_video else "Preview unavailable")
        self.preview.setStyleSheet("border-radius: 7px; background: rgba(127,127,127,0.10);")
        self.preview.activated.connect(lambda: self.open_requested.emit(record.path))
        layout.addWidget(self.preview)

        metadata = QLabel(("VIDEO  ·  " if record.is_video else "PHOTO  ·  ") + record.captured_at.strftime("%B %d, %Y  •  %H:%M"))
        metadata.setProperty("subtle", True)
        layout.addWidget(metadata)
        name = QLabel(record.path.name)
        name.setToolTip(str(record.path))
        name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(name)
        try:
            relative = record.path.parent.relative_to(root_folder)
            folder_text = "Library" if str(relative) == "." else str(relative)
        except ValueError:
            folder_text = str(record.path.parent)
        folder = QLabel(folder_text)
        folder.setProperty("muted", True)
        folder.setToolTip(str(record.path.parent))
        layout.addWidget(folder)

        cached = thumbnail_cache_path(record.path, record.file_size, record.modified_ns)
        if cached.exists():
            self._set_thumbnail(cached)
        else:
            task = _ThumbnailTask(record)
            task.signals.ready.connect(self._set_thumbnail)
            self._task = task
            pool.start(task)

    def _set_thumbnail(self, path: Path | None) -> None:
        if not path or not path.exists():
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return
        self.preview.setPixmap(pixmap.scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        self._task = None
