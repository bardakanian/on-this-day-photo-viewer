from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QTableView, QVBoxLayout, QWidget,
)

from ...core.models import VideoRecord
from ..widgets.common import EmptyState, PageHeader, SearchBox


class VideoTableModel(QAbstractTableModel):
    headers = ("Name", "Type", "Captured", "Location")

    def __init__(self, rows: list[VideoRecord] | None = None, parent=None):
        super().__init__(parent)
        self.rows = rows or []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        record = self.rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            values = (
                record.path.name,
                record.path.suffix.lstrip(".").upper(),
                record.capture_ts.replace("T", "  ") if record.capture_ts else "Date unavailable",
                str(record.path.parent),
            )
            return values[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return str(record.path)
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() == 1:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def replace(self, rows: list[VideoRecord]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


class VideoFilterModel(QSortFilterProxyModel):
    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        expression = self.filterRegularExpression()
        if not expression.pattern():
            return True
        model = self.sourceModel()
        return any(expression.match(str(model.data(model.index(source_row, column)))).hasMatch()
                   for column in range(model.columnCount()))


class VideosPage(QWidget):
    back_requested = Signal()
    open_requested = Signal(object)
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)
        self.header = PageHeader("Video Library", "Browse every indexed video in the current media folder")
        back = QPushButton("Back")
        back.setProperty("variant", "ghost")
        back.clicked.connect(self.back_requested)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_requested)
        self.header.actions.addWidget(back)
        self.header.actions.addWidget(refresh)
        layout.addWidget(self.header)
        controls = QHBoxLayout()
        self.count = QLabel()
        self.count.setProperty("muted", True)
        self.search = SearchBox("Search videos")
        self.search.setAccessibleName("Search indexed videos")
        controls.addWidget(self.count)
        controls.addStretch()
        controls.addWidget(self.search)
        layout.addLayout(controls)
        self.model = VideoTableModel(parent=self)
        self.proxy = VideoFilterModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(42)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.resizeSection(0, 250)
        header.resizeSection(1, 80)
        header.resizeSection(2, 190)
        self.table.doubleClicked.connect(self._open_index)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        open_action = self.table.addAction("Open Video")
        open_action.triggered.connect(self.open_selected)
        self.results = QStackedWidget()
        self.empty = EmptyState("No videos indexed", "Rescan your media library to discover supported video files.")
        self.results.addWidget(self.table)
        self.results.addWidget(self.empty)
        layout.addWidget(self.results, 1)
        self.search.textChanged.connect(self._filter)

    def set_records(self, rows: list[VideoRecord]) -> None:
        self.model.replace(rows)
        self.count.setText(f"{len(rows):,} indexed {'video' if len(rows) == 1 else 'videos'}")
        self.results.setCurrentWidget(self.table if rows else self.empty)
        if not rows:
            self.count.setText("No indexed videos")

    def _filter(self, text: str) -> None:
        self.proxy.setFilterFixedString(text)
        shown = self.proxy.rowCount()
        total = self.model.rowCount()
        self.count.setText(f"{shown:,} of {total:,} videos" if text else f"{total:,} indexed videos")

    def _open_index(self, index: QModelIndex) -> None:
        source = self.proxy.mapToSource(index)
        self.open_requested.emit(self.model.rows[source.row()].path)

    def open_selected(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        if indexes:
            self._open_index(indexes[0])
