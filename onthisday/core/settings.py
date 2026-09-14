import json
from dataclasses import dataclass
from pathlib import Path

from .constants import APP_DIR, CONFIG_FILE, THUMBNAIL_DIR


@dataclass(slots=True)
class AppSettings:
    photo_folder: Path | None = None
    theme: str = "system"


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
            candidate = Path(folder_text).expanduser()
            if candidate.is_dir():
                folder = candidate
        theme = data.get("theme", "system")
        if theme not in {"system", "light", "dark"}:
            theme = "system"
        return AppSettings(folder, theme)

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
        })
        CONFIG_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
