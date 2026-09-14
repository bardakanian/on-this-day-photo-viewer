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
