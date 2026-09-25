import sys, tempfile, threading, re, hashlib, time
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from idm.downloader import DownloadTask
from idm.media import MediaDownloadTask
from unittest.mock import patch
DATA=bytes(range(256))*(64*1024)
SLOW_DATA=bytes(range(256))*(16*1024)
class Handler(BaseHTTPRequestHandler):
    heads=0; ranges=0
    def log_message(self,*args):pass
    def do_HEAD(self):
        type(self).heads+=1
        self.send_response(200);self.send_header('Content-Length',str(len(DATA)));self.send_header('Accept-Ranges','bytes');self.end_headers()
    def do_GET(self):
        if self.path=='/slow':
            self.send_response(200);self.send_header('Content-Length',str(len(SLOW_DATA)));self.end_headers()
            try:
                for offset in range(0,len(SLOW_DATA),64*1024):
                    self.wfile.write(SLOW_DATA[offset:offset+64*1024]);self.wfile.flush();time.sleep(0.03)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
            return
        start,end=0,len(DATA)-1
        header=self.headers.get('Range')
        if header and self.path!='/ignore':
            type(self).ranges+=1
            m=re.fullmatch(r'bytes=(\d+)-(\d*)',header)
            start=int(m[1]);end=int(m[2]) if m[2] else end
            self.send_response(206);self.send_header('Content-Range',f'bytes {start}-{end}/{len(DATA)}')
        else:self.send_response(200)
        self.send_header('Content-Length',str(end-start+1));self.end_headers()
        try:self.wfile.write(DATA[start:end+1])
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
class Storage:
    def __init__(self):self.data={};self.lock=threading.Lock()
    def update(self,rid,**kwargs):
        with self.lock:self.data.update(kwargs)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{server.server_port}'
def task(path,url,connections=4,payload=DATA):
    return DownloadTask({'id':1,'url':url,'path':str(path),'expected_hash':hashlib.sha256(payload).hexdigest()},Storage(),threading.Event(),threading.Event(),connections=connections,max_retries=0)
try:
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        d=task(root/'multi.bin',base+'/range');d.run()
        assert d.storage.data['status']=='Completed',d.storage.data
        assert (root/'multi.bin').read_bytes()==DATA
        assert Handler.heads==1 and Handler.ranges==2,(Handler.heads,Handler.ranges)
        # Resume existing segments with the unchanged two-range partition.
        path=root/'resume.bin';parts=Path(str(path)+'.idm-parts');parts.mkdir()
        (parts/'part-00.bin').write_bytes(DATA[:1024*1024])
        d=task(path,base+'/range');d.run()
        assert d.storage.data['status']=='Completed' and path.read_bytes()==DATA
        d=task(root/'fallback.bin',base+'/ignore');d.run()
        assert d.storage.data['status']=='Completed',d.storage.data
        assert (root/'fallback.bin').read_bytes()==DATA
        heads=Handler.heads
        d=task(root/'single.bin',base+'/range',1);d.run()
        assert Handler.heads==heads and (root/'single.bin').read_bytes()==DATA
        # Slow streams should publish progress frequently instead of jumping once per megabyte.
        d=task(root/'smooth.bin',base+'/slow',connections=1,payload=SLOW_DATA)
        updates=[];d.signals.progress.connect(lambda *args:updates.append(args));d.run()
        assert d.storage.data['status']=='Completed' and (root/'smooth.bin').read_bytes()==SLOW_DATA
        assert len(updates)>=8,f'Expected frequent progress updates, got {len(updates)}'
        # The media downloader uses the configured parallelism without changing quality selection.
        media=MediaDownloadTask(base+'/range','best',root,connections=6)
        with patch('idm.media.yt_dlp.YoutubeDL') as ydl:
            media.run()
            opts=ydl.call_args[0][0]
            assert opts['concurrent_fragment_downloads']==6 and opts['buffersize']==1024*1024
            assert opts['ratelimit'] is None
        print('Download integrity, parallel ranges, single HEAD, resume, fallback and media concurrency passed')
finally:server.shutdown();server.server_close()
