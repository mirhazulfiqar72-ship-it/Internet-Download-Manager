"""Actual available resolutions for the browser dropdown."""
import re


def valid_quality(value):
    return value == 'best' or bool(re.fullmatch(r'[1-9][0-9]{0,4}', str(value)))


def video_type(quality):
    return 'mkv' if quality != 'best' and int(quality) >= 1440 else 'mp4'


def rows_from_info(info):
    heights = set()
    for f in info.get('formats') or [info]:
        if not f.get('url') or f.get('has_drm') or f.get('vcodec') in (None, 'none'):
            continue
        height = f.get('height')
        if isinstance(height, (int, float)) and 0 < height < 100000:
            heights.add(int(height))
    return [{'quality': str(h), 'type': video_type(str(h)).upper()} for h in sorted(heights, reverse=True)]


def probe_formats(url):
    try:
        if not re.match(r'^https?://', url, re.I):
            raise ValueError('Invalid video URL')
        import yt_dlp
        # Native host stdout is reserved for framed JSON responses.
        class QuietLogger:
            def debug(self, *args): pass
            def warning(self, *args): pass
            def error(self, *args): pass
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True,
                'logger': QuietLogger(), 'skip_download': True, 'noplaylist': True,
                'socket_timeout': 12, 'retries': 0, 'extractor_retries': 0}) as ydl:
            info = ydl.extract_info(url, download=False)
        rows = rows_from_info(info or {})
        if rows:
            from .media_selection import prepare_format_sizes
            prepare_format_sizes(url,info,rows)
        return {'ok': bool(rows), 'application': 'InternetDownloadManager',
                'title': (info or {}).get('title') or 'Video', 'formats': rows,
                'error': '' if rows else 'No downloadable video resolutions detected. Click again to retry.'}
    except Exception:
        return {'ok': False, 'application': 'InternetDownloadManager',
                'error': 'Could not read this video. Check the connection or video access and retry.'}
