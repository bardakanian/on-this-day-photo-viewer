import hashlib
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from .constants import LEGACY_THUMBNAIL_SIZE, THUMBNAIL_DIR, THUMBNAIL_SIZE, VIDEO_EXTENSIONS
from .database import ensure_app_dirs

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_ENABLED = True
except ImportError:
    HEIC_ENABLED = False

try:
    import imageio_ffmpeg
    FFMPEG_ENABLED = True
except ImportError:
    imageio_ffmpeg = None
    FFMPEG_ENABLED = False

Image.MAX_IMAGE_PIXELS = None


def media_type_for_path(path: Path) -> str:
    return "video" if path.suffix.lower() in VIDEO_EXTENSIONS else "image"


def parse_macos_metadata_date(path: Path) -> datetime | None:
    if sys.platform != "darwin":
        return None
    for field in ("kMDItemContentCreationDate", "kMDItemFSCreationDate"):
        try:
            result = subprocess.run(
                ["mdls", "-raw", "-name", field, str(path)],
                capture_output=True, text=True, timeout=5, check=False,
            )
            value = result.stdout.strip()
            if not value or value == "(null)":
                continue
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")
            return parsed.astimezone().replace(tzinfo=None)
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
    return None


def get_image_exif_date(path: Path) -> datetime | None:
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            for tag in (36867, 36868, 306):
                value = exif.get(tag) if exif else None
                if not value:
                    continue
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="ignore")
                for date_format in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return datetime.strptime(str(value).strip(), date_format)
                    except ValueError:
                        continue
    except (OSError, ValueError, TypeError):
        pass
    return None


def get_video_metadata_date(path: Path) -> datetime | None:
    if not FFMPEG_ENABLED:
        return None
    try:
        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        candidates = []
        for line in result.stderr.splitlines():
            stripped = line.strip()
            if "creation_time" in stripped:
                candidates.append(stripped.partition(":")[2].strip())
            elif "date" in stripped.lower() and ":" in stripped:
                key, _, value = stripped.partition(":")
                if key.strip().lower() in {"date", "date-eng", "creation date"}:
                    candidates.append(value.strip())
        for value in filter(None, candidates):
            normalized = value.replace("Z", "+00:00")
            for parser in (
                datetime.fromisoformat,
                lambda item: datetime.strptime(item, "%Y-%m-%d %H:%M:%S"),
                lambda item: datetime.strptime(item, "%Y/%m/%d %H:%M:%S"),
            ):
                try:
                    parsed = parser(normalized)
                    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
                except ValueError:
                    continue
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def get_filesystem_creation_date(path: Path) -> datetime | None:
    try:
        stat = path.stat()
        return datetime.fromtimestamp(getattr(stat, "st_birthtime", stat.st_ctime))
    except OSError:
        return None


def get_capture_date(path: Path, media_type: str) -> datetime | None:
    if media_type == "image":
        detected = get_image_exif_date(path) or parse_macos_metadata_date(path)
    else:
        detected = get_video_metadata_date(path) or parse_macos_metadata_date(path) or get_filesystem_creation_date(path)
    if detected is not None:
        return detected
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def thumbnail_cache_path(
    path: Path, file_size: int, modified_ns: int, size: tuple[int, int] = THUMBNAIL_SIZE,
) -> Path:
    signature = f"{path}|{file_size}|{modified_ns}|{size[0]}x{size[1]}"
    return THUMBNAIL_DIR / f"{hashlib.sha256(signature.encode()).hexdigest()}.jpg"


def legacy_thumbnail_cache_path(path: Path, file_size: int, modified_ns: int) -> Path:
    return thumbnail_cache_path(path, file_size, modified_ns, LEGACY_THUMBNAIL_SIZE)


def _failure_marker(target: Path) -> Path:
    return target.with_suffix(".failed")


def thumbnail_cache_files(path: Path, file_size: int, modified_ns: int) -> list[Path]:
    """Every cache file that may exist for one media item."""
    target = thumbnail_cache_path(path, file_size, modified_ns)
    return [target, _failure_marker(target), legacy_thumbnail_cache_path(path, file_size, modified_ns)]


def _image_thumbnail(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        if getattr(image, "is_animated", False):
            try:
                image.seek(0)
            except EOFError:
                pass
        # Let JPEGs decode at a reduced scale. This must happen before exif_transpose
        # loads the full image; a square request covers both rotated orientations.
        longest = max(THUMBNAIL_SIZE)
        image.draft("RGB", (longest, longest))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", THUMBNAIL_SIZE, (18, 20, 24))
        canvas.paste(image, ((THUMBNAIL_SIZE[0] - image.width) // 2, (THUMBNAIL_SIZE[1] - image.height) // 2))
        canvas.save(target, "JPEG", quality=87, optimize=True)


def _video_thumbnail(source: Path, target: Path) -> bool:
    # Prefer a frame one second in (skips black fade-ins); clips shorter than that
    # produce nothing, so fall back to the very first frame.
    for seek in (["-ss", "1"], []):
        try:
            subprocess.run([
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", *seek, "-i", str(source),
                "-frames:v", "1", "-vf",
                f"scale={THUMBNAIL_SIZE[0]}:{THUMBNAIL_SIZE[1]}:force_original_aspect_ratio=decrease,"
                f"pad={THUMBNAIL_SIZE[0]}:{THUMBNAIL_SIZE[1]}:(ow-iw)/2:(oh-ih)/2",
                "-q:v", "3", str(target),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if target.exists() and target.stat().st_size > 0:
            return True
    return False


def get_cached_thumbnail(path: Path, media_type: str, file_size: int, modified_ns: int) -> Path | None:
    ensure_app_dirs()
    target = thumbnail_cache_path(path, file_size, modified_ns)
    if target.exists():
        return target
    failed = _failure_marker(target)
    if failed.exists():
        return None
    if media_type == "video" and not FFMPEG_ENABLED:
        return None
    try:
        if media_type == "video":
            if not _video_thumbnail(path, target):
                raise OSError("ffmpeg produced no frame")
        else:
            _image_thumbnail(path, target)
        return target
    except (OSError, ValueError):
        try:
            target.unlink(missing_ok=True)
            # Remember the failure so the file isn't re-decoded every time it is shown.
            # Skip this when the source is missing (e.g. an unmounted drive) so it retries later.
            # The cache key includes size and mtime, so editing the file also retries.
            if path.exists():
                failed.touch()
        except OSError:
            pass
        return None


def open_in_default_app(path: Path) -> tuple[bool, str | None]:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path))
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True, None
    except OSError as exc:
        return False, str(exc)
