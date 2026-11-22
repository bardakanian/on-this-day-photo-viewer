import json
from dataclasses import dataclass
from pathlib import Path

from .constants import APP_DIR, CONFIG_FILE, HIGH_THUMBNAIL_EDGE, THUMBNAIL_DIR, THUMBNAIL_EDGE
from .gallery_layout import DEFAULT_TILE, MAX_TILE, MIN_TILE
from .timeformat import DEFAULT_TIME_FORMAT, TIME_FORMATS

PREVIEW_STANDARD, PREVIEW_HIGH = "standard", "high"
PREVIEW_QUALITIES = {PREVIEW_STANDARD: THUMBNAIL_EDGE, PREVIEW_HIGH: HIGH_THUMBNAIL_EDGE}
DEFAULT_PREVIEW_QUALITY = PREVIEW_HIGH


def preview_edge(quality: str) -> int:
    """The longest side previews are saved at for a quality setting."""
    return PREVIEW_QUALITIES.get(quality, PREVIEW_QUALITIES[DEFAULT_PREVIEW_QUALITY])


@dataclass(slots=True)
class AppSettings:
    photo_folder: Path | None = None
    theme: str = "system"
    save_previews: bool = True  # a preview of every item, for browsing while the drive is disconnected
    time_format: str = DEFAULT_TIME_FORMAT
    auto_rescan: bool = True  # re-check the library when returning to the app
    preview_quality: str = DEFAULT_PREVIEW_QUALITY  # how large saved previews are
    tile_size: int = DEFAULT_TILE  # the gallery's tile size in points, changed by zooming

    @property
    def preview_edge(self) -> int:
        return preview_edge(self.preview_quality)


class SettingsStore:
    """Backward-compatible access to the existing JSON configuration."""

    def load(self) -> AppSettings:
        data: dict = {}
        try:
            if CONFIG_FILE.exists():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            data = {}

        folder = None
        folder_text = data.get("photo_folder", "")
        if folder_text:
            # Kept even when it's missing right now: it may be on a drive that isn't connected,
            # and dropping it would make the next save forget the library for good.
            folder = Path(folder_text).expanduser()
        theme = data.get("theme", "system")
        if theme not in {"system", "light", "dark"}:
            theme = "system"
        time_format = data.get("time_format", DEFAULT_TIME_FORMAT)
        if time_format not in TIME_FORMATS:
            time_format = DEFAULT_TIME_FORMAT
        quality = data.get("preview_quality", DEFAULT_PREVIEW_QUALITY)
        if quality not in PREVIEW_QUALITIES:
            quality = DEFAULT_PREVIEW_QUALITY
        try:
            tile = int(data.get("tile_size", DEFAULT_TILE))
        except (TypeError, ValueError):
            tile = DEFAULT_TILE
        return AppSettings(folder, theme, data.get("save_previews", True) is not False, time_format,
                           data.get("auto_rescan", True) is not False, quality,
                           max(MIN_TILE, min(MAX_TILE, tile)))

    def save(self, settings: AppSettings) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
        existing: dict = {}
        try:
            if CONFIG_FILE.exists():
                existing = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            pass
        existing.update({
            "photo_folder": str(settings.photo_folder) if settings.photo_folder else "",
            "theme": settings.theme,
            "save_previews": settings.save_previews,
            "time_format": settings.time_format,
            "auto_rescan": settings.auto_rescan,
            "preview_quality": settings.preview_quality,
            "tile_size": settings.tile_size,
        })
        CONFIG_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
