"""One format decision shared by File Info and the download worker."""
import json


def preset_selector(quality, kind='video'):
    if kind == 'audio':
        return 'bestaudio[ext=m4a]/bestaudio/best'
    constraint = '' if quality == 'best' else f'[height={int(quality)}]'
    return (f'bestvideo{constraint}[ext=mp4]+bestaudio[ext=m4a]/'
            f'bestvideo{constraint}+bestaudio/best{constraint}[ext=mp4]/best{constraint}')


def selection_parts(info):
    return info.get('requested_formats') or [info]


def verify_height(info, quality, kind):
    if kind != 'video' or quality == 'best':
        return
    videos = [f for f in selection_parts(info) if f.get('vcodec') not in (None, 'none')]
    if not videos or any(int(f.get('height') or 0) != int(quality) for f in videos):
        raise ValueError(f'Selected {quality}p is unavailable. Lower quality was not downloaded.')


def describe_selection(info, quality, kind):
    verify_height(info, quality, kind)
    parts = selection_parts(info)
    fmt = '+'.join(str(f['format_id']) for f in parts)
    ext = ('mkv' if kind == 'video' and len(parts) > 1 and quality != 'best' and int(quality) >= 1440
           else 'mp4' if kind == 'video' and len(parts) > 1 else info.get('ext') or parts[0].get('ext') or 'mp4')
    total = 0
    approximate = len(parts) > 1  # Final mux container adds overhead.
    for f in parts:
        n = f.get('filesize')
        if not n:
            n = f.get('filesize_approx')
            approximate = True
        if not n and f.get('tbr') and info.get('duration'):
            n = float(f['tbr']) * 1000 / 8 * float(info['duration'])
            approximate = True
        if not n:
            total = 0
            break
        total += int(n)
    return dict(title=info.get('title') or 'Video', ext=ext, size=total,
                approximate=approximate, selector='locked:' + json.dumps(
                    dict(format=fmt, quality=quality, kind=kind, ext=ext), separators=(',', ':')))


def unpack_selector(value):
    return json.loads(value[7:]) if str(value).startswith('locked:') else None


def _cache_path(url, quality, kind):
    import os, hashlib
    from pathlib import Path
    from urllib.parse import urlsplit, parse_qs
    parsed=urlsplit(url)
    if (parsed.hostname or '').endswith('.youtube.com') or parsed.hostname == 'youtube.com':
        video_id=parse_qs(parsed.query).get('v', [''])[0]
        if video_id: url='https://www.youtube.com/watch?v='+video_id
    key=hashlib.sha256(f'{url}|{quality}|{kind}'.encode()).hexdigest()
    root=Path(os.environ.get('LOCALAPPDATA', Path.home()/'.cache'))/'InternetDownloadManager'/'MediaInfoCache'
    return root/(key+'.json')


def cached_selection(url, quality, kind):
    import time
    try:
        record=json.loads(_cache_path(url,quality,kind).read_text(encoding='utf-8'))
        if record.get('version') != 2: return None
        data=record['data']
        if 0 <= time.time()-record['created'] < 300 and unpack_selector(data['selector']):
            return data
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def cache_selection(url, quality, kind, data, info=None):
    import time, tempfile, os
    path=_cache_path(url,quality,kind)
    if info:
        import yt_dlp
        data=dict(data)
        # Reuse the resolved stream, not another webpage extraction at Start.
        selected=yt_dlp.YoutubeDL.sanitize_info(info)
        for key in ('formats','thumbnails','subtitles','automatic_captions','requested_downloads','filepath','_filename'):
            selected.pop(key,None)
        data['download_info']=selected
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
            temp=f.name
            json.dump({'version':2,'created':time.time(),'data':data},f)
        os.replace(temp,path)
        # Keep this small metadata cache bounded.
        files=sorted(path.parent.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        for old in files[160:]: old.unlink(missing_ok=True)
    except OSError:
        pass


def fill_reported_sizes(info):
    """Ask only selected direct streams for missing exact Content-Length."""
    import requests
    from concurrent.futures import ThreadPoolExecutor
    def probe(f):
        if f.get('filesize') or f.get('protocol') not in ('http','https'):
            return
        try:
            headers=dict(f.get('http_headers') or {})
            headers['Accept-Encoding']='identity'
            with requests.head(f['url'],headers=headers,allow_redirects=True,timeout=(2,3)) as response:
                n=response.headers.get('Content-Length','')
                mime=response.headers.get('Content-Type','').lower()
                if response.status_code==200 and n.isdigit() and int(n)>0 and ('video/' in mime or 'audio/' in mime or 'octet-stream' in mime):
                    f['filesize']=int(n)
        except requests.RequestException:
            pass
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(probe, selection_parts(info)))


def resolve_selection(url, quality, kind):
    cached=cached_selection(url,quality,kind)
    if cached: return cached
    import yt_dlp
    with yt_dlp.YoutubeDL({'quiet':True,'no_warnings':True,'noplaylist':True,
            'format':preset_selector(quality,kind),'socket_timeout':15}) as ydl:
        info=ydl.extract_info(url,download=False)
    fill_reported_sizes(info)
    data=describe_selection(info,quality,kind)
    cache_selection(url,quality,kind,data,info)
    return data


def prepare_format_sizes(url, info, rows):
    """Reuse already extracted metadata, so opening File Info needs no re-extraction."""
    import copy, yt_dlp
    from concurrent.futures import ThreadPoolExecutor
    base={k:info[k] for k in ('id','title','duration','formats','webpage_url','extractor','extractor_key') if k in info}
    def prepare(row):
        quality=row['quality']
        cached=cached_selection(url,quality,'video')
        if cached: return
        try:
            class QuietLogger:
                def debug(self,*args): pass
                def warning(self,*args): pass
                def error(self,*args): pass
            with yt_dlp.YoutubeDL({'quiet':True,'no_warnings':True,'logger':QuietLogger(),
                    'format':preset_selector(quality),'noplaylist':True}) as ydl:
                selected=ydl.process_ie_result(copy.deepcopy(base),download=False)
            fill_reported_sizes(selected)
            cache_selection(url,quality,'video',describe_selection(selected,quality,'video'),selected)
        except Exception:
            pass  # The desktop retries this quality if metadata was incomplete.
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(prepare,rows))


def cached_download_info(url, locked):
    import copy, time
    from urllib.parse import urlsplit,parse_qs
    data=cached_selection(url,locked['quality'],locked['kind'])
    if not data or unpack_selector(data['selector']) != locked:
        return None
    info=data.get('download_info')
    if not info: return None
    try:
        for part in selection_parts(info):
            expiry=parse_qs(urlsplit(part.get('url','')).query).get('expire',[''])[0]
            if expiry and float(expiry)<time.time()+30: return None
        verify_height(info,locked['quality'],locked['kind'])
        return copy.deepcopy(info)
    except (ValueError,TypeError):
        return None
