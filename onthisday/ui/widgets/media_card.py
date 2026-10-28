from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QCursor, QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from ...core.media import get_cached_thumbnail, legacy_thumbnail_cache_path, thumbnail_cache_path
from ...core.models import MediaRecord


def _load_scaled(path: Path | None, size: QSize) -> QImage | None:
    """Decode and scale a cached thumbnail. QImage is safe to use off the UI thread; QPixmap is not."""
    if path is None:
        return None
    image = QImage(str(path))
    if image.isNull():
        return None
    return image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


class _ThumbnailSignals(QObject):
    ready = Signal(object)
    needs_generation = Signal()


class _ThumbnailLoadTask(QRunnable):
    """Read an existing cached thumbnail. Fast, so it runs on its own pool and never waits behind ffmpeg."""

    def __init__(self, record: MediaRecord, size: QSize):
        super().__init__()
        self.record = record
        self.size = size
        self.signals = _ThumbnailSignals()

    def run(self) -> None:
        record = self.record
        cached = thumbnail_cache_path(record.path, record.file_size, record.modified_ns)
        if cached.exists():
            self.signals.ready.emit(_load_scaled(cached, self.size))
            return
        # Show an older low-resolution thumbnail while the sharp one is generated.
        legacy = legacy_thumbnail_cache_path(record.path, record.file_size, record.modified_ns)
        if legacy.exists():
            self.signals.ready.emit(_load_scaled(legacy, self.size))
        self.signals.needs_generation.emit()


class _ThumbnailTask(QRunnable):
    def __init__(self, record: MediaRecord, size: QSize):
        super().__init__()
        self.record = record
        self.size = size
        self.signals = _ThumbnailSignals()

    def run(self) -> None:
        result = get_cached_thumbnail(
            self.record.path, self.record.media_type, self.record.file_size, self.record.modified_ns
        )
        self.signals.ready.emit(_load_scaled(result, self.size))


class ClickablePreview(QLabel):
    activated = Signal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
        super().mouseReleaseEvent(event)


class MediaCard(QFrame):
    open_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, record: MediaRecord, root_folder: Path, pool: QThreadPool, read_pool: QThreadPool,
                 parent=None):
        super().__init__(parent)
        self.record = record
        self._tasks: list[QRunnable] = []  # keep Python wrappers alive while queued
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
        self.preview.activated.connect(lambda: self.open_requested.emit(record))
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
        details = QHBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(5)
        folder = QLabel(folder_text)
        folder.setProperty("muted", True)
        folder.setToolTip(str(record.path.parent))
        details.addWidget(folder, 1)
        delete = QPushButton("Move to Trash")
        delete.setProperty("variant", "danger")
        delete.setToolTip(f"Move {record.path.name} to Trash")
        delete.clicked.connect(lambda: self.delete_requested.emit(record))
        details.addWidget(delete)
        layout.addLayout(details)

        # Both decoding and scaling happen on worker threads; only the finished image reaches the UI thread.
        self.pool = pool
        self._ratio = self.devicePixelRatioF()
        self._pixel_size = self.preview.size() * self._ratio
        task = _ThumbnailLoadTask(record, self._pixel_size)
        task.signals.ready.connect(self._set_thumbnail)
        task.signals.needs_generation.connect(self._generate_thumbnail)
        self._tasks.append(task)
        read_pool.start(task)

    def _generate_thumbnail(self) -> None:
        task = _ThumbnailTask(self.record, self._pixel_size)
        task.signals.ready.connect(self._set_thumbnail)
        self._tasks.append(task)
        self.pool.start(task)

    def _set_thumbnail(self, image: QImage | None) -> None:
        if image is None:
            return
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(self._ratio)
        self.preview.setPixmap(pixmap)
