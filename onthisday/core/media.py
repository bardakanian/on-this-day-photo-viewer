import hashlib
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from .constants import THUMBNAIL_DIR, THUMBNAIL_SIZE, VIDEO_EXTENSIONS
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


def thumbnail_cache_path(path: Path, file_size: int, modified_ns: int) -> Path:
    signature = f"{path}|{file_size}|{modified_ns}|{THUMBNAIL_SIZE[0]}x{THUMBNAIL_SIZE[1]}"
    return THUMBNAIL_DIR / f"{hashlib.sha256(signature.encode()).hexdigest()}.jpg"


def _image_thumbnail(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        if getattr(image, "is_animated", False):
            try:
                image.seek(0)
            except EOFError:
                pass
        image = image.convert("RGB")
        image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", THUMBNAIL_SIZE, (18, 20, 24))
        canvas.paste(image, ((THUMBNAIL_SIZE[0] - image.width) // 2, (THUMBNAIL_SIZE[1] - image.height) // 2))
        canvas.save(target, "JPEG", quality=87, optimize=True)


def _video_thumbnail(source: Path, target: Path) -> bool:
    if not FFMPEG_ENABLED:
        return False
    try:
        subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-ss", "1", "-i", str(source),
            "-frames:v", "1", "-vf",
            f"scale={THUMBNAIL_SIZE[0]}:{THUMBNAIL_SIZE[1]}:force_original_aspect_ratio=decrease,"
            f"pad={THUMBNAIL_SIZE[0]}:{THUMBNAIL_SIZE[1]}:(ow-iw)/2:(oh-ih)/2",
            "-q:v", "3", str(target),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
        return target.exists() and target.stat().st_size > 0
    except (OSError, subprocess.SubprocessError):
        return False


def get_cached_thumbnail(path: Path, media_type: str, file_size: int, modified_ns: int) -> Path | None:
    ensure_app_dirs()
    target = thumbnail_cache_path(path, file_size, modified_ns)
    if target.exists():
        return target
    try:
        if media_type == "video":
            if not _video_thumbnail(path, target):
                return None
        else:
            _image_thumbnail(path, target)
        return target
    except (OSError, ValueError):
        try:
            target.unlink(missing_ok=True)
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
