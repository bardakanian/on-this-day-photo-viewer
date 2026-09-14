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
