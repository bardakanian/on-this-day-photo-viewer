# Changelog

With every change, bump `VERSION` in `onthisday/core/constants.py` and add an entry here.

## 1.10.1 — 2026-11-08

- On a read-only drive, such as an NTFS drive on a Mac, Move to Trash is dimmed and explains why, instead of asking for confirmation and then failing with a permission error.

## 1.10.0 — 2026-11-08

- After each scan, a preview of every item is saved in the background, starting with the calendar days coming up soonest. The status bar shows the progress. It can be turned off in Settings.
- While the library's drive is disconnected, the gallery still shows every indexed item with its saved preview instead of an empty page. The viewer shows the preview enlarged to fit, and Open in Default App, Move to Trash and video playback wait until the drive is back. The Info panel falls back to the date in the index.
- Saving previews resumes when the app opens, without scanning the library.
- The viewer keeps a photo's preview on screen when the original can't be read, instead of replacing it with an error.

## 1.9.1 — 2026-11-08

- The app no longer scans the library every time it opens; it shows the saved index right away. Use **Rescan** to pick up new files at any time. The library is still re-checked when you return to the app after 10 minutes.

## 1.7.0 — 2026-11-02

- The library refreshes itself: at launch, and when you return to the app after 10 minutes. Scans that find nothing new leave the gallery as it is.
- A library on a drive that isn't connected is no longer forgotten. The gallery says the folder is unavailable, and the photos come back as soon as the drive does. Before, changing a setting while the drive was unplugged erased the saved folder.
- The gallery is a virtual grid: only the cards on screen are drawn and load thumbnails, so every item shows without "Load more" and scrolling stays smooth at any size. Right-click a card for Open and Move to Trash.
- Videos keep the local time they were recorded at (QuickTime creation date) instead of converting UTC with this computer's time zone, so travel videos land on the right day. The next scan re-reads dates once.
- `tools/build_app.py` builds a standalone app (macOS .app, Windows .exe) that runs without Python or the project folder.
- GitHub Actions runs the tests on macOS and Windows and builds both apps for every push.
- Fixed the empty-gallery message being cut off at the bottom.

## 1.6.0 — 2026-11-01

- Info panel in the viewer: select **Info** or press **I** to see the capture date and where it came from, dimensions, type, file size and path. Videos also show duration, frame rate and codec.

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
