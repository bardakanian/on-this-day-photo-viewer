from collections import defaultdict
from datetime import date
from pathlib import Path

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...core.constants import INITIAL_YEAR_BATCH
from ...core.models import MediaRecord
from ..widgets.common import EmptyState, PageHeader
from ..widgets.flow_layout import FlowLayout
from ..widgets.media_card import MediaCard


class YearSection(QWidget):
    open_requested = Signal(object)
    delete_requested = Signal(object)
    more_requested = Signal()

    def __init__(self, year: int, records: list[MediaRecord], root_folder: Path, pool: QThreadPool,
                 read_pool: QThreadPool, rendered: int = INITIAL_YEAR_BATCH, expanded: bool = True, parent=None):
        super().__init__(parent)
        self.year, self.records, self.root_folder, self.pool = year, records, root_folder, pool
        self.read_pool = read_pool
        self.rendered = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(12)
        header = QHBoxLayout()
        self.toggle = QPushButton(f"▾  {year}")
        self.toggle.setProperty("variant", "ghost")
        self.toggle.setStyleSheet("text-align: left; font-size: 16px; font-weight: 600;")
        self.toggle.clicked.connect(self._toggle)
        count = QLabel(f"{len(records):,} {'item' if len(records) == 1 else 'items'}")
        count.setProperty("role", "badge")
        header.addWidget(self.toggle)
        header.addWidget(count)
        header.addStretch()
        layout.addLayout(header)
        self.body = QWidget()
        self.flow = FlowLayout(self.body, spacing=16)
        layout.addWidget(self.body)
        self.more = QPushButton()
        self.more.setProperty("variant", "ghost")
        self.more.clicked.connect(self.more_requested)
        self.more.clicked.connect(lambda: self.render_more(INITIAL_YEAR_BATCH))
        layout.addWidget(self.more, alignment=Qt.AlignmentFlag.AlignLeft)
        self.render_more(max(INITIAL_YEAR_BATCH, rendered))
        if not expanded:
            self._toggle()

    @property
    def expanded(self) -> bool:
        return not self.body.isHidden()

    def _toggle(self) -> None:
        # isHidden, not isVisible: a section that isn't on screen yet still counts as expanded.
        visible = self.body.isHidden()
        self.body.setVisible(visible)
        self.more.setVisible(visible and self.rendered < len(self.records))
        self.toggle.setText(f"{'▾' if visible else '›'}  {self.year}")

    def render_more(self, amount: int) -> None:
        end = min(self.rendered + amount, len(self.records))
        for record in self.records[self.rendered:end]:
            card = MediaCard(record, self.root_folder, self.pool, self.read_pool)
            card.open_requested.connect(self.open_requested)
            card.delete_requested.connect(self.delete_requested)
            self.flow.addWidget(card)
        self.rendered = end
        remaining = len(self.records) - end
        self.more.setVisible(remaining > 0)
        self.more.setText(f"Load {min(INITIAL_YEAR_BATCH, remaining):,} more  ·  {remaining:,} remaining")
        self.body.updateGeometry()


class GalleryPage(QWidget):
    choose_folder_requested = Signal()
    open_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        # Separate pool for reading cached thumbnails so they never queue behind slow generation.
        self.read_pool = QThreadPool(self)
        self.read_pool.setMaxThreadCount(4)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(20)
        self.header = PageHeader("On This Day", "Rediscover photos and videos from years past")
        outer.addWidget(self.header)
        self.summary = QLabel()
        self.summary.setProperty("muted", True)
        outer.addWidget(self.summary)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 8, 24)
        self.content_layout.setSpacing(22)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)
        # Every record for the shown day, in display order; the viewer steps through this list.
        self.records: list[MediaRecord] = []
        self._shown_key: tuple | None = None
        self._pending_scroll: int | None = None
        self.scroll.verticalScrollBar().rangeChanged.connect(self._apply_pending_scroll)
        # Once the user scrolls or loads more, an old position must not be restored any more.
        self.scroll.verticalScrollBar().actionTriggered.connect(self._forget_pending_scroll)

    def cancel_pending(self) -> None:
        """Drop queued thumbnail jobs for cards about to be destroyed; running ones just finish."""
        self.pool.clear()
        self.read_pool.clear()

    def _forget_pending_scroll(self, *_args) -> None:
        self._pending_scroll = None

    def _apply_pending_scroll(self, _minimum: int, maximum: int) -> None:
        if self._pending_scroll is not None and maximum >= self._pending_scroll:
            self.scroll.verticalScrollBar().setValue(self._pending_scroll)
            self._pending_scroll = None

    def show_records(self, records: list[MediaRecord], selected_date: date, media_filter: str, folder: Path | None) -> None:
        self.cancel_pending()
        # Reloading the same day (after a rescan or a deletion) keeps the scroll position.
        key = (folder, selected_date, media_filter)
        same_view = key == self._shown_key
        self._shown_key = key
        self._pending_scroll = self.scroll.verticalScrollBar().value() if same_view else None
        if not same_view:
            self.scroll.verticalScrollBar().setValue(0)
        # Keep each year as it was (cards loaded with "Load more", collapsed or not), so the page
        # is as tall as before and the scroll position can be restored.
        previous = {
            section.year: (section.rendered, section.expanded)
            for section in self.content.findChildren(YearSection)
        } if same_view else {}
        self.records = []
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        display_date = selected_date.strftime("%B %d").replace(" 0", " ")
        self.header.title.setText(display_date)
        self.header.subtitle.setText(f"{media_filter} captured on this date across your library")
        if folder is None:
            self.summary.clear()
            empty = EmptyState("Choose your media library", "Select a folder to begin rediscovering moments from years past.", "Choose Folder")
            empty.action_requested.connect(self.choose_folder_requested)
            self.content_layout.addWidget(empty)
            return
        if not records:
            self.summary.setText(str(folder))
            empty = EmptyState(f"No {media_filter.lower()} for {display_date}", "Try another day, change the media filter, or rescan your library.")
            self.content_layout.addWidget(empty)
            return
        photos = sum(record.media_type == "image" for record in records)
        videos = len(records) - photos
        self.summary.setText(f"{len(records):,} items  ·  {photos:,} photos  ·  {videos:,} videos")
        grouped: dict[int, list[MediaRecord]] = defaultdict(list)
        for record in records:
            grouped[record.captured_at.year].append(record)
        for year in sorted(grouped, reverse=True):
            self.records.extend(grouped[year])
            rendered, expanded = previous.get(year, (INITIAL_YEAR_BATCH, True))
            section = YearSection(year, grouped[year], folder, self.pool, self.read_pool, rendered, expanded)
            section.more_requested.connect(self._forget_pending_scroll)
            section.open_requested.connect(self.open_requested)
            section.delete_requested.connect(self.delete_requested)
            self.content_layout.addWidget(section)
