# Internet Download Manager v1.3.3 — Classic Main Interface Rebuild

This build keeps the existing download/video engine and browser integration, while rebuilding the main window into a classic desktop download-manager layout: menu bar, large icon toolbar, category tree, compact transfer list, classic Windows-style buttons, queues and status bar. Toolbar artwork is original and drawn by the application.

# Internet Download Manager 1.2.3 ROOT FIX

This build fixes two root causes found in v1.2.1:

1. **Add URL button:** Qt `clicked(bool)` was being passed into `add_url(initial_url=...)`. The toolbar/menu/tray actions now explicitly call `add_url()` without the Qt boolean argument.
2. **Immediate download failure:** SQLite returns `sqlite3.Row`. The download worker used `.get()` on that object, which raises `AttributeError` before any HTTP request starts. `DownloadTask` now converts the row to a normal `dict` once at startup.

Build size cleanup:
- PyInstaller remains a one-file build with unnecessary Qt modules excluded.
- After a successful build, `.venv` and build cache are removed. The ~1.3 GB Python/PySide build environment is not the installed/runtime software.
- Final runtime is `dist\InternetDownloadManager.exe`.

Build: run `BUILD_EXE.bat`.

## v1.2.3 pause/resume + progress window
- Fixed paused downloads staying registered as active tasks, which prevented Resume from creating a new worker.
- Resume now continues from saved single-stream bytes or durable segmented `.idm-parts` data when the server supports resume/ranges.
- Every direct download now opens a separate live progress window with status, size, downloaded percentage, speed, ETA, resume indication, progress bar, connection rows, Pause/Resume and Cancel/Close controls.


## v1.3.0 Professional UI + Browser Video Integration
- Refreshed professional desktop styling while preserving the working downloader.
- Browser extension can send links, direct HTML5 video/audio, or the current page to the desktop app.
- Current-page media uses yt-dlp for publicly accessible supported sites.
- Direct media links use the native HTTP downloader.
- Does not bypass DRM, subscriptions, logins, paywalls, or access controls.
- Run BUILD_EXE.bat first, then INSTALL_BROWSER_INTEGRATION.bat and load browser_extension as an unpacked extension.

## v1.3.1 browser video button
The unpacked Chrome/Edge extension now places an original **Download this video** control over the largest visible HTML5 video, including normal YouTube watch pages. Clicking it opens a quality menu (Best, 2160p, 1440p, 1080p, 720p, 480p, 360p, 240p, 144p, or best audio). Choosing an item sends the page URL and preset to the desktop app and starts the media job in the default Downloads folder.

For direct HTML5 media URLs, an **Original media file** option also appears when the browser exposes an HTTP/HTTPS media source. The extension and desktop app do not bypass DRM, authentication, paywalls, or site access controls. Site changes can affect extraction support.

High-resolution sites often publish video and audio as separate streams. The Windows build now includes `imageio-ffmpeg` so yt-dlp can merge supported video/audio streams without requiring the user to install ffmpeg separately.

After updating from an older source folder, open `chrome://extensions/`, remove or reload the older unpacked extension, and load this version's `browser_extension` folder.


## v1.3.2 direct browser download

The browser extension now sends a selected video quality directly to the desktop app. It first uses a loopback-only local bridge when the app is already running, and falls back to Chrome/Edge Native Messaging to launch the app when needed. It no longer creates an `idm://` browser tab for the quality menu.

After building the EXE, run `INSTALL_BROWSER_INTEGRATION.bat`, then reload the unpacked `browser_extension` folder. The stable extension ID used by the native host is `degijjganjjjdkgibkndbdemjfnndmne`.

## v1.4.8 browser media flow fix
- One browser quality click is de-duplicated so it creates only one desktop request/task.
- Media downloads keep the required flow: Download File Info -> Download Progress -> Download Complete.
- yt-dlp progress now feeds real downloaded bytes, total bytes, transfer speed and ETA into the normal progress window.
- Existing classic UI and dialogs are unchanged.


## v1.4.9 Extension workflow
- Quality click shows Download File Info even when the main app is minimized or hidden in the notification area.
- Main window stays minimized/hidden; the requested dialog itself is brought to the foreground.
- Media Progress uses real byte counters plus live-speed fallback and ETA.
- Media starts in Preparing media rather than remaining visually on Connecting.
- Progress closes on completion and Download Complete is brought to the foreground.
- Normal HTTP/HTTPS browser downloads are routed through File Info -> Progress -> Complete.
- Existing classic main UI is unchanged.


## v1.5.2 extension media transfer fix
Repeated browser downloads now use the File Info filename and a fresh unique output path.
This prevents yt-dlp from finding an already-downloaded title, skipping the transfer, leaving
the Progress window at Preparing media, and immediately firing Download Complete.
Real yt-dlp progress hooks continue to feed bytes, transfer rate and ETA to both the Progress
window and the main download list.
