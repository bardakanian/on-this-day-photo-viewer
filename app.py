import hashlib
import json
import os
import queue
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIC_ENABLED = True
except ImportError:
    HEIC_ENABLED = False

try:
    import imageio_ffmpeg

    FFMPEG_ENABLED = True
except ImportError:
    imageio_ffmpeg = None
    FFMPEG_ENABLED = False


Image.MAX_IMAGE_PIXELS = None

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    ".webp",
    ".heic",
    ".heif",
}

VIDEO_EXTENSIONS = {
    ".mov",
    ".mp4",
    ".m4v",
    ".avi",
    ".mkv",
    ".wmv",
    ".mpeg",
    ".mpg",
    ".3gp",
}

SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

THUMBNAIL_SIZE = (240, 180)
COLUMNS = 4
WINDOW_TITLE = "On This Day Photos"

APP_DIR = Path.home() / ".on_this_day_photo_viewer"
CONFIG_FILE = APP_DIR / "config.json"
DB_FILE = APP_DIR / "photo_index.sqlite3"
THUMBNAIL_DIR = APP_DIR / "thumbnails"

BATCH_COMMIT_SIZE = 250
VIDEO_METADATA_VERSION = 5
RENDER_BATCH_SIZE = 60


def ensure_app_dirs():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)


def load_saved_folder():
    try:
        if not CONFIG_FILE.exists():
            return None

        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        folder_text = data.get("photo_folder", "")

        if not folder_text:
            return None

        folder = Path(folder_text).expanduser()

        if folder.exists() and folder.is_dir():
            return folder
    except Exception:
        pass

    return None


def save_folder(folder):
    try:
        ensure_app_dirs()
        CONFIG_FILE.write_text(
            json.dumps(
                {"photo_folder": str(folder)},
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def open_database():
    ensure_app_dirs()

    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS photos (
            folder_root TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            capture_ts TEXT,
            capture_year INTEGER,
            capture_month INTEGER,
            capture_day INTEGER,
            media_type TEXT DEFAULT 'image',
            video_metadata_version INTEGER DEFAULT 0,
            PRIMARY KEY (folder_root, file_path)
        )
        """
    )

    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(photos)")
    }

    if "media_type" not in columns:
        conn.execute(
            """
            ALTER TABLE photos
            ADD COLUMN media_type TEXT DEFAULT 'image'
            """
        )

    if "video_metadata_version" not in columns:
        conn.execute(
            """
            ALTER TABLE photos
            ADD COLUMN video_metadata_version INTEGER DEFAULT 0
            """
        )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_photos_date
        ON photos (
            folder_root,
            capture_month,
            capture_day,
            capture_year
        )
        """
    )

    conn.commit()
    return conn


def media_type_for_path(path):
    suffix = path.suffix.lower()

    if suffix in VIDEO_EXTENSIONS:
        return "video"

    return "image"


def parse_macos_metadata_date(path):
    if sys.platform != "darwin":
        return None

    fields = (
        "kMDItemContentCreationDate",
        "kMDItemFSCreationDate",
    )

    for field in fields:
        try:
            result = subprocess.run(
                [
                    "mdls",
                    "-raw",
                    "-name",
                    field,
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

            value = result.stdout.strip()

            if not value or value == "(null)":
                continue

            try:
                parsed = datetime.strptime(
                    value,
                    "%Y-%m-%d %H:%M:%S %z",
                )

                if parsed.tzinfo is not None:
                    parsed = (
                        parsed.astimezone()
                        .replace(tzinfo=None)
                    )

                return parsed

            except ValueError:
                pass

        except Exception:
            pass

    return None


def get_image_exif_date(image_path):
    try:
        with Image.open(image_path) as img:
            exif = img.getexif()

            if not exif:
                return None

            tag_ids = {
                "DateTimeOriginal": 36867,
                "DateTimeDigitized": 36868,
                "DateTime": 306,
            }

            for tag_name in (
                "DateTimeOriginal",
                "DateTimeDigitized",
                "DateTime",
            ):
                value = exif.get(tag_ids[tag_name])

                if not value:
                    continue

                if isinstance(value, bytes):
                    value = value.decode(
                        "utf-8",
                        errors="ignore",
                    )

                value = str(value).strip()

                for fmt in (
                    "%Y:%m:%d %H:%M:%S",
                    "%Y-%m-%d %H:%M:%S",
                ):
                    try:
                        return datetime.strptime(
                            value,
                            fmt,
                        )
                    except ValueError:
                        pass

    except Exception:
        pass

    return None


def get_video_metadata_date(path):
    if not FFMPEG_ENABLED:
        return None

    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        result = subprocess.run(
            [
                ffmpeg_exe,
                "-hide_banner",
                "-i",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        metadata_text = result.stderr

        candidates = []

        for line in metadata_text.splitlines():
            stripped = line.strip()

            if "creation_time" in stripped:
                _, _, value = stripped.partition(":")
                value = value.strip()
                if value:
                    candidates.append(value)

            elif "date" in stripped.lower() and ":" in stripped:
                key, _, value = stripped.partition(":")
                if key.strip().lower() in {
                    "date",
                    "date-eng",
                    "creation date",
                }:
                    value = value.strip()
                    if value:
                        candidates.append(value)

        for value in candidates:
            normalized = value.replace("Z", "+00:00")

            for parser in (
                lambda v: datetime.fromisoformat(v),
                lambda v: datetime.strptime(v, "%Y-%m-%d %H:%M:%S"),
                lambda v: datetime.strptime(v, "%Y/%m/%d %H:%M:%S"),
            ):
                try:
                    parsed = parser(normalized)

                    if parsed.tzinfo is not None:
                        parsed = (
                            parsed.astimezone()
                            .replace(tzinfo=None)
                        )

                    return parsed
                except ValueError:
                    continue

    except Exception:
        pass

    return None


def get_filesystem_creation_date(path):
    try:
        stat = path.stat()

        if hasattr(stat, "st_birthtime"):
            return datetime.fromtimestamp(
                stat.st_birthtime
            )

        return datetime.fromtimestamp(
            stat.st_ctime
        )

    except OSError:
        return None

def get_capture_date(path, media_type):
    if media_type == "image":
        exif_date = get_image_exif_date(
            path
        )

        if exif_date is not None:
            return exif_date

        mac_date = parse_macos_metadata_date(
            path
        )

        if mac_date is not None:
            return mac_date

    if media_type == "video":
        # 1. Embedded metadata from MOV/MP4 container.
        video_date = get_video_metadata_date(
            path
        )

        if video_date is not None:
            return video_date

        # 2. macOS Spotlight metadata.
        mac_date = parse_macos_metadata_date(
            path
        )

        if mac_date is not None:
            return mac_date

        # 3. Filesystem creation date.
        created_date = get_filesystem_creation_date(
            path
        )

        if created_date is not None:
            return created_date

    try:
        return datetime.fromtimestamp(
            path.stat().st_mtime
        )
    except OSError:
        return None

def open_file(path):
    try:
        if sys.platform == "darwin":
            subprocess.run(
                ["open", str(path)],
                check=False,
            )
        elif os.name == "nt":
            os.startfile(str(path))
        else:
            subprocess.run(
                ["xdg-open", str(path)],
                check=False,
            )
    except Exception as exc:
        messagebox.showerror(
            "Open File",
            f"Could not open file:\n{exc}",
        )


def thumbnail_cache_path(
    path,
    file_size,
    modified_ns,
):
    signature = (
        f"{path}|{file_size}|{modified_ns}|"
        f"{THUMBNAIL_SIZE[0]}x{THUMBNAIL_SIZE[1]}"
    )

    digest = hashlib.sha256(
        signature.encode("utf-8")
    ).hexdigest()

    return THUMBNAIL_DIR / f"{digest}.jpg"


def create_image_thumbnail(
    source_path,
    cache_path,
):
    with Image.open(source_path) as img:
        img = ImageOps.exif_transpose(img)

        if getattr(img, "is_animated", False):
            try:
                img.seek(0)
            except EOFError:
                pass

        img = img.convert("RGB")

        img.thumbnail(
            THUMBNAIL_SIZE,
            Image.Resampling.LANCZOS,
        )

        canvas = Image.new(
            "RGB",
            THUMBNAIL_SIZE,
            "black",
        )

        x = (
            THUMBNAIL_SIZE[0] - img.width
        ) // 2

        y = (
            THUMBNAIL_SIZE[1] - img.height
        ) // 2

        canvas.paste(
            img,
            (x, y),
        )

        canvas.save(
            cache_path,
            "JPEG",
            quality=85,
            optimize=True,
        )


def create_video_thumbnail(
    source_path,
    cache_path,
):
    if not FFMPEG_ENABLED:
        return False

    try:
        ffmpeg_exe = (
            imageio_ffmpeg.get_ffmpeg_exe()
        )

        subprocess.run(
            [
                ffmpeg_exe,
                "-y",
                "-ss",
                "1",
                "-i",
                str(source_path),
                "-frames:v",
                "1",
                "-vf",
                (
                    f"scale={THUMBNAIL_SIZE[0]}:"
                    f"{THUMBNAIL_SIZE[1]}:"
                    "force_original_aspect_ratio=decrease,"
                    f"pad={THUMBNAIL_SIZE[0]}:"
                    f"{THUMBNAIL_SIZE[1]}:"
                    "(ow-iw)/2:(oh-ih)/2"
                ),
                "-q:v",
                "3",
                str(cache_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )

        return (
            cache_path.exists()
            and cache_path.stat().st_size > 0
        )

    except Exception:
        return False


def get_cached_thumbnail(
    path,
    media_type,
    file_size,
    modified_ns,
):
    ensure_app_dirs()

    cache_path = thumbnail_cache_path(
        path,
        file_size,
        modified_ns,
    )

    if cache_path.exists():
        return cache_path

    try:
        if media_type == "video":
            success = create_video_thumbnail(
                path,
                cache_path,
            )

            if not success:
                return None
        else:
            create_image_thumbnail(
                path,
                cache_path,
            )

        return cache_path

    except Exception:
        try:
            if cache_path.exists():
                cache_path.unlink()
        except OSError:
            pass

        return None


class MediaIndexer:
    def __init__(
        self,
        folder,
        event_queue,
        stop_event,
        scan_id,
    ):
        self.folder = Path(folder)
        self.folder_root = str(
            self.folder.resolve()
        )
        self.event_queue = event_queue
        self.stop_event = stop_event
        self.scan_id = scan_id

    def send(
        self,
        event_type,
        **payload,
    ):
        event = {
            "type": event_type,
            "scan_id": self.scan_id,
        }
        event.update(payload)
        self.event_queue.put(event)

    def run(self):
        conn = None

        try:
            conn = open_database()

            cached = {
                row[0]: (
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                )
                for row in conn.execute(
                    """
                    SELECT
                        file_path,
                        file_size,
                        modified_ns,
                        media_type,
                        video_metadata_version
                    FROM photos
                    WHERE folder_root = ?
                    """,
                    (
                        self.folder_root,
                    )
                )
            }

            seen_paths = set()

            scanned = 0
            updated = 0
            unchanged = 0
            errors = 0
            pending = 0

            self.send(
                "scan_started"
            )

            for path in self.folder.rglob("*"):
                if self.stop_event.is_set():
                    self.send(
                        "scan_cancelled"
                    )
                    return

                try:
                    if not path.is_file():
                        continue

                    suffix = path.suffix.lower()

                    if suffix not in SUPPORTED_EXTENSIONS:
                        continue

                    if (
                        suffix in {".heic", ".heif"}
                        and not HEIC_ENABLED
                    ):
                        continue

                    scanned += 1

                    path_text = str(
                        path.resolve()
                    )

                    seen_paths.add(
                        path_text
                    )

                    stat = path.stat()
                    file_size = stat.st_size
                    modified_ns = stat.st_mtime_ns

                    cached_info = cached.get(
                        path_text
                    )

                    media_type = media_type_for_path(
                        path
                    )

                    existing_media_type = (
                        cached_info[2]
                        if cached_info is not None
                        else None
                    )

                    existing_video_version = (
                        cached_info[3]
                        if cached_info is not None
                        else 0
                    )

                    force_video_refresh = (
                        media_type == "video"
                        and (
                            existing_media_type != "video"
                            or existing_video_version < VIDEO_METADATA_VERSION
                        )
                    )

                    if (
                        cached_info is not None
                        and cached_info[0] == file_size
                        and cached_info[1] == modified_ns
                        and not force_video_refresh
                    ):
                        unchanged += 1
                    else:
                        capture_date = get_capture_date(
                            path,
                            media_type,
                        )

                        if capture_date is None:
                            capture_ts = None
                            capture_year = None
                            capture_month = None
                            capture_day = None
                        else:
                            capture_ts = (
                                capture_date.isoformat(
                                    timespec="seconds"
                                )
                            )
                            capture_year = (
                                capture_date.year
                            )
                            capture_month = (
                                capture_date.month
                            )
                            capture_day = (
                                capture_date.day
                            )

                        conn.execute(
                            """
                            INSERT INTO photos (
                                folder_root,
                                file_path,
                                file_size,
                                modified_ns,
                                capture_ts,
                                capture_year,
                                capture_month,
                                capture_day,
                                media_type,
                                video_metadata_version
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(folder_root, file_path)
                            DO UPDATE SET
                                file_size = excluded.file_size,
                                modified_ns = excluded.modified_ns,
                                capture_ts = excluded.capture_ts,
                                capture_year = excluded.capture_year,
                                capture_month = excluded.capture_month,
                                capture_day = excluded.capture_day,
                                media_type = excluded.media_type,
                                video_metadata_version = excluded.video_metadata_version
                            """,
                            (
                                self.folder_root,
                                path_text,
                                file_size,
                                modified_ns,
                                capture_ts,
                                capture_year,
                                capture_month,
                                capture_day,
                                media_type,
                                (
                                    VIDEO_METADATA_VERSION
                                    if media_type == "video"
                                    else 0
                                ),
                            )
                        )

                        updated += 1
                        pending += 1

                        if pending >= BATCH_COMMIT_SIZE:
                            conn.commit()
                            pending = 0

                    if scanned % 50 == 0:
                        self.send(
                            "scan_progress",
                            scanned=scanned,
                            updated=updated,
                            unchanged=unchanged,
                            errors=errors,
                        )

                except Exception:
                    errors += 1

            if pending:
                conn.commit()

            deleted_paths = (
                set(cached.keys())
                - seen_paths
            )

            deleted = 0

            for file_path in deleted_paths:
                if self.stop_event.is_set():
                    self.send(
                        "scan_cancelled"
                    )
                    return

                conn.execute(
                    """
                    DELETE FROM photos
                    WHERE folder_root = ?
                    AND file_path = ?
                    """,
                    (
                        self.folder_root,
                        file_path,
                    )
                )

                deleted += 1

            conn.commit()

            total_indexed = conn.execute(
                """
                SELECT COUNT(*)
                FROM photos
                WHERE folder_root = ?
                """,
                (
                    self.folder_root,
                )
            ).fetchone()[0]

            total_videos = conn.execute(
                """
                SELECT COUNT(*)
                FROM photos
                WHERE folder_root = ?
                AND media_type = 'video'
                """,
                (
                    self.folder_root,
                )
            ).fetchone()[0]

            self.send(
                "scan_complete",
                scanned=scanned,
                updated=updated,
                unchanged=unchanged,
                deleted=deleted,
                errors=errors,
                total_indexed=total_indexed,
                total_videos=total_videos,
            )

        except Exception as exc:
            self.send(
                "scan_error",
                message=str(exc),
            )

        finally:
            if conn is not None:
                conn.close()


class MediaViewer(tk.Tk):
    def __init__(self):
        super().__init__()

        self.root_folder = load_saved_folder()
        self.current_date = datetime.now().date()
        self.thumbnail_refs = []
        self.current_matches = []
        self.media_filter = tk.StringVar(value="All")
        self.collapsed_years = set()
        self.year_sections = {}
        self.year_render_counts = {}
        self.year_total_counts = {}
        self.year_records = {}

        self.event_queue = queue.Queue()
        self.index_thread = None
        self.stop_event = threading.Event()
        self.active_scan_id = 0
        self.pending_index_start = False
        self.thumbnail_executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="thumbnail",
        )

        self.title(
            WINDOW_TITLE
        )

        self.geometry(
            "1220x820"
        )

        self.minsize(
            850,
            540
        )

        self._build_ui()

        self.after(
            100,
            self.startup,
        )

        self.after(
            200,
            self.process_index_events,
        )

        self.protocol(
            "WM_DELETE_WINDOW",
            self.on_close,
        )

    def _build_ui(self):
        top = ttk.Frame(
            self,
            padding=10,
        )

        top.pack(
            fill="x"
        )

        ttk.Button(
            top,
            text="Change Folder",
            command=self.choose_folder,
        ).pack(
            side="left"
        )

        self.rescan_button = ttk.Button(
            top,
            text="Rescan",
            command=self.start_indexing,
        )

        self.rescan_button.pack(
            side="left",
            padx=(8, 8),
        )

        ttk.Button(
            top,
            text="Video Index Viewer",
            command=self.open_video_index_viewer,
        ).pack(
            side="left",
            padx=(0, 16),
        )

        ttk.Button(
            top,
            text="< Previous Day",
            command=lambda: self.change_day(-1),
        ).pack(
            side="left"
        )

        ttk.Button(
            top,
            text="Today",
            command=self.go_today,
        ).pack(
            side="left",
            padx=8,
        )

        ttk.Button(
            top,
            text="Next Day >",
            command=lambda: self.change_day(1),
        ).pack(
            side="left"
        )

        ttk.Label(
            top,
            text="Show:",
        ).pack(
            side="left",
            padx=(16, 4),
        )

        self.filter_box = ttk.Combobox(
            top,
            textvariable=self.media_filter,
            values=("All", "Photos", "Videos"),
            state="readonly",
            width=8,
        )
        self.filter_box.pack(
            side="left"
        )
        self.filter_box.bind(
            "<<ComboboxSelected>>",
            lambda event: self.render_current_day(),
        )

        self.date_label = ttk.Label(
            top,
            text="",
            font=(
                "Helvetica",
                18,
                "bold",
            ),
        )

        self.date_label.pack(
            side="left",
            padx=20,
        )

        self.status_label = ttk.Label(
            top,
            text="",
        )

        self.status_label.pack(
            side="right"
        )

        folder_bar = ttk.Frame(
            self,
            padding=(
                10,
                0,
                10,
                8,
            ),
        )

        folder_bar.pack(
            fill="x"
        )

        ttk.Label(
            folder_bar,
            text="Current folder:",
        ).pack(
            side="left"
        )

        self.folder_label = ttk.Label(
            folder_bar,
            text="Not selected",
        )

        self.folder_label.pack(
            side="left",
            padx=(6, 0),
            fill="x",
            expand=True,
        )

        self.progress = ttk.Progressbar(
            folder_bar,
            mode="indeterminate",
            length=160,
        )

        self.progress.pack(
            side="right"
        )

        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
        )

        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )

        self.content = ttk.Frame(
            self.canvas
        )

        self.content.bind(
            "<Configure>",
            lambda event: self.canvas.configure(
                scrollregion=self.canvas.bbox(
                    "all"
                )
            ),
        )

        self.canvas_window = (
            self.canvas.create_window(
                (0, 0),
                window=self.content,
                anchor="nw",
            )
        )

        self.canvas.configure(
            yscrollcommand=self.scrollbar.set,
        )

        self.canvas.pack(
            side="left",
            fill="both",
            expand=True,
        )

        self.scrollbar.pack(
            side="right",
            fill="y",
        )

        self.canvas.bind(
            "<Configure>",
            self._resize_content,
        )

        self.canvas.bind_all(
            "<MouseWheel>",
            self._on_mousewheel,
        )

    def _resize_content(
        self,
        event,
    ):
        self.canvas.itemconfigure(
            self.canvas_window,
            width=event.width,
        )

    def _on_mousewheel(
        self,
        event,
    ):
        if sys.platform == "darwin":
            step = int(
                -event.delta
            )
        else:
            step = int(
                -event.delta / 120
            )

        if step != 0:
            self.canvas.yview_scroll(
                step,
                "units",
            )

    def startup(self):
        warnings = []

        if not HEIC_ENABLED:
            warnings.append(
                "HEIC support is not installed.\n"
                "Install with:\n"
                "python3 -m pip install pillow-heif"
            )

        if not FFMPEG_ENABLED:
            warnings.append(
                "Video thumbnails and embedded video dates are disabled.\n"
                "Install with:\n"
                "python3 -m pip install imageio-ffmpeg"
            )

        if warnings:
            self.after(
                500,
                lambda: messagebox.showinfo(
                    "Optional Components",
                    "\n\n".join(warnings),
                ),
            )

        if self.root_folder is None:
            self.choose_folder()
        else:
            self.folder_label.config(
                text=str(self.root_folder),
            )

            self.render_current_day()

    def choose_folder(self):
        initial_dir = (
            str(self.root_folder)
            if self.root_folder
            else str(Path.home())
        )

        selected = filedialog.askdirectory(
            title="Choose Photo and Video Folder",
            initialdir=initial_dir,
        )

        if not selected:
            return

        new_folder = Path(
            selected
        )

        if (
            not new_folder.exists()
            or not new_folder.is_dir()
        ):
            messagebox.showerror(
                "Invalid Folder",
                "The selected folder is not available.",
            )
            return

        self.cancel_indexing()

        self.root_folder = new_folder

        save_folder(
            self.root_folder
        )

        self.current_date = (
            datetime.now().date()
        )

        self.folder_label.config(
            text=str(self.root_folder),
        )

        self.render_current_day()
        self.start_indexing()

    def start_indexing(self):
        if self.root_folder is None:
            self.choose_folder()
            return

        if (
            self.index_thread is not None
            and self.index_thread.is_alive()
        ):
            # A folder change can arrive while the previous scan is still
            # closing its database connection.  Wait for that worker rather
            # than silently dropping the requested scan or running two
            # writers against the same database.
            self.pending_index_start = True
            self.stop_event.set()
            self.status_label.config(text="Stopping current scan...")
            self.after(50, self.start_indexing)
            return

        self.pending_index_start = False
        self.active_scan_id += 1
        self.stop_event = threading.Event()

        indexer = MediaIndexer(
            self.root_folder,
            self.event_queue,
            self.stop_event,
            self.active_scan_id,
        )

        self.index_thread = threading.Thread(
            target=indexer.run,
            daemon=True,
        )

        self.index_thread.start()

    def cancel_indexing(self):
        if (
            self.index_thread is not None
            and self.index_thread.is_alive()
        ):
            self.stop_event.set()

    def process_index_events(self):
        try:
            while True:
                event = (
                    self.event_queue.get_nowait()
                )

                event_type = event.get(
                    "type"
                )

                # Events from a previous worker must not change the status
                # of a newer scan (for example after changing folders).
                if event.get("scan_id") != self.active_scan_id:
                    continue

                if event_type == "scan_started":
                    self.progress.start(
                        10
                    )

                    self.rescan_button.config(
                        state="disabled",
                    )

                    self.status_label.config(
                        text="Indexing...",
                    )

                elif event_type == "scan_progress":
                    self.status_label.config(
                        text=(
                            f"Scanned {event['scanned']:,} | "
                            f"Updated {event['updated']:,} | "
                            f"Cached {event['unchanged']:,}"
                        )
                    )

                elif event_type == "scan_complete":
                    self.progress.stop()

                    if self.pending_index_start:
                        self.status_label.config(text="Starting requested scan...")
                    else:
                        self.rescan_button.config(
                            state="normal",
                        )

                        self.status_label.config(
                            text=(
                                f"{event['total_indexed']:,} indexed | "
                                f"{event['total_videos']:,} videos | "
                                f"{event['updated']:,} updated | "
                                f"{event['deleted']:,} removed"
                            )
                        )

                        self.render_current_day()

                elif event_type == "scan_cancelled":
                    self.progress.stop()

                    if self.pending_index_start:
                        self.status_label.config(text="Starting requested scan...")
                    else:
                        self.rescan_button.config(
                            state="normal",
                        )

                        self.status_label.config(
                            text="Indexing cancelled",
                        )

                elif event_type == "scan_error":
                    self.progress.stop()

                    if self.pending_index_start:
                        self.status_label.config(text="Starting requested scan...")
                    else:
                        self.rescan_button.config(
                            state="normal",
                        )

                        self.status_label.config(
                            text="Indexing failed",
                        )

                        messagebox.showerror(
                            "Indexing Error",
                            event.get(
                                "message",
                                "Unknown indexing error.",
                            ),
                        )

        except queue.Empty:
            pass

        self.after(
            200,
            self.process_index_events,
        )

    def get_matches(self):
        if self.root_folder is None:
            return []

        folder_root = str(
            self.root_folder.resolve()
        )

        conn = None

        try:
            conn = open_database()

            selected_filter = self.media_filter.get()

            sql = """
                SELECT
                    file_path,
                    capture_ts,
                    media_type,
                    file_size,
                    modified_ns
                FROM photos
                WHERE folder_root = ?
                AND capture_month = ?
                AND capture_day = ?
            """

            params = [
                folder_root,
                self.current_date.month,
                self.current_date.day,
            ]

            if selected_filter == "Photos":
                sql += " AND media_type = 'image'"
            elif selected_filter == "Videos":
                sql += " AND media_type = 'video'"

            sql += " ORDER BY capture_year DESC, capture_ts DESC"

            rows = conn.execute(
                sql,
                params,
            ).fetchall()

            matches = []

            for (
                file_path,
                capture_ts,
                media_type,
                file_size,
                modified_ns,
            ) in rows:
                path = Path(
                    file_path
                )

                if not path.exists():
                    continue

                try:
                    capture_date = (
                        datetime.fromisoformat(
                            capture_ts
                        )
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    continue

                matches.append(
                    (
                        path,
                        capture_date,
                        media_type or "image",
                        file_size,
                        modified_ns,
                    )
                )

            return matches

        except Exception:
            return []

        finally:
            if conn is not None:
                conn.close()

    def change_day(
        self,
        offset,
    ):
        self.current_date += timedelta(
            days=offset
        )

        self.render_current_day()

    def go_today(self):
        self.current_date = (
            datetime.now().date()
        )

        self.render_current_day()

    def clear_gallery(self):
        for widget in (
            self.content.winfo_children()
        ):
            widget.destroy()

        self.thumbnail_refs.clear()

    def render_current_day(self):
        self.clear_gallery()
        self.year_sections = {}
        self.year_render_counts = {}
        self.year_total_counts = {}
        self.year_records = {}

        display_date = (
            self.current_date.strftime(
                "%B %d"
            )
        )

        selected_filter = self.media_filter.get()

        self.date_label.config(
            text=(
                f"{selected_filter} from "
                f"{display_date}"
            ),
        )

        if self.root_folder is None:
            ttk.Label(
                self.content,
                text=(
                    "Click Change Folder to "
                    "select your media library."
                ),
                font=(
                    "Helvetica",
                    14,
                ),
            ).pack(
                pady=40
            )
            return

        self.current_matches = self.get_matches()

        if not self.current_matches:
            ttk.Label(
                self.content,
                text=(
                    f"No indexed {selected_filter.lower()} "
                    f"found for {display_date}.\n\n"
                    "Try changing the Show filter or press Rescan."
                ),
                font=(
                    "Helvetica",
                    14,
                ),
                justify="center",
            ).pack(
                pady=40
            )
            return

        for record in self.current_matches:
            year = record[1].year
            self.year_records.setdefault(year, []).append(record)
            self.year_total_counts[year] = (
                self.year_total_counts.get(year, 0) + 1
            )

        photo_count = sum(
            1 for item in self.current_matches
            if item[2] == "image"
        )
        video_count = sum(
            1 for item in self.current_matches
            if item[2] == "video"
        )

        summary = ttk.Label(
            self.content,
            text=(
                f"{len(self.current_matches):,} items on this date "
                f"({photo_count:,} photos, {video_count:,} videos)"
            ),
            font=(
                "Helvetica",
                11,
            ),
        )
        summary.pack(
            anchor="w",
            padx=14,
            pady=(8, 0),
        )

        self.render_all_year_sections()

    def render_all_year_sections(self):
        for year in sorted(
            self.year_records.keys(),
            reverse=True,
        ):
            section = ttk.Frame(
                self.content,
                padding=(10, 6),
            )
            section.pack(
                fill="x",
                anchor="w",
            )

            header = ttk.Frame(
                section
            )
            header.pack(
                fill="x"
            )

            is_collapsed = (
                year in self.collapsed_years
            )

            toggle_text = (
                f"> {year}"
                if is_collapsed
                else f"v {year}"
            )

            toggle_button = ttk.Button(
                header,
                text=toggle_text,
                width=12,
            )
            toggle_button.pack(
                side="left"
            )

            total_items = self.year_total_counts.get(
                year,
                0,
            )

            count_label = ttk.Label(
                header,
                text=(
                    f"{total_items} item"
                    f"{'' if total_items == 1 else 's'}"
                ),
            )
            count_label.pack(
                side="left",
                padx=(8, 0),
            )

            body = ttk.Frame(
                section
            )
            body.pack(
                fill="x",
                pady=(6, 0),
            )

            def toggle_year(
                selected_year=year,
                selected_body=body,
                selected_button=toggle_button,
            ):
                if selected_year in self.collapsed_years:
                    self.collapsed_years.remove(
                        selected_year
                    )
                    selected_body.pack(
                        fill="x",
                        pady=(6, 0),
                    )
                    selected_button.config(
                        text=f"v {selected_year}"
                    )
                else:
                    self.collapsed_years.add(
                        selected_year
                    )
                    selected_body.pack_forget()
                    selected_button.config(
                        text=f"> {selected_year}"
                    )

            toggle_button.config(
                command=toggle_year
            )

            self.year_sections[year] = {
                "section": section,
                "body": body,
                "button": toggle_button,
                "count_label": count_label,
                "load_frame": None,
            }

            self.year_render_counts[year] = 0

            self.render_more_for_year(
                year,
                RENDER_BATCH_SIZE,
            )

            if is_collapsed:
                body.pack_forget()

    def render_more_for_year(
        self,
        year,
        amount,
    ):
        records = self.year_records.get(
            year,
            [],
        )

        start_index = self.year_render_counts.get(
            year,
            0,
        )

        end_index = min(
            start_index + amount,
            len(records),
        )

        body = self.year_sections[year]["body"]

        load_frame = self.year_sections[year].get(
            "load_frame"
        )

        if load_frame is not None:
            try:
                load_frame.destroy()
            except tk.TclError:
                pass
            self.year_sections[year]["load_frame"] = None

        for item_index in range(
            start_index,
            end_index,
        ):
            (
                path,
                capture_date,
                media_type,
                file_size,
                modified_ns,
            ) = records[item_index]

            row = (
                item_index // COLUMNS
            )

            col = (
                item_index % COLUMNS
            )

            card = self.create_media_card(
                body,
                path,
                capture_date,
                media_type,
                file_size,
                modified_ns,
            )

            card.grid(
                row=row,
                column=col,
                padx=8,
                pady=8,
                sticky="n",
            )

        for col in range(
            COLUMNS
        ):
            body.columnconfigure(
                col,
                weight=1,
            )

        self.year_render_counts[year] = end_index

        if end_index < len(records):
            remaining = (
                len(records) - end_index
            )

            load_frame = ttk.Frame(
                body,
                padding=(0, 10),
            )
            load_frame.grid(
                row=(end_index + COLUMNS - 1) // COLUMNS,
                column=0,
                columnspan=COLUMNS,
                sticky="ew",
            )

            ttk.Button(
                load_frame,
                text=(
                    f"Load More {year} "
                    f"({remaining:,} remaining)"
                ),
                command=lambda y=year: self.render_more_for_year(
                    y,
                    RENDER_BATCH_SIZE,
                ),
            ).pack()

            self.year_sections[year]["load_frame"] = load_frame

    def create_media_card(
        self,
        parent,
        path,
        capture_date,
        media_type,
        file_size,
        modified_ns,
    ):
        card = ttk.Frame(
            parent,
            padding=5,
        )

        preview_host = ttk.Frame(card)
        preview_host.pack()

        cache_path = thumbnail_cache_path(
            path,
            file_size,
            modified_ns,
        )

        if (
            cache_path.exists()
        ):
            try:
                self.show_thumbnail(
                    preview_host,
                    cache_path,
                    path,
                )

            except Exception:
                self.create_placeholder(
                    preview_host,
                    media_type,
                    path,
                )
        else:
            self.create_placeholder(
                preview_host,
                media_type,
                path,
            )
            future = self.thumbnail_executor.submit(
                get_cached_thumbnail,
                path,
                media_type,
                file_size,
                modified_ns,
            )
            future.add_done_callback(
                lambda completed: self.schedule_thumbnail_ready(
                    completed,
                    preview_host,
                    path,
                )
            )

        if media_type == "video":
            type_text = "VIDEO"
        else:
            type_text = "PHOTO"

        ttk.Label(
            card,
            text=type_text,
            font=(
                "Helvetica",
                10,
                "bold",
            ),
            anchor="center",
        ).pack(
            pady=(
                4,
                0,
            ),
        )

        ttk.Label(
            card,
            text=capture_date.strftime(
                "%Y-%m-%d %H:%M"
            ),
            anchor="center",
        ).pack()

        ttk.Label(
            card,
            text=path.name,
            anchor="center",
            width=32,
        ).pack()

        relative_parent = (
            path.parent
        )

        if self.root_folder is not None:
            try:
                relative_parent = (
                    path.parent.relative_to(
                        self.root_folder
                    )
                )
            except ValueError:
                pass

        ttk.Label(
            card,
            text=str(
                relative_parent
            ),
            anchor="center",
            width=32,
        ).pack()

        return card

    def schedule_thumbnail_ready(self, future, preview_host, path):
        try:
            self.after(
                0,
                self.thumbnail_ready,
                future,
                preview_host,
                path,
            )
        except (RuntimeError, tk.TclError):
            # The window may have been closed while a worker was finishing.
            pass

    def show_thumbnail(self, preview_host, cache_path, path):
        with Image.open(cache_path) as img:
            preview = img.copy()

        photo = ImageTk.PhotoImage(preview)
        self.thumbnail_refs.append(photo)

        image_button = tk.Button(
            preview_host,
            image=photo,
            borderwidth=0,
            cursor="hand2",
            command=lambda p=path: open_file(p),
        )
        image_button.pack()

    def thumbnail_ready(self, future, preview_host, path):
        try:
            cache_path = future.result()
            if cache_path is None or not cache_path.exists():
                return

            for widget in preview_host.winfo_children():
                widget.destroy()

            self.show_thumbnail(preview_host, cache_path, path)
        except Exception:
            # The placeholder is already visible; a failed thumbnail should
            # not interrupt the gallery or show an error dialog.
            pass

    def create_placeholder(
        self,
        card,
        media_type,
        path,
    ):
        if media_type == "video":
            text = (
                "VIDEO\n"
                "Thumbnail unavailable"
            )
        else:
            text = (
                "PHOTO\n"
                "Preview unavailable"
            )

        button = tk.Button(
            card,
            text=text,
            width=28,
            height=9,
            cursor="hand2",
            command=lambda p=path: open_file(p),
        )

        button.pack()
        return button

    def get_all_indexed_videos(self):
        if self.root_folder is None:
            return []

        folder_root = str(
            self.root_folder.resolve()
        )

        conn = None

        try:
            conn = open_database()

            rows = conn.execute(
                """
                SELECT
                    file_path,
                    capture_ts,
                    file_size,
                    modified_ns
                FROM photos
                WHERE folder_root = ?
                AND media_type = 'video'
                ORDER BY
                    capture_year DESC,
                    capture_month DESC,
                    capture_day DESC,
                    capture_ts DESC,
                    file_path ASC
                """,
                (
                    folder_root,
                ),
            ).fetchall()

            return rows

        except Exception as exc:
            messagebox.showerror(
                "Video Index Viewer",
                f"Could not read video index:\n{exc}",
            )
            return []

        finally:
            if conn is not None:
                conn.close()

    def open_video_index_viewer(self):
        if self.root_folder is None:
            messagebox.showinfo(
                "Video Index Viewer",
                "Choose a media folder first.",
            )
            return

        rows = self.get_all_indexed_videos()

        window = tk.Toplevel(
            self
        )

        window.title(
            "Video Index Viewer"
        )

        window.geometry(
            "1100x650"
        )

        window.minsize(
            800,
            450
        )

        top = ttk.Frame(
            window,
            padding=10,
        )

        top.pack(
            fill="x"
        )

        ttk.Label(
            top,
            text=(
                f"Indexed Videos: {len(rows):,}"
            ),
            font=(
                "Helvetica",
                14,
                "bold",
            ),
        ).pack(
            side="left"
        )

        search_var = tk.StringVar()

        ttk.Label(
            top,
            text="Search:",
        ).pack(
            side="left",
            padx=(20, 5),
        )

        search_entry = ttk.Entry(
            top,
            textvariable=search_var,
            width=35,
        )

        search_entry.pack(
            side="left"
        )

        table_frame = ttk.Frame(
            window,
            padding=(
                10,
                0,
                10,
                10,
            ),
        )

        table_frame.pack(
            fill="both",
            expand=True,
        )

        columns = (
            "filename",
            "extension",
            "detected_date",
            "full_path",
        )

        tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
        )

        tree.heading(
            "filename",
            text="Filename",
        )

        tree.heading(
            "extension",
            text="Type",
        )

        tree.heading(
            "detected_date",
            text="Detected Date",
        )

        tree.heading(
            "full_path",
            text="Full Path",
        )

        tree.column(
            "filename",
            width=220,
            anchor="w",
        )

        tree.column(
            "extension",
            width=70,
            anchor="center",
        )

        tree.column(
            "detected_date",
            width=170,
            anchor="center",
        )

        tree.column(
            "full_path",
            width=580,
            anchor="w",
        )

        y_scroll = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=tree.yview,
        )

        x_scroll = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=tree.xview,
        )

        tree.configure(
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )

        tree.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        y_scroll.grid(
            row=0,
            column=1,
            sticky="ns",
        )

        x_scroll.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        table_frame.rowconfigure(
            0,
            weight=1,
        )

        table_frame.columnconfigure(
            0,
            weight=1,
        )

        def populate(filter_text=""):
            for item in tree.get_children():
                tree.delete(item)

            normalized_filter = (
                filter_text.strip().lower()
            )

            for (
                file_path,
                capture_ts,
                file_size,
                modified_ns,
            ) in rows:
                path = Path(
                    file_path
                )

                filename = (
                    path.name
                )

                extension = (
                    path.suffix.lower()
                    .lstrip(".")
                    .upper()
                )

                detected_date = (
                    capture_ts
                    if capture_ts
                    else "No date"
                )

                searchable = (
                    f"{filename} "
                    f"{extension} "
                    f"{detected_date} "
                    f"{file_path}"
                ).lower()

                if (
                    normalized_filter
                    and normalized_filter not in searchable
                ):
                    continue

                tree.insert(
                    "",
                    "end",
                    values=(
                        filename,
                        extension,
                        detected_date,
                        file_path,
                    ),
                )

        def on_search_change(*args):
            populate(
                search_var.get()
            )

        search_var.trace_add(
            "write",
            on_search_change,
        )

        def open_selected(event=None):
            selection = (
                tree.selection()
            )

            if not selection:
                return

            values = tree.item(
                selection[0],
                "values",
            )

            if not values:
                return

            file_path = (
                values[3]
            )

            open_file(
                Path(file_path)
            )

        tree.bind(
            "<Double-1>",
            open_selected,
        )

        button_bar = ttk.Frame(
            window,
            padding=10,
        )

        button_bar.pack(
            fill="x"
        )

        ttk.Button(
            button_bar,
            text="Open Selected",
            command=open_selected,
        ).pack(
            side="left"
        )

        ttk.Button(
            button_bar,
            text="Refresh",
            command=lambda: (
                window.destroy(),
                self.open_video_index_viewer(),
            ),
        ).pack(
            side="left",
            padx=8,
        )

        ttk.Button(
            button_bar,
            text="Close",
            command=window.destroy,
        ).pack(
            side="right"
        )

        populate()

    def on_close(self):
        self.cancel_indexing()
        self.thumbnail_executor.shutdown(
            wait=False,
            cancel_futures=True,
        )
        self.destroy()


def main():
    app = MediaViewer()
    app.mainloop()


if __name__ == "__main__":
    main()
