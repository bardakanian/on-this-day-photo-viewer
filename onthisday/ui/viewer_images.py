"""Background decoding of photos for the viewer, with a small cache for neighbours."""

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Signal, Slot
from PySide6.QtGui import QImage, QImageIOHandler, QImageReader

from ..core.media import display_size, get_cached_thumbnail, letterbox_content_rect, load_display_image
from ..core.models import ViewerItem
from ..core.workqueue import WorkQueue

CACHE_SIZE = 5  # current photo, its neighbours, and a little history
PLACEHOLDER = "placeholder"


Decoded = tuple[QImage | None, tuple[int, int] | None]  # image, the photo's full displayed size


def decode_display_image(path: Path, max_edge: int | None) -> Decoded:
    """EXIF-rotated image, at most `max_edge` px on its longest side (None: full size). Thread-safe.

    Also returns the photo's real size (rotation applied), so the viewer knows what "100%" is
    and when a sharper decode is needed, even though the index stores no dimensions.
    """
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if max_edge and size.isValid() and max(size.width(), size.height()) > max_edge:
        # For rotated photos size() is pre-rotation, but the longest side is the same either way.
        scale = max_edge / max(size.width(), size.height())
        reader.setScaledSize(QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale))))
    image = reader.read()
    if not image.isNull():
        natural = (size.width(), size.height()) if size.isValid() else (image.width(), image.height())
        if reader.transformation() & QImageIOHandler.Transformation.TransformationRotate90:
            natural = natural[1], natural[0]
        return image, natural
    # Formats Qt can't read here (or damaged files Pillow tolerates) go through Pillow.
    try:
        pil_image = load_display_image(path, max_edge or 1 << 16)
    except Exception:
        return None, None
    natural = display_size(path) or pil_image.size
    mode = pil_image.mode
    if mode not in {"RGB", "RGBA"}:
        pil_image = pil_image.convert("RGB")
        mode = "RGB"
    data = pil_image.tobytes()
    image_format = QImage.Format.Format_RGBA8888 if mode == "RGBA" else QImage.Format.Format_RGB888
    channels = 4 if mode == "RGBA" else 3
    image = QImage(data, pil_image.width, pil_image.height, pil_image.width * channels, image_format).copy()
    return image, natural


def load_placeholder(item: ViewerItem) -> QImage | None:
    """The gallery thumbnail with its letterbox padding cropped off, or None if that isn't reliable."""
    path = get_cached_thumbnail(item.path, "image", item.file_size, item.modified_ns)
    if path is None:
        return None
    image = QImage(str(path))
    if image.isNull():
        return None

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        colour = image.pixelColor(x, y)
        return colour.red(), colour.green(), colour.blue()

    rect = letterbox_content_rect(image.width(), image.height(), pixel)
    return image.copy(*rect) if rect else None


class _Signals(QObject):
    loaded = Signal(object, object)  # key, Decoded


class ViewerImageLoader(QObject):
    """Emits `loaded(item_key, image, natural_size, kind)` on the UI thread.

    kind is PLACEHOLDER, a screen edge in pixels, or None for full resolution.
    natural_size is None for placeholders.
    """

    loaded = Signal(object, object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = WorkQueue(2, "viewer-decode")
        self._cache: OrderedDict[tuple, Decoded] = OrderedDict()
        # Signals live on the UI thread, so results are delivered there.
        self._signals = _Signals()
        self._signals.loaded.connect(self._on_loaded)

    def cached(self, item: ViewerItem, max_edge: int | None) -> Decoded | None:
        result = self._cache.get(self._key(item, max_edge))
        if (result is None or result[0] is None) and max_edge is not None:
            # A full-resolution decode is just as good.
            result = self._cache.get(self._key(item, None))
        return result if result is not None and result[0] is not None else None

    def request(self, item: ViewerItem, max_edge: int | None) -> None:
        self._submit(self._key(item, max_edge), lambda: decode_display_image(item.path, max_edge))

    def request_placeholder(self, item: ViewerItem) -> None:
        self._submit(self._key(item, PLACEHOLDER), lambda: (load_placeholder(item), None))

    def focus(self, keep: list[tuple[ViewerItem, object]]) -> None:
        """Drop queued work that isn't for the current photo or its neighbours, in the given order."""
        self._queue.retain([self._key(item, kind) for item, kind in keep])

    def shutdown(self) -> None:
        self._queue.shutdown()

    def _submit(self, key: tuple, decode) -> None:
        if key in self._cache:
            self.loaded.emit(key[0], *self._cache[key], key[1])
            return

        def job():
            result = decode()
            try:
                self._signals.loaded.emit(key, result)
            except RuntimeError:
                pass  # the window closed while decoding

        self._queue.submit(key, job)

    @staticmethod
    def _key(item: ViewerItem, kind) -> tuple:
        return item.key, kind

    @Slot(object, object)
    def _on_loaded(self, key: tuple, result: Decoded) -> None:
        if key[1] != PLACEHOLDER:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        self.loaded.emit(key[0], *result, key[1])
