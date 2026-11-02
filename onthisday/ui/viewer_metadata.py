"""Background reading of the viewer's Info panel details, with a small cache."""

from collections import OrderedDict

from PySide6.QtCore import QObject, Signal, Slot

from ..core.metadata import MediaMetadata, read_metadata
from ..core.models import ViewerItem
from ..core.workqueue import WorkQueue

CACHE_SIZE = 20


class _Signals(QObject):
    loaded = Signal(object, object)  # item key, MediaMetadata


class ViewerMetadataLoader(QObject):
    """Emits `loaded(item_key, metadata)` on the UI thread."""

    loaded = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = WorkQueue(1, "viewer-metadata")
        self._cache: OrderedDict[tuple, MediaMetadata] = OrderedDict()
        self._signals = _Signals()
        self._signals.loaded.connect(self._on_loaded)

    def cached(self, item: ViewerItem) -> MediaMetadata | None:
        return self._cache.get(item.key)

    def request(self, item: ViewerItem) -> None:
        key = item.key
        # Only the item on screen matters; stepping quickly drops the ones skipped past.
        self._queue.retain([key])

        def job():
            result = read_metadata(item.path, item.media_type)
            try:
                self._signals.loaded.emit(key, result)
            except RuntimeError:
                pass  # the window closed while reading

        self._queue.submit(key, job)

    def shutdown(self) -> None:
        self._queue.shutdown()

    @Slot(object, object)
    def _on_loaded(self, key: tuple, result: MediaMetadata) -> None:
        self._cache[key] = result
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        self.loaded.emit(key, result)
