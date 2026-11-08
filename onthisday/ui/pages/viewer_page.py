from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from ...core.media import read_only_trash_reason
from ...core.metadata import MediaMetadata, metadata_rows
from ...core.models import ViewerItem
from ..viewer_images import PLACEHOLDER, ViewerImageLoader
from ..viewer_metadata import ViewerMetadataLoader
from ..widgets.image_canvas import ImageCanvas
from ..widgets.info_panel import InfoPanel
from ..widgets.video_player import VideoPlayer


def native_keys(keys: str) -> str:
    """A shortcut as this platform writes it: "Ctrl+0" reads ⌘0 on macOS and Ctrl+0 on Windows."""
    return QKeySequence(keys).toString(QKeySequence.SequenceFormat.NativeText)


class ViewerPage(QWidget):
    """Full-window viewer for one item at a time, with previous/next navigation."""

    closed = Signal()
    open_externally_requested = Signal(object)  # ViewerItem
    trash_requested = Signal(object)            # ViewerItem

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("viewerPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.images = ViewerImageLoader(self)
        self.images.loaded.connect(self._image_loaded)
        self.metadata = ViewerMetadataLoader(self)
        self.metadata.loaded.connect(self._metadata_loaded)
        self.items: list[ViewerItem] = []
        self.index = 0
        self._full_requested = False
        self._screen_decoded = False
        # The original and the saved preview load side by side; either can finish first.
        self._original_failed = False
        self._placeholder_done = False
        self.offline = False  # the library's drive is disconnected: saved previews only
        self.read_only = False  # the library's drive can't be changed: nothing can be moved to the Trash

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        top = QFrame()
        top.setProperty("role", "viewerBar")
        bar = QHBoxLayout(top)
        bar.setContentsMargins(14, 8, 14, 8)
        bar.setSpacing(8)
        back = self._button("‹  Back", "Back (Esc)")
        back.clicked.connect(self.close_viewer)
        bar.addWidget(back)
        bar.addSpacing(8)
        self.previous_button = self._button("‹", "Previous (←)", compact=True)
        self.previous_button.clicked.connect(lambda: self.step(-1))
        self.next_button = self._button("›", "Next (→)", compact=True)
        self.next_button.clicked.connect(lambda: self.step(1))
        bar.addWidget(self.previous_button)
        bar.addWidget(self.next_button)
        bar.addStretch(1)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle = QLabel()
        self.subtitle.setProperty("muted", True)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        bar.addLayout(titles)
        bar.addStretch(1)
        self.zoom_label = QLabel()
        self.zoom_label.setProperty("muted", True)
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(self.zoom_label)
        self.fit_button = self._button("100%", f"Actual size ({native_keys('Ctrl+0')})")
        self.fit_button.clicked.connect(lambda: self.canvas.toggle_actual_size())
        bar.addWidget(self.fit_button)
        self.position_label = QLabel()
        self.position_label.setProperty("muted", True)
        self.position_label.setMinimumWidth(80)
        self.position_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(self.position_label)
        bar.addSpacing(8)
        self.info_button = self._button("Info", "Show or hide details (I)")
        self.info_button.setCheckable(True)
        self.info_button.toggled.connect(self._set_info_visible)
        bar.addWidget(self.info_button)
        self.open_button = self._button("Open in Default App", "Open in the default app")
        self.open_button.clicked.connect(self._open_externally)
        bar.addWidget(self.open_button)
        self.trash_button = trash = self._button("Move to Trash", f"Move to Trash ({native_keys('Ctrl+Backspace')})")
        trash.setProperty("variant", "danger")
        trash.clicked.connect(self._trash_current)
        bar.addWidget(trash)
        layout.addWidget(top)

        self.content = QStackedWidget()
        self.canvas = ImageCanvas()
        self.canvas.zoom_changed.connect(self._zoom_changed)
        self.canvas.needs_full_resolution.connect(self._request_full_resolution)
        self.video = VideoPlayer()
        self.video.open_externally_requested.connect(self._open_externally)
        self.content.addWidget(self.canvas)
        self.content.addWidget(self.video)
        self.info_panel = InfoPanel()
        self.info_panel.hide()
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.content, 1)
        body.addWidget(self.info_panel)
        layout.addLayout(body, 1)

        def shortcut(keys, slot):
            item = QShortcut(QKeySequence(keys), self)
            item.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            item.activated.connect(slot)

        shortcut("Esc", self.close_viewer)
        shortcut("Left", lambda: self.step(-1))
        shortcut("Right", lambda: self.step(1))
        shortcut("Home", lambda: self.go_to(0))
        shortcut("End", lambda: self.go_to(len(self.items) - 1))
        shortcut("Space", self._space)
        shortcut("Shift+Left", lambda: self.video.seek_by(-5000))
        shortcut("Shift+Right", lambda: self.video.seek_by(5000))
        shortcut("M", self.video.toggle_mute)
        shortcut("Ctrl+=", self.canvas.zoom_in)
        shortcut("Ctrl++", self.canvas.zoom_in)
        shortcut("Ctrl+-", self.canvas.zoom_out)
        shortcut("Ctrl+0", self.canvas.toggle_actual_size)
        shortcut("Ctrl+Backspace", self._trash_current)
        shortcut("I", self.info_button.toggle)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @staticmethod
    def _button(text: str, tooltip: str, compact: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        # Keyboard shortcuts belong to the viewer, not to whichever button was last clicked.
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if compact:
            button.setProperty("compact", True)
        return button

    # Public API ------------------------------------------------------------

    @property
    def current_item(self) -> ViewerItem | None:
        return self.items[self.index] if 0 <= self.index < len(self.items) else None

    def set_offline(self, offline: bool, read_only: bool = False) -> None:
        """While the library's drive is disconnected, photos show their saved preview and files can't
        be opened elsewhere or moved to the Trash."""
        self.offline = offline
        self.read_only = read_only
        for button in (self.open_button, self.trash_button):
            button.setEnabled(not offline)
        reason = "The library's drive isn't connected"
        self.open_button.setToolTip(reason if offline else "Open in the default app")
        self.trash_button.setEnabled(not offline and not read_only)
        self.trash_button.setToolTip(reason if offline else read_only_trash_reason() if read_only
                                     else f"Move to Trash ({native_keys('Ctrl+Backspace')})")

    def show_items(self, items: list[ViewerItem], index: int) -> None:
        self.items = items
        self.go_to(index)
        self.setFocus()

    def go_to(self, index: int) -> None:
        if not self.items:
            return
        self.index = max(0, min(len(self.items) - 1, index))
        self._show_current()

    def step(self, direction: int) -> None:
        if 0 <= self.index + direction < len(self.items):
            self.go_to(self.index + direction)

    def close_viewer(self) -> None:
        self.stop()
        self.closed.emit()

    def stop(self) -> None:
        """Stop playback and release the video file."""
        self.video.stop()

    def remove_current(self) -> None:
        """Drop the current item (it was moved to Trash) and show the next one, or close."""
        if self.current_item is None:
            return
        del self.items[self.index]
        if not self.items:
            self.close_viewer()
            return
        self.go_to(min(self.index, len(self.items) - 1))

    def shutdown(self) -> None:
        self.video.stop()
        self.images.shutdown()
        self.metadata.shutdown()

    # Showing items -----------------------------------------------------------

    def _display_edge(self) -> int:
        """Longest side worth decoding for the screen: device pixels of the screen's long side."""
        screen = self.screen()
        if screen is None:
            return 2560
        size = screen.size()
        return int(max(size.width(), size.height()) * screen.devicePixelRatio())

    def _update_labels(self, item: ViewerItem) -> None:
        self.title.setText(item.path.name)
        self.title.setToolTip(str(item.path))
        self.subtitle.setText(item.captured_at.strftime("%B %d, %Y  •  %H:%M") if item.captured_at else "Date unavailable")
        self.position_label.setText(f"{self.index + 1:,} of {len(self.items):,}")
        self.previous_button.setEnabled(self.index > 0)
        self.next_button.setEnabled(self.index < len(self.items) - 1)

    def _show_current(self) -> None:
        item = self.current_item
        if item is None:
            return
        self._update_labels(item)
        self._full_requested = False
        self._original_failed = self._placeholder_done = False
        if item.is_video:
            self.zoom_label.clear()
            self.fit_button.hide()
            self.canvas.clear()
            self.content.setCurrentWidget(self.video)
            if self.offline:
                self.video.show_unavailable("The drive holding this video isn't connected.\n"
                                            "Connect it to play the video.", can_open=False)
            else:
                self.video.load(item.path)
        else:
            self.video.stop()
            self.fit_button.show()
            self.content.setCurrentWidget(self.canvas)
            self._show_photo(item)
        self._prefetch_neighbours()
        self._update_info()

    def _show_photo(self, item: ViewerItem) -> None:
        edge = self._display_edge()
        decoded = self.images.cached(item, edge)
        self._screen_decoded = decoded is not None
        if decoded is not None:
            image, natural = decoded
            self.canvas.set_content(QPixmap.fromImage(image), natural)
        else:
            # The gallery thumbnail shows first; the sharp decode then replaces it in place.
            self.canvas.set_message("Loading…")
            self.images.request_placeholder(item, keep_padding=self.offline)
            self.images.request(item, edge)

    def _prefetch_neighbours(self) -> None:
        edge = self._display_edge()
        keep: list[tuple[ViewerItem, object]] = []
        current = self.current_item
        if current is not None and not current.is_video:
            keep += [(current, PLACEHOLDER), (current, edge)]
            if self._full_requested:
                keep.append((current, None))
        neighbours = []
        for offset in (1, -1):
            index = self.index + offset
            if 0 <= index < len(self.items) and not self.items[index].is_video:
                neighbours.append(self.items[index])
        keep += [(item, edge) for item in neighbours]
        self.images.focus(keep)
        for item in neighbours:
            if self.images.cached(item, edge) is None:
                self.images.request(item, edge)

    def _image_loaded(self, key, image, natural, kind) -> None:
        current = self.current_item
        if current is None or current.key != key or current.is_video:
            return  # a stale result for an item we've moved away from (or a prefetch)
        if kind == PLACEHOLDER:
            self._placeholder_done = True
            # Only useful until the screen-sized decode lands, or instead of an original that can't be read.
            if image is not None and not self._screen_decoded:
                self.canvas.set_content(QPixmap.fromImage(image), self._offline_display_size(image) if self.offline else None)
            if self._original_failed:
                self._show_original_failure()
            return
        if image is None:
            if kind is not None and not self._screen_decoded:
                self._original_failed = True
                if self.canvas.has_image or self._placeholder_done:
                    self._show_original_failure()
                # Otherwise the saved preview is still loading; it reports the failure when it lands.
            return
        if kind is not None:
            self._screen_decoded = True
        self.canvas.set_pixmap(QPixmap.fromImage(image), natural)

    def _offline_display_size(self, image) -> tuple[int, int]:
        """With no original to load, show the saved preview fitted to the window instead of at its
        own small size: soft, but far easier to see."""
        width, height = image.width(), image.height()
        scale = max(1.0, min(self.canvas.width() / max(1, width), self.canvas.height() / max(1, height)))
        return round(width * scale), round(height * scale)

    def _show_original_failure(self) -> None:
        if self.canvas.has_image:
            # The original can't be read (its drive may be disconnected): keep the saved preview.
            note = "saved preview; original unavailable"
            if note not in self.subtitle.text():
                self.subtitle.setText(f"{self.subtitle.text()}  ·  {note}")
        elif self.offline:
            self.canvas.set_message("The drive holding this photo isn't connected, and no preview was saved.")
        else:
            self.canvas.set_message("This photo can't be displayed.")

    # Info panel --------------------------------------------------------------

    def _set_info_visible(self, visible: bool) -> None:
        self.info_panel.setVisible(visible)
        self._update_info()

    def _update_info(self) -> None:
        item = self.current_item
        if item is None or self.info_panel.isHidden():
            return  # details are only read while the panel is open
        cached = self.metadata.cached(item)
        if cached is not None:
            self.info_panel.show_rows(metadata_rows(cached, item.captured_at))
        else:
            self.info_panel.show_message("Loading…")
            self.metadata.request(item)

    def _metadata_loaded(self, key, metadata: MediaMetadata) -> None:
        current = self.current_item
        if current is not None and current.key == key and not self.info_panel.isHidden():
            self.info_panel.show_rows(metadata_rows(metadata, current.captured_at))

    def _request_full_resolution(self) -> None:
        item = self.current_item
        # Wait for the screen-sized decode first; it is enough unless the user zooms in.
        if item is None or item.is_video or not self._screen_decoded or self._full_requested:
            return
        self._full_requested = True
        self.images.request(item, None)

    def _zoom_changed(self, scale: float) -> None:
        self.zoom_label.setText("Fit" if self.canvas.is_fitted else f"{round(scale * 100)}%")
        self.fit_button.setText("100%" if self.canvas.is_fitted else "Fit")
        self.fit_button.setToolTip(f"{'Actual size' if self.canvas.is_fitted else 'Zoom to fit'} ({native_keys('Ctrl+0')})")

    def _space(self) -> None:
        item = self.current_item
        if item is not None and item.is_video:
            self.video.toggle_play()
        else:
            self.close_viewer()

    def _open_externally(self) -> None:
        if self.current_item is not None:
            self.open_externally_requested.emit(self.current_item)

    def _trash_current(self) -> None:
        if self.current_item is not None and not self.offline and not self.read_only:
            # Release the file before it is moved.
            self.stop()
            self.trash_requested.emit(self.current_item)
