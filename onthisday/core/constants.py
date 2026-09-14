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
# Keep the legacy cache signature so existing user thumbnails remain reusable.
THUMBNAIL_SIZE = (240, 180)
BATCH_COMMIT_SIZE = 250
VIDEO_METADATA_VERSION = 5
INITIAL_YEAR_BATCH = 60
