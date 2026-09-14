import sqlite3
from datetime import date, datetime
from pathlib import Path

from .constants import APP_DIR, DB_FILE, THUMBNAIL_DIR
from .models import AnalyticsResult, MediaRecord, VideoRecord, YearMediaCount


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

    def library_analytics(self, folder: Path) -> AnalyticsResult:
        """Return index-only analytics for one folder.

        Ties are deterministic: the earliest calendar day, year, or month wins.
        Each date-based aggregate ignores only rows missing the components it
        needs, so a row with a month but no year still contributes by month.
        """
        folder_root = str(folder.resolve())
        connection = open_database()
        try:
            combined, videos = connection.execute("""
                SELECT COUNT(*),
                       COALESCE(SUM(CASE WHEN media_type = 'video' THEN 1 ELSE 0 END), 0)
                FROM photos
                WHERE folder_root = ?
            """, (folder_root,)).fetchone()

            busiest_row = connection.execute("""
                SELECT capture_month, capture_day, COUNT(*) AS media_count
                FROM photos
                WHERE folder_root = ?
                  AND capture_month IS NOT NULL
                  AND capture_day IS NOT NULL
                GROUP BY capture_month, capture_day
                ORDER BY media_count DESC, capture_month ASC, capture_day ASC
                LIMIT 1
            """, (folder_root,)).fetchone()

            year_rows = connection.execute("""
                SELECT capture_year,
                       SUM(CASE WHEN media_type = 'video' THEN 0 ELSE 1 END) AS photos,
                       SUM(CASE WHEN media_type = 'video' THEN 1 ELSE 0 END) AS videos
                FROM photos
                WHERE folder_root = ? AND capture_year IS NOT NULL
                GROUP BY capture_year
                ORDER BY capture_year ASC
            """, (folder_root,)).fetchall()
            media_by_year = tuple(YearMediaCount(int(year), int(photos), int(year_videos))
                                  for year, photos, year_videos in year_rows)
            largest = min(media_by_year, key=lambda item: (-item.total, item.year), default=None)

            month_row = connection.execute("""
                SELECT capture_month, COUNT(*) AS media_count
                FROM photos
                WHERE folder_root = ? AND capture_month IS NOT NULL
                GROUP BY capture_month
                ORDER BY media_count DESC, capture_month ASC
                LIMIT 1
            """, (folder_root,)).fetchone()

            return AnalyticsResult(
                total_photos=int(combined - videos),
                total_videos=int(videos),
                combined_total=int(combined),
                busiest_day=(int(busiest_row[0]), int(busiest_row[1])) if busiest_row else None,
                busiest_day_count=int(busiest_row[2]) if busiest_row else 0,
                largest_year=largest.year if largest else None,
                largest_year_count=largest.total if largest else 0,
                media_by_year=media_by_year,
                most_active_month=int(month_row[0]) if month_row else None,
                most_active_month_count=int(month_row[1]) if month_row else 0,
            )
        finally:
            connection.close()
