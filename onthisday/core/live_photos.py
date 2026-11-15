"""Pair the two files of an iPhone Live Photo: a still (HEIC/JPG) and a short motion clip (MOV).

Exports and backups keep them as separate files with the same name in the same folder, for
example IMG_4330.HEIC and IMG_4330.MOV. Shown separately, every Live Photo would appear twice:
once as a photo and once as a 1-3 second "video".
"""

import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

# The still and its clip are dated by the same camera clock, a second or two apart. A video
# that merely shares a photo's name was taken at some other time.
MAX_TIME_GAP_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class PairingRow:
    file_path: str
    media_type: str
    captured_at: datetime | None


def _belong_together(photo: PairingRow, video: PairingRow) -> bool:
    if photo.captured_at is None or video.captured_at is None:
        return False
    return abs((photo.captured_at - video.captured_at).total_seconds()) <= MAX_TIME_GAP_SECONDS


def pair_live_photos(rows: list[PairingRow]) -> list[tuple[str, str]]:
    """(photo path, video path) for every Live Photo: one photo and one video sharing a folder and name."""
    groups: dict[tuple[str, str], list[PairingRow]] = defaultdict(list)
    for row in rows:
        folder, name = os.path.split(row.file_path)
        groups[(folder, os.path.splitext(name)[0].lower())].append(row)
    pairs = []
    for members in groups.values():
        if len(members) != 2:
            continue  # a lone file, or an ambiguous group (two photos or two videos with one name)
        photos = [row for row in members if row.media_type == "image"]
        videos = [row for row in members if row.media_type == "video"]
        if len(photos) == 1 and len(videos) == 1 and _belong_together(photos[0], videos[0]):
            pairs.append((photos[0].file_path, videos[0].file_path))
    return pairs


def _parse(stamp: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        return None


def repair_live_photos(connection: sqlite3.Connection, folder_root: str) -> int:
    """Re-pair every Live Photo in one folder's index (one query and a dictionary pass).

    Each file of a pair stores the other's path in `live_pair`. The caller commits.
    """
    rows = [PairingRow(path, media_type or "image", _parse(stamp))
            for path, media_type, stamp in connection.execute(
                "SELECT file_path, media_type, capture_ts FROM photos WHERE folder_root = ?", (folder_root,))]
    pairs = pair_live_photos(rows)
    connection.execute("UPDATE photos SET live_pair = NULL WHERE folder_root = ? AND live_pair IS NOT NULL",
                       (folder_root,))
    connection.executemany(
        "UPDATE photos SET live_pair = ? WHERE folder_root = ? AND file_path = ?",
        [link for photo, video in pairs for link in ((video, folder_root, photo), (photo, folder_root, video))],
    )
    return len(pairs)
