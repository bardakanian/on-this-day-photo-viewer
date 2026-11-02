# Changelog

With every change, bump `VERSION` in `onthisday/core/constants.py` and add an entry here.

## 1.5.1 — 2026-11-01

- Photos are dated by when they were taken (EXIF DateTimeOriginal). Before, that tag was never found, so edited photos got their edit date. The next scan re-reads every date once.
- A date that is a placeholder (1904, 1970, 1980) no longer stops the search; the next date in the photo or video is tried.
- Thumbnails are written to a temporary file and renamed into place, so a half-written one is never shown or kept.
- Hidden and system files are no longer indexed: macOS "._" files on external and network drives, `.Trashes`, Synology `@eaDir`, and Windows `$RECYCLE.BIN`.
- February 29 photos and videos show on February 28 in years without a leap day.
- After a delete, the gallery keeps the years you expanded with "Load more" or collapsed, and no longer jumps later.
- The Video Library count respects an active search after Refresh.

## 1.5.0 — 2026-11-01

- Show the version number in the window title ("On This Day 1.5.0") and in the macOS launcher's Get Info.
- Added this changelog.

## 1.4.1 — 2026-10-31

- Fixed the viewer going black when a photo finished loading after "Loading…" was shown (for example after jumping with End).

## 1.4.0 — 2026-10-28

- Windows support: no console windows flash up for ffmpeg, file creation dates read correctly, and shortcuts show Windows key names.
- `tools/make_launcher.py` adds a Start-menu (and optional Desktop) shortcut on Windows.
- README documents the in-app viewer and its keyboard shortcuts.

## 1.3.1 — 2026-10-28

- Files without capture metadata are no longer dated by when they were copied; placeholder dates (1904, 1970, 1980) are ignored.

## 1.3.0 — 2026-10-28

- In-app viewer for photos and videos: zoom and pan, previous/next, full-resolution decoding on zoom, prefetching of neighbours, and Move to Trash.
- Gallery queries and thumbnail reads run in the background, and indexing reads capture dates in parallel.
- macOS launcher in the Applications folder (`tools/make_launcher.py`).

## 1.2.0 — 2026-10-28

- Sharper Retina thumbnails, faster JPEG decoding, and a fallback frame for videos that fail to seek.
- Files that can't be previewed are remembered, so they aren't retried on every scroll.

## 1.1.1 — 2026-09-26

- Added the MIT license, a polished README, and privacy-safe screenshots.

## 1.1.0 — 2026-09-18

- Delete photos and videos from the gallery (moved to the Trash).

## 1.0.0 — 2026-09-13

- First release of the PySide6 app: "On This Day" gallery of photos and videos from past years, a Videos page, and Library Insights analytics.
