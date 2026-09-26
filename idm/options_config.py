"""Persistent Options settings and helpers; defaults preserve existing behavior."""
import copy, json, os, sys, fnmatch, subprocess, threading, shlex
from pathlib import Path
from urllib.parse import urlsplit, quote
from PySide6.QtCore import QSettings

DEFAULTS = {
 'startup':False,'clipboard':False,'integration':True,'browsers':['Chrome','Edge','Opera','Brave'],
 'file_types':'*','excluded_sites':'','excluded_urls':'','context_menu':True,'video_panel':True,
 'prevent_keys':['Alt','Shift'],'force_keys':[],
 'connection_type':'High speed / Ethernet / Wi-Fi','connection_rules':[],
 'categories':{},'temp_dir':'','show_start':True,'show_complete':True,
 'progress_view':'Normal','progress_speed':True,'progress_completion':True,'progress_details':True,
 'user_agent':'OriginalDownloadManager/1.2.2','scanner':'','scanner_args':'[File]',
 'proxy_mode':'System','proxy_scheme':'http','proxy_host':'','proxy_port':8080,'proxy_user':'','proxy_secret':'','proxy_exceptions':'',
 'logins':[],'dial_enabled':False,'dial_name':'','dial_retries':0,'dial_delay':30,
 'sounds':{}
}
CATEGORIES={'Programs':('exe msi msix appx apk xapk bat cmd com dll jar deb rpm dmg iso run ps1 sh sys bin','Programs'),
 'Video':('mp4 mkv webm avi mov m4v wmv flv mpeg mpg 3gp ts m2ts mts ogv','Video'),
 'Audio':('mp3 m4a aac wav flac ogg opus wma aiff mid midi alac mka','Music'),
 'Documents':('pdf doc docx docm xls xlsx xlsm ppt pptx pptm txt csv rtf odt epub ods odp','Documents'),
 'Archives':('zip rar 7z gz tar bz2 xz tgz','Compressor'),
 'Pictures':('jpg jpeg png gif bmp webp svg tif tiff ico heic heif avif raw psd','Pictures'),
 'Other':('','Other')}

def load_options():
    data=copy.deepcopy(DEFAULTS)
    try:data.update(json.loads(QSettings('OriginalDownloadManager','InternetDownloadManager').value('options_v1','{}')))
    except (ValueError,TypeError):pass
    return data

def save_options(data):
    q=QSettings('OriginalDownloadManager','InternetDownloadManager');q.setValue('options_v1',json.dumps(data));q.sync()

def protect(secret):
    if not secret:return ''
    if os.name!='nt':raise ValueError('Saving passwords requires Windows user encryption.')
    return _crypt(secret.encode(),False)

def unprotect(secret):
    if not secret:return ''
    return _crypt(secret,True).decode()

def _crypt(value,decrypt):
    import ctypes, base64
    from ctypes import wintypes
    class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    raw=base64.b64decode(value) if decrypt else value
    buffer=ctypes.create_string_buffer(raw);source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));target=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    function=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    function.restype=wintypes.BOOL
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):raise ctypes.WinError(ctypes.get_last_error())
    try:
        result=ctypes.string_at(target.data,target.size)
        return result if decrypt else base64.b64encode(result).decode()
    finally:kernel.LocalFree(target.data)

def matches(url,patterns):
    host=(urlsplit(url).hostname or '').lower()
    return any(fnmatch.fnmatchcase(url.lower(),p.lower()) if '://' in p else fnmatch.fnmatchcase(host,p.lower()) for p in str(patterns).split())

def category_settings(category,options=None):
    from .storage import DEFAULT_DIR
    options=options or load_options();types,sub=CATEGORIES.get(category,('',''))
    return {'types':types,'folder':str(Path(DEFAULT_DIR)/sub),'remember':False,**options['categories'].get(category,{})}

def category_folder(category):return Path(category_settings(category)['folder']).expanduser()

def connection_count(url,default,options=None):
    for rule in (options or load_options())['connection_rules']:
        if matches(url,rule['host']):return max(1,min(16,int(rule['count'])))
    return default

def proxy_url(url,options):
    if matches(url,options['proxy_exceptions']):return ''
    if options['proxy_mode']=='None':return ''
    if options['proxy_mode']=='System':
        from urllib.request import getproxies,proxy_bypass
        if proxy_bypass(urlsplit(url).hostname or ''):return ''
        return getproxies().get(urlsplit(url).scheme,'')
    host=options['proxy_host'].strip()
    if not host:return ''
    auth=''
    if options['proxy_user']:auth=quote(options['proxy_user'],safe='')+':'+quote(unprotect(options['proxy_secret']),safe='')+'@'
    if ':' in host and not host.startswith('['):host='['+host+']'
    return f"{options['proxy_scheme']}://{auth}{host}:{int(options['proxy_port'])}"

def site_login(url,options):
    target=urlsplit(url)
    for login in sorted(options['logins'],key=lambda v:len(v['url']),reverse=True):
        site=urlsplit(login['url'])
        # Exact origin and path boundary prevent credentials leaking to look-alike hosts.
        if (site.scheme,site.netloc.lower())==(target.scheme,target.netloc.lower()) and (target.path==site.path.rstrip('/') or target.path.startswith(site.path.rstrip('/')+'/')):
            return login['user'],unprotect(login['secret'])
    return None

def request_kwargs(url,options):
    proxy=proxy_url(url,options)
    result={'proxies':{'http':proxy,'https':proxy}}
    login=site_login(url,options)
    if login:result['auth']=login
    return result

def media_options(url,options=None):
    options=options or load_options()
    result={'proxy':proxy_url(url,options)}
    if options['user_agent']:result['http_headers']={'User-Agent':options['user_agent']}
    login=site_login(url,options)
    if login:result.update(username=login[0],password=login[1])
    if options['temp_dir']:result['paths']={'temp':options['temp_dir']}
    return result

def apply_startup(enabled):
    if os.name!='nt':return
    import winreg
    command=subprocess.list2cmdline([sys.executable]+([] if getattr(sys,'frozen',False) else [str(Path(__file__).resolve().parents[1]/'main.py')]))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:winreg.SetValueEx(key,'OriginalDownloadManager',0,winreg.REG_SZ,command)
        else:
            try:winreg.DeleteValue(key,'OriginalDownloadManager')
            except FileNotFoundError:pass

def sound_event(event,options=None):
    item=(options or load_options())['sounds'].get(event,{})
    if item.get('enabled') and item.get('path') and os.name=='nt':
        import winsound
        try:winsound.PlaySound(item['path'],winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
        except RuntimeError:pass

def scan_file(path,options=None):
    options=options or load_options()
    if not options['scanner']:return
    args=shlex.split(options['scanner_args'],posix=False)
    args=[a.strip('"').replace('[File]',str(path)) for a in args]
    if '[File]' not in options['scanner_args']:args.append(str(path))
    subprocess.Popen([options['scanner'],*args],shell=False,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

_dial_lock=threading.Lock()
def dial_connect(options=None,disconnect=False):
    options=options or load_options()
    if os.name!='nt':raise OSError('Windows Dial-Up / VPN is available on Windows only.')
    name=options['dial_name'].strip()
    if not name or name.startswith('/') or '\n' in name:raise ValueError('Select a Windows connection first.')
    with _dial_lock:
        command=[str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/'rasdial.exe'),name]
        if disconnect:command.append('/disconnect')
        result=subprocess.run(command,capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise OSError(result.stdout.strip() or result.stderr.strip() or 'Connection failed')
        return result.stdout.strip()

def ensure_connection(options,stop=None):
    if not options['dial_enabled']:return
    for attempt in range(int(options['dial_retries'])+1):
        if stop and stop.is_set():return
        try:dial_connect(options);return
        except OSError:
            if attempt>=int(options['dial_retries']):raise
            if stop:stop.wait(int(options['dial_delay']))
            else:
                import time;time.sleep(int(options['dial_delay']))
