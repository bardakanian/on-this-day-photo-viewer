from pathlib import Path

APP_NAME = "On This Day"
APP_DIR = Path.home() / ".on_this_day_photo_viewer"
CONFIG_FILE = APP_DIR / "config.json"
DB_FILE = APP_DIR / "photo_index.sqlite3"
THUMBNAIL_DIR = APP_DIR / "thumbnails"

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif",
    ".webp", ".heic", ".heif",
}
VIDEO_EXTENSIONS = {
    ".mov", ".mp4", ".m4v", ".avi", ".mkv", ".wmv", ".mpeg",
    ".mpg", ".3gp",
}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
# Rendered at 2x the 248x186 preview so thumbnails stay sharp on Retina displays.
THUMBNAIL_SIZE = (496, 372)
# Older thumbnails are still shown as placeholders while sharper ones are generated.
LEGACY_THUMBNAIL_SIZE = (240, 180)
BATCH_COMMIT_SIZE = 250
# Bump to make the next scan re-read every file's capture date. Despite the name (kept for
# database compatibility) it applies to photos and videos since version 6, which stopped
# dating metadata-less files by when they were copied; 7 ignores epoch and unset-clock dates.
VIDEO_METADATA_VERSION = 7
INITIAL_YEAR_BATCH = 60
