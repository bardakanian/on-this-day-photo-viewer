import sqlite3
from datetime import date, datetime
from pathlib import Path

from .constants import APP_DIR, DB_FILE, THUMBNAIL_DIR
from .models import MediaRecord, VideoRecord


def ensure_app_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)


def open_database() -> sqlite3.Connection:
    """Open the existing database and apply only its established additive upgrades."""
    ensure_app_dirs()
    connection = sqlite3.connect(DB_FILE)
    connection.execute("""
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
    """)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(photos)")}
    if "media_type" not in columns:
        connection.execute("ALTER TABLE photos ADD COLUMN media_type TEXT DEFAULT 'image'")
    if "video_metadata_version" not in columns:
        connection.execute("ALTER TABLE photos ADD COLUMN video_metadata_version INTEGER DEFAULT 0")
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_photos_date
        ON photos (folder_root, capture_month, capture_day, capture_year)
    """)
    connection.commit()
    return connection


class MediaRepository:
    def matches_for_date(self, folder: Path, selected_date: date, media_filter: str) -> list[MediaRecord]:
        sql = """
            SELECT file_path, capture_ts, media_type, file_size, modified_ns
            FROM photos
            WHERE folder_root = ? AND capture_month = ? AND capture_day = ?
        """
        params: list[object] = [str(folder.resolve()), selected_date.month, selected_date.day]
        if media_filter == "Photos":
            sql += " AND media_type = 'image'"
        elif media_filter == "Videos":
            sql += " AND media_type = 'video'"
        sql += " ORDER BY capture_year DESC, capture_ts DESC"
        connection = open_database()
        try:
            records = []
            for file_path, capture_ts, media_type, file_size, modified_ns in connection.execute(sql, params):
                path = Path(file_path)
                if not path.exists():
                    continue
                try:
                    captured_at = datetime.fromisoformat(capture_ts)
                except (TypeError, ValueError):
                    continue
                records.append(MediaRecord(path, captured_at, media_type or "image", file_size, modified_ns))
            return records
        finally:
            connection.close()

    def all_videos(self, folder: Path) -> list[VideoRecord]:
        connection = open_database()
        try:
            rows = connection.execute("""
                SELECT file_path, capture_ts, file_size, modified_ns
                FROM photos
                WHERE folder_root = ? AND media_type = 'video'
                ORDER BY capture_year DESC, capture_month DESC, capture_day DESC,
                         capture_ts DESC, file_path ASC
            """, (str(folder.resolve()),)).fetchall()
            return [VideoRecord(Path(path), timestamp, size, modified) for path, timestamp, size, modified in rows]
        finally:
            connection.close()
