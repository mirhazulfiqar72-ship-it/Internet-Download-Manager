from idm.browser_formats import probe_formats, valid_quality
import sys, os, json, struct, subprocess, urllib.parse

EXTENSION_ID = 'degijjganjjjdkgibkndbdemjfnndmne'


def _is_native_host_invocation(argv):
    if '--native-host' in argv:
        return True
    # Chromium launches a Windows native-messaging host with the extension
    # origin on its command line. Detect our stable unpacked-extension ID.
    return any(a.startswith(f'chrome-extension://{EXTENSION_ID}/') for a in argv[1:])


def _read_exact_windows(n):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.GetStdHandle.argtypes = [wintypes.DWORD]
    k32.GetStdHandle.restype = wintypes.HANDLE
    k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    k32.ReadFile.restype = wintypes.BOOL
    h = k32.GetStdHandle(wintypes.DWORD(0xFFFFFFF6))  # STD_INPUT_HANDLE (-10)
    out = bytearray()
    while len(out) < n:
        buf = ctypes.create_string_buffer(n - len(out))
        got = wintypes.DWORD()
        if not k32.ReadFile(h, buf, len(buf), ctypes.byref(got), None) or got.value == 0:
            break
        out.extend(buf.raw[:got.value])
    return bytes(out)


def _write_all_windows(data):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.GetStdHandle.argtypes = [wintypes.DWORD]
    k32.GetStdHandle.restype = wintypes.HANDLE
    k32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    k32.WriteFile.restype = wintypes.BOOL
    h = k32.GetStdHandle(wintypes.DWORD(0xFFFFFFF5))  # STD_OUTPUT_HANDLE (-11)
    pos = 0
    while pos < len(data):
        chunk = data[pos:pos+65536]
        wrote = wintypes.DWORD()
        if not k32.WriteFile(h, chunk, len(chunk), ctypes.byref(wrote), None):
            return False
        pos += wrote.value
    return True


def _native_read_message():
    try:
        if os.name == 'nt':
            header = _read_exact_windows(4)
            if len(header) != 4: return None
            n = struct.unpack('<I', header)[0]
            if n <= 0 or n > 1024 * 1024: return None
            body = _read_exact_windows(n)
        else:
            stream = getattr(sys.stdin, 'buffer', None)
            if stream is None: return None
            header = stream.read(4)
            if len(header) != 4: return None
            n = struct.unpack('<I', header)[0]
            if n <= 0 or n > 1024 * 1024: return None
            body = stream.read(n)
        if len(body) != n: return None
        return json.loads(body.decode('utf-8'))
    except Exception:
        return None


def _native_write_message(payload):
    data = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    framed = struct.pack('<I', len(data)) + data
    try:
        if os.name == 'nt':
            return _write_all_windows(framed)
        stream = getattr(sys.stdout, 'buffer', None)
        if stream is None: return False
        stream.write(framed); stream.flush(); return True
    except Exception:
        return False


def _app_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    return [sys.executable, os.path.abspath(__file__)]


def native_host_main():
    msg = _native_read_message()
    if not isinstance(msg, dict):
        _native_write_message({'ok':False,'error':'Invalid browser message.'})
        return 1
    action = str(msg.get('action','')).strip()
    url = str(msg.get('url','')).strip()
    if action == 'mediaFormats':
        _native_write_message(probe_formats(url))
        return 0
    quality = str(msg.get('quality','best')).strip().lower()
    kind = str(msg.get('kind','video')).strip().lower()
    request_id = str(msg.get('requestId','')).strip()
    if action not in {'mediaPreset','directMedia','pageMedia'} or not url.lower().startswith(('http://','https://')):
        _native_write_message({'ok':False,'error':'Invalid download request.'})
        return 1
    if not valid_quality(quality): quality='best'
    if kind not in {'video','audio'}: kind='video'
    cmd = _app_command() + ['--browser-action', action, '--url', url, '--quality', quality, '--kind', kind]
    if msg.get('title'): cmd += ['--browser-title', str(msg.get('title'))]
    if request_id: cmd += ['--request-id', request_id]
    try:
        creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) if os.name == 'nt' else 0
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, creationflags=creationflags)
        _native_write_message({'ok':True})
        return 0
    except Exception as e:
        _native_write_message({'ok':False,'error':str(e)})
        return 1


if _is_native_host_invocation(sys.argv):
    raise SystemExit(native_host_main())

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from idm.main_window import MainWindow
from idm.wizard import FirstRunWizard


def _arg_value(argv, name, default=''):
    try:
        i = argv.index(name)
        return argv[i+1] if i+1 < len(argv) else default
    except ValueError:
        return default


def protocol_request(argv):
    action = _arg_value(argv, '--browser-action', '')
    if action:
        target = _arg_value(argv, '--url', '')
        quality = _arg_value(argv, '--quality', 'best').strip().lower()
        kind = _arg_value(argv, '--kind', 'video').strip().lower()
        if not valid_quality(quality): quality='best'
        if kind not in {'video','audio'}: kind='video'
        if action == 'mediaPreset': return target, 'media', quality, kind, _arg_value(argv,'--browser-title','')
        if action == 'directMedia': return target, 'direct', '', kind, ''
        return target, 'media', '', kind, ''

    for a in argv[1:]:
        if a.lower().startswith('idm://'):
            try:
                u = urllib.parse.urlparse(a)
                q = urllib.parse.parse_qs(u.query)
                target = urllib.parse.unquote(q.get('url', [''])[0])
                mode = 'media' if (u.netloc.lower() == 'media' or u.path.lower().strip('/') == 'media') else 'add'
                quality = (q.get('quality', [''])[0] or '').strip().lower()
                kind = (q.get('kind', ['video'])[0] or 'video').strip().lower()
                if quality != '' and not valid_quality(quality):
                    quality = ''
                if kind not in {'video', 'audio'}:
                    kind = 'video'
                return target, mode, quality, kind, ''
            except Exception:
                pass
    return '', 'add', '', 'video', ''


app = QApplication(sys.argv)
app.setApplicationName('Internet Download Manager')
_icon_path=os.path.join(os.path.dirname(os.path.abspath(__file__)),'assets','app_icon.png')
if os.path.exists(_icon_path): app.setWindowIcon(QIcon(_icon_path))
app.setOrganizationName('OriginalDownloadManager')
app.setQuitOnLastWindowClosed(False)
app.setProperty('really_quit', False)
if FirstRunWizard.should_show():
    FirstRunWizard().exec()
url, mode, quality, kind, browser_title = protocol_request(sys.argv)
window = MainWindow(url, mode, quality, kind, browser_title)
window.show()
sys.exit(app.exec())
