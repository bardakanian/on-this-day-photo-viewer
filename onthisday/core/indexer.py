import sqlite3
import threading
from pathlib import Path
from typing import Callable

from .constants import BATCH_COMMIT_SIZE, SUPPORTED_EXTENSIONS, VIDEO_METADATA_VERSION
from .database import open_database
from .media import HEIC_ENABLED, get_capture_date, media_type_for_path


class MediaIndexer:
    """Framework-neutral scanner. Events are delivered through a callback."""

    def __init__(self, folder: Path, stop_event: threading.Event, scan_id: int, emit: Callable[[dict], None]):
        self.folder = Path(folder)
        self.folder_root = str(self.folder.resolve())
        self.stop_event = stop_event
        self.scan_id = scan_id
        self.emit = emit

    def send(self, event_type: str, **payload: object) -> None:
        self.emit({"type": event_type, "scan_id": self.scan_id, **payload})

    def run(self) -> None:
        connection: sqlite3.Connection | None = None
        try:
            connection = open_database()
            cached = {
                row[0]: (row[1], row[2], row[3], row[4])
                for row in connection.execute("""
                    SELECT file_path, file_size, modified_ns, media_type, video_metadata_version
                    FROM photos WHERE folder_root = ?
                """, (self.folder_root,))
            }
            seen: set[str] = set()
            scanned = updated = unchanged = errors = pending = 0
            self.send("scan_started")
            for path in self.folder.rglob("*"):
                if self.stop_event.is_set():
                    self.send("scan_cancelled")
                    return
                try:
                    if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                        continue
                    if path.suffix.lower() in {".heic", ".heif"} and not HEIC_ENABLED:
                        continue
                    scanned += 1
                    resolved = str(path.resolve())
                    seen.add(resolved)
                    stat = path.stat()
                    media_type = media_type_for_path(path)
                    old = cached.get(resolved)
                    force_video = media_type == "video" and (
                        old is None or old[2] != "video" or old[3] < VIDEO_METADATA_VERSION
                    )
                    if old and old[0] == stat.st_size and old[1] == stat.st_mtime_ns and not force_video:
                        unchanged += 1
                    else:
                        captured = get_capture_date(path, media_type)
                        values = (None, None, None, None) if captured is None else (
                            captured.isoformat(timespec="seconds"), captured.year, captured.month, captured.day,
                        )
                        connection.execute("""
                            INSERT INTO photos (
                                folder_root, file_path, file_size, modified_ns, capture_ts,
                                capture_year, capture_month, capture_day, media_type, video_metadata_version
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(folder_root, file_path) DO UPDATE SET
                                file_size=excluded.file_size, modified_ns=excluded.modified_ns,
                                capture_ts=excluded.capture_ts, capture_year=excluded.capture_year,
                                capture_month=excluded.capture_month, capture_day=excluded.capture_day,
                                media_type=excluded.media_type,
                                video_metadata_version=excluded.video_metadata_version
                        """, (
                            self.folder_root, resolved, stat.st_size, stat.st_mtime_ns, *values,
                            media_type, VIDEO_METADATA_VERSION if media_type == "video" else 0,
                        ))
                        updated += 1
                        pending += 1
                        if pending >= BATCH_COMMIT_SIZE:
                            connection.commit()
                            pending = 0
                    if scanned % 50 == 0:
                        self.send("scan_progress", scanned=scanned, updated=updated, unchanged=unchanged, errors=errors)
                except Exception:
                    errors += 1
            if pending:
                connection.commit()
            deleted = 0
            for file_path in set(cached) - seen:
                if self.stop_event.is_set():
                    self.send("scan_cancelled")
                    return
                connection.execute("DELETE FROM photos WHERE folder_root=? AND file_path=?", (self.folder_root, file_path))
                deleted += 1
            connection.commit()
            total = connection.execute("SELECT COUNT(*) FROM photos WHERE folder_root=?", (self.folder_root,)).fetchone()[0]
            videos = connection.execute(
                "SELECT COUNT(*) FROM photos WHERE folder_root=? AND media_type='video'", (self.folder_root,)
            ).fetchone()[0]
            self.send("scan_complete", scanned=scanned, updated=updated, unchanged=unchanged,
                      deleted=deleted, errors=errors, total_indexed=total, total_videos=videos)
        except Exception as exc:
            self.send("scan_error", message=str(exc))
        finally:
            if connection is not None:
                connection.close()
