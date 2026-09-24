import re, time, threading, math, hashlib, os, shutil
from pathlib import Path
from urllib.parse import urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from PySide6.QtCore import QObject, Signal, QRunnable

USER_AGENT = "OriginalDownloadManager/1.2.2"

REQUEST_HEADERS = {'User-Agent': USER_AGENT, 'Accept': '*/*', 'Accept-Encoding': 'identity'}


def safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name or "download")
    name = name.strip(" .")
    return name[:240] or "download"


def filename_from_response(url, response):
    cd = response.headers.get("Content-Disposition", "")
    m = re.search(r"filename\\*=UTF-8''([^;]+)", cd, re.I)
    if m: return safe_filename(unquote(m.group(1)))
    m = re.search(r'filename="?([^";]+)"?', cd, re.I)
    if m: return safe_filename(m.group(1))
    name = Path(unquote(urlparse(response.url).path)).name
    return safe_filename(name or "download")


class RangeUnsupported(IOError):
    pass


class DownloadSignals(QObject):
    progress = Signal(int, int, float, float)
    status = Signal(str, str)
    finished = Signal()
    failed = Signal(str)
    stopped = Signal()


class DownloadTask(QRunnable):
    """Resumable downloader with automatic multi-connection HTTP Range support.

    The main task remains one queue item while up to `connections` worker threads
    download byte ranges into durable .idm-part-N files. If Range is unsupported,
    it transparently falls back to the original single-stream downloader.
    """
    def __init__(self, row, storage, stop_event, pause_event, speed_limit_kbps=0, connections=4, max_retries=3):
        super().__init__()
        # sqlite3.Row is mapping-like but does not implement .get(). Convert it
        # once here so worker code can safely use both [] and .get().
        self.row=dict(row); self.storage=storage; self.stop_event=stop_event; self.pause_event=pause_event
        self.speed_limit_bps=max(0,int(speed_limit_kbps))*1024
        self.connections=max(1,min(16,int(connections)))
        self.max_retries=max(0,min(10,int(max_retries)))
        self.expected_hash=(self.row.get("expected_hash") or "").strip().lower()
        self.hash_algorithm=(self.row.get("hash_algorithm") or "SHA-256").upper()
        self.signals=DownloadSignals()
        self._lock=threading.RLock(); self._last_emit=0.0; self._last_bytes=0
        self._started=time.monotonic()
        self._metadata_total=0
        self._range_disabled=False
        self._range_abort=threading.Event()
        self._aggregate_bytes=0

    def run(self):
        rid,url,path=self.row['id'],self.row['url'],Path(self.row['path'])
        for attempt in range(self.max_retries + 1):
            if self.stop_event.is_set(): self.signals.stopped.emit(); return
            try:
                self._check_disk(path.parent)
                if not self._range_disabled and self.connections>1 and self._supports_segmented(url):
                    try:
                        self._segmented(rid,url,path)
                    except RangeUnsupported:
                        self._range_disabled=True
                        self._single(rid,url,path)
                        shutil_rmtree(self._part_dir(path))
                else: self._single(rid,url,path)
                return
            except Exception as exc:
                if self.stop_event.is_set(): self.signals.stopped.emit(); return
                if self.pause_event.is_set():
                    self.storage.update(rid,status='Paused')
                    self.signals.status.emit('Paused','Resume available'); return
                if attempt>=self.max_retries:
                    msg=self._friendly_error(exc)
                    self.storage.update(rid,status='Failed',error=msg,retry_count=attempt+1); self.signals.failed.emit(msg); return
                self.storage.update(rid,status='Retrying',error=str(exc),retry_count=attempt+1)
                self.signals.status.emit('Retrying',f'Attempt {attempt+2}/{self.max_retries+1}: {self._friendly_error(exc)}')
                time.sleep(min(2.0*(attempt+1), 8.0))

    @staticmethod
    def _friendly_error(exc):
        msg=str(exc).strip() or exc.__class__.__name__
        if isinstance(exc, requests.exceptions.ConnectionError):
            return f'Network connection failed: {msg}'
        if isinstance(exc, requests.exceptions.Timeout):
            return f'Network timeout: {msg}'
        if isinstance(exc, requests.exceptions.HTTPError):
            code=getattr(exc.response, 'status_code', None) if getattr(exc, 'response', None) is not None else None
            return f'HTTP {code}: server rejected the download request.' if code else f'HTTP error: {msg}'
        return msg

    def _check_disk(self, folder):
        try:
            free=shutil.disk_usage(folder).free
            # Keep a small safety reserve; the actual file size is checked by the stream/segments.
            if free < 10*1024*1024:
                raise OSError('Not enough free disk space (less than 10 MB available).')
        except FileNotFoundError:
            Path(folder).mkdir(parents=True, exist_ok=True)

    def _verify_hash(self, path):
        if not self.expected_hash:
            return True, ''
        algo=self.hash_algorithm.replace('-','').lower()
        if algo not in hashlib.algorithms_available:
            return False, f'Unsupported hash algorithm: {self.hash_algorithm}'
        h=hashlib.new(algo)
        with open(path,'rb') as f:
            while True:
                b=f.read(1024*1024)
                if not b: break
                h.update(b)
        actual=h.hexdigest().lower()
        return actual==self.expected_hash, actual

    def _supports_segmented(self,url):
        # Prefer server metadata. A Range probe can itself trigger anti-bot/rate
        # limits and was causing false failures on otherwise downloadable files.
        try:
            with requests.head(url, headers=REQUEST_HEADERS, timeout=(12,25), allow_redirects=True) as r:
                if not r.ok:
                    return False
                length=r.headers.get('Content-Length')
                accept=r.headers.get('Accept-Ranges','').lower()
                if length and int(length)>1024*1024 and accept=='bytes':
                    self._metadata_total=int(length)
                    return True
        except (requests.RequestException, ValueError):
            pass
        return False

    def _total_size(self,url):
        try:
            with requests.head(url, headers=REQUEST_HEADERS, timeout=(12,25), allow_redirects=True) as r:
                if r.ok and r.headers.get('Content-Length'):
                    return int(r.headers['Content-Length'])
        except (requests.RequestException, ValueError):
            pass
        # A one-byte Range request is only used when HEAD does not expose size.
        with requests.get(url, headers={**REQUEST_HEADERS,'Range':'bytes=0-0'}, stream=True, timeout=(12,30), allow_redirects=True) as r:
            r.raise_for_status()
            cr=r.headers.get('Content-Range','')
            m=re.match(r'^bytes\s+\d+-\d+/(\d+)$',cr,re.I)
            if m: return int(m.group(1))
            return int(r.headers.get('Content-Length','0') or 0)

    def _part_dir(self,path):
        return Path(str(path)+'.idm-parts')

    def _segmented(self,rid,url,path):
        path.parent.mkdir(parents=True,exist_ok=True)
        total=self._metadata_total or self._total_size(url)
        if total<=0 or self.connections<=1: return self._single(rid,url,path)
        partdir=self._part_dir(path); partdir.mkdir(parents=True,exist_ok=True)
        n=min(self.connections,max(2,math.ceil(total/(8*1024*1024))))
        ranges=[]
        for i in range(n):
            start=(total*i)//n; end=(total*(i+1))//n-1
            ranges.append((i,start,end))
        self.row['total']=total
        self._range_abort.clear()
        self._aggregate_bytes=self._parts_size(partdir,ranges)
        self._last_bytes=self._aggregate_bytes
        self._last_emit=time.monotonic()
        self.storage.update(rid,status='Downloading',total=total,downloaded=self._parts_size(partdir,ranges))
        self.signals.status.emit('Downloading',f'Multi-connection: {n} connections')
        with ThreadPoolExecutor(max_workers=n,thread_name_prefix='idm-range') as ex:
            futures=[ex.submit(self._range_worker,url,partdir,i,start,end) for i,start,end in ranges]
            for fut in as_completed(futures): fut.result()
        if self.stop_event.is_set(): self.storage.update(rid,status='Stopped',downloaded=self._parts_size(partdir,ranges),total=total); self.signals.stopped.emit(); return
        if self.pause_event.is_set(): self.storage.update(rid,status='Paused',downloaded=self._parts_size(partdir,ranges),total=total); self.signals.status.emit('Paused','Partial ranges saved for resume'); return
        tmp=Path(str(path)+'.idm-assembling')
        with open(tmp,'wb') as out:
            for i,start,end in ranges:
                part=partdir/f'part-{i:02d}.bin'
                expected=end-start+1
                if not part.exists() or part.stat().st_size!=expected: raise IOError(f'Incomplete download segment {i+1}/{n}')
                with open(part,'rb') as f:
                    while True:
                        b=f.read(1024*1024)
                        if not b:break
                        out.write(b)
        os.replace(tmp,path)
        size=path.stat().st_size
        if size!=total: raise IOError(f'Final file size mismatch: expected {total}, got {size}')
        ok, actual=self._verify_hash(path)
        if not ok:
            self.storage.update(rid,status='Failed',downloaded=size,total=total,error=f'Checksum mismatch. Expected {self.expected_hash}; actual {actual}')
            self.signals.failed.emit('Checksum mismatch. The downloaded file failed SHA/hash verification.')
            return
        shutil_rmtree(partdir)
        self.storage.update(rid,status='Completed',downloaded=size,total=total,error='',completed=time.time())
        self.signals.progress.emit(size,total,0,0); self.signals.finished.emit()

    def _range_worker(self,url,partdir,index,start,end):
        part=partdir/f'part-{index:02d}.bin'; expected=end-start+1
        existing=part.stat().st_size if part.exists() else 0
        if existing>expected: part.unlink(); existing=0
        if existing==expected:return
        offset=start+existing; headers={**REQUEST_HEADERS,'Range':f'bytes={offset}-{end}'}
        with requests.get(url,headers=headers,stream=True,timeout=(15,60),allow_redirects=True) as r:
            if r.status_code!=206:
                if r.status_code==200:
                    self._range_abort.set()
                    raise RangeUnsupported('Server ignored HTTP Range')
                r.raise_for_status()
                raise IOError(f'Server did not honor HTTP Range (HTTP {r.status_code})')
            cr=r.headers.get('Content-Range','')
            if not re.match(rf'^bytes\s+{offset}-{end}/{self._current_total}$', cr, re.I):
                raise IOError('Server returned an invalid Content-Range response')
            with open(part,'ab') as f:
                for chunk in r.iter_content(1024*1024):
                    if self.stop_event.is_set() or self.pause_event.is_set() or self._range_abort.is_set(): return
                    if not chunk:continue
                    f.write(chunk); self._emit_aggregate(len(chunk))
        if part.stat().st_size!=expected: raise IOError(f'Incomplete segment {index+1}')

    def _parts_size(self,partdir,ranges):
        return sum(min((partdir/f'part-{i:02d}.bin').stat().st_size if (partdir/f'part-{i:02d}.bin').exists() else 0,end-start+1) for i,start,end in ranges)

    def _emit_aggregate(self,received):
        # Count received bytes in memory; only one worker publishes each UI tick.
        # Avoid repeatedly scanning/stat-ing all segment files on the hot path.
        with self._lock:
            self._aggregate_bytes+=received
            now=time.monotonic()
            if now-self._last_emit<0.2:return
            total=self._aggregate_bytes
            speed=max(0,total-self._last_bytes)/max(now-self._last_emit,0.001)
            self._last_emit=now; self._last_bytes=total
            rid=self.row['id']; expected=self._current_total
            eta=(expected-total)/speed if speed>0 else 0
            self.storage.update(rid,status='Downloading',downloaded=total,total=expected)
            self.signals.progress.emit(total,expected,speed,eta)

    @property
    def _current_total(self):
        return int(self.row.get('total') or 0) or 0

    def _single(self,rid,url,path):
        path.parent.mkdir(parents=True,exist_ok=True); existing=path.stat().st_size if path.exists() else 0
        headers=dict(REQUEST_HEADERS)
        if existing:headers['Range']=f'bytes={existing}-'
        self.signals.status.emit('Connecting','')
        with requests.get(url,headers=headers,stream=True,timeout=(15,60),allow_redirects=True) as r:
            r.raise_for_status(); supports=r.status_code==206
            if existing and not supports: existing=0
            cr=r.headers.get('Content-Range','')
            if supports and '/' in cr:
                try:total=int(cr.rsplit('/',1)[1])
                except ValueError:total=0
            else:
                try:total=int(r.headers.get('Content-Length','0'))+existing
                except ValueError:total=0
            mode='ab' if existing and supports else 'wb'; downloaded=existing
            started=time.monotonic(); last_t=started; last_b=downloaded
            with open(path,mode) as f:
                for chunk in r.iter_content(1024*1024):
                    if self.stop_event.is_set(): self.storage.update(rid,status='Stopped',downloaded=downloaded,total=total); self.signals.stopped.emit(); return
                    if self.pause_event.is_set(): self.storage.update(rid,status='Paused',downloaded=downloaded,total=total); self.signals.status.emit('Paused','Resume available'); return
                    if not chunk:continue
                    if self.speed_limit_bps:
                        elapsed=time.monotonic()-started; expected=(downloaded-existing)/max(self.speed_limit_bps,1)
                        if expected>elapsed:time.sleep(min(expected-elapsed,2.0))
                    f.write(chunk); downloaded+=len(chunk); now=time.monotonic()
                    if now-last_t>=0.2:
                        speed=(downloaded-last_b)/max(now-last_t,.001); eta=(total-downloaded)/speed if total and speed>0 else 0
                        self.storage.update(rid,status='Downloading',downloaded=downloaded,total=total); self.signals.progress.emit(downloaded,total,speed,eta); last_t,last_b=now,downloaded
            ok, actual=self._verify_hash(path)
            if not ok:
                msg=f'Checksum mismatch. Expected {self.expected_hash}; actual {actual}'
                self.storage.update(rid,status='Failed',downloaded=downloaded,total=total,error=msg)
                self.signals.failed.emit(msg); return
            self.storage.update(rid,status='Completed',downloaded=downloaded,total=total,error='',completed=time.time()); self.signals.progress.emit(downloaded,total,0,0); self.signals.finished.emit()


def shutil_rmtree(p):
    import shutil
    try: shutil.rmtree(p)
    except FileNotFoundError: pass
