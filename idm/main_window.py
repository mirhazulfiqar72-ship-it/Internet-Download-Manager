from .duplicates import DuplicateDownloadDialog, url_key, same_selection, numbered_path, path_key
from .browser_formats import probe_formats, valid_quality, video_type
import threading
import re, threading, time, os, sys, subprocess, json
from pathlib import Path
from PySide6.QtCore import QSettings, QFileInfo, Qt, QEvent, QThreadPool, QTimer, QDateTime, Signal, QObject, QSize, QRectF, QPointF
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QPen, QColor, QBrush, QFont, QPolygonF
from PySide6.QtWidgets import (QFileIconProvider,
    QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QLineEdit,QApplication,
    QTableWidget,QTableWidgetItem,QHeaderView,QMessageBox,QDialog,QFormLayout,
    QDialogButtonBox,QFileDialog,QInputDialog,QComboBox,QStatusBar,QMenu,QSpinBox,QCheckBox,QDateTimeEdit,
    QSystemTrayIcon,QToolButton,QStyle,QTreeWidget,QTreeWidgetItem,QFrame,QProgressBar,QTabWidget,QGroupBox
)
from .storage import Storage, DEFAULT_DIR
from .downloader import DownloadTask, filename_from_response, safe_filename
from .settings import AppSettings
from .release import VERSION, UPDATE_MANIFEST_URL
from .options_dialog import SettingsDialog
import requests
import hashlib, socket




class BrowserBridge(QObject):
    """Small loopback-only bridge used by the browser extension.

    It accepts only local HTTP requests and forwards validated commands to the
    Qt main thread through a signal. This avoids opening an idm:// browser tab.
    """
    request = Signal(object)

    def __init__(self, parent=None, port=17654):
        super().__init__(parent)
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        try:
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
            bridge = self

            class Handler(BaseHTTPRequestHandler):
                server_version = 'IDMLocalBridge/1.0'
                def log_message(self, *args):
                    return
                def _headers(self, status=200):
                    self.send_response(status)
                    self.send_header('Content-Type','application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin','*')
                    self.send_header('Access-Control-Allow-Methods','POST, OPTIONS')
                    self.send_header('Access-Control-Allow-Headers','Content-Type')
                    self.send_header('Access-Control-Allow-Private-Network','true')
                    self.send_header('Cache-Control','no-store')
                    self.end_headers()
                def do_OPTIONS(self):
                    self._headers(204)
                def do_POST(self):
                    if self.path != '/v1/download':
                        self._headers(404); self.wfile.write(b'{"ok":false}'); return
                    try:
                        n = int(self.headers.get('Content-Length','0') or '0')
                        if n <= 0 or n > 65536:
                            raise ValueError('invalid body size')
                        data = json.loads(self.rfile.read(n).decode('utf-8'))
                        if not isinstance(data, dict):
                            raise ValueError('invalid request')
                        url = str(data.get('url','')).strip()
                        action = str(data.get('action','')).strip()
                        if action == 'mediaFormats':
                            result = probe_formats(url)
                            self._headers(200)
                            self.wfile.write(json.dumps(result).encode('utf-8'))
                            return
                        if action not in {'mediaPreset','directMedia','pageMedia'} or not re.match(r'^https?://', url, re.I):
                            raise ValueError('invalid command')
                        bridge.request.emit(data)
                        self._headers(202)
                        self.wfile.write(b'{"ok":true,"application":"InternetDownloadManager"}')
                    except Exception:
                        self._headers(400)
                        self.wfile.write(b'{"ok":false,"application":"InternetDownloadManager"}')

            self.server = ThreadingHTTPServer(('127.0.0.1', self.port), Handler)
            self.server.daemon_threads = True
            self.thread = threading.Thread(target=self.server.serve_forever, name='IDMBrowserBridge', daemon=True)
            self.thread.start()
            return True
        except OSError:
            # Another running app instance may already own the bridge port.
            return False
        except Exception:
            return False

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.server = None

class AddressDialog(QDialog):
    """First Add URL step: compact address entry before Download File Info."""
    def __init__(self, parent=None, initial_url=''):
        super().__init__(parent)
        self.setWindowTitle('Enter new address to download')
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setFixedSize(480,118)
        self.setObjectName('classicAddressDialog')
        root=QVBoxLayout(self); root.setContentsMargins(10,8,10,8); root.setSpacing(6)
        row=QHBoxLayout(); row.setSpacing(8); row.addWidget(QLabel('Address'))
        self.url=QLineEdit(initial_url); self.url.setMinimumHeight(22); self.url.selectAll(); row.addWidget(self.url,1)
        ok=QPushButton('OK'); cancel=QPushButton('Cancel'); ok.setDefault(True); ok.setFixedSize(68,25); cancel.setFixedSize(68,25)
        ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        buttons=QVBoxLayout(); buttons.addWidget(ok); buttons.addWidget(cancel); row.addLayout(buttons); root.addLayout(row)
        auth=QCheckBox('Use authorization'); root.addWidget(auth)
        creds=QHBoxLayout(); creds.setSpacing(7); creds.addWidget(QLabel('Login')); login=QLineEdit(); login.setEnabled(False); creds.addWidget(login); creds.addWidget(QLabel('Password')); password=QLineEdit(); password.setEchoMode(QLineEdit.Password); password.setEnabled(False); creds.addWidget(password); root.addLayout(creds)
        auth.toggled.connect(login.setEnabled); auth.toggled.connect(password.setEnabled)
        self.url.returnPressed.connect(self.accept)

class AddDialog(QDialog):
    remote_metadata_ready=Signal(object)

    def __init__(self, parent=None, initial_url=''):
        super().__init__(parent); self.setWindowTitle('Download File Info'); self.setFixedSize(570,210); self.action='cancel'
        self._user_save_as_edited=False; self._user_category_selected=False
        self.remote_metadata_ready.connect(self._apply_remote_metadata)
        flags=(self.windowFlags() | Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint) & ~Qt.WindowContextHelpButtonHint
        self.setWindowFlags(flags)
        self.setObjectName('classicDownloadDialog')
        root=QVBoxLayout(self); root.setContentsMargins(10,8,10,10); root.setSpacing(8)
        content=QHBoxLayout(); form=QFormLayout(); form.setLabelAlignment(Qt.AlignRight|Qt.AlignVCenter); form.setHorizontalSpacing(6); form.setVerticalSpacing(4)
        self.url=QLineEdit(initial_url); self.url.setMinimumHeight(24); self.url.setPlaceholderText('https://example.com/file.zip'); form.addRow('URL',self.url)
        self.category=QComboBox(); self.category.addItems(['Programs','Video','Audio','Documents','Archives','Pictures','Other'])
        catrow=QHBoxLayout(); catrow.setSpacing(4); catrow.addWidget(self.category); plus=QPushButton('+'); plus.setFixedSize(26,23); catrow.addWidget(plus); form.addRow('Category',catrow)
        self.folder=QLineEdit(str(DEFAULT_DIR)); self.filename=QLineEdit(''); self.filename.setPlaceholderText('Filename is detected from URL')
        self.folder.hide(); self.filename.hide()
        self.save_as=QLineEdit(str(DEFAULT_DIR)); self.save_as.setPlaceholderText(r'E:\Movie Explain\Video title.mp4')
        saverow=QHBoxLayout(); saverow.setSpacing(4); saverow.addWidget(self.save_as,1); browse=QPushButton('...'); browse.setFixedSize(30,23); saverow.addWidget(browse); browse.clicked.connect(self.browse); form.addRow('Save As',saverow)
        self.remember=QCheckBox('Remember this path for the selected category'); form.addRow('',self.remember)
        self.path_display=QLineEdit(str(DEFAULT_DIR)); self.path_display.setReadOnly(True); form.addRow('',self.path_display)
        self.category.currentTextChanged.connect(lambda t:self.remember.setText(f'Remember this path for "{t}" category'))
        self.description=QLineEdit(); form.addRow('Description',self.description); content.addLayout(form,1)
        previewcol=QVBoxLayout(); previewcol.setContentsMargins(8,28,0,0); previewcol.setAlignment(Qt.AlignTop|Qt.AlignHCenter)
        self.file_icon=QLabel(); self.file_icon.setFixedSize(48,48); self.file_icon.setAlignment(Qt.AlignCenter); self.file_icon.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon).pixmap(40,40)); previewcol.addWidget(self.file_icon,0,Qt.AlignHCenter)
        self.file_size=QLabel('--'); self.file_size.setAlignment(Qt.AlignCenter); previewcol.addWidget(self.file_size)
        content.addLayout(previewcol)
        root.addLayout(content)
        root.setAlignment(Qt.AlignTop)
        buttons=QHBoxLayout(); buttons.setContentsMargins(0,1,0,0); buttons.setSpacing(16); buttons.addStretch(1); later=QPushButton('Download Later'); start=QPushButton('Start Download'); cancel=QPushButton('Cancel'); start.setDefault(True)
        for b in (later,start,cancel):
            b.setFixedSize(128,28)
            b.setObjectName('fileInfoAction')
        self.start_button=start; self.later_button=later
        start.setObjectName('fileInfoPrimary')
        self.setStyleSheet(self.styleSheet() + '''
            QDialog#classicDownloadDialog QPushButton#fileInfoAction {
                border:1px solid #c7ccd3; border-radius:5px; background:#ffffff;
                padding:3px 10px; font-weight:500;
            }
            QDialog#classicDownloadDialog QPushButton#fileInfoAction:hover {
                background:#f3f6f9; border-color:#9aa4b2;
            }
            QDialog#classicDownloadDialog QPushButton#fileInfoPrimary {
                border:1px solid #0878c9; border-radius:5px; background:#ffffff;
                color:#1f2937; padding:3px 5px; font-weight:500;
            }
            QDialog#classicDownloadDialog QPushButton#fileInfoPrimary:hover { background:#eef6ff; }
        ''')
        later.clicked.connect(self.later); start.clicked.connect(self.start_now); cancel.clicked.connect(self.reject)
        buttons.addWidget(later); buttons.addWidget(start); buttons.addWidget(cancel); buttons.addStretch(1); root.addLayout(buttons)
        self.queue=QComboBox(); self.queue.addItems(['Main','High Priority','Later']); self.queue.hide()
        self.priority=QSpinBox(); self.priority.setRange(0,100); self.priority.hide()
        self.schedule=QCheckBox(); self.schedule.hide(); self.sched=QDateTimeEdit(QDateTime.currentDateTime()); self.sched.hide()
        self.category.currentTextChanged.connect(self._set_category_folder)
        self.category.activated.connect(lambda *_: setattr(self,'_user_category_selected',True))
        self.url.textChanged.connect(self.guess_name); self.guess_name(initial_url)
        self._remote_probe_timer=QTimer(self); self._remote_probe_timer.setSingleShot(True); self._remote_probe_timer.setInterval(250); self._remote_probe_timer.timeout.connect(self._probe_remote_size)
        self.url.textChanged.connect(lambda *_: self._remote_probe_timer.start())
        self.save_as.textChanged.connect(self._update_file_type_icon)
        self.save_as.textChanged.connect(lambda text:self.path_display.setText(str(Path(text).parent)))
        self.save_as.textEdited.connect(lambda *_: setattr(self,'_user_save_as_edited',True))
        self._update_file_type_icon()
    @staticmethod
    def _category_for_filename(name):
        ext=Path(name).suffix.lower()
        groups={
            'Programs':{'.exe','.msi','.msix','.appx','.apk','.xapk','.bat','.cmd','.com','.dll','.jar','.deb','.rpm','.dmg','.iso','.run','.ps1','.sh','.sys','.bin'},
            'Video':{'.mp4','.mkv','.webm','.avi','.mov','.m4v','.wmv','.flv','.mpeg','.mpg','.3gp','.ts','.m2ts','.mts','.ogv'},
            'Audio':{'.mp3','.m4a','.aac','.wav','.flac','.ogg','.opus','.wma','.aiff','.mid','.midi','.alac','.mka'},
            'Documents':{'.pdf','.doc','.docx','.docm','.xls','.xlsx','.xlsm','.ppt','.pptx','.pptm','.txt','.csv','.rtf','.odt','.epub','.ods','.odp'},
            'Archives':{'.zip','.rar','.7z','.gz','.tar','.bz2','.xz','.tgz'},
            'Pictures':{'.jpg','.jpeg','.png','.gif','.bmp','.webp','.svg','.tif','.tiff','.ico','.heic','.heif','.avif','.raw','.psd'}
        }
        return next((category for category,extensions in groups.items() if ext in extensions),None)

    def _set_category_folder(self, category):
        from .options_config import category_settings
        configured=category_settings(category).get('folder','')
        folder=Path(configured or DEFAULT_DIR).expanduser()
        try: folder.mkdir(parents=True,exist_ok=True)
        except OSError: pass  # Start/Download Later reports an unwritable folder.
        name=self.filename.text().strip() or Path(self.save_as.text()).name
        self.folder.setText(str(folder))
        self.save_as.setText(str(folder/name) if self.filename.text().strip() else str(folder))
        self.save_as.setCursorPosition(0)
        self.save_as.setToolTip(self.save_as.text())
        self.path_display.setText(str(folder))

    def guess_name(self,url):
        try:
            from urllib.parse import urlparse,unquote
            n=Path(unquote(urlparse(url).path)).name
            if n:
                picked=safe_filename(n)
                self.filename.setText(picked)
                detected=self._category_for_filename(picked) or 'Other'
                selected=self.category.currentText()
                self.category.setCurrentText(detected)
                if selected==detected: self._set_category_folder(detected)
                self.save_as.setText(str(Path(self.folder.text()) / picked))
                self.save_as.setCursorPosition(0)
                self.path_display.setText(self.folder.text())
        except Exception: pass
    def refresh_native_preview(self):
        self._update_file_type_icon()

    def sync_save_as(self):
        if getattr(self,'_media_ext',''):
            self.save_as.setText(str(Path(self.save_as.text()).with_suffix(self._media_ext)))
        raw=self.save_as.text().strip()
        if raw:
            pp=Path(raw)
            self.folder.setText(str(pp.parent))
            self.filename.setText(pp.name)

    def browse(self):
        d=QFileDialog.getExistingDirectory(self,'Download folder',self.folder.text())
        if d:
            self._user_save_as_edited=True
            self.folder.setText(d)
            self.save_as.setText(str(Path(d) / self.filename.text()))
            self.refresh_native_preview()
    def _format_bytes(self, n):
        try:
            n=float(n)
            units=['B','KB','MB','GB','TB']; i=0
            while n>=1024 and i<len(units)-1:
                n/=1024.0; i+=1
            return f'{n:.2f} {units[i]}' if i else f'{int(n)} B'
        except Exception:
            return '--'

    @staticmethod
    def _file_type_preview_icon(path):
        ext=Path(path).suffix.lower().lstrip('.').upper()[:5] or 'FILE'
        colors={
            'PDF':'#d64040','DOC':'#2874b8','DOCX':'#2874b8','XLS':'#23834a','XLSX':'#23834a',
            'PPT':'#c76532','PPTX':'#c76532','TXT':'#64748b','CSV':'#23834a','RTF':'#64748b'
        }
        color=QColor(colors.get(ext,'#536b83'))
        pm=QPixmap(48,48); pm.fill(Qt.transparent)
        painter=QPainter(pm); painter.setRenderHint(QPainter.Antialiasing,True)
        painter.setPen(QPen(QColor('#9aa7b5'),1)); painter.setBrush(QBrush(QColor('#f7f9fc')))
        painter.drawRoundedRect(7,3,34,42,3,3)
        painter.setPen(Qt.NoPen); painter.setBrush(QBrush(QColor('#dfe6ee')))
        painter.drawPolygon(QPolygonF([QPointF(29,4),QPointF(39,14),QPointF(29,14)]))
        painter.setBrush(QBrush(color)); painter.drawRoundedRect(5,28,38,14,3,3)
        painter.setPen(QPen(Qt.white)); painter.setFont(QFont('Segoe UI',8,QFont.Bold))
        painter.drawText(QRectF(5,28,38,14),Qt.AlignCenter,ext)
        painter.end()
        return QIcon(pm)

    def _update_file_type_icon(self):
        try:
            target=self.save_as.text().strip() if hasattr(self,'save_as') else ''
            info=QFileInfo(target)
            icon=self._file_type_preview_icon(target) if info.suffix() else QFileIconProvider().icon(info)
            if icon.isNull():
                icon=self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
            self.file_icon.setPixmap(icon.pixmap(48,48))
        except Exception:
            self.file_icon.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon).pixmap(48,48))

    def _probe_remote_size(self):
        if getattr(self,'_media_mode',False): return
        url=self.url.text().strip()
        if not url.lower().startswith(('http://','https://')): return
        def worker():
            import mimetypes
            from urllib.parse import unquote, urlsplit
            metadata={'url':url,'size':None,'filename':'','content_type':''}

            def read_headers(response, ranged=False):
                headers=response.headers
                metadata['content_type']=str(headers.get('Content-Type','')).split(';',1)[0].strip().lower()
                content_range=headers.get('Content-Range','')
                match=re.search(r'/([0-9]+)$',str(content_range))
                if match:
                    metadata['size']=int(match.group(1))
                elif not ranged or response.status_code!=206:
                    length=headers.get('Content-Length','')
                    if str(length).isdigit(): metadata['size']=int(length)
                disposition=headers.get('Content-Disposition','')
                name=''
                encoded=re.search(r"filename\*\s*=\s*UTF-8''([^;]+)",str(disposition),re.I)
                plain=re.search(r'filename\s*=\s*"?([^";]+)',str(disposition),re.I)
                if encoded: name=unquote(encoded.group(1).strip().strip('"'))
                elif plain: name=plain.group(1).strip()
                if not name:
                    name=Path(unquote(urlsplit(response.url).path)).name
                if name:
                    metadata['filename']=safe_filename(name)
                ctype=metadata['content_type']
                if ctype and (not metadata['filename'] or not Path(metadata['filename']).suffix):
                    extension=mimetypes.guess_extension(ctype,strict=False)
                    extension={'.jpe':'.jpg'}.get(extension,extension)
                    if extension:
                        base=Path(metadata['filename']).stem if metadata['filename'] else 'download'
                        metadata['filename']=safe_filename(base+extension)

            try:
                with requests.head(url,allow_redirects=True,timeout=(3,6)) as response:
                    read_headers(response)
            except Exception:
                pass
            if metadata['size'] is None or not Path(metadata['filename']).suffix:
                try:
                    headers={'Range':'bytes=0-0','Accept-Encoding':'identity'}
                    with requests.get(url,headers=headers,stream=True,allow_redirects=True,timeout=(3,8)) as response:
                        read_headers(response,ranged=True)
                except Exception:
                    pass
            self.remote_metadata_ready.emit(metadata)
        threading.Thread(target=worker,daemon=True).start()

    def _apply_remote_metadata(self,metadata):
        if not isinstance(metadata,dict) or metadata.get('url')!=self.url.text().strip(): return
        size=metadata.get('size')
        if size is not None and int(size)>=0:
            self.file_size.setText(self._format_bytes(size))
        filename=str(metadata.get('filename') or '').strip()
        if filename and not self._user_save_as_edited:
            content_type=str(metadata.get('content_type') or '').lower()
            detected=self._category_for_filename(filename)
            if not detected and content_type.startswith('image/'): detected='Pictures'
            if not detected and content_type in {
                'application/x-msdownload','application/vnd.microsoft.portable-executable',
                'application/vnd.android.package-archive','application/x-apple-diskimage'
            }: detected='Programs'
            detected=detected or 'Other'
            self.filename.setText(filename)
            if not self._user_category_selected:
                selected=self.category.currentText()
                self.category.setCurrentText(detected)
                if selected==detected: self._set_category_folder(detected)
            self.save_as.setText(str(Path(self.folder.text())/filename))
            self.path_display.setText(self.folder.text())
        self._update_file_type_icon()

    def preview_file(self):
        QMessageBox.information(self,'Preview','Preview becomes available after the file is downloaded.')
    def start_now(self):
        self.sync_save_as()
        self.refresh_native_preview()
        self.action='start'; self.accept()
    def later(self):
        self.sync_save_as()
        self.refresh_native_preview()
        self.action='later'; self.accept()
    def scheduled_at(self): return 0


class DownloadCompleteDialog(QDialog):
    """Compact classic completion dialog shown after a successful download."""
    def __init__(self, parent, record):
        super().__init__(parent)
        self.record = record or {}
        self.path = str(self.record.get('path') or '')
        self.setWindowTitle('Download complete')
        self.setObjectName('classicDownloadComplete')
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setFixedSize(470,220)
        root=QVBoxLayout(self); root.setContentsMargins(12,10,12,10); root.setSpacing(7)
        head=QHBoxLayout(); ico=QLabel(); ico.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton).pixmap(34,34)); head.addWidget(ico)
        total=int(self.record.get('total') or self.record.get('downloaded') or 0)
        msg=QLabel(f'<b>Download complete</b><br>Downloaded {self._size(total)} ({total} Bytes)'); head.addWidget(msg,1); root.addLayout(head)
        root.addWidget(QLabel('Address'))
        url=QLineEdit(str(self.record.get('url') or '')); url.setReadOnly(True); url.setMinimumHeight(23); root.addWidget(url)
        root.addWidget(QLabel('The file saved as'))
        saved=QLineEdit(self.path); saved.setReadOnly(True); saved.setMinimumHeight(23); root.addWidget(saved)
        row=QHBoxLayout(); row.setSpacing(8)
        self.open_btn=QPushButton('Open'); self.with_btn=QPushButton('Open with...'); self.folder_btn=QPushButton('Open folder'); close=QPushButton('Close')
        for b in (self.open_btn,self.with_btn,self.folder_btn,close): b.setFixedSize(108,27); b.setObjectName('completeActionButton')
        self.open_btn.setDefault(True); self.open_btn.clicked.connect(self.open_file); self.with_btn.clicked.connect(self.open_with); self.folder_btn.clicked.connect(self.open_folder); close.clicked.connect(self.accept)
        row.addStretch(); [row.addWidget(b) for b in (self.open_btn,self.with_btn,self.folder_btn,close)]; row.addStretch(); root.addLayout(row)
        bottom=QHBoxLayout(); self.dont_show=QCheckBox("Don't show this dialog again"); bottom.addWidget(self.dont_show); bottom.addStretch(); root.addLayout(bottom)
        exists=bool(self.path and Path(self.path).exists()); self.open_btn.setEnabled(exists); self.with_btn.setEnabled(exists); self.folder_btn.setEnabled(bool(self.path))
    @staticmethod
    def _size(n):
        x=float(n or 0); units=['Bytes','KB','MB','GB']; i=0
        while x>=1024 and i<3: x/=1024; i+=1
        return f'{x:.2f} {units[i]}' if i else f'{int(x)} Bytes'
    def open_file(self):
        self.accept()
        QApplication.processEvents()
        try:
            if os.name=='nt': os.startfile(self.path)
            else: subprocess.Popen(['xdg-open',self.path])
        except Exception as e: QMessageBox.warning(self,'Open file',str(e))
    def open_with(self):
        self.accept()
        QApplication.processEvents()
        try:
            if os.name=='nt': subprocess.Popen(['rundll32.exe','shell32.dll,OpenAs_RunDLL',self.path])
            else: subprocess.Popen(['xdg-open',self.path])
        except Exception as e: QMessageBox.warning(self,'Open with',str(e))
    def open_folder(self):
        self.accept()
        QApplication.processEvents()
        try:
            folder=str(Path(self.path).parent)
            if os.name=='nt': os.startfile(folder)
            else: subprocess.Popen(['xdg-open',folder])
        except Exception as e: QMessageBox.warning(self,'Open folder',str(e))

class MediaDialog(QDialog):
    def __init__(self,parent,title,formats):
        super().__init__(parent); self.setWindowTitle('Choose Media Format'); self.resize(760,380); self.selected=None
        lay=QVBoxLayout(self); lay.addWidget(QLabel(f'<b>{title}</b>'))
        self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(['Format','Type','Resolution','FPS','Size','Note'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents); self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
        for f in formats:
            i=self.table.rowCount(); self.table.insertRow(i)
            typ='Video+Audio' if f['vcodec']!='none' and f['acodec']!='none' else ('Video' if f['vcodec']!='none' else 'Audio')
            vals=[f['format_id'],typ,str(f['resolution']),str(f['fps'] or ''),self.size(f['filesize']),f['note']]
            for c,v in enumerate(vals):self.table.setItem(i,c,QTableWidgetItem(v))
        lay.addWidget(self.table); buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); lay.addWidget(buttons)
    def accept(self):
        rows=self.table.selectionModel().selectedRows()
        if not rows: QMessageBox.warning(self,'Select a format','Please select a media format.'); return
        self.selected=self.table.item(rows[0].row(),0).text(); super().accept()
    @staticmethod
    def size(n):
        if not n:return '--'
        x=float(n); u=['B','KB','MB','GB']; i=0
        while x>=1024 and i<3:x/=1024;i+=1
        return f'{x:.1f} {u[i]}'

class PropertiesDialog(QDialog):
    def __init__(self,parent,row):
        super().__init__(parent); self.parent=parent; self.row=row; self.setWindowTitle('Download Properties'); self.resize(620,360)
        lay=QFormLayout(self)
        self.name=QLineEdit(str(row['filename'])); self.name.setReadOnly(True); lay.addRow('File Name:',self.name)
        self.url=QLineEdit(str(row['url'])); self.url.setReadOnly(True); lay.addRow('URL:',self.url)
        self.path=QLineEdit(str(row['path'])); self.path.setReadOnly(True); lay.addRow('Location:',self.path)
        self.category=QLineEdit(str(row['category'])); self.category.setReadOnly(True); lay.addRow('Category:',self.category)
        self.queue=QLineEdit(str(row['queue_name'])); self.queue.setReadOnly(True); lay.addRow('Queue:',self.queue)
        self.conn=QSpinBox(); self.conn.setRange(1,16); self.conn.setValue(int(row['connections'] or parent.connections)); lay.addRow('Connections:',self.conn)
        self.hash=QLineEdit(str(row['expected_hash'] or '')); self.hash.setPlaceholderText('Optional SHA-256 hash (64 hex characters)'); lay.addRow('Expected SHA-256:',self.hash)
        self.status=QLineEdit(str(row['status'])); self.status.setReadOnly(True); lay.addRow('Status:',self.status)
        self.error=QLineEdit(str(row['error'] or '')); self.error.setReadOnly(True); lay.addRow('Last Error:',self.error)
        self.schedule=QLineEdit(MainWindow.sched_text(row['scheduled_at'])); self.schedule.setReadOnly(True); lay.addRow('Scheduled:',self.schedule)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Close); buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); lay.addRow(buttons)
        verify=QPushButton('Verify Existing File'); verify.clicked.connect(self.verify_existing); lay.addRow(verify)
    def save(self):
        hv=self.hash.text().strip().lower()
        if hv and not re.fullmatch(r'[0-9a-f]{64}',hv):
            QMessageBox.warning(self,'Invalid SHA-256','Expected SHA-256 must contain exactly 64 hexadecimal characters.'); return
        self.parent.storage.update(self.row['id'],connections=self.conn.value(),expected_hash=hv,hash_algorithm='SHA-256')
        QMessageBox.information(self,'Saved','Download properties updated. New connection count applies when the download is started/resumed.')
        self.accept()
    def verify_existing(self):
        p=Path(self.row['path']); expected=self.hash.text().strip().lower()
        if not p.exists(): QMessageBox.information(self,'Verify','The file does not exist at the saved location.'); return
        if not expected: QMessageBox.information(self,'Verify','Enter an expected SHA-256 hash first.'); return
        h=hashlib.sha256()
        with open(p,'rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
        actual=h.hexdigest()
        QMessageBox.information(self,'Checksum verification','SHA-256 MATCH' if actual==expected else f'SHA-256 MISMATCH\n\nExpected: {expected}\nActual: {actual}')

class LegacySettingsDialog(QDialog):
    def __init__(self,parent,settings):
        super().__init__(parent); self.setWindowTitle('Download Settings'); self.resize(400,270); lay=QFormLayout(self)
        self.maxdl=QSpinBox(); self.maxdl.setRange(1,20); self.maxdl.setValue(settings.max_downloads); lay.addRow('Maximum simultaneous downloads:',self.maxdl)
        self.auto=QCheckBox('Start downloads automatically after adding'); self.auto.setChecked(settings.auto_start); lay.addRow(self.auto)
        self.speed=QSpinBox(); self.speed.setRange(0,1024000); self.speed.setValue(settings.speed_limit_kbps); self.speed.setSuffix(' KB/s (0 = Unlimited)'); lay.addRow('Global speed limit:',self.speed)
        self.retries=QSpinBox(); self.retries.setRange(0,10); self.retries.setValue(settings.max_retries); lay.addRow('Automatic retries:',self.retries)
        self.connections=QSpinBox(); self.connections.setRange(1,16); self.connections.setValue(settings.connections); self.connections.setSuffix(' connections'); lay.addRow('Connections per download:',self.connections)
        self.notify=QCheckBox('Show desktop notifications'); self.notify.setChecked(settings.notifications); lay.addRow(self.notify)
        self.tray=QCheckBox('Minimize to system tray when window is minimized'); self.tray.setChecked(settings.minimize_to_tray); lay.addRow(self.tray)
        self.duplicate=QComboBox()
        for text,value in [('Ask every time','ask'),('Numbered file name','number'),('Overwrite existing file','overwrite'),('Show complete / resume','resume')]: self.duplicate.addItem(text,value)
        self.duplicate.setCurrentIndex(max(0,self.duplicate.findData(settings.q.value('duplicate_action','ask'))))
        lay.addRow('Duplicate download links:',self.duplicate)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); lay.addRow(buttons)


class DownloadProgressDialog(QDialog):
    """Functional per-download window with classic download-manager workflow."""
    def __init__(self,parent,rid):
        super().__init__(None); self.owner=parent; self.rid=rid; self.details_visible=True
        # Standalone top-level download window: it has its own taskbar entry and
        # can be minimized/restored independently of the main dashboard.
        # Custom title bar so the green tray button sits beside Minimize/Maximize/Close,
        # exactly as a title-bar control. Native Minimize still goes to the Windows taskbar.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setWindowTitle('Download progress'); self.resize(512,448); self.setModal(False)
        self.setWindowIcon(self._download_icon())
        self.download_tray=QSystemTrayIcon(self)
        self.download_tray.setIcon(self._tray_download_icon())
        self.download_tray.setToolTip('Download progress')
        tray_menu=QMenu(self)
        tray_menu.addAction('Show download progress',self.restore_progress)
        self.download_tray.setContextMenu(tray_menu)
        self.download_tray.activated.connect(lambda reason: self.restore_progress() if reason in (QSystemTrayIcon.Trigger,QSystemTrayIcon.DoubleClick) else None)
        QApplication.instance().aboutToQuit.connect(self.download_tray.hide)
        root=QVBoxLayout(self); root.setContentsMargins(1,1,1,1); root.setSpacing(0)
        self.titlebar=QFrame(); self.titlebar.setObjectName('downloadTitleBar'); self.titlebar.setFixedHeight(30)
        self.titlebar.installEventFilter(self); self._drag_offset=None
        th=QHBoxLayout(self.titlebar); th.setContentsMargins(8,0,0,0); th.setSpacing(0)
        icon=QLabel(); icon.setPixmap(self._download_icon().pixmap(20,20)); th.addWidget(icon); th.addSpacing(6)
        self.title_label=QLabel('Download progress'); self.title_label.setObjectName('downloadTitleText'); th.addWidget(self.title_label,1)
        self.tray_btn=QToolButton(); self.tray_btn.setIcon(self._download_icon()); self.tray_btn.setToolTip('Minimize to system tray'); self.tray_btn.clicked.connect(self.minimize_to_tray)
        self.min_btn=QToolButton(); self.min_btn.setText('—'); self.min_btn.setToolTip('Minimize to taskbar'); self.min_btn.clicked.connect(self.showMinimized)
        self.max_btn=QToolButton(); self.max_btn.setText('□'); self.max_btn.setToolTip('Maximize / Restore'); self.max_btn.clicked.connect(self.toggle_maximize)
        self.close_btn=QToolButton(); self.close_btn.setText('×'); self.close_btn.setToolTip('Close progress window'); self.close_btn.clicked.connect(self.close)
        for b in (self.tray_btn,self.min_btn,self.max_btn,self.close_btn): b.setFixedSize(42,30); b.setObjectName('titleButton'); th.addWidget(b)
        root.addWidget(self.titlebar)
        body=QWidget(); bodylay=QVBoxLayout(body); bodylay.setContentsMargins(16,6,16,6); root.addWidget(body,1)
        root=bodylay
        self.setStyleSheet("""#downloadTitleBar{background:#0878c9;} #downloadTitleText{color:white;font-weight:600;} QToolButton#titleButton{border:0;background:transparent;color:white;font-size:15px;} QToolButton#titleButton:hover{background:rgba(255,255,255,45);}
            QTabWidget::pane{border:1px solid #a7a7a7;background:white;}
            QTabBar::tab{padding:3px 7px;}
            QProgressBar#downloadProgressBar{height:16px;border:1px solid #929292;background:#f2f2f2;text-align:center;}
            QProgressBar#downloadProgressBar::chunk{background:#18b52a;}
            QProgressBar#connectionProgressBar{height:15px;border:1px solid #929292;background:#f2f2f2;}
            QProgressBar#connectionProgressBar::chunk{background:#1981d1;width:40px;margin-right:38px;border-right:1px solid #df3333;}
            QTableWidget{gridline-color:#d4d4d4;alternate-background-color:#ededed;}
        """)
        self.tabs=QTabWidget(); root.addWidget(self.tabs)
        status=QWidget(); form=QFormLayout(status); form.setContentsMargins(10,3,10,3); form.setVerticalSpacing(0); form.setHorizontalSpacing(8)
        self.url=QLineEdit(); self.url.setReadOnly(True); form.addRow('URL:',self.url)
        self.state=QLabel('Connecting...'); form.addRow('Status:',self.state)
        self.size_lbl=QLabel('--'); form.addRow('File size:',self.size_lbl)
        self.done_lbl=QLabel('0 B'); form.addRow('Downloaded:',self.done_lbl)
        self.speed_lbl=QLabel('0 KB/sec'); form.addRow('Transfer rate:',self.speed_lbl)
        self.eta_lbl=QLabel('--'); form.addRow('Time left:',self.eta_lbl)
        self.resume_lbl=QLabel('Checking...'); form.addRow('Resume capability:',self.resume_lbl); self.tabs.addTab(status,'Download status')
        speedtab=QWidget(); sf=QFormLayout(speedtab); self.live_speed=QLabel('0 KB/sec'); sf.addRow('Transfer rate',self.live_speed)
        self.use_limiter=QCheckBox('Use Speed Limiter'); sf.addRow(self.use_limiter)
        self.limit=QSpinBox(); self.limit.setRange(1,1024000); self.limit.setValue(max(10,self.owner.speed_limit_kbps or 10)); self.limit.setSuffix(' KBytes/sec'); self.limit.setEnabled(False); sf.addRow('Maximum download speed:',self.limit)
        self.remember_limit=QCheckBox('Remember Speed Limiter settings for this file on download stop/resume'); sf.addRow(self.remember_limit)
        self.use_limiter.toggled.connect(self.limit.setEnabled); self.use_limiter.toggled.connect(self.apply_limit); self.limit.valueChanged.connect(self.apply_limit); self.tabs.addTab(speedtab,'Speed Limiter')
        opt=QWidget(); of=QFormLayout(opt); self.save_to=QLineEdit(); self.save_to.setReadOnly(True); of.addRow('Save To:',self.save_to)
        self.complete_dialog=QCheckBox('Show download complete dialog'); self.complete_dialog.setChecked(True); of.addRow(self.complete_dialog)
        self.hang=QCheckBox('Hang up modem when done'); self.exit_app=QCheckBox('Exit Internet Download Manager when done'); self.shutdown=QCheckBox('Turn off computer when done')
        for w in (self.hang,self.exit_app,self.shutdown): w.setEnabled(False); of.addRow(w)
        self.tabs.addTab(opt,'Options on completion')
        self.bar=QProgressBar(); self.bar.setObjectName('downloadProgressBar'); self.bar.setRange(0,1000); self.bar.setTextVisible(False); self.bar.setFixedHeight(16); root.addWidget(self.bar)
        # Controls live directly below the green progress bar.
        controls=QHBoxLayout(); self.hide_btn=QPushButton('<< Hide details'); self.action_btn=QPushButton('Pause'); self.cancel_btn=QPushButton('Cancel')
        self.hide_btn.setFixedSize(138,22); self.action_btn.setFixedSize(80,22); self.cancel_btn.setFixedSize(72,22)
        self.hide_btn.clicked.connect(self.toggle_details); self.action_btn.clicked.connect(self.toggle_pause); self.cancel_btn.clicked.connect(self.cancel_download)
        controls.addWidget(self.hide_btn); controls.addStretch(); controls.addWidget(self.action_btn); controls.addWidget(self.cancel_btn); root.addLayout(controls)
        self.details=QWidget(); dl=QVBoxLayout(self.details); dl.setContentsMargins(0,0,0,0); dl.addWidget(QLabel('Start positions and download progress by connections'))
        self.connection_bar=QProgressBar(); self.connection_bar.setObjectName('connectionProgressBar'); self.connection_bar.setRange(0,1000); self.connection_bar.setValue(1000); self.connection_bar.setTextVisible(False); self.connection_bar.setFixedHeight(15); dl.addWidget(self.connection_bar)
        self.connections=QTableWidget(0,3); self.connections.setHorizontalHeaderLabels(['N.','Downloaded','Info']); self.connections.setAlternatingRowColors(True); self.connections.setShowGrid(False); self.connections.verticalHeader().setVisible(False); self.connections.verticalHeader().setDefaultSectionSize(20); self.connections.horizontalHeader().setFixedHeight(23); self.connections.setColumnWidth(0,32); self.connections.setColumnWidth(1,90); self.connections.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch); self.connections.setMinimumHeight(126); dl.addWidget(self.connections); root.addWidget(self.details)
        self.refresh_static(); self.sync_timer=QTimer(self); self.sync_timer.timeout.connect(self.sync); self.sync_timer.start(500); self.sync()
    def _download_icon(self):
        # Small green right-arrow indicator inspired by the user's reference,
        # drawn locally so no third-party artwork/assets are bundled.
        pm=QPixmap(32,32); pm.fill(Qt.transparent)
        qp=QPainter(pm); qp.setRenderHint(QPainter.Antialiasing,True)
        pen=QPen(QColor('#174b22')); pen.setWidth(2); qp.setPen(pen); qp.setBrush(QColor('#23b14d'))
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPolygonF
        qp.drawPolygon(QPolygonF([QPointF(5,12),QPointF(19,12),QPointF(19,6),QPointF(29,16),QPointF(19,26),QPointF(19,20),QPointF(5,20)])); qp.end()
        return QIcon(pm)
    def eventFilter(self,obj,event):
        if obj is self.titlebar:
            if event.type()==QEvent.MouseButtonPress and event.button()==Qt.LeftButton:
                self._drag_offset=event.globalPosition().toPoint()-self.frameGeometry().topLeft()
                return True
            if event.type()==QEvent.MouseMove and self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
                if not self.isMaximized():
                    self.move(event.globalPosition().toPoint()-self._drag_offset)
                return True
            if event.type()==QEvent.MouseButtonRelease:
                self._drag_offset=None
                return True
        return super().eventFilter(obj,event)

    @staticmethod
    def _tray_download_icon():
        pm=QPixmap(32,32); pm.fill(Qt.transparent)
        painter=QPainter(pm); painter.setRenderHint(QPainter.Antialiasing)
        for x,y in ((4,21),(12,14),(20,7)):
            painter.setPen(QPen(QColor('#075525'),1))
            painter.setBrush(QColor('#25ce45'))
            painter.drawPolygon(QPolygonF([QPointF(x,y-5),QPointF(x+9,y),QPointF(x,y+5)]))
        painter.end()
        return QIcon(pm)

    def minimize_to_tray(self):
        row=self.owner.storage.get(self.rid)
        self.download_tray.setToolTip(('Download: '+str(row['filename']))[:127] if row else 'Download progress')
        self.download_tray.show()
        self.hide()

    def restore_progress(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    def showEvent(self,event):
        self.download_tray.hide()
        super().showEvent(event)

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal(); self.max_btn.setText('□')
        else:
            self.showMaximized(); self.max_btn.setText('❐')
    def changeEvent(self,event):
        # IMPORTANT: ordinary Minimize remains visible on the Windows taskbar.
        # Only the dedicated green button hides this window into the notification area.
        super().changeEvent(event)
    def closeEvent(self,event):
        # Closing the progress window must not cancel the download.
        self.download_tray.hide()
        event.accept()

    def refresh_static(self):
        r=self.owner.storage.get(self.rid)
        if r: self.url.setText(str(r['url'])); self.save_to.setText(str(r['path']))
    def apply_limit(self):
        # Current engine exposes a global limiter; update it live from this dialog.
        self.owner.speed_limit_kbps=self.limit.value() if self.use_limiter.isChecked() else 0
    def toggle_details(self):
        self.details_visible=not self.details_visible; self.details.setVisible(self.details_visible); self.hide_btn.setText('<< Hide details' if self.details_visible else 'Show details >>'); self.adjustSize()
    def sync(self):
        r=self.owner.storage.get(self.rid)
        if not r:return
        st=str(r['status']); d=int(r['downloaded'] or 0); t=int(r['total'] or 0); pct=int(1000*d/t) if t else 0
        percent=int(100*d/t) if t else 0; title=f"{percent}% {r['filename']}"; self.setWindowTitle(title); self.title_label.setText(title); self.title_label.setToolTip(str(r['filename']))
        self.state.setText('Receiving data...' if st=='Downloading' else st); self.size_lbl.setText(self.owner.size(t)); self.done_lbl.setText(f'{self.owner.size(d)} ({(d*100/t):.2f}%)' if t else self.owner.size(d)); self.resume_lbl.setText('Yes' if st in ('Downloading','Paused','Retrying','Connecting') else ('Completed' if st=='Completed' else '--'))
        self.bar.setValue(pct); self.connection_bar.setValue(1000)
        if st=='Paused': self.action_btn.setText('Start')
        elif st in ('Completed','Failed','Stopped'): self.action_btn.setText('Start'); self.action_btn.setEnabled(st!='Completed')
        else: self.action_btn.setText('Pause'); self.action_btn.setEnabled(True)
        self.cancel_btn.setText('Cancel')
    def update_live(self,downloaded,total,speed,eta,status='Downloading'):
        previous=getattr(self,'_display_speed',None)
        speed=float(speed or 0)
        if status=='Downloading' and previous is not None:speed=previous*0.75+speed*0.25
        self._display_speed=speed
        r0=self.owner.storage.get(self.rid); percent=int(100*downloaded/total) if total else 0
        if r0:
            title=f"{percent}% {r0['filename']}"; self.setWindowTitle(title); self.title_label.setText(title); self.title_label.setToolTip(str(r0['filename']))
        shown='Receiving data...' if status=='Downloading' else status; self.state.setText(shown); self.size_lbl.setText(self.owner.size(total)); self.done_lbl.setText(f'{self.owner.size(downloaded)} ({(downloaded*100/total):.2f}%)' if total else self.owner.size(downloaded)); self.speed_lbl.setText(self.owner.speed_text(speed)); self.live_speed.setText(self.owner.speed_text(speed)); self.eta_lbl.setText(self.owner.eta_text(eta)); pct=int(1000*downloaded/total) if total else 0; self.bar.setValue(pct); self.connection_bar.setValue(1000)
        r=self.owner.storage.get(self.rid); n=max(1,int(r['connections'] or self.owner.connections)) if r else 1
        if self.connections.rowCount()!=n:
            self.connections.setRowCount(n)
            for i in range(n): self.connections.setItem(i,0,QTableWidgetItem(str(i+1))); self.connections.setItem(i,1,QTableWidgetItem('--')); self.connections.setItem(i,2,QTableWidgetItem('Receiving data...'))
        per=downloaded//n if n else downloaded
        for i in range(n): self.connections.item(i,1).setText(self.owner.size(per)); self.connections.item(i,2).setText('Receiving data...' if status=='Downloading' else status)
    def toggle_pause(self):
        r=self.owner.storage.get(self.rid)
        if not r:return
        if r['status'] in ('Paused','Failed','Stopped'): self.owner.start_ids([self.rid])
        elif r['status']!='Completed': self.owner.pause_ids([self.rid])
    def cancel_download(self):
        r=self.owner.storage.get(self.rid)
        if r and r['status'] not in ('Completed','Failed','Stopped'):
            self.owner.stop_ids([self.rid])
        # Cancel is different from the green tray button: remove this progress
        # window from the owner's active-dialog registry and close it outright.
        try:
            if self.sync_timer:
                self.sync_timer.stop()
        except Exception:
            pass
        self.owner.progress_dialogs.pop(self.rid, None)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.close()
        self.deleteLater()

class MainWindow(QMainWindow):
    def __init__(self, startup_url='', startup_mode='add', startup_quality='', startup_kind='video', startup_title=''):
        super().__init__(); self.setWindowTitle(f'Internet Download Manager {VERSION}'); self.resize(1180,680); self.setMinimumSize(900,560)
        self.storage=Storage(); self.storage.recover_incomplete(); self.pool=QThreadPool.globalInstance(); self.settings=AppSettings()
        self.max_downloads=max(1,min(20,self.settings.max_downloads)); self.settings.max_downloads=self.max_downloads; self.auto_start=self.settings.auto_start; self.speed_limit_kbps=max(0,self.settings.speed_limit_kbps)
        self.notifications=self.settings.notifications; self.minimize_to_tray=self.settings.minimize_to_tray; self.connections=max(1,min(16,self.settings.connections)); self.settings.connections=self.connections
        self.tasks={}; self.pauses={}; self.stops={}; self.media_selectors={}; self.media_expected_totals={}; self.progress_dialogs={}; self.live_telemetry={}; self.build_ui(); self.setup_tray(); self.load_rows()
        self.browser_bridge=BrowserBridge(self); self.browser_bridge.request.connect(self.handle_browser_request); self.browser_bridge.start()
        self._browser_recent_requests = {}
        self.timer=QTimer(self); self.timer.timeout.connect(self.queue_tick); self.timer.start(1500)
        self.clip_timer=QTimer(self); self.clip_timer.timeout.connect(self.check_clipboard); self.clip_timer.start(2000); self.last_clipboard_url=''
        QTimer.singleShot(0, self.showMaximized)
        self._update_busy=False; self._update_auto=False; self._notified_version=''
        QTimer.singleShot(8000,lambda:self.check_updates(automatic=True))
        self.update_timer=QTimer(self); self.update_timer.timeout.connect(lambda:self.check_updates(automatic=True)); self.update_timer.start(4*60*60*1000)
        if startup_url:
            if startup_mode == 'media' and startup_quality:
                QTimer.singleShot(350, lambda u=startup_url,q=startup_quality,k=startup_kind,t=startup_title:self.download_media_preset(u,q,k,t))
            elif startup_mode == 'media':
                QTimer.singleShot(350, lambda u=startup_url:self.download_media(u))
            elif startup_mode == 'direct':
                QTimer.singleShot(350, lambda u=startup_url:self.download_direct_url(u, show_file_info=True))
            else:
                QTimer.singleShot(350, lambda u=startup_url:self.add_url(u))

    def build_ui(self):
        """Classic desktop download-manager shell.

        The layout follows the familiar early-Windows download-manager pattern
        (menu bar, large icon toolbar, category tree and compact transfer list)
        while using original programmatic icons and the existing download engine.
        """
        self.build_menus()
        self.queue_filter=None
        self.special_filter=None

        central=QWidget(); self.setCentralWidget(central)
        root=QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # --- classic large-icon toolbar -------------------------------------------------
        toolbar_frame=QFrame(); toolbar_frame.setObjectName('classicToolbar')
        toolbar=QHBoxLayout(toolbar_frame); toolbar.setContentsMargins(5,3,5,3); toolbar.setSpacing(1)

        def add_tool(text, kind, slot, tip=''):
            b=QToolButton(toolbar_frame)
            b.setObjectName('classicToolButton')
            b.setText(text)
            b.setIcon(self._classic_icon(kind))
            b.setIconSize(QSize(34,34))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setFixedSize(72,64)
            b.setAutoRaise(False)
            if tip: b.setToolTip(tip)
            b.clicked.connect(slot)
            toolbar.addWidget(b)
            return b

        def separator():
            line=QFrame(toolbar_frame); line.setFrameShape(QFrame.VLine); line.setFrameShadow(QFrame.Sunken); line.setFixedHeight(54)
            toolbar.addWidget(line)

        add_tool('Add URL','add',lambda checked=False:self.add_url(),'Add a new download URL')
        add_tool('Resume','resume',self.resume_selected,'Resume selected download')
        add_tool('Stop','stop',self.stop_selected,'Stop selected download')
        add_tool('Stop All','stopall',self.stop_all,'Stop all active downloads')
        separator()
        add_tool('Delete','delete',self.delete_selected,'Delete selected record')
        add_tool('Delete Co...','delete_done',self.delete_completed,'Delete completed downloads from the list')
        separator()
        add_tool('Options','options',self.show_settings,'Open options and settings')
        add_tool('Scheduler','scheduler',self.show_settings,'Open scheduler settings')
        separator()
        add_tool('Start Queue','startq',self.resume_all,'Start queued/paused downloads')
        add_tool('Stop Queue','stopq',self.pause_all,'Pause active queue')
        add_tool('Grabber','grabber',self.download_media,'Download video/media from a supported public page')
        toolbar.addStretch(1)
        root.addWidget(toolbar_frame)

        # --- body: category tree + classic list -----------------------------------------
        body=QHBoxLayout(); body.setContentsMargins(6,4,6,6); body.setSpacing(6)
        side_frame=QFrame(); side_frame.setObjectName('categoryPanel'); side_frame.setFixedWidth(138)
        side=QVBoxLayout(side_frame); side.setContentsMargins(1,1,1,1); side.setSpacing(0)
        side_header=QWidget(); side_header.setObjectName('categoryHeader')
        sh=QHBoxLayout(side_header); sh.setContentsMargins(6,2,3,2)
        sh.addWidget(QLabel('Categories')); sh.addStretch(1)
        close_side=QToolButton(); close_side.setText('×'); close_side.setObjectName('paneClose'); close_side.setFixedSize(18,18)
        close_side.clicked.connect(side_frame.hide); sh.addWidget(close_side)
        side.addWidget(side_header)

        self.nav_tree=QTreeWidget(); self.nav_tree.setHeaderHidden(True); self.nav_tree.setIndentation(15); self.nav_tree.setRootIsDecorated(True)
        self.nav_tree.setObjectName('categoryTree'); side.addWidget(self.nav_tree,1)

        all_item=QTreeWidgetItem(['All Downloads']); all_item.setIcon(0,self._category_icon('folder')); all_item.setData(0,Qt.UserRole,('all',''))
        self.nav_tree.addTopLevelItem(all_item)
        for label,cat,icon_kind in [('Compressed','Archives','archive'),('Documents','Documents','document'),('Music','Audio','music'),('Programs','Programs','program'),('Video','Video','video')]:
            it=QTreeWidgetItem([label]); it.setIcon(0,self._category_icon(icon_kind)); it.setData(0,Qt.UserRole,('category',cat)); all_item.addChild(it)

        unfinished=QTreeWidgetItem(['Unfinished']); unfinished.setIcon(0,self._category_icon('unfinished')); unfinished.setData(0,Qt.UserRole,('special','unfinished')); self.nav_tree.addTopLevelItem(unfinished)
        finished=QTreeWidgetItem(['Finished']); finished.setIcon(0,self._category_icon('finished')); finished.setData(0,Qt.UserRole,('special','finished')); self.nav_tree.addTopLevelItem(finished)
        grabber=QTreeWidgetItem(['Grabber projects']); grabber.setIcon(0,self._category_icon('grabber')); grabber.setData(0,Qt.UserRole,('special','media')); self.nav_tree.addTopLevelItem(grabber)
        queues=QTreeWidgetItem(['Queues']); queues.setIcon(0,self._category_icon('queue')); queues.setData(0,Qt.UserRole,('all','')); self.nav_tree.addTopLevelItem(queues)
        for label,qname in [('Main Queue','Main'),('High Priority','High Priority'),('Later','Later')]:
            it=QTreeWidgetItem([label]); it.setIcon(0,self._category_icon('folder')); it.setData(0,Qt.UserRole,('queue',qname)); queues.addChild(it)
        all_item.setExpanded(True); queues.setExpanded(True); self.nav_tree.setCurrentItem(all_item)
        self.nav_tree.currentItemChanged.connect(self._tree_filter_changed)
        body.addWidget(side_frame)
        self.category_panel=side_frame

        main=QVBoxLayout(); main.setContentsMargins(0,0,0,0); main.setSpacing(0)
        self.table=QTableWidget(0,10)
        # Reference-style one-page order: the most useful live details stay together.
        self.table.setHorizontalHeaderLabels(['File Name','Q','Size','Status','Time left','Transfer rate','Last Try Date','Description','Date Added','Save To'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        hh=self.table.horizontalHeader()
        hh.setStretchLastSection(False)
        # Compact IDM-style single-page grid: every detail stays visible without
        # horizontal scrolling. File Name gets the flexible remaining space.
        for col in range(10):
            hh.setSectionResizeMode(col,QHeaderView.Fixed)
        hh.setSectionResizeMode(0,QHeaderView.Stretch)
        compact_widths={1:28,2:78,3:92,4:150,5:96,6:92,7:92,8:86,9:145}
        for col,width in compact_widths.items():
            self.table.setColumnWidth(col,width)
        hh.setMinimumSectionSize(24)
        # Reorder sections visually only; storage/data mapping stays untouched.
        desired=[0,1,2,3,8,5,6,4,7,9]
        for visual,logical in enumerate(desired):
            current=hh.visualIndex(logical)
            if current != visual:
                hh.moveSection(current,visual)
        # Compact widths modeled on the supplied reference screenshot.
        widths={1:26,2:72,3:88,8:78,5:92,6:88,4:145,7:86,9:120}
        for logical,width in widths.items():
            self.table.setColumnWidth(logical,width)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        self.table.doubleClicked.connect(self.double_click_action)
        move_action=QAction(self);move_action.setShortcut('Ctrl+M');move_action.triggered.connect(self.move_rename);self.addAction(move_action)
        main.addWidget(self.table,1)
        body.addLayout(main,1)
        root.addLayout(body,1)

        # Hidden state controls keep the existing filtering API compatible.
        self.filter=QComboBox(central); self.filter.addItems(['All Downloads','Downloading','Completed','Paused','Failed','Queued','Stopped','Retrying']); self.filter.hide()
        self.cat=QComboBox(central); self.cat.addItems(['All Categories','Programs','Video','Audio','Documents','Archives','Other']); self.cat.hide()
        self.search=QLineEdit(central); self.search.hide()
        self.filter.currentTextChanged.connect(self.refresh_visibility)
        self.cat.currentTextChanged.connect(self.refresh_visibility)
        self.search.textChanged.connect(self.refresh_visibility)

        self.setStatusBar(QStatusBar())
        self.status_files=QLabel('0 file(s)'); self.status_size=QLabel('Total size: 0 B'); self.status_ready=QLabel('Ready')
        self.status_files.setMinimumWidth(170); self.status_size.setMinimumWidth(260)
        self.statusBar().addWidget(self.status_files); self.statusBar().addWidget(self.status_size,1); self.statusBar().addPermanentWidget(self.status_ready)
        self.statusBar().showMessage('')
        self.apply_style()

    def _category_icon(self, kind):
        """Original compact category icons matching the classic tree visual language."""
        pm=QPixmap(24,24); pm.fill(Qt.transparent); p=QPainter(pm); p.setRenderHint(QPainter.Antialiasing,True)
        dark=QColor('#555b62'); blue=QColor('#1688df'); yellow=QColor('#f3c33c'); green=QColor('#18a94b'); red=QColor('#d63b35')
        if kind in ('folder','queue','unfinished','finished','grabber'):
            p.setPen(QPen(QColor('#b07b00'),1)); p.setBrush(QBrush(QColor('#ffd85b'))); p.drawRoundedRect(2,7,20,14,2,2); p.drawRect(4,4,8,5)
            if kind=='unfinished': p.setBrush(QBrush(green)); p.setPen(Qt.NoPen); p.drawRect(14,8,5,8); p.drawPolygon(QPolygonF([QPointF(11,15),QPointF(21,15),QPointF(16,21)]))
            elif kind=='finished': p.setPen(QPen(QColor('#175ad1'),3)); p.drawLine(9,14,13,18); p.drawLine(13,18,21,8)
            elif kind=='grabber': p.setPen(QPen(blue,2)); p.drawEllipse(10,6,11,11); p.drawLine(10,17,20,7)
        elif kind=='archive':
            cols=[QColor('#8c2bd1'),QColor('#2264d8'),QColor('#22a95a')]
            for i,c in enumerate(cols): p.setBrush(QBrush(c)); p.setPen(QPen(dark,1)); p.drawRect(3,3+i*6,18,6)
            p.setBrush(QBrush(QColor('#d88924'))); p.drawRect(11,3,4,18)
        elif kind=='document':
            p.setBrush(QBrush(QColor('#eef7ff'))); p.setPen(QPen(QColor('#4776a5'),1)); p.drawRect(5,2,14,20); p.setPen(QPen(blue,2)); [p.drawLine(8,y,16,y) for y in (9,13,17)]
        elif kind=='music':
            p.setPen(QPen(blue,3)); p.drawLine(14,4,14,17); p.drawLine(14,5,21,3); p.drawEllipse(8,15,6,5); p.drawEllipse(17,13,6,5)
        elif kind=='program':
            p.setBrush(QBrush(QColor('#eaf3ff'))); p.setPen(QPen(QColor('#4776a5'),1)); p.drawRect(3,4,17,14); p.setBrush(QBrush(QColor('#4aa3e8'))); p.drawRect(3,4,17,4); p.setBrush(QBrush(QColor('#e8e8e8'))); p.drawEllipse(14,13,8,8)
        elif kind=='video':
            p.setBrush(QBrush(QColor('#1979bd'))); p.setPen(QPen(QColor('#27333d'),1)); p.drawRect(3,3,18,18); p.setBrush(QBrush(Qt.white)); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(9,7),QPointF(17,12),QPointF(9,17)]))
            p.setPen(QPen(Qt.white,1)); [p.drawLine(x,3,x,6) for x in (5,19)]; [p.drawLine(x,18,x,21) for x in (5,19)]
        p.end(); return QIcon(pm)

    def _classic_icon(self, kind):
        """Draw small original toolbar icons instead of copying proprietary artwork."""
        pm=QPixmap(42,42); pm.fill(Qt.transparent)
        p=QPainter(pm); p.setRenderHint(QPainter.Antialiasing,True)
        dark=QColor('#55585c'); light=QColor('#d8dde2'); blue=QColor('#2f6fd0'); green=QColor('#24964b'); red=QColor('#c43b35'); yellow=QColor('#f0cf27'); orange=QColor('#e48b19')
        p.setPen(QPen(dark,1.4))
        if kind=='add':
            p.setBrush(QBrush(yellow)); p.drawRect(5,14,31,18); p.setBrush(QBrush(QColor('#fff28b'))); p.drawRect(9,9,24,8)
            p.setBrush(QBrush(green)); p.setPen(Qt.NoPen); p.drawRect(18,3,6,16); p.drawPolygon(QPolygonF([QPointF(12,14),QPointF(30,14),QPointF(21,24)]))
        elif kind in ('resume','startq'):
            if kind=='startq': p.setBrush(QBrush(yellow)); p.setPen(QPen(dark,1.2)); p.drawRect(4,16,33,20)
            p.setBrush(QBrush(light)); p.setPen(QPen(dark,1.4)); p.drawEllipse(5,5,32,32)
            p.setBrush(QBrush(green)); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(16,12),QPointF(31,21),QPointF(16,30)]))
        elif kind in ('stop','stopall','stopq'):
            p.setBrush(QBrush(light)); p.setPen(QPen(dark,1.4)); p.drawEllipse(5,5,32,32)
            p.setBrush(QBrush(red)); p.setPen(Qt.NoPen); p.drawRect(14,14,15,15)
            if kind=='stopall': p.setBrush(QBrush(QColor('#b7bcc3'))); p.drawEllipse(1,12,17,17); p.setBrush(QBrush(red)); p.drawRect(6,17,7,7)
            if kind=='stopq': p.setPen(QPen(yellow,4)); p.drawLine(5,35,36,35)
        elif kind in ('delete','delete_done'):
            p.setBrush(QBrush(QColor('#b8bcc0'))); p.setPen(QPen(dark,1.3)); p.drawRect(12,13,19,23); p.drawRect(9,9,25,5); p.drawLine(17,17,17,31); p.drawLine(22,17,22,31); p.drawLine(27,17,27,31)
            if kind=='delete_done': p.setBrush(QBrush(green)); p.setPen(Qt.NoPen); p.drawEllipse(25,25,13,13); p.setPen(QPen(Qt.white,2)); p.drawLine(28,31,31,34); p.drawLine(31,34,36,28)
        elif kind=='options':
            p.setBrush(QBrush(QColor('#8d949c'))); p.setPen(QPen(dark,2)); p.drawEllipse(9,9,24,24); p.setBrush(QBrush(QColor('#eef1f3'))); p.drawEllipse(16,16,10,10)
            for a,b,c,d in [(20,2,20,9),(20,33,20,40),(2,20,9,20),(33,20,40,20),(7,7,12,12),(30,30,35,35),(30,12,35,7),(7,35,12,30)]: p.drawLine(a,b,c,d)
        elif kind=='scheduler':
            p.setBrush(QBrush(QColor('#fff5d7'))); p.setPen(QPen(orange,3)); p.drawEllipse(7,7,29,29); p.setPen(QPen(dark,2)); p.drawLine(21,21,21,11); p.drawLine(21,21,29,25)
        elif kind=='grabber':
            p.setBrush(QBrush(QColor('#dfe8f7'))); p.setPen(QPen(blue,2)); p.drawEllipse(8,8,26,26); p.drawLine(12,29,31,10); p.setPen(QPen(dark,3)); p.drawLine(5,36,17,24); p.drawLine(25,18,37,6)
        p.end(); return QIcon(pm)

    def _tree_filter_changed(self, current, previous=None):
        if not current:return
        data=current.data(0,Qt.UserRole)
        if not data:return
        kind,value=data
        self.queue_filter=None; self.special_filter=None
        self.filter.blockSignals(True); self.cat.blockSignals(True)
        self.filter.setCurrentText('All Downloads'); self.cat.setCurrentText('All Categories')
        if kind=='category': self.cat.setCurrentText(value)
        elif kind=='queue': self.queue_filter=value
        elif kind=='special': self.special_filter=value
        self.filter.blockSignals(False); self.cat.blockSignals(False)
        self.refresh_visibility()

    def _set_status_filter(self, status):
        self.queue_filter=None; self.special_filter=None; self.cat.setCurrentText('All Categories'); self.filter.setCurrentText(status); self.refresh_visibility()

    def _show_categories(self):
        self.category_panel.show()

    def select_queue(self, queue_label):
        mapping={'Main Queue':'Main','High Priority':'High Priority','Later':'Later'}
        self.queue_filter=mapping.get(queue_label,queue_label); self.special_filter=None
        self.filter.setCurrentText('All Downloads'); self.cat.setCurrentText('All Categories'); self.refresh_visibility()

    def build_menus(self):
        bar=self.menuBar(); bar.clear()
        st=self.style()
        I={
          'add':st.standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder), 'open':st.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
          'folder':st.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), 'info':st.standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView),
          'stop':st.standardIcon(QStyle.StandardPixmap.SP_MediaStop), 'remove':st.standardIcon(QStyle.StandardPixmap.SP_TrashIcon),
          'start':st.standardIcon(QStyle.StandardPixmap.SP_MediaPlay), 'redo':st.standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
          'find':st.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView), 'settings':st.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),
          'save':st.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), 'help':st.standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton),
          'exit':st.standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton), 'up':st.standardIcon(QStyle.StandardPixmap.SP_ArrowUp),
          'down':st.standardIcon(QStyle.StandardPixmap.SP_ArrowDown), 'pause':st.standardIcon(QStyle.StandardPixmap.SP_MediaPause)
        }
        def act(menu,text,slot=None,icon=None,shortcut=None,check=False):
            q=QAction(I.get(icon,QIcon()),text,self); q.setCheckable(check)
            if shortcut:q.setShortcut(shortcut)
            if slot:q.triggered.connect(slot)
            menu.addAction(q); return q
        def sub(menu,text,icon=None):
            m=QMenu(text,menu); m.setIcon(I.get(icon,QIcon())); menu.addMenu(m); return m

        tasks=bar.addMenu('Tasks')
        act(tasks,'Add new download',lambda checked=False:self.add_url(),'add')
        act(tasks,'Add batch download',lambda checked=False:self.add_url(),'add')
        act(tasks,'Add batch download from clipboard',self.add_from_clipboard,'open')
        act(tasks,'Run site grabber',self.download_media,'down'); tasks.addSeparator()
        drop=act(tasks,'Show drop target',None,'info',check=True); drop.setChecked(False); tasks.addSeparator()
        ex=sub(tasks,'Export','save'); act(ex,'To download-manager export file',self.export_json,'save'); act(ex,'To text file',self.export_csv,'save')
        im=sub(tasks,'Import','open'); act(im,'From download-manager export file',self.import_history,'open'); act(im,'From text file',self.import_history,'open')
        tasks.addSeparator(); act(tasks,'Exit',self.request_exit,'exit')

        filem=bar.addMenu('File')
        act(filem,'Open Downloaded File',self.open_file,'open','Return')
        act(filem,'Open Folder',self.open_folder,'folder','Ctrl+O')
        act(filem,'Download Properties',self.details,'info','Ctrl+D'); filem.addSeparator()
        act(filem,'Stop Download',self.stop_selected,'stop')
        act(filem,'Remove',self.delete_selected,'remove','Del')
        act(filem,'Download Now',self.start_selected,'start')
        act(filem,'Redownload',self.redownload_selected,'redo'); filem.addSeparator()
        act(filem,'Exit',self.request_exit,'exit')

        downloads=bar.addMenu('Downloads')
        act(downloads,'Pause All',self.pause_all,'pause'); act(downloads,'Stop All',self.stop_all,'stop'); downloads.addSeparator()
        act(downloads,'Delete All Completed',self.delete_completed,'remove'); downloads.addSeparator()
        act(downloads,'Find (Ctrl-F)',self.find_download,'find','Ctrl+F'); act(downloads,'Find Next (F3)',self.find_next,'find','F3'); downloads.addSeparator()
        act(downloads,'Scheduler',self.show_settings,'settings')
        startq=sub(downloads,'Start queue','start')
        for label in ('Main','High Priority','Later'): act(startq,label,lambda checked=False,n=label:self.start_queue_named(n),'start')
        stopq=sub(downloads,'Stop queue','stop')
        for label in ('Main','High Priority','Later'): act(stopq,label,lambda checked=False,n=label:self.stop_queue_named(n),'stop')
        downloads.addSeparator(); limiter=sub(downloads,'Speed Limiter','down'); act(limiter,'Turn Off',lambda:self.set_speed_limit(0),'stop'); act(limiter,'Set Limit...',self.speed_limit_dialog,'settings')
        downloads.addSeparator(); act(downloads,'Options',self.show_settings,'settings')

        view=bar.addMenu('View')
        cats=act(view,'Hide categories',lambda:self.category_panel.setVisible(not self.category_panel.isVisible()),'folder')
        arrange=sub(view,'Arrange files','info')
        for label,col in [('By File Name',0),('By Size',2),('By Status',3),('By Transfer Rate',5),('By Last Try Date',6),('By Date Added',7),('By Time Left',8),('By Save Path',9)]: act(arrange,label,lambda checked=False,c=col:self.table.sortItems(c,Qt.AscendingOrder),'info')
        tool=sub(view,'Toolbar','settings'); act(tool,'Customize...',self.show_settings,'settings'); act(tool,'Large Buttons',lambda:self.set_toolbar_compact(False),'up'); act(tool,'Small Buttons',lambda:self.set_toolbar_compact(True),'down'); tool.addSeparator(); act(tool,'Classic',lambda:self.set_toolbar_compact(False),'info'); act(tool,'Compact',lambda:self.set_toolbar_compact(True),'info')
        traym=sub(view,'IDM tray icon','info'); act(traym,'Show',lambda:self.tray.show(),'start'); act(traym,'Hide',lambda:self.tray.hide(),'stop')
        act(view,'Customize URL List...',self.show_settings,'settings'); dark=act(view,'Dark Mode support',None,'info',check=True); dark.setChecked(False)
        fontm=sub(view,'Font','info'); act(fontm,'Default',lambda:None,'info'); act(fontm,'Larger',lambda:QApplication.setFont(QFont('Segoe UI',10)),'up')
        lang=sub(view,'Language','info'); en=act(lang,'English',None,'info',check=True); en.setChecked(True)

        helpm=bar.addMenu('Help'); act(helpm,'Help contents',self.show_about,'help'); act(helpm,'Check for Updates',self.check_updates,'redo'); act(helpm,'Download Diagnostics',self.diagnostics,'info'); helpm.addSeparator(); act(helpm,'About',self.show_about,'info')
        reg=bar.addMenu('Registration'); act(reg,'About this build',self.show_about,'info')

    def add_from_clipboard(self):
        text=QApplication.clipboard().text().strip()
        m=re.search(r'https?://[^\s]+',text,re.I)
        if m: self.add_url(m.group(0))
        else: QMessageBox.information(self,'Clipboard','No HTTP/HTTPS download URL was found in the clipboard.')

    def set_toolbar_compact(self, compact):
        for b in self.findChildren(QToolButton,'classicToolButton'):
            b.setIconSize(QSize(24,24) if compact else QSize(34,34))
            b.setFixedSize(64,50) if compact else b.setFixedSize(72,64)

    def setup_tray(self):
        self.tray=QSystemTrayIcon(self); self.tray.setIcon(QIcon(str(Path(__file__).resolve().parent.parent/'assets'/'app_icon.png'))); self.tray.setToolTip('Internet Download Manager')
        menu=QMenu(); menu.addAction('Show Main Window',self.restore_from_tray); menu.addAction('Show Download Windows',self.restore_download_windows); menu.addAction('Add URL',lambda checked=False: self.add_url()); menu.addAction('Pause All',self.pause_all); menu.addAction('Resume All',self.resume_all); menu.addSeparator(); menu.addAction('Exit',QApplication.quit); self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason:self.restore_from_tray() if reason==QSystemTrayIcon.Trigger else None); self.tray.show()
    def restore_download_windows(self):
        shown=False
        for dlg in self.progress_dialogs.values():
            if dlg and not dlg.isVisible(): dlg.showNormal(); dlg.raise_(); dlg.activateWindow(); shown=True
        if not shown: self.showNormal(); self.raise_(); self.activateWindow()
    def restore_from_tray(self):
        self.showNormal(); self.raise_(); self.activateWindow()
    def apply_style(self):
        self.setStyleSheet("""
        QMainWindow, QWidget{background:#f2f2f2;color:#111;font-family:'Segoe UI';font-size:8.5pt;}
        QMenuBar{background:#f7f7f7;border-bottom:1px solid #b7b7b7;padding:1px 3px;}
        QMenuBar::item{padding:3px 7px;background:transparent;}
        QMenuBar::item:selected,QMenu::item:selected{background:#dce9f8;color:#111;}
        QMenu{background:#fafafa;border:1px solid #9b9b9b;padding:2px;}
        #classicToolbar{background:#f7f7f7;border-top:1px solid white;border-bottom:1px solid #b9b9b9;}
        #classicToolButton{background:#f0f0f0;border:1px solid #9b9b9b;border-top-color:#ffffff;border-left-color:#ffffff;border-radius:0;padding:1px;color:#111;}
        #classicToolButton:hover{background:#f7f7f7;border:1px solid #6d9dcc;}
        #classicToolButton:pressed{background:#e2e2e2;border:1px solid #777;border-top-color:#777;border-left-color:#777;}
        #categoryPanel{background:white;border:1px solid #a6a6a6;}
        #categoryHeader{background:#f4f4f4;border-bottom:1px solid #b7b7b7;}
        #categoryHeader QLabel{font-weight:600;}
        #paneClose{background:transparent;border:none;font-size:12pt;padding:0;}
        #paneClose:hover{background:#e8e8e8;}
        #categoryTree{background:white;border:0;show-decoration-selected:1;selection-background-color:#cfe4ff;selection-color:#111;}
        #categoryTree::item{height:22px;padding:1px 2px;} #categoryTree{font-size:9pt;}
        QTableWidget{background:white;border:1px solid #a6a6a6;selection-background-color:#cfe4ff;selection-color:#111;outline:0;}
        QTableWidget::item{padding:2px 4px;border:0;}
        QHeaderView::section{background:#f2f2f2;border:0;border-right:1px solid #b6b6b6;border-bottom:1px solid #9f9f9f;padding:3px 5px;font-weight:400;}
        QStatusBar{background:#f2f2f2;border-top:1px solid #b7b7b7;min-height:20px;}
        QPushButton{background:linear-gradient(#ffffff,#f0f3f6);border:1px solid #9aa6b2;border-radius:4px;padding:3px 10px;min-height:20px;color:#1f2937;font-weight:500;} QPushButton:default{border:1px solid #287fc2;background:linear-gradient(#fafdff,#dbeeff);padding:3px 10px;} QPushButton:pressed{background:#dbe7f2;border-color:#6e8295;} QPushButton:hover{background:#eef7ff;border-color:#4288bd;}
        QDialog QPushButton{min-height:23px;padding:3px 12px;border-radius:4px;} QDialogButtonBox QPushButton{min-width:76px;} QDialog QLabel{color:#1f2937;} QDialog QLineEdit,QDialog QComboBox,QDialog QSpinBox,QDialog QDateTimeEdit{min-height:21px;padding:2px 5px;border:1px solid #9aa6b2;border-radius:3px;}
        QLineEdit,QComboBox,QSpinBox,QDateTimeEdit{background:white;border:1px solid #9f9f9f;padding:3px;}
        QDialog#classicAddressDialog,QDialog#classicDownloadDialog,QDialog#classicDownloadComplete{background:#f3f3f3;} QDialog#classicAddressDialog QLabel,QDialog#classicDownloadDialog QLabel{background:transparent;} QDialog#classicAddressDialog QLineEdit,QDialog#classicDownloadDialog QLineEdit,QDialog#classicDownloadDialog QComboBox{background:#fff;border:1px solid #8f9dad;padding:3px 5px;min-height:18px;} QDialog#classicAddressDialog QPushButton,QDialog#classicDownloadDialog QPushButton,QDialog#classicDownloadComplete QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ffffff,stop:0.48 #f7f7f7,stop:0.52 #e9e9e9,stop:1 #dddddd);border:1px solid #8b8b8b;border-radius:1px;padding:3px 10px;} QDialog#classicAddressDialog QPushButton:hover,QDialog#classicDownloadDialog QPushButton:hover,QDialog#classicDownloadComplete QPushButton:hover{border:1px solid #3c7fb1;background:#eaf5ff;} QDialog#classicAddressDialog QPushButton:default,QDialog#classicDownloadDialog QPushButton:default,QDialog#classicDownloadComplete QPushButton:default{border:2px solid #3399ff;padding:2px 9px;}
        QTabWidget::pane,QGroupBox{border:1px solid #a6a6a6;background:#f7f7f7;}
        """)

    def notify(self,title,message):
        if self.notifications and self.tray.isVisible(): self.tray.showMessage(title,message,QSystemTrayIcon.Information,5000)
    def load_rows(self):
        # Rebuild the view from storage. Clearing first prevents Refresh from
        # appending the same database records again and creating duplicates.
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for r in self.storage.all():
            self.insert_row(r)
            live=getattr(self,'live_telemetry',{}).get(r['id'])
            if live:
                sp,et=live
                self.update_row(r['id'],speed=sp,eta=et,status=r['status'])
        self.table.setSortingEnabled(True)
        self.refresh_visibility()
    def insert_row(self,r):
        sorting=self.table.isSortingEnabled(); self.table.setSortingEnabled(False)
        i=self.table.rowCount(); self.table.insertRow(i)
        vals=self._classic_row_values(r,0,0)
        for c,v in enumerate(vals):
            it=QTableWidgetItem(v)
            if c==0:
                it.setData(Qt.UserRole,r['id'])
                it.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
            self.table.setItem(i,c,it)
        self.table.setSortingEnabled(sorting)
    def _queue_mark(self,r):
        q=str(r['queue_name'] or '')
        if q=='High Priority': return 'H'
        if q=='Later': return 'L'
        return ''
    @staticmethod
    def date_text(v):
        try:
            if not v:return ''
            return time.strftime('%b %d %H:%M:%S %Y',time.localtime(float(v)))
        except Exception:return ''
    def _classic_row_values(self,r,speed=0,eta=0):
        desc=str(r['error'] or '') if str(r['status'])=='Failed' else ''
        last=r['started'] or r['updated'] or r['created']
        return [
            str(r['filename']), self._queue_mark(r), self.size(r['total']), str(r['status']), desc,
            self.speed_text(speed or 0) if speed else '', self.date_text(last), self.date_text(r['created']),
            self.eta_text(eta or 0) if eta else '', str(r['path'])
        ]
    def row_by_id(self,rid):
        for i in range(self.table.rowCount()):
            item=self.table.item(i,0)
            if item and item.data(Qt.UserRole)==rid:return i
        return -1
    def update_row(self,rid,downloaded=None,total=None,speed=None,eta=None,status=None):
        i=self.row_by_id(rid); rr=self.storage.get(rid)
        if i<0 or not rr:return
        # total/status are sometimes supplied before the async storage refresh has
        # been observed, so render those live values without changing the model.
        vals=self._classic_row_values(rr,speed or 0,eta or 0)
        if total is not None: vals[2]=self.size(total)
        if status is not None: vals[3]=status
        sorting=self.table.isSortingEnabled();self.table.setSortingEnabled(False)
        for c,v in enumerate(vals):
            item=self.table.item(i,c)
            if item and item.text()!=v:item.setText(v)
        if self.table.item(i,3): self.table.item(i,3).setToolTip(str(rr['error'] or ''))
        self.table.setSortingEnabled(sorting)
        self.refresh_visibility()
    def selected_ids(self): return [self.table.item(i,0).data(Qt.UserRole) for i in sorted({x.row() for x in self.table.selectedIndexes()})]
    def _duplicate_target(self,url,path,selector=''):
        # Duplicate prompts are based only on entries that are actually still
        # present in the downloader list.  Deleted/stale database rows and old
        # "Replaced" shadow rows must never trigger the duplicate dialog.
        listed_ids={self.table.item(i,0).data(Qt.UserRole) for i in range(self.table.rowCount()) if self.table.item(i,0)}
        rows=[dict(r) for r in self.storage.all() if r['id'] in listed_ids and str(r['status'])!='Replaced']
        q=QSettings('InternetDownloadManager','InternetDownloadManager')
        existing=None
        for row in sorted(rows,key=lambda r:r['id'],reverse=True):
            old=self.media_selectors.get(row['id'],('',None,None))[0] or str(q.value(f"media_selector/{row['id']}",''))
            if url_key(row['url'])==url_key(url) and same_selection(selector,old):
                existing=row;break
        if existing is None: return numbered_path(path,rows)
        rid=existing['id']; target=Path(existing['path'])
        active_ids=[i for i in self.tasks if self.storage.get(i) and path_key(self.storage.get(i)['path'])==path_key(target)]
        active=bool(active_ids)
        action=str(self.settings.q.value('duplicate_action','ask'))
        if action not in {'number','overwrite','resume'} or (active and action=='overwrite'):
            dlg=DuplicateDownloadDialog(None,url,active);dlg.setWindowIcon(self.windowIcon())
            if self._show_browser_dialog(dlg)!=QDialog.Accepted: return None
            action=dlg.choice()
            if dlg.remember.isChecked(): self.settings.q.setValue('duplicate_action',action)
        if action=='number': return numbered_path(path,rows,force=True)
        if action=='resume':
            if existing['status']=='Completed' and target.is_file():
                self.show_download_complete(rid)
            elif active:
                self.show_progress_dialog(active_ids[0])
            else:
                if selector:
                    self.media_selectors[rid]=(selector,target.parent,target.name)
                    q.setValue(f'media_selector/{rid}',selector)
                self.storage.update(rid,url=url,status='Queued',error='',scheduled_at=0)
                self.start_ids([rid])
            return None
        # This branch is reached only after the user's overwrite choice.
        if active: return None
        try:
            import shutil
            target.unlink(missing_ok=True)
            for suffix in ('.part','.ytdl'):
                Path(str(target)+suffix).unlink(missing_ok=True)
            partial=Path(str(target)+'.idm-parts')
            if partial.is_dir(): shutil.rmtree(partial)
            if selector:
                # Only yt-dlp sidecars belonging to this exact output stem.
                pattern=re.compile(re.escape(target.stem)+r'\.f[^.]+\.(?:mp4|m4a|webm|mkv|mp3)(?:\.part|\.ytdl)?$')
                for item in target.parent.iterdir():
                    if item.is_file() and pattern.fullmatch(item.name): item.unlink()
            # Prevent the older row from being auto-started alongside the replacement.
            self.storage.update(rid,status='Replaced',error='')
            self.update_row(rid,status='Replaced')
            return target
        except OSError as exc:
            QMessageBox.warning(self,'Cannot overwrite file',str(exc));return None

    def add_url(self,initial_url=''):
        # Always open the Add URL dialog first. Do not perform a blocking network
        # request from the GUI thread just to discover the filename; that made
        # the button appear frozen and prevented downloads from being queued when
        # DNS/server access was temporarily unavailable. The actual downloader
        # performs the network request asynchronously and reports errors in the
        # download row.
        first=AddressDialog(self,initial_url)
        if first.exec()!=QDialog.Accepted:return
        entered_url=first.url.text().strip()
        if not re.match(r'^https?://',entered_url,re.I):
            QMessageBox.warning(self,'Invalid URL','Please enter a valid HTTP/HTTPS URL.')
            return
        d=AddDialog(self,entered_url)
        if d.exec()!=QDialog.Accepted:return
        url=d.url.text().strip()
        if not re.match(r'^https?://',url,re.I):
            QMessageBox.warning(self,'Invalid URL','Please enter a valid HTTP/HTTPS URL.')
            return
        folder=Path(d.folder.text()).expanduser()
        try:
            folder.mkdir(parents=True,exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self,'Invalid download folder',str(e))
            return
        # Get a useful initial filename from the URL without contacting the server.
        # The downloader will still follow redirects and download the real content.
        from urllib.parse import urlparse, unquote
        raw_name=d.filename.text().strip() or Path(unquote(urlparse(url).path)).name or 'download'
        name=safe_filename(raw_name)
        ext=Path(name).suffix.lower()
        auto_cat='Video' if ext in {'.mp4','.mkv','.webm','.mov','.avi','.m4v'} else ('Audio' if ext in {'.mp3','.wav','.flac','.m4a','.aac','.ogg'} else ('Documents' if ext in {'.pdf','.doc','.docx','.txt','.xlsx','.csv'} else ('Archives' if ext in {'.zip','.7z','.rar','.tar','.gz','.iso'} else 'Other')))
        if d.category.currentText() == 'Video' and auto_cat != 'Other': d.category.setCurrentText(auto_cat)
        path=self._duplicate_target(url,folder/name)
        if path is None:return
        folder=path.parent;name=path.name
        scheduled = d.scheduled_at()
        rid=self.storage.add(url,name,str(path),'Queued',category=d.category.currentText(),queue_name=d.queue.currentText(),priority=d.priority.value(),scheduled_at=scheduled,connections=self.connections)
        self.insert_row(self.storage.get(rid))
        if d.action == 'later':
            self.statusBar().showMessage(f'Queued for later: {name}')
        elif scheduled:
            self.statusBar().showMessage(f'Queued for {MainWindow.sched_text(scheduled)}: {name}')
        else:
            # An Add URL action is an explicit user request to download now.
            # Start it immediately rather than relying only on the 1-second queue
            # timer or a persisted auto-start preference from an older build.
            self.start_ids([rid])
            if rid in self.tasks:
                self.statusBar().showMessage(f'Connecting: {name}')
            else:
                rr=self.storage.get(rid)
                err=(rr['error'] if rr else '') or 'No free download slot.'
                self.statusBar().showMessage(f'Queued: {name} — {err}')
    def _present_for_browser_request(self):
        """Keep the main window in its current tray/minimized state.

        Browser requests show their own top-level File Info dialog, so a user
        can accept a download without first restoring the main window.
        """
        QApplication.processEvents()

    @staticmethod
    def _show_browser_dialog(dialog):
        # A top-level, foreground dialog remains visible even while the main
        # application is minimized or hidden in the notification area.
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.show(); dialog.raise_(); dialog.activateWindow()
        return dialog.exec()

    def handle_browser_request(self, payload):
        """Handle every extension download request through the normal desktop dialog flow."""
        try:
            from .options_config import load_options
            if not load_options().get('integration', True):
                self.statusBar().showMessage('Browser integration is disabled in Options')
                return
            action = str(payload.get('action',''))
            url = str(payload.get('url','')).strip()
            if not re.match(r'^https?://', url, re.I):
                return
            # Browser service workers can retry/replay a request while the native
            # host is starting. De-duplicate by request id (or by a short-lived
            # action/url/quality fingerprint) so one quality click creates ONE task.
            now = time.monotonic()
            self._browser_recent_requests = {k:v for k,v in self._browser_recent_requests.items() if now-v < 15.0}
            request_id = str(payload.get('requestId','')).strip()
            fingerprint = request_id or '|'.join([action,url,str(payload.get('quality','')),str(payload.get('kind',''))])
            if fingerprint in self._browser_recent_requests:
                return
            self._browser_recent_requests[fingerprint] = now
            # If the main window was hidden in the notification area, restore it
            # automatically. The user never has to open Show hidden icons first.
            self._present_for_browser_request()
            if action == 'mediaPreset':
                self.download_media_preset(url, payload.get('quality','best'), payload.get('kind','video'))
            elif action == 'directMedia':
                self.download_direct_url(url, show_file_info=True)
            elif action == 'pageMedia':
                self.download_media(url)
        except Exception as e:
            self.statusBar().showMessage(f'Browser integration error: {e}')

    def download_direct_url(self, url, show_file_info=True):
        """Handle a direct browser file/media URL through Download File Info."""
        from .options_config import load_options, matches
        options=load_options()
        if matches(url, options.get('excluded_sites','')) or matches(url, options.get('excluded_urls','')):
            self.statusBar().showMessage('Download skipped by Options exclusions')
            return
        if not re.match(r'^https?://', url or '', re.I):
            return
        from urllib.parse import urlparse, unquote
        raw_name = Path(unquote(urlparse(url).path)).name or 'download'
        name = safe_filename(raw_name)
        ext = Path(name).suffix.lower()
        category = AddDialog._category_for_filename(name) or 'Other'

        if show_file_info and options.get('show_start',True):
            d=AddDialog(None,url)
            d.setWindowIcon(self.windowIcon())
            d.filename.setText(name)
            d.category.setCurrentText(category)
            d.description.setText('Browser extension download request')
            if self._show_browser_dialog(d)!=QDialog.Accepted:
                return
            folder=Path(d.folder.text()).expanduser()
            name=safe_filename(d.filename.text().strip() or name)
            category=d.category.currentText()
            start_now=(d.action!='later')
        else:
            folder=Path(DEFAULT_DIR).expanduser(); start_now=True
        try:
            folder.mkdir(parents=True,exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self,'Invalid download folder',str(e)); return
        path=self._duplicate_target(url,folder/name)
        if path is None:return
        folder=path.parent;name=path.name
        rid=self.storage.add(url,name,str(path),'Queued',category=category,queue_name='Main',priority=50,connections=self.connections)
        self.insert_row(self.storage.get(rid))
        if start_now:
            self.start_ids([rid])
            self.statusBar().showMessage(f'Starting browser download: {name}')
        else:
            self.statusBar().showMessage(f'Queued for later: {name}')

    def _media_size_key(self,url,quality,kind):
        return hashlib.sha256(f'{url}|{quality}|{kind}'.encode('utf-8')).hexdigest()

    def _cached_media_size(self,url,quality,kind):
        try:
            return int(QSettings('InternetDownloadManager','InternetDownloadManager').value('media_size/'+self._media_size_key(url,quality,kind),0) or 0)
        except Exception:
            return 0

    def _save_media_size(self,url,quality,kind,size):
        try:
            if int(size or 0)>0:
                QSettings('InternetDownloadManager','InternetDownloadManager').setValue('media_size/'+self._media_size_key(url,quality,kind),int(size))
        except Exception:
            pass

    def _probe_media_file_info(self, dialog, url, quality, kind, prepared_info=None):
        dialog._media_mode=True
        dialog.start_button.setEnabled(False)
        dialog.later_button.setEnabled(False)
        dialog.file_size.setText('')
        dialog.url.setReadOnly(True)
        result=dict(prepared_info or {})
        result['done']=bool(prepared_info)
        original_path=dialog.save_as.text()
        def worker():
            try:
                from .media_selection import resolve_selection
                result.update(resolve_selection(url,quality,kind))
            except Exception as exc:
                result['error']=str(exc)
            finally:
                result['done']=True
        timer=QTimer(dialog)
        timer.setInterval(100)
        def apply_when_ready():
            if not result['done']: return
            timer.stop()
            if result.get('error'):
                dialog.file_size.setText('Unavailable')
                dialog.description.setText(result['error'])
                dialog.description.setToolTip(result['error'])
                return
            dialog._resolved_selector=result['selector']
            dialog._media_ext='.'+result['ext']
            if dialog.save_as.text()==original_path:
                name=safe_filename(result['title'])+dialog._media_ext
                dialog.filename.setText(name)
                dialog.save_as.setText(str(Path(dialog.folder.text())/name))
            else:
                path=Path(dialog.save_as.text()).with_suffix(dialog._media_ext)
                dialog.save_as.setText(str(path))
            dialog.save_as.setCursorPosition(0)
            dialog.save_as.setToolTip(dialog.save_as.text())
            dialog._update_file_type_icon()
            total=result['size']
            dialog._expected_media_total=total
            dialog.file_size.setText(('Approx. ' if result['approximate'] else '') + dialog._format_bytes(total) if total else 'Size unavailable')
            dialog.file_size.setToolTip('Size of the selected video/audio streams; final merged file may differ slightly.' if result['approximate'] else 'Reported size of the selected file.')
            dialog.start_button.setEnabled(True)
            dialog.later_button.setEnabled(True)
        timer.timeout.connect(apply_when_ready)
        timer.start()
        dialog._media_info_timer=timer
        if prepared_info:
            apply_when_ready()
        else:
            threading.Thread(target=worker,daemon=True).start()

    def download_media_preset(self, url, quality='best', kind='video', browser_title='', prepared_info=None):
        """Browser quality selection -> File Info -> Progress -> Complete."""
        if not re.match(r'^https?://', url or '', re.I):
            QMessageBox.warning(self,'Invalid URL','Please enter a valid HTTP/HTTPS URL.')
            return
        from .options_config import load_options, matches
        if matches(url, load_options().get('excluded_sites','')) or matches(url, load_options().get('excluded_urls','')):
            QMessageBox.information(self,'Download blocked','This address is excluded in Options.')
            return
        kind = 'audio' if str(kind).lower() == 'audio' else 'video'
        quality = str(quality or 'best').lower()
        if not valid_quality(quality):
            quality = 'best'
        label = 'Audio' if kind == 'audio' else ('Best Video' if quality == 'best' else f'{quality}p Video')

        from .media_selection import cached_selection, resolve_selection
        prepared_info=prepared_info or cached_selection(url,quality,kind)
        if not prepared_info:
            # Finish a cache miss off the GUI thread before opening the dialog.
            pending={}
            def prepare():
                try: pending['info']=resolve_selection(url,quality,kind)
                except Exception as exc: pending['error']=str(exc)
                finally: pending['done']=True
            ready=QTimer(self)
            def open_ready():
                if not pending.get('done'): return
                ready.stop(); ready.deleteLater()
                if 'error' in pending:
                    QMessageBox.warning(self,'Media information',pending['error'])
                else:
                    self.download_media_preset(url,quality,kind,browser_title,pending['info'])
            ready.timeout.connect(open_ready); ready.start(100)
            threading.Thread(target=prepare,daemon=True).start()
            return

        # Do not start immediately from the browser overlay. First show the same
        # professional Download File Info dialog used by normal downloads.
        d = AddDialog(None, url)
        d.setWindowIcon(self.windowIcon())
        d.category.setCurrentText('Audio' if kind == 'audio' else 'Video')
        raw_title = re.sub(r'\s*-\s*YouTube\s*$', '', str(browser_title or '').strip(), flags=re.I).strip()
        if not raw_title:
            raw_title = 'Video' if kind == 'video' else 'Audio'
        ext = '.m4a' if kind == 'audio' else ('.' + video_type(quality))
        safe_label = safe_filename(raw_title) + ext
        d.filename.setText(safe_label)
        if hasattr(d,'save_as'):
            d.save_as.setText(str(Path(d.folder.text()) / safe_label))
            QTimer.singleShot(0, d._update_file_type_icon)
        self._probe_media_file_info(d, url, quality, kind, prepared_info)
        d.description.setText(f'Browser media quality: {label}')
        if self._show_browser_dialog(d) != QDialog.Accepted:
            return

        folder = Path(d.folder.text()).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self,'Invalid download folder',str(e)); return
        name = safe_filename(d.filename.text().strip() or safe_label)
        selector = d._resolved_selector
        target=self._duplicate_target(url,folder/name,selector)
        if target is None:return
        folder=target.parent;name=target.name
        # Media presets need their selector at start time, so Download Later is
        # kept queued in the list rather than silently starting in the browser.
        status = 'Queued' if d.action == 'later' else 'Preparing media...'
        rid = self.storage.add(url,name,str(folder/name),status,category=('Audio' if kind == 'audio' else 'Video'),queue_name='Main',priority=50)
        self.insert_row(self.storage.get(rid))
        self.media_selectors[rid]=(selector,folder,name)
        QSettings('InternetDownloadManager','InternetDownloadManager').setValue(f'media_selector/{rid}',selector)
        if d.action == 'later':
            self.statusBar().showMessage(f'Queued for later: {name}')
            return

        from .media import MediaDownloadTask
        self.pauses[rid]=threading.Event()
        self.stops[rid]=threading.Event()
        task = MediaDownloadTask(url,selector,folder,name,self.stops[rid],self.pauses[rid],connections=self.connections,speed_limit_kbps=self.speed_limit_kbps)
        task.signals.progress.connect(lambda p,s,e,st,dn,tt,r=rid:self.media_progress(r,p,s,e,dn,tt))
        task.signals.finished.connect(lambda final,r=rid:self.media_done(r,final))
        task.signals.failed.connect(lambda e,r=rid:self.media_failed(r,e))
        self.tasks[rid]=task
        self.media_selectors[rid]=(selector,folder,name)
        expected_total=int(getattr(d,'_expected_media_total',0) or 0)
        if expected_total:
            self.media_expected_totals[rid]=expected_total
            self.storage.update(rid,total=expected_total)
        self.storage.update(rid,status='Preparing media...')
        self.show_progress_dialog(rid)
        self.pool.start(task)
        self.statusBar().showMessage(f'Resolving {label} stream... download speed will appear as soon as bytes start.')


    def download_media(self, initial_url=''):
        # Browser integration can send a page directly to the media extractor.
        # Manual use still opens the same dialog.
        if isinstance(initial_url, bool): initial_url=''
        d=AddDialog(self, initial_url); d.setWindowTitle('Download Video / Media')
        if d.exec()!=QDialog.Accepted:return
        url=d.url.text().strip()
        if not re.match(r'^https?://',url,re.I):QMessageBox.warning(self,'Invalid URL','Please enter a valid HTTP/HTTPS URL.');return
        from .media import MediaInfoTask
        self.statusBar().showMessage('Reading available media formats...'); task=MediaInfoTask(url)
        task.signals.formats.connect(lambda info,u=url,f=d.folder.text(),cat=d.category.currentText(),q=d.queue.currentText(),pr=d.priority.value():self.choose_media(u,f,info,cat,q,pr))
        task.signals.failed.connect(lambda e:QMessageBox.critical(self,'Media detection failed',e)); self.pool.start(task)
    def choose_media(self,url,folder,info,category,queue_name,priority):
        dlg=MediaDialog(self,info['title'],info['formats'])
        if dlg.exec()!=QDialog.Accepted:return
        name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',info['title']).strip(' .')[:180] or 'media'
        path=Path(folder).expanduser();path.mkdir(parents=True,exist_ok=True)
        target=self._duplicate_target(url,path/name,dlg.selected)
        if target is None:return
        path=target.parent;name=target.name
        rid=self.storage.add(url,name,str(path/name),'Downloading',category=category,queue_name=queue_name,priority=priority)
        self.insert_row(self.storage.get(rid)); self.storage.update(rid,status='Downloading')
        from .media import MediaDownloadTask
        self.pauses[rid]=threading.Event(); self.stops[rid]=threading.Event()
        self.media_selectors[rid]=(dlg.selected,path,name)
        QSettings('InternetDownloadManager','InternetDownloadManager').setValue(f'media_selector/{rid}',dlg.selected)
        task=MediaDownloadTask(url,dlg.selected,path,name,self.stops[rid],self.pauses[rid],connections=self.connections,speed_limit_kbps=self.speed_limit_kbps)
        task.signals.progress.connect(lambda p,s,e,st,dn,tt,r=rid:self.media_progress(r,p,s,e,dn,tt))
        task.signals.finished.connect(lambda final,r=rid:self.media_done(r,final)); task.signals.failed.connect(lambda e,r=rid:self.media_failed(r,e)); self.tasks[rid]=task; self.pool.start(task)
    def media_progress(self,rid,p,s,e,downloaded=0,total=0):
        # Use yt-dlp's real byte counters, transfer speed and ETA rather than
        # storing the percentage as if it were a byte count.
        downloaded=max(0,int(downloaded or 0))
        expected_total=max(0,int(self.media_expected_totals.get(rid,0) or 0))
        if expected_total:
            total=expected_total
            pct=max(0.0,min(100.0,(downloaded*100.0/total) if total else 0.0))
        else:
            pct=max(0.0,min(100.0,float(p or 0)))
            total=max(0,int(total or 0))
            if total <= 0 and downloaded > 0 and pct > 0:
                total=int(downloaded*100.0/pct)
        eta=0
        try: eta=max(0,int(float(e or 0)))
        except Exception: eta=0
        speed=float(s or 0)
        self.live_telemetry[rid]=(speed,eta)
        self.storage.update(rid,status='Downloading',downloaded=downloaded,total=total)
        self.update_row(rid,downloaded=downloaded,total=total,speed=speed,eta=eta,status='Downloading')
        dlg=self.progress_dialogs.get(rid)
        if dlg: dlg.update_live(downloaded,total,speed,eta,'Downloading')
        self.statusBar().showMessage(f'Media {pct:.1f}%  •  {self.speed_text(speed)}')
    def media_done(self,rid,path):
        from .options_config import sound_event, scan_file
        self.live_telemetry.pop(rid,None)
        expected_total=int(self.media_expected_totals.get(rid,0) or 0)
        size=Path(path).stat().st_size if Path(path).exists() else 0

        # A resumed media job must not be declared Complete when yt-dlp has
        # produced only a tiny fragment. File Info's expected combined size is
        # the guard. Allow normal container/estimate variance, but reject a
        # clearly incomplete result (<50% of expected total).
        if expected_total and size < int(expected_total * 0.50):
            self.storage.update(rid,status='Paused',downloaded=size,total=expected_total,error='')
            self.tasks.pop(rid,None)
            self.update_row(rid,status='Paused',downloaded=size,total=expected_total)
            dlg=self.progress_dialogs.get(rid)
            if dlg: dlg.sync()
            return

        self.media_expected_totals.pop(rid,None)
        display_total=expected_total or size
        self.storage.update(rid,status='Completed',path=str(path),filename=Path(path).name,downloaded=size,total=display_total); self.tasks.pop(rid,None); self.update_row(rid,status='Completed',downloaded=size,total=display_total); self.notify('Download completed',Path(path).name);
        try: sound_event('Download complete')
        except Exception: pass
        try: scan_file(path)
        except Exception: pass
        self.statusBar().showMessage(f'Media completed: {path}'); self.close_progress_dialog(rid);
        from .options_config import load_options
        if load_options().get('show_complete',True): QTimer.singleShot(0, lambda r=rid: self.show_download_complete(r))
    def media_failed(self,rid,e):
        from .options_config import sound_event
        self.live_telemetry.pop(rid,None)
        msg=str(e)
        try:
            if msg != '__IDM_PAUSED__': sound_event('Download failed')
        except Exception: pass
        self.tasks.pop(rid,None)
        if msg=='__IDM_PAUSED__':
            self.storage.update(rid,status='Paused',error='')
            self.update_row(rid,status='Paused')
            self.pauses.pop(rid,None); self.stops.pop(rid,None)
            dlg=self.progress_dialogs.get(rid)
            if dlg: dlg.sync()
            return
        if msg=='__IDM_STOPPED__':
            self.storage.update(rid,status='Stopped',error='')
            self.update_row(rid,status='Stopped')
            self.pauses.pop(rid,None); self.stops.pop(rid,None)
            dlg=self.progress_dialogs.get(rid)
            if dlg: dlg.sync()
            return
        self.pauses.pop(rid,None); self.stops.pop(rid,None)
        self.storage.update(rid,status='Failed',error=msg); self.update_row(rid,status='Failed'); self.notify('Download failed',msg); QMessageBox.critical(self,'Media download failed',msg)
    def refresh_queue_filter(self):
        # Restore normal status/category filtering after a queue shortcut.
        self.refresh_visibility()

    def check_clipboard(self):
        app=QApplication.instance();text=app.clipboard().text().strip() if app else ''
        if not re.match(r'^https?://',text,re.I) or text==self.last_clipboard_url:return
        self.last_clipboard_url=text;self.statusBar().showMessage('URL detected in clipboard — use + Add URL or Download Media')
    def start_selected(self):self.start_ids(self.selected_ids())
    def resume_selected(self):self.start_ids(self.selected_ids())
    def start_ids(self,ids):
        # Normalize persisted settings so an old/corrupt value can never leave
        # every new download permanently stuck in Queued.
        self.max_downloads=max(1,min(20,int(self.max_downloads or 1)))
        self.connections=max(1,min(16,int(self.connections or 1)))
        for rid in ids:
            if rid in self.tasks:
                continue
            if len(self.tasks)>=self.max_downloads:
                self.statusBar().showMessage(f'Download queued — {self.max_downloads} simultaneous download slot(s) in use')
                break
            rr=self.storage.get(rid)
            if not rr or rr['status']=='Completed':
                continue
            if rr['scheduled_at'] and rr['scheduled_at']>time.time():
                continue
            try:
                self.pauses[rid]=threading.Event()
                self.stops[rid]=threading.Event()
                self.storage.update(rid,status='Connecting',error='')
                saved_selector=QSettings('InternetDownloadManager','InternetDownloadManager').value(f'media_selector/{rid}','')
                if saved_selector and rid not in self.media_selectors:
                    self.media_selectors[rid]=(str(saved_selector),Path(rr['path']).parent,rr['filename'])
                if rid in self.media_selectors:
                    from .media import MediaDownloadTask
                    selector, folder, name = self.media_selectors[rid]
                    task=MediaDownloadTask(rr['url'],selector,folder,name,self.stops[rid],self.pauses[rid],connections=self.connections,speed_limit_kbps=self.speed_limit_kbps)
                    task.signals.progress.connect(lambda p,s,e,st,dn,tt,r=rid:self.media_progress(r,p,s,e,dn,tt))
                    task.signals.finished.connect(lambda final,r=rid:self.media_done(r,final))
                    task.signals.failed.connect(lambda e,r=rid:self.media_failed(r,e))
                else:
                    task=DownloadTask(rr,self.storage,self.stops[rid],self.pauses[rid],self.speed_limit_kbps,__import__('idm.options_config',fromlist=['connection_count']).connection_count(rr['url'],int(rr['connections'] or self.connections)),int(self.settings.max_retries))
                if rid not in self.media_selectors:
                    task.signals.progress.connect(lambda d,t,s,e,r=rid:self.download_progress(r,d,t,s,e))
                    task.signals.status.connect(lambda st,msg,r=rid:self.task_status(r,st,msg))
                    task.signals.finished.connect(lambda r=rid:self.task_done(r))
                    task.signals.failed.connect(lambda err,r=rid:self.task_failed(r,err))
                    task.signals.stopped.connect(lambda r=rid:self.task_stopped(r))
                self.tasks[rid]=task
                # Mark the item immediately so the UI can never remain on
                # Queued merely because the worker has not entered run() yet.
                self.update_row(rid,status='Connecting')
                self.pool.start(task)
                self.show_progress_dialog(rid)
            except Exception as exc:
                self.tasks.pop(rid,None); self.pauses.pop(rid,None); self.stops.pop(rid,None)
                self.storage.update(rid,status='Failed',error=str(exc))
                self.update_row(rid,status='Failed')
                self.statusBar().showMessage(f'Could not start download: {exc}')

    def _apply_media_live_progress(self, rid, downloaded=0, total=0, speed=0.0, eta=None, status='Downloading'):
        """Persist real media transfer telemetry so both Progress dialog and main table stay live."""
        try:
            downloaded = int(downloaded or 0)
            total = int(total or 0)
            speed = float(speed or 0.0)
            percent = int((downloaded * 100 / total)) if total > 0 else 0
            eta_val = int(eta) if eta is not None else (int((total-downloaded)/speed) if total > downloaded and speed > 0 else None)
            self.storage.update_progress(rid, downloaded, total, speed, eta_val, status)
        except Exception:
            try:
                self.storage.update_status(rid, status)
            except Exception:
                pass
        try:
            self.refresh()
        except Exception:
            pass
        try:
            dlg = self.progress_dialogs.get(rid)
            if dlg:
                dlg.refresh_data()
        except Exception:
            pass

    def show_progress_dialog(self,rid):
        dlg=self.progress_dialogs.get(rid)
        if dlg is None:
            dlg=DownloadProgressDialog(self,rid); self.progress_dialogs[rid]=dlg
            dlg.destroyed.connect(lambda _=None,r=rid:self.progress_dialogs.pop(r,None))
        dlg.show(); dlg.raise_(); dlg.activateWindow()
    def download_progress(self,rid,d,t,s,e):
        self.update_row(rid,d,t,s,e,'Downloading')
        dlg=self.progress_dialogs.get(rid)
        if dlg: dlg.update_live(d,t,s,e,'Downloading')
    def task_status(self,rid,st,msg):
        self.update_row(rid,status=st); self.statusBar().showMessage(msg or st)
        if st=='Paused':
            # A paused worker has exited. Remove its task/event handles so Resume
            # can create a fresh worker that continues from saved bytes/parts.
            self.tasks.pop(rid,None); self.pauses.pop(rid,None); self.stops.pop(rid,None)
        dlg=self.progress_dialogs.get(rid)
        if dlg: dlg.sync()
    def queue_tick(self):
        if len(self.tasks)>=self.max_downloads:return
        for r in self.storage.all():
            if len(self.tasks)>=self.max_downloads:break
            if r['queue_name'] and r['status'] in ('Queued','Retrying') and (not r['scheduled_at'] or r['scheduled_at']<=time.time()):
                self.start_ids([r['id']])
    def pause_selected(self): self.pause_ids(self.selected_ids())
    def pause_ids(self,ids):
        for rid in ids:
            if rid in self.pauses: self.pauses[rid].set()
            else:
                r=self.storage.get(rid)
                if r and r['status'] not in ('Completed','Failed','Stopped'):
                    self.storage.update(rid,status='Paused'); self.update_row(rid,status='Paused')
    def stop_selected(self): self.stop_ids(self.selected_ids())
    def stop_all(self):
        ids=list(self.tasks.keys())
        if ids:self.stop_ids(ids)
    def delete_completed(self):
        ids=[r['id'] for r in self.storage.all() if r['status']=='Completed']
        for rid in ids:
            self.storage.delete(rid)
            i=self.row_by_id(rid)
            if i>=0:self.table.removeRow(i)
        self.statusBar().showMessage(f'Deleted {len(ids)} completed record(s).')
    def stop_ids(self,ids):
        for rid in ids:
            if rid in self.stops: self.stops[rid].set()
            else:
                r=self.storage.get(rid)
                if r and r['status'] not in ('Completed','Failed'):
                    self.storage.update(rid,status='Stopped'); self.update_row(rid,status='Stopped')
    def find_download(self):
        d=QDialog(self); d.setWindowTitle('Find'); d.setFixedSize(300,98)
        lay=QVBoxLayout(d); row=QHBoxLayout(); row.addWidget(QLabel('Find what:'))
        edit=QLineEdit(getattr(self,'_find_text','')); row.addWidget(edit,1); lay.addLayout(row)
        btns=QHBoxLayout(); btns.addStretch(); findb=QPushButton('Find Next'); cancel=QPushButton('Cancel'); btns.addWidget(findb); btns.addWidget(cancel); lay.addLayout(btns)
        def go():
            self._find_text=edit.text().strip(); self._find_row=-1; self.find_next(); d.accept()
        findb.clicked.connect(go); edit.returnPressed.connect(go); cancel.clicked.connect(d.reject); edit.selectAll(); edit.setFocus(); d.exec()
    def find_next(self):
        q=getattr(self,'_find_text','').strip().lower()
        if not q: self.find_download(); return
        n=self.table.rowCount(); start=(getattr(self,'_find_row',-1)+1)%max(1,n)
        for off in range(n):
            r=(start+off)%n
            if any(self.table.item(r,c) and q in self.table.item(r,c).text().lower() for c in range(self.table.columnCount())):
                self._find_row=r; self.table.selectRow(r); self.table.scrollToItem(self.table.item(r,0)); return
        QMessageBox.information(self,'Find',f'Cannot find "{getattr(self,"_find_text","")}".')
    def start_queue_named(self,name):
        ids=[r['id'] for r in self.storage.all() if str(r['queue_name'])==name and r['status'] in ('Paused','Stopped','Queued','Retrying','Failed')]
        for rid in ids:
            if self.storage.get(rid) and self.storage.get(rid)['status']=='Failed': self.storage.update(rid,status='Retrying',error='')
        self.start_ids(ids)
    def stop_queue_named(self,name):
        ids=[r['id'] for r in self.storage.all() if str(r['queue_name'])==name and r['status'] not in ('Completed','Failed','Stopped')]
        self.stop_ids(ids)
    def set_speed_limit(self,value):
        self.speed_limit_kbps=max(0,int(value)); self.settings.speed_limit_kbps=self.speed_limit_kbps
        self.statusBar().showMessage('Speed Limiter: Unlimited' if not value else f'Speed Limiter: {value} KB/s')
    def speed_limit_dialog(self):
        d=QDialog(self); d.setWindowTitle('Speed Limiter'); d.setFixedSize(300,115); lay=QFormLayout(d)
        spin=QSpinBox(); spin.setRange(1,1024000); spin.setValue(max(10,self.speed_limit_kbps or 100)); spin.setSuffix(' KB/s'); lay.addRow('Maximum download speed:',spin)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); lay.addRow(buttons)
        buttons.accepted.connect(d.accept); buttons.rejected.connect(d.reject)
        if d.exec()==QDialog.Accepted:self.set_speed_limit(spin.value())
    def pause_all(self):
        for e in self.pauses.values():e.set()
    def resume_all(self):
        ids=[r['id'] for r in self.storage.all() if r['status'] in ('Paused','Stopped','Queued','Retrying')];self.start_ids(ids)
    def retry_selected(self):
        ids=[rid for rid in self.selected_ids() if self.storage.get(rid) and self.storage.get(rid)['status']=='Failed']
        for rid in ids:self.storage.update(rid,status='Retrying',error='')
        self.refresh_all_rows();self.start_ids(ids)
    def task_done(self,rid):
        from .options_config import load_options, sound_event, scan_file
        rr=self.storage.get(rid);self.tasks.pop(rid,None);self.pauses.pop(rid,None);self.stops.pop(rid,None);self.update_row(rid,status='Completed');self.notify('Download completed',rr['filename'] if rr else 'Download');
        if rr:
            try: sound_event('Download complete')
            except Exception: pass
            try: scan_file(rr['path'])
            except Exception: pass
        self.close_progress_dialog(rid);
        from .options_config import load_options
        if load_options().get('show_complete',True): QTimer.singleShot(0, lambda r=rid: self.show_download_complete(r))
    def close_progress_dialog(self,rid):
        dlg=self.progress_dialogs.pop(rid,None)
        if dlg:
            try:
                dlg.sync_timer.stop()
            except Exception:
                pass
            dlg.download_tray.hide()
            dlg.hide()
            dlg.deleteLater()

    def show_download_complete(self,rid):
        rr=self.storage.get(rid)
        if rr:
            dlg=DownloadCompleteDialog(None,dict(rr)); dlg.setWindowIcon(self.windowIcon())
            dlg.setWindowFlag(Qt.WindowStaysOnTopHint,True); dlg.show(); dlg.raise_(); dlg.activateWindow(); dlg.exec()
    def task_failed(self,rid,err):
        from .options_config import sound_event
        rr=self.storage.get(rid);self.tasks.pop(rid,None);self.pauses.pop(rid,None);self.stops.pop(rid,None);self.storage.update(rid,status='Failed',error=str(err));self.update_row(rid,status='Failed');self.notify('Download failed',rr['filename'] if rr else str(err));self.statusBar().showMessage(str(err)); QMessageBox.critical(self,'Download failed',str(err))
    def task_stopped(self,rid):self.tasks.pop(rid,None);self.pauses.pop(rid,None);self.stops.pop(rid,None);self.update_row(rid,status='Stopped')
    def redownload_selected(self):
        ids=self.selected_ids()
        for rid in ids:
            r=self.storage.get(rid)
            if r:
                try:
                    p=Path(r['path'])
                    if p.exists(): p.unlink()
                except Exception: pass
                self.storage.update(rid,status='Queued',downloaded=0,total=0,error='')
                self.update_row(rid,status='Queued')
        if ids:self.start_ids(ids)

    def delete_selected(self):
        ids=self.selected_ids()
        if not ids:
            QMessageBox.information(self,'Remove Download','Select one or more downloads first.')
            return
        d=QDialog(self); d.setWindowTitle('Remove Download'); d.setFixedSize(430,165)
        root=QVBoxLayout(d); row=QHBoxLayout(); icon=QLabel(); icon.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxQuestion).pixmap(48,48)); row.addWidget(icon)
        row.addWidget(QLabel('Are you sure you want to remove the selected download(s) from the list?'),1); root.addLayout(row)
        disk=QCheckBox('Also delete file(s) from disk (if available)'); root.addWidget(disk,0,Qt.AlignCenter)
        buttons=QDialogButtonBox(QDialogButtonBox.Yes|QDialogButtonBox.No); root.addWidget(buttons,0,Qt.AlignRight); buttons.accepted.connect(d.accept); buttons.rejected.connect(d.reject)
        if d.exec()!=QDialog.Accepted:return
        for rid in ids:
            r=self.storage.get(rid)
            if rid in self.tasks:self.stops[rid].set()
            if disk.isChecked() and r:
                try:
                    p=Path(r['path'])
                    if p.exists():p.unlink()
                except Exception:pass
            self.storage.delete(rid); i=self.row_by_id(rid)
            if i>=0:self.table.removeRow(i)

    def refresh_all_rows(self):
        selected=self.selected_ids();self.table.setRowCount(0);self.load_rows();
        for rid in selected:
            i=self.row_by_id(rid)
            if i>=0:self.table.selectRow(i)
    def open_file(self):
        ids=self.selected_ids();
        if not ids:return
        r=self.storage.get(ids[0]);p=Path(r['path']) if r else None
        if p and p.exists():os.startfile(str(p))
        else:QMessageBox.information(self,'File not found','The downloaded file is not available at its saved location.')
    def open_folder(self):
        ids=self.selected_ids();
        if not ids:return
        r=self.storage.get(ids[0]);p=Path(r['path']).parent if r else None
        if p and p.exists():subprocess.Popen(['explorer',str(p)])
    def refresh_visibility(self):
        q=self.search.text().lower().strip() if hasattr(self,'search') else ''
        f=self.filter.currentText() if hasattr(self,'filter') else 'All Downloads'
        c=self.cat.currentText() if hasattr(self,'cat') else 'All Categories'
        queue=getattr(self,'queue_filter',None); special=getattr(self,'special_filter',None)
        for i in range(self.table.rowCount()):
            item=self.table.item(i,0); rid=item.data(Qt.UserRole) if item else None; r=self.storage.get(rid) if rid else None
            visible=bool(r)
            if visible and q and q not in str(r['filename']).lower() and q not in str(r['url']).lower(): visible=False
            if visible and f!='All Downloads' and str(r['status'])!=f: visible=False
            if visible and c!='All Categories' and str(r['category'])!=c: visible=False
            if visible and queue and str(r['queue_name'])!=queue: visible=False
            if visible and special=='unfinished' and str(r['status'])=='Completed': visible=False
            if visible and special=='finished' and str(r['status'])!='Completed': visible=False
            if visible and special=='media' and str(r['category']) not in ('Video','Audio'): visible=False
            self.table.setRowHidden(i,not visible)
        if hasattr(self,'status_files'):
            rows=[self.storage.get(self.table.item(i,0).data(Qt.UserRole)) for i in range(self.table.rowCount()) if not self.table.isRowHidden(i) and self.table.item(i,0)]
            rows=[r for r in rows if r]
            total=sum(int(r['total'] or r['downloaded'] or 0) for r in rows)
            self.status_files.setText(f'{len(rows)} file(s)')
            self.status_size.setText(f'Total size: {self.size(total)}')
            self.status_ready.setText('Ready')

    def double_click_action(self,*args):
        mode=str(self.settings.q.value('double_click_action','Properties'))
        {'Open':self.open_file,'Open folder':self.open_folder,'Properties':self.details}[mode]()

    def context_menu(self,pos):
        item=self.table.itemAt(pos)
        if item and not item.isSelected(): self.table.selectRow(item.row())
        ids=self.selected_ids()
        if not ids:return
        rows=[self.storage.get(i) for i in ids]; r=rows[0]
        active=any(i in self.tasks for i in ids)
        complete=all(x['status']=='Completed' for x in rows)
        exists=len(ids)==1 and Path(r['path']).is_file()
        m=QMenu(self)
        m.setStyleSheet('QMenu {background:#fafafa; color:#111; padding:3px; border:1px solid #ddd;} QMenu::item {padding:5px 24px;} QMenu::item:selected {background:#dceafa;} QMenu::item:disabled {color:#999;} QMenu::separator {height:1px; background:#d6d6d6; margin:4px;}')
        def action(label,fn,enabled=True):
            a=m.addAction(label,fn);a.setEnabled(enabled);return a
        action('Open',self.open_file,exists and complete)
        action('Open with...',self.open_with,exists and complete)
        action('Open folder',self.open_folder,Path(r['path']).parent.is_dir())
        m.addSeparator()
        action('Move/Rename (Ctrl-M)',self.move_rename,len(ids)==1 and exists and not active)
        m.addSeparator();action('Redownload',self.redownload_selected,not active)
        m.addSeparator();action('Resume Download',self.resume_selected,not active and not complete)
        action('Stop Download',self.stop_selected,active)
        m.addSeparator();action('Refresh download address',self.refresh_address,len(ids)==1 and not active and not complete)
        m.addSeparator();action('Remove',self.delete_selected)
        m.addSeparator();q=m.addMenu('Add to queue')
        for name in ('Main','High Priority','Later'):
            q.addAction(name,lambda checked=False,n=name:self.assign_queue(n))
        action('Delete from queue',lambda:self.assign_queue(''),any(x['queue_name'] for x in rows))
        m.addSeparator();d=m.addMenu('On double click')
        for mode in ('Open','Open folder','Properties'):
            a=d.addAction(mode);a.setCheckable(True);a.setChecked(str(self.settings.q.value('double_click_action','Properties'))==mode)
            a.triggered.connect(lambda checked=False,v=mode:self.settings.q.setValue('double_click_action',v))
        m.addSeparator();action('Properties',self.details)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def open_with(self):
        ids=self.selected_ids()
        if ids:
            path=self.storage.get(ids[0])['path']
            subprocess.Popen(['rundll32.exe','shell32.dll,OpenAs_RunDLL',str(path)])

    def move_rename(self):
        ids=self.selected_ids()
        if len(ids)!=1 or ids[0] in self.tasks:return
        r=self.storage.get(ids[0]);old=Path(r['path'])
        if not old.is_file():return
        dest,_=QFileDialog.getSaveFileName(self,'Move/Rename',str(old))
        if not dest or Path(dest)==old:return
        if Path(dest).exists():
            QMessageBox.warning(self,'Move/Rename','Choose a filename that does not already exist.');return
        try:
            import shutil
            shutil.move(str(old),dest)
            self.storage.update(ids[0],path=dest,filename=Path(dest).name);self.update_row(ids[0])
        except Exception as e:QMessageBox.warning(self,'Move/Rename',str(e))

    def assign_queue(self,name):
        for rid in self.selected_ids():
            self.storage.update(rid,queue_name=name);self.update_row(rid)

    def refresh_address(self):
        ids=self.selected_ids()
        if len(ids)!=1 or ids[0] in self.tasks:return
        r=self.storage.get(ids[0])
        value,ok=QInputDialog.getText(self,'Refresh download address','Download URL:',text=r['url'])
        if ok and value.strip().startswith(('https://','http://')):
            self.storage.update(ids[0],url=value.strip(),error='');self.update_row(ids[0])

    def refresh_selected(self):
        # Re-read the latest database rows and repaint the list/progress windows.
        # Keep the selected row and active download tasks intact.
        selected=self.selected_ids()
        try:
            self.storage.conn.commit()
        except Exception:
            pass
        self.load_rows()
        for rid, dlg in list(self.progress_dialogs.items()):
            try:
                dlg.sync()
            except RuntimeError:
                self.progress_dialogs.pop(rid, None)
        for rid in selected:
            row=self.row_by_id(rid)
            if row >= 0:
                self.table.selectRow(row)
        self.table.viewport().update()
        self.statusBar().showMessage('Download list refreshed')
    def diagnostics(self):
        ids=self.selected_ids()
        if not ids:
            QMessageBox.information(self,'Download Diagnostics','Select a download row first, then open Diagnostics.')
            return
        r=self.storage.get(ids[0])
        if not r:return
        lines=[]
        try:
            host=requests.utils.urlparse(r['url']).hostname or ''
            ip=socket.gethostbyname(host) if host else 'N/A'
            lines.append(f'Host: {host}\nResolved IP: {ip}')
        except Exception as e: lines.append(f'DNS: {e}')
        lines += [f'Status: {r["status"]}', f'URL: {r["url"]}', f'File: {r["path"]}', f'Bytes: {r["downloaded"]} / {r["total"]}', f'Connections: {r["connections"]}', f'Retries: {r["retry_count"]}', f'Error: {r["error"] or "None"}']
        QMessageBox.information(self,'Download Diagnostics','\n'.join(lines))

    def details(self):
        ids=self.selected_ids();
        if not ids:
            QMessageBox.information(self,'Download Properties','Select a download row first.')
            return
        r=self.storage.get(ids[0]);
        if r:PropertiesDialog(self,r).exec()
    def backup_database(self):
        p,_=QFileDialog.getSaveFileName(self,'Backup download database','idm-downloads-backup.db','SQLite Database (*.db)')
        if not p:return
        try:self.storage.backup(p); QMessageBox.information(self,'Backup complete',f'Database backup saved to:\n{p}')
        except Exception as e:QMessageBox.critical(self,'Backup failed',str(e))
    def export_json(self):
        p,_=QFileDialog.getSaveFileName(self,'Export download history','download-history.json','JSON (*.json)')
        if p:
            try:self.storage.export_json(p); QMessageBox.information(self,'Export complete',f'History exported to:\n{p}')
            except Exception as e:QMessageBox.critical(self,'Export failed',str(e))
    def export_csv(self):
        p,_=QFileDialog.getSaveFileName(self,'Export download history','download-history.csv','CSV (*.csv)')
        if p:
            try:self.storage.export_csv(p); QMessageBox.information(self,'Export complete',f'History exported to:\n{p}')
            except Exception as e:QMessageBox.critical(self,'Export failed',str(e))
    def import_history(self):
        p,_=QFileDialog.getOpenFileName(self,'Import download history','','JSON (*.json)')
        if not p:return
        try:
            n=self.storage.import_json(p); self.refresh_all_rows(); QMessageBox.information(self,'Import complete',f'Imported {n} download record(s).')
        except Exception as e:QMessageBox.critical(self,'Import failed',str(e))
    def check_updates(self,automatic=False):
        if self._update_busy:return
        self._update_busy=True;self._update_auto=automatic
        url=(self.settings.update_url or UPDATE_MANIFEST_URL).strip()
        from .update import UpdateTask
        self._update_task=UpdateTask(url)
        self._update_task.signals.checked.connect(self.update_result)
        self._update_task.signals.failed.connect(self.update_failed)
        self.pool.start(self._update_task)
    def update_result(self,data):
        self._update_busy=False
        remote=str(data.get('version',''))
        from .update import newer
        if newer(remote):
            if self._update_auto and self._notified_version==remote:return
            self._notified_version=remote
            url=data.get('installer_url','')
            existing=getattr(self,'_update_dialog',None)
            if existing and existing.isVisible():
                existing.raise_(); existing.activateWindow(); return
            dialog=QMessageBox(QMessageBox.Information,'Update available',
                f'Internet Download Manager {remote} is available.\nCurrent version: {VERSION}',
                QMessageBox.NoButton, None)
            dialog.setWindowIcon(self.tray.icon())
            download=dialog.addButton('Download update',QMessageBox.AcceptRole)
            dialog.addButton('Later',QMessageBox.RejectRole)
            dialog.setDefaultButton(download)
            def selected(button):
                if button is download:
                    from PySide6.QtGui import QDesktopServices
                    from PySide6.QtCore import QUrl
                    QDesktopServices.openUrl(QUrl(url))
            dialog.buttonClicked.connect(selected)
            self._update_dialog=dialog
            dialog.show(); dialog.raise_(); dialog.activateWindow()
        elif not self._update_auto:QMessageBox.information(self,'No update','You are using the latest version.')
    def update_failed(self,error):
        self._update_busy=False
        if not self._update_auto:QMessageBox.warning(self,'Update check failed',f'Could not check for updates.\n{error}')
    def request_exit(self):
        try: self.browser_bridge.stop()
        except Exception: pass
        QApplication.instance().setProperty('really_quit',True); QApplication.instance().quit()
    def show_settings(self):
        d=SettingsDialog(self,self.settings)
        d.applied.connect(self._settings_applied)
        d.exec()

    def _settings_applied(self):
        from .options_config import load_options, sound_event
        options=load_options()
        self.max_downloads=max(1,min(20,self.settings.max_downloads))
        self.auto_start=self.settings.auto_start
        self.speed_limit_kbps=max(0,self.settings.speed_limit_kbps)
        self.notifications=self.settings.notifications
        self.minimize_to_tray=self.settings.minimize_to_tray
        self.connections=max(1,min(16,self.settings.connections))
        self.statusBar().showMessage('Options saved')
        # Existing progress windows immediately follow the saved visibility preferences.
        for dlg in self.progress_dialogs.values():
            if not options.get('progress_speed',True):
                if dlg.tabs.count()>1: dlg.tabs.setTabVisible(1,False)
            if not options.get('progress_completion',True):
                if dlg.tabs.count()>2: dlg.tabs.setTabVisible(2,False)
            dlg.details.setVisible(bool(options.get('progress_details',True)))
        if options.get('progress_view')=='System tray':
            for dlg in list(self.progress_dialogs.values()): dlg.minimize_to_tray()

    def show_about(self):QMessageBox.about(self,'About',f'Internet Download Manager\nVersion {VERSION}\n\nWindows download manager with HTTP/HTTPS downloads, resume, queues and media support.')
    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized() and self.minimize_to_tray:
            self.tray.show()
            QTimer.singleShot(0,self.hide)
    def closeEvent(self,event):
        if self.minimize_to_tray and self.tray.isVisible() and not QApplication.instance().property('really_quit'):
            event.ignore();self.hide();self.tray.showMessage('Internet Download Manager','Running in the system tray.',QSystemTrayIcon.Information,2500);return
        try: self.browser_bridge.stop()
        except Exception: pass
        self.tray.hide();event.accept()
    @staticmethod
    def sched_text(v):return QDateTime.fromSecsSinceEpoch(int(v)).toString('dd/MM/yyyy HH:mm') if v else 'Immediate'
    @staticmethod
    def size(n):
        n=n or 0;units=['B','KB','MB','GB','TB'];i=0;x=float(n)
        while x>=1024 and i<4:x/=1024;i+=1
        return f'{x:.1f} {units[i]}'
    @staticmethod
    def percent(r):return MainWindow.percent_vals(r['downloaded'],r['total'])
    @staticmethod
    def percent_vals(d,t):return f'{d*100/t:.1f}%' if t else '0.0%'
    @staticmethod
    def speed_text(s):return f'{s/1024:.1f} KB/s' if s<1024*1024 else f'{s/1024/1024:.2f} MB/s'
    @staticmethod
    def eta_text(e):
        if not e:return '--'
        e=int(e);h=e//3600;m=(e%3600)//60;s=e%60;return f'{h:02d}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'
