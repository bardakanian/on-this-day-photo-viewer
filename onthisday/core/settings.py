import json
from dataclasses import dataclass
from pathlib import Path

from .constants import APP_DIR, CONFIG_FILE, THUMBNAIL_DIR
from .timeformat import DEFAULT_TIME_FORMAT, TIME_FORMATS


@dataclass(slots=True)
class AppSettings:
    photo_folder: Path | None = None
    theme: str = "system"
    save_previews: bool = True  # a preview of every item, for browsing while the drive is disconnected
    time_format: str = DEFAULT_TIME_FORMAT


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
        return AppSettings(folder, theme, data.get("save_previews", True) is not False, time_format)

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
        })
        CONFIG_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
