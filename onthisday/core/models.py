from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MediaRecord:
    path: Path
    captured_at: datetime
    media_type: str
    file_size: int
    modified_ns: int

    @property
    def is_video(self) -> bool:
        return self.media_type == "video"


@dataclass(frozen=True, slots=True)
class VideoRecord:
    path: Path
    capture_ts: str | None
    file_size: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class YearMediaCount:
    year: int
    photos: int
    videos: int

    @property
    def total(self) -> int:
        return self.photos + self.videos


@dataclass(frozen=True, slots=True)
class AnalyticsResult:
    """Folder-scoped aggregates calculated exclusively from the media index."""

    total_photos: int
    total_videos: int
    combined_total: int
    busiest_day: tuple[int, int] | None
    busiest_day_count: int
    largest_year: int | None
    largest_year_count: int
    media_by_year: tuple[YearMediaCount, ...]
    most_active_month: int | None
    most_active_month_count: int


@dataclass(frozen=True, slots=True)
class ViewerItem:
    """One item the in-app viewer can show; built from gallery records or Video Library rows."""

    path: Path
    captured_at: datetime | None
    media_type: str
    file_size: int
    modified_ns: int

    @property
    def is_video(self) -> bool:
        return self.media_type == "video"

    @property
    def key(self) -> tuple[str, int]:
        return str(self.path), self.modified_ns

    @classmethod
    def from_media(cls, record: MediaRecord) -> "ViewerItem":
        return cls(record.path, record.captured_at, record.media_type, record.file_size, record.modified_ns)

    @classmethod
    def from_video(cls, record: VideoRecord) -> "ViewerItem":
        try:
            captured = datetime.fromisoformat(record.capture_ts) if record.capture_ts else None
        except ValueError:
            captured = None
        return cls(record.path, captured, "video", record.file_size, record.modified_ns)
