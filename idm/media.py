from .media_runtime import runtime_options
from .media_selection import preset_selector, unpack_selector, verify_height, cached_download_info

from PySide6.QtCore import QObject, Signal, QRunnable
import time
import threading
from pathlib import Path
import yt_dlp

def _ffmpeg_exe():
    """Return an optional bundled ffmpeg executable for high-quality A/V merging."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ''


class MediaSignals(QObject):
    formats = Signal(object)
    progress = Signal(float, float, str, str, object, object)  # percent, speed, eta, status, downloaded, total
    finished = Signal(str)
    failed = Signal(str)

class MediaInfoTask(QRunnable):
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.signals = MediaSignals()

    def run(self):
        try:
            opts = {"quiet": True, "no_warnings": True, "skip_download": True}
            with yt_dlp.YoutubeDL({**runtime_options(), **opts}) as ydl:
                info = ydl.extract_info(self.url, download=False)
            formats = []
            for f in info.get("formats", []):
                if not f.get("url"): continue
                vcodec, acodec = f.get("vcodec"), f.get("acodec")
                if vcodec == "none" and acodec == "none": continue
                formats.append({
                    "format_id": f.get("format_id",""),
                    "ext": f.get("ext",""),
                    "resolution": f.get("resolution") or
                                 (f'{f.get("height")}p' if f.get("height") else "audio"),
                    "fps": f.get("fps") or "",
                    "filesize": f.get("filesize") or f.get("filesize_approx") or 0,
                    "vcodec": vcodec or "none",
                    "acodec": acodec or "none",
                    "note": f.get("format_note") or "",
                })
            title = info.get("title") or "Media download"
            self.signals.formats.emit({"title": title, "formats": formats})
        except Exception as e:
            self.signals.failed.emit(str(e))

class DownloadPaused(Exception):
    pass

class DownloadCancelled(Exception):
    pass

class MediaDownloadTask(QRunnable):
    def __init__(self, url, format_id, output_dir, target_name='media', stop_event=None, pause_event=None):
        super().__init__()
        self.url, self.format_id, self.output_dir = url, format_id, Path(output_dir)
        self.target_name = str(target_name or 'media')
        self.stop_event = stop_event or threading.Event()
        self.pause_event = pause_event or threading.Event()
        self.signals = MediaSignals()

    def _fresh_template(self):
        # Browser media must never silently reuse an old yt-dlp output. Reusing
        # an existing title was the reason Progress stayed at Preparing media
        # and then jumped straight to Complete on repeated tests.
        stem = Path(self.target_name).stem or 'media'
        bad = '<>:"/\\|?*'
        stem = ''.join('_' if c in bad or ord(c) < 32 else c for c in stem).strip(' .') or 'media'
        candidate = self.output_dir / stem
        n = 1
        # yt-dlp adds the actual extension, so test common media extensions.
        # Completed outputs require a new name, but .part files must be reused
        # by yt-dlp so Resume continues the original transfer.
        while any(Path(str(candidate)+ext).exists() for ext in ('.mp4','.mkv','.webm','.m4a','.mp3')):
            candidate = self.output_dir / f'{stem} ({n})'
            n += 1
        return str(candidate) + '.%(ext)s'

    def _format_selector(self):
        locked=unpack_selector(self.format_id)
        if locked: return locked['format']
        value=(self.format_id or '').strip()
        if value.startswith('preset-'):
            kind, quality=value.split(':',1)
            return preset_selector(quality,kind.replace('preset-',''))
        return value or 'bestvideo*+bestaudio/best'

    def run(self):
        try:
            last_done = 0
            last_time = time.monotonic()
            smooth_speed = 0.0
            last_emit = 0.0
            completed_streams = {}
            def hook(d):
                nonlocal last_done, last_time, smooth_speed, last_emit
                # yt-dlp only yields control to us through progress hooks.
                # Raising DownloadCancelled stops the active network transfer
                # immediately enough for Stop/Cancel/Pause to be real controls.
                if self.stop_event.is_set():
                    raise DownloadCancelled('Stopped by user')
                if self.pause_event.is_set():
                    raise DownloadPaused('Paused by user')
                status = d.get("status")
                if status == "downloading":
                    stream_key = str(d.get("filename") or d.get("info_dict", {}).get("format_id") or "stream")
                    offset = sum(v for k,v in completed_streams.items() if k != stream_key)
                    done = offset + int(d.get("downloaded_bytes") or 0)
                    total = offset + int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
                    now = time.monotonic()
                    reported = float(d.get("speed") or 0.0)
                    dt, db = now-last_time, done-last_done
                    if reported <= 0 and dt > 0.05 and db >= 0:
                        reported = db/dt
                    if reported > 0:
                        smooth_speed = reported if smooth_speed <= 0 else smooth_speed*0.55 + reported*0.45
                    last_done, last_time = done, now
                    pct = done*100.0/total if total > 0 else 0.0
                    eta = d.get("eta")
                    if eta is None and total > done and smooth_speed > 0:
                        eta = int((total-done)/smooth_speed)
                    if now-last_emit < 0.2:return
                    last_emit=now
                    self.signals.progress.emit(pct, float(smooth_speed or reported or 0.0),
                                               str(int(eta)) if eta is not None else "",
                                               "Downloading", done, total)
                elif status == "finished":
                    key = str(d.get("filename") or d.get("info_dict", {}).get("format_id") or "stream")
                    completed_streams[key] = int(d.get("downloaded_bytes") or d.get("total_bytes") or 0)
                    # Final completion is emitted only after all streams are merged.
            opts = {
                "format": self._format_selector(),
                "outtmpl": self._fresh_template(),
                "noplaylist": True, "quiet": True, "no_warnings": True,
                "progress_hooks": [hook], "merge_output_format": ("mkv" if str(self.format_id).startswith("preset-video:") and str(self.format_id).split(":", 1)[1].isdigit() and int(str(self.format_id).split(":", 1)[1]) >= 1440 else "mp4"),
                "overwrites": False,
                "continuedl": True,
                "nopart": False,
            }
            locked=unpack_selector(self.format_id)
            if locked: opts['merge_output_format']=locked['ext']
            ffmpeg = _ffmpeg_exe()
            if ffmpeg: opts["ffmpeg_location"] = ffmpeg
            with yt_dlp.YoutubeDL({**runtime_options(), **opts}) as ydl:
                info = cached_download_info(self.url,locked) if locked else None
                used_cache = info is not None
                if info is None:
                    info = ydl.extract_info(self.url, download=False)
                if locked:
                    verify_height(info,locked['quality'],locked['kind'])
                elif str(self.format_id).startswith('preset-video:'):
                    verify_height(info,str(self.format_id).split(':',1)[1],'video')
                if self.stop_event.is_set(): raise DownloadCancelled('Stopped by user')
                if self.pause_event.is_set(): raise DownloadPaused('Paused by user')
                if locked and info.get('requested_formats'):
                    info['ext']=locked['ext']
                try:
                    ydl.process_info(info)
                except yt_dlp.utils.DownloadError as exc:
                    # Refresh an expired/rejected signed URL once, without changing quality.
                    if not used_cache or last_done or not any(code in str(exc) for code in ('403','410')):
                        raise
                    info=ydl.extract_info(self.url,download=False)
                    verify_height(info,locked['quality'],locked['kind'])
                    if info.get('requested_formats'): info['ext']=locked['ext']
                    if self.stop_event.is_set(): raise DownloadCancelled('Stopped by user')
                    if self.pause_event.is_set(): raise DownloadPaused('Paused by user')
                    ydl.process_info(info)
                requested = info.get("requested_downloads") or []
                final_path = info.get("filepath") or ""
                if not final_path and requested:
                    for item in reversed(requested):
                        candidate = item.get("filepath") or ""
                        if candidate and Path(candidate).exists():
                            final_path = candidate; break
                if not final_path: final_path = ydl.prepare_filename(info)
            self.signals.finished.emit(str(final_path))
        except DownloadPaused:
            self.signals.failed.emit('__IDM_PAUSED__')
        except DownloadCancelled:
            self.signals.failed.emit('__IDM_STOPPED__')
        except Exception as e:
            self.signals.failed.emit(str(e))

