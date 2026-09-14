import logging
import threading
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QStackedWidget, QStyle, QVBoxLayout, QWidget,
)

from ..core.database import MediaRepository
from ..core.indexer import MediaIndexer
from ..core.media import FFMPEG_ENABLED, HEIC_ENABLED, open_in_default_app
from ..core.settings import SettingsStore
from .dialogs import PreferencesDialog
from .pages import GalleryPage, VideosPage
from .theme import ThemeManager

LOGGER = logging.getLogger(__name__)


class IndexEvents(QObject):
    received = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, app: QApplication):
        super().__init__()
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self.repository = MediaRepository()
        self.theme = ThemeManager(app, self.settings.theme)
        self.current_date = date.today()
        self.media_filter = "All"
        self.index_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.active_scan_id = 0
        self.pending_index_start = False
        self.index_events = IndexEvents()
        self.index_events.received.connect(self._handle_index_event)

        self.setWindowTitle("On This Day")
        self.setMinimumSize(900, 620)
        self.resize(1240, 840)
        self._build_ui()
        self._build_menus()
        QTimer.singleShot(0, self._startup)

    @property
    def root_folder(self) -> Path | None:
        return self.settings.photo_folder

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        toolbar = QFrame()
        toolbar.setProperty("role", "toolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(18, 10, 18, 10)
        toolbar_layout.setSpacing(8)
        self.folder_button = QPushButton("Choose Folder")
        self.folder_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.folder_button.clicked.connect(self.choose_folder)
        toolbar_layout.addWidget(self.folder_button)
        self.rescan_button = QPushButton("Rescan")
        self.rescan_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.rescan_button.clicked.connect(self.start_indexing)
        toolbar_layout.addWidget(self.rescan_button)
        self.videos_button = QPushButton("Video Library")
        self.videos_button.clicked.connect(self.show_videos)
        toolbar_layout.addWidget(self.videos_button)
        toolbar_layout.addStretch()
        self.date_navigation = QWidget()
        date_layout = QHBoxLayout(self.date_navigation)
        date_layout.setContentsMargins(0, 0, 0, 0)
        date_layout.setSpacing(8)
        previous = QPushButton()
        previous.setAccessibleName("Previous day")
        previous.setToolTip("Previous day")
        previous.setProperty("compact", True)
        previous.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        previous.clicked.connect(lambda: self.change_day(-1))
        date_layout.addWidget(previous)
        today = QPushButton("Today")
        today.setProperty("variant", "ghost")
        today.clicked.connect(self.go_today)
        date_layout.addWidget(today)
        following = QPushButton()
        following.setAccessibleName("Next day")
        following.setToolTip("Next day")
        following.setProperty("compact", True)
        following.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        following.clicked.connect(lambda: self.change_day(1))
        date_layout.addWidget(following)
        self.filter_box = QComboBox()
        self.filter_box.addItems(["All", "Photos", "Videos"])
        self.filter_box.setAccessibleName("Media type")
        self.filter_box.currentTextChanged.connect(self._filter_changed)
        date_layout.addSpacing(6)
        date_layout.addWidget(self.filter_box)
        toolbar_layout.addWidget(self.date_navigation)
        root_layout.addWidget(toolbar)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.hide()
        root_layout.addWidget(self.progress)
        self.stack = QStackedWidget()
        self.gallery = GalleryPage()
        self.gallery.choose_folder_requested.connect(self.choose_folder)
        self.gallery.open_requested.connect(self.open_media)
        self.videos = VideosPage()
        self.videos.back_requested.connect(lambda: self.stack.setCurrentWidget(self.gallery))
        self.videos.refresh_requested.connect(self._load_videos)
        self.videos.open_requested.connect(self.open_media)
        self.stack.addWidget(self.gallery)
        self.stack.addWidget(self.videos)
        self.stack.currentChanged.connect(self._page_changed)
        root_layout.addWidget(self.stack, 1)
        self.status = QLabel("Ready")
        self.status.setProperty("muted", True)
        self.statusBar().addWidget(self.status, 1)
        self.folder_status = QLabel("No folder selected")
        self.folder_status.setProperty("subtle", True)
        self.folder_status.setMaximumWidth(440)
        self.statusBar().addPermanentWidget(self.folder_status)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        choose = QAction("Choose Media Folder…", self, shortcut=QKeySequence("Ctrl+O"))
        choose.triggered.connect(self.choose_folder)
        file_menu.addAction(choose)
        rescan = QAction("Rescan Library", self, shortcut=QKeySequence("Ctrl+R"))
        rescan.triggered.connect(self.start_indexing)
        file_menu.addAction(rescan)
        file_menu.addSeparator()
        close = QAction("Close Window", self, shortcut=QKeySequence.StandardKey.Close)
        close.triggered.connect(self.close)
        file_menu.addAction(close)

        view_menu = self.menuBar().addMenu("View")
        previous = QAction("Previous Day", self, shortcut=QKeySequence("Ctrl+Left"))
        previous.triggered.connect(lambda: self.change_day(-1))
        view_menu.addAction(previous)
        following = QAction("Next Day", self, shortcut=QKeySequence("Ctrl+Right"))
        following.triggered.connect(lambda: self.change_day(1))
        view_menu.addAction(following)
        today = QAction("Go to Today", self, shortcut=QKeySequence("Ctrl+T"))
        today.triggered.connect(self.go_today)
        view_menu.addAction(today)
        view_menu.addSeparator()
        videos = QAction("Video Library", self, shortcut=QKeySequence("Ctrl+Shift+V"))
        videos.triggered.connect(self.show_videos)
        view_menu.addAction(videos)
        search = QAction("Search Videos", self, shortcut=QKeySequence.StandardKey.Find)
        search.triggered.connect(self.focus_search)
        view_menu.addAction(search)

        app_menu = self.menuBar().addMenu("Settings")
        preferences = QAction("Settings…", self, shortcut=QKeySequence("Ctrl+,"))
        preferences.triggered.connect(self.show_preferences)
        app_menu.addAction(preferences)

    def _startup(self) -> None:
        if self.root_folder:
            self.folder_status.setText(str(self.root_folder))
            self.folder_status.setToolTip(str(self.root_folder))
            self.folder_button.setText("Change Folder")
        self.refresh_gallery()
        missing = []
        if not HEIC_ENABLED:
            missing.append("HEIC image support")
        if not FFMPEG_ENABLED:
            missing.append("video thumbnails and embedded dates")
        if missing:
            self.status.setText("Optional support unavailable: " + ", ".join(missing))

    def choose_folder(self) -> None:
        initial = str(self.root_folder or Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Choose Photo and Video Folder", initial)
        if not selected:
            return
        folder = Path(selected)
        if not folder.is_dir():
            self._error("Folder unavailable", "The selected folder could not be opened.")
            return
        self.stop_event.set()
        self.settings.photo_folder = folder
        try:
            self.settings_store.save(self.settings)
        except OSError:
            LOGGER.exception("Could not save selected media folder")
            self._error("Settings could not be saved", "Your folder selection will work for this session but may not be remembered.")
        self.current_date = date.today()
        self.folder_status.setText(str(folder))
        self.folder_status.setToolTip(str(folder))
        self.folder_button.setText("Change Folder")
        self.refresh_gallery()
        self.start_indexing()

    def start_indexing(self) -> None:
        if self.root_folder is None:
            self.choose_folder()
            return
        if self.index_thread and self.index_thread.is_alive():
            self.pending_index_start = True
            self.stop_event.set()
            self.status.setText("Stopping the current scan…")
            QTimer.singleShot(80, self.start_indexing)
            return
        self.pending_index_start = False
        self.active_scan_id += 1
        self.stop_event = threading.Event()
        indexer = MediaIndexer(self.root_folder, self.stop_event, self.active_scan_id, self.index_events.received.emit)
        self.index_thread = threading.Thread(target=indexer.run, daemon=True, name="media-indexer")
        self.index_thread.start()

    def _handle_index_event(self, event: dict) -> None:
        if event.get("scan_id") != self.active_scan_id:
            return
        event_type = event.get("type")
        if event_type == "scan_started":
            self.progress.show()
            self.rescan_button.setEnabled(False)
            self.status.setText("Indexing media library…")
        elif event_type == "scan_progress":
            self.status.setText(
                f"Scanning  ·  {event['scanned']:,} checked  ·  {event['updated']:,} updated  ·  {event['unchanged']:,} cached"
            )
        elif event_type in {"scan_complete", "scan_cancelled", "scan_error"}:
            self.progress.hide()
            if self.pending_index_start:
                self.status.setText("Starting requested scan…")
                return
            self.rescan_button.setEnabled(True)
            if event_type == "scan_complete":
                self.status.setText(
                    f"Library ready  ·  {event['total_indexed']:,} items  ·  {event['updated']:,} updated  ·  {event['deleted']:,} removed"
                )
                self.refresh_gallery()
                if self.stack.currentWidget() is self.videos:
                    self._load_videos()
            elif event_type == "scan_cancelled":
                self.status.setText("Indexing cancelled")
            else:
                self.status.setText("Indexing failed")
                LOGGER.error("Indexing failed: %s", event.get("message", "Unknown error"))
                self._error("Unable to index the library", "The folder may be unavailable or contain files that cannot be read. Details were written to the application log.")

    def refresh_gallery(self) -> None:
        records = []
        if self.root_folder:
            try:
                records = self.repository.matches_for_date(self.root_folder, self.current_date, self.media_filter)
            except Exception:
                LOGGER.exception("Could not query gallery records")
                self._error("Unable to load your library", "The media index could not be read. Try rescanning the library.")
        self.gallery.show_records(records, self.current_date, self.media_filter, self.root_folder)

    def _filter_changed(self, value: str) -> None:
        self.media_filter = value
        self.refresh_gallery()

    def _page_changed(self, index: int) -> None:
        self.date_navigation.setVisible(self.stack.widget(index) is self.gallery)

    def change_day(self, amount: int) -> None:
        self.current_date += timedelta(days=amount)
        self.stack.setCurrentWidget(self.gallery)
        self.refresh_gallery()

    def go_today(self) -> None:
        self.current_date = date.today()
        self.stack.setCurrentWidget(self.gallery)
        self.refresh_gallery()

    def show_videos(self) -> None:
        if self.root_folder is None:
            QMessageBox.information(self, "Choose a media folder", "Choose a media folder before opening the video library.")
            return
        self._load_videos()
        self.stack.setCurrentWidget(self.videos)

    def _load_videos(self) -> None:
        if not self.root_folder:
            self.videos.set_records([])
            return
        try:
            self.videos.set_records(self.repository.all_videos(self.root_folder))
        except Exception:
            LOGGER.exception("Could not query video records")
            self._error("Unable to load videos", "The video index could not be read. Try rescanning the library.")

    def focus_search(self) -> None:
        self.show_videos()
        if self.stack.currentWidget() is self.videos:
            self.videos.search.setFocus()
            self.videos.search.selectAll()

    def open_media(self, path: Path) -> None:
        success, detail = open_in_default_app(path)
        if not success:
            self._error("Unable to open file", "The file may have moved or you may not have permission to access it.\n\n" + (detail or ""))

    def show_preferences(self) -> None:
        dialog = PreferencesDialog(self.settings.theme, self)
        if dialog.exec():
            self.settings.theme = dialog.selected_theme
            self.theme.apply(self.settings.theme)
            try:
                self.settings_store.save(self.settings)
            except OSError:
                LOGGER.exception("Could not save appearance preference")
                self._error("Settings could not be saved", "The appearance changed for this session but may not be remembered.")

    def _error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_event.set()
        self.gallery.pool.clear()
        event.accept()
