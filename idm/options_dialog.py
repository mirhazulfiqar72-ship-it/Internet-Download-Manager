"""Compact Options dialog with nine configuration pages."""
import copy, os, threading
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QGridLayout,QFormLayout,QWidget,QStackedWidget,QPushButton,QLabel,QCheckBox,QLineEdit,QComboBox,QSpinBox,QPlainTextEdit,QTableWidget,QTableWidgetItem,QHeaderView,QDialogButtonBox,QFileDialog,QMessageBox,QInputDialog,QAbstractItemView,QFrame,QScrollArea)
from .options_config import load_options,save_options,DEFAULTS,CATEGORIES,category_settings,protect,unprotect,apply_startup,sound_event,dial_connect

STYLE='''QDialog{background:#f2f2f2;} QWidget{font-family:"Segoe UI";font-size:8.5pt;color:#111;}
QPushButton{min-height:22px;min-width:60px;padding:1px 8px;border:1px solid #9a9a9a;border-radius:2px;background:#f2f2f2;}
QPushButton:hover{border-color:#5f8fb8;background:#eef6ff;} QPushButton:pressed{background:#dce9f5;}
QPushButton:disabled{color:#8d8d8d;background:#ededed;} QPushButton:default{border:1px solid #2678b8;}
QPushButton[pageButton="true"]{min-width:0;min-height:18px;padding:0 4px;border:1px solid #8f8f8f;border-radius:0;background:#e7e7e7;font-weight:400;}
QPushButton[pageButton="true"]:hover{background:#f1f1f1;} QPushButton[pageButton="true"]:checked{background:white;border-bottom-color:white;font-weight:600;color:#111;}
QStackedWidget#optionsPages{background:white;border:1px solid #8f8f8f;}
QLineEdit,QSpinBox,QComboBox,QPlainTextEdit,QTableWidget{background:white;border:1px solid #9a9a9a;selection-background-color:#cfe6ff;selection-color:#111;}
QLineEdit,QSpinBox,QComboBox{min-height:21px;} QTableWidget{gridline-color:#dedede;} QLabel[heading="true"]{font-size:9pt;font-weight:700;color:#111;}
QFrame#browserCapture{background:#f7f7f7;border:1px solid #c8c8c8;} QScrollArea#browserList{background:white;border:1px solid #aaa;}
QScrollArea#browserList QWidget{background:white;} QCheckBox{spacing:5px;} QDialogButtonBox QPushButton{min-width:68px;}
'''

def buttons(dialog,layout):
    box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);box.accepted.connect(dialog.accept);box.rejected.connect(dialog.reject);layout.addWidget(box);return box

def editor(parent,title):
    d=QDialog(parent);d.setWindowTitle(title);d.setStyleSheet(STYLE);d.resize(430,220);layout=QVBoxLayout(d);form=QFormLayout();form.setSpacing(8);layout.addLayout(form);return d,layout,form

def check(text,value):
    w=QCheckBox(text);w.setChecked(bool(value));return w

def spin(value,lo,hi):
    w=QSpinBox();w.setRange(lo,hi);w.setValue(int(value));return w

def combo(values,value):
    w=QComboBox();w.addItems(values);w.setCurrentText(str(value));return w

class SettingsDialog(QDialog):
    applied=Signal()
    def __init__(self,parent,settings):
        super().__init__(parent);self.settings=settings;self.data=load_options();self.setWindowTitle('Internet Download Manager Configuration');self.setStyleSheet(STYLE)
        self.resize(442,500);self.setMinimumSize(442,500)
        root=QVBoxLayout(self);root.setContentsMargins(7,6,7,7);root.setSpacing(5)
        nav=QGridLayout();nav.setContentsMargins(0,0,0,0);nav.setHorizontalSpacing(0);nav.setVerticalSpacing(0);root.addLayout(nav)
        self.pages=QStackedWidget();self.pages.setObjectName('optionsPages');root.addWidget(self.pages,1);self.nav=[]
        names=['General','File types','Save to','Downloads','Connection','Proxy / Socks','Sites Logins','Dial Up / VPN','Sounds']
        builders=[self.general,self.filetypes,self.saveto,self.downloads,self.connection,self.proxy,self.logins,self.dialup,self.sounds]
        for i,(name,build) in enumerate(zip(names,builders)):
            b=QPushButton(name);b.setProperty('pageButton',True);b.setCheckable(True);b.clicked.connect(lambda checked=False,n=i:self.select_page(n));self.nav.append(b)
            page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(8,8,8,6);layout.setSpacing(5);build(layout);self.pages.addWidget(page)
        for col,index in enumerate((5,6,7,8)):nav.addWidget(self.nav[index],0,col*5,1,5)
        for col,index in enumerate((0,1,2,3,4)):nav.addWidget(self.nav[index],1,col*4,1,4)
        box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel|QDialogButtonBox.Apply|QDialogButtonBox.Help)
        box.accepted.connect(self.accept);box.rejected.connect(self.reject);box.button(QDialogButtonBox.Apply).clicked.connect(self.apply)
        box.helpRequested.connect(lambda:QMessageBox.information(self,'Options help','Select a tab to configure downloads. OK saves and closes; Apply saves immediately; Cancel discards changes since the last Apply.\n\nBrowser settings take effect within a few seconds with the updated extension. Connection settings apply to new or resumed downloads. Dial-Up uses connections already saved in Windows.'))
        root.addWidget(box);self.select_page(0)
    def select_page(self,n):
        self.pages.setCurrentIndex(n)
        for i,b in enumerate(self.nav):b.setChecked(i==n)
    def heading(self,lay,text):
        w=QLabel(text);w.setProperty('heading',True);lay.addWidget(w)
    def row(self,lay,label,widget):
        f=QFormLayout();f.setContentsMargins(0,0,0,0);f.addRow(label,widget);lay.addLayout(f)
    def action(self,lay,text,callback,button_text='Edit…'):
        row=QHBoxLayout();row.setContentsMargins(0,0,0,0);row.setSpacing(6);label=QLabel(text);label.setWordWrap(True);row.addWidget(label,1);b=QPushButton(button_text);b.clicked.connect(callback);row.addWidget(b);lay.addLayout(row)
    def boolean_editor(self,title,label,control):
        d,layout,form=editor(self,title);d.resize(390,130);enabled=check(label,control.isChecked());form.addRow(enabled);buttons(d,layout)
        if d.exec()==QDialog.Accepted:control.setChecked(enabled.isChecked())
    def general(self,lay):
        self.heading(lay,'Browser/System Integration')
        self.startup=check('Launch Internet Download Manager on startup',self.data['startup']);lay.addWidget(self.startup)
        self.monitor=check('Run module for monitoring in IE-based browsers (AOL, MSN, Avant, etc)',self.data['integration']);lay.addWidget(self.monitor)
        self.clipboard=check('Automatically start downloading of URLs placed to clipboard',self.data['clipboard']);lay.addWidget(self.clipboard)
        self.integration=check('Use advanced browser integration',self.data['integration']);lay.addWidget(self.integration)
        self.monitor.toggled.connect(self.integration.setChecked);self.integration.toggled.connect(self.monitor.setChecked)
        self.tray=check('Minimize main window to the system tray',self.settings.minimize_to_tray);lay.addWidget(self.tray)
        self.notify=check('Show desktop notifications',self.settings.notifications);lay.addWidget(self.notify)

        frame=QFrame();frame.setObjectName('browserCapture');frame_layout=QVBoxLayout(frame);frame_layout.setContentsMargins(7,5,7,6);frame_layout.setSpacing(4)
        frame_layout.addWidget(QLabel('Capture downloads from the following browsers:'))
        scroll=QScrollArea();scroll.setObjectName('browserList');scroll.setWidgetResizable(True);scroll.setFixedHeight(112)
        browser_page=QWidget();browser_layout=QVBoxLayout(browser_page);browser_layout.setContentsMargins(5,3,5,3);browser_layout.setSpacing(1);self.browser_checks={}
        rows=[(None,'Apple Safari'),('Chrome','Google Chrome'),(None,'Internet Explorer'),('Edge','Microsoft Edge'),(None,'Mozilla'),(None,'Mozilla Firefox'),('Opera','Opera'),(None,'Opera GX'),('Brave','Brave')]
        for key,label in rows:
            if key:
                w=check(label,key in self.data['browsers']);self.browser_checks[key]=w
            else:
                w=check(label,True);w.setEnabled(False)
            browser_layout.addWidget(w)
        browser_layout.addStretch();scroll.setWidget(browser_page);frame_layout.addWidget(scroll)
        add_row=QHBoxLayout();add_row.addStretch();add_browser=QPushButton('Add browser…');add_browser.setEnabled(False);add_browser.setToolTip('Supported Chromium browsers are detected through the installed extension.');add_row.addWidget(add_browser);frame_layout.addLayout(add_row);lay.addWidget(frame)

        self.action(lay,'Customize keys to prevent or force downloading with IDM',self.keys_editor,'Keys…')
        self.context_menu=check('',self.data['context_menu'])
        self.video_panel=check('',self.data['video_panel'])
        self.action(lay,'Customize IDM menu items in context menu of browsers',lambda:self.boolean_editor('Browser context menu','Show download commands in browser context menus',self.context_menu))
        self.action(lay,'Customize IDM Download panels in browsers',lambda:self.boolean_editor('Download panels','Show “Download this video” panel',self.video_panel))
        lay.addStretch()
    def filetypes(self,lay):
        self.heading(lay,'Downloaded file types')
        lay.addWidget(QLabel('Automatically capture these file extensions (space separated; * = all):'))
        self.file_types=QPlainTextEdit(self.data['file_types']);self.file_types.setMaximumHeight(72);lay.addWidget(self.file_types)
        reset=QPushButton('Default');reset.clicked.connect(lambda:self.file_types.setPlainText(DEFAULTS['file_types']));row=QHBoxLayout();row.addStretch();row.addWidget(reset);lay.addLayout(row)
        lay.addWidget(QLabel('Do not automatically capture downloads from these sites:'))
        self.excluded_sites=QPlainTextEdit(self.data['excluded_sites']);self.excluded_sites.setMaximumHeight(70);lay.addWidget(self.excluded_sites)
        lay.addWidget(QLabel('Space separated; wildcards supported, e.g. *.example.com'))
        lay.addWidget(QLabel('Excluded download addresses (one URL pattern per line):'))
        self.excluded_urls=QPlainTextEdit(self.data['excluded_urls']);self.excluded_urls.setMaximumHeight(95);lay.addWidget(self.excluded_urls);lay.addStretch()
    def saveto(self,lay):
        self.heading(lay,'Categories, file types and folders')
        self.category=QComboBox();self.category.addItems(list(dict.fromkeys([*CATEGORIES,*self.data['categories']])));self.row(lay,'Category:',self.category)
        self.category_types=QLineEdit();self.row(lay,'File extensions:',self.category_types)
        self.category_path=QLineEdit();self.browse_row(lay,'Default download folder:',self.category_path,True)
        self.category_remember=check('Remember the last selected folder for this category',False);lay.addWidget(self.category_remember)
        self._category='';self.category.currentTextChanged.connect(self.switch_category);self.switch_category(self.category.currentText())
        b=QPushButton('New category…');b.clicked.connect(self.new_category);lay.addWidget(b,0,Qt.AlignRight)
        self.temp_dir=QLineEdit(self.data['temp_dir']);self.temp_dir.setPlaceholderText('Default: beside the destination file');self.browse_row(lay,'Temporary download folder:',self.temp_dir,True)
        note=QLabel('New downloads use these folders. Existing downloads keep their saved locations.');note.setWordWrap(True);lay.addWidget(note);lay.addStretch()
    def store_category(self):
        if self._category:self.data['categories'][self._category]={'types':self.category_types.text().strip(),'folder':self.category_path.text().strip(),'remember':self.category_remember.isChecked()}
    def switch_category(self,name):
        self.store_category();self._category=name;data=category_settings(name,self.data);self.category_types.setText(data['types']);self.category_path.setText(data['folder']);self.category_remember.setChecked(data['remember'])
    def new_category(self):
        name,ok=QInputDialog.getText(self,'New category','Category name:')
        name=name.strip()
        if ok and name and self.category.findText(name)<0:self.category.addItem(name);self.category.setCurrentText(name)
    def browse_row(self,lay,label,edit,folder=False,filter='All files (*)'):
        lay.addWidget(QLabel(label));row=QHBoxLayout();row.addWidget(edit,1);b=QPushButton('Browse…');row.addWidget(b);lay.addLayout(row)
        def browse():
            path=QFileDialog.getExistingDirectory(self,label,edit.text()) if folder else QFileDialog.getOpenFileName(self,label,edit.text(),filter)[0]
            if path:edit.setText(path)
        b.clicked.connect(browse)
    def downloads(self,lay):
        self.heading(lay,'Default download settings')
        self.action(lay,'Customize “Download progress” dialog',self.progress_editor)
        self.show_start=check('Show start download dialog for browser downloads',self.data['show_start']);lay.addWidget(self.show_start)
        self.show_complete=check('Show download complete dialog',self.data['show_complete']);lay.addWidget(self.show_complete)
        self.auto=check('Start downloads automatically after adding',self.settings.auto_start);lay.addWidget(self.auto)
        self.maxdl=spin(self.settings.max_downloads,1,20);self.row(lay,'Maximum simultaneous downloads:',self.maxdl)
        self.retries=spin(self.settings.max_retries,0,10);self.row(lay,'Automatic retries:',self.retries)
        self.duplicate=QComboBox()
        for label,value in [('Ask every time','ask'),('Numbered file name','number'),('Overwrite existing file','overwrite'),('Show complete / resume','resume')]:self.duplicate.addItem(label,value)
        self.duplicate.setCurrentIndex(max(0,self.duplicate.findData(self.settings.q.value('duplicate_action','ask'))));self.row(lay,'Duplicate download links:',self.duplicate)
        self.user_agent=QLineEdit(self.data['user_agent']);self.row(lay,'User-Agent:',self.user_agent)
        self.action(lay,'Virus checking after download',self.scanner_editor);lay.addStretch()
    def connection(self,lay):
        self.heading(lay,'Connection settings')
        self.connection_type=combo(['High speed / Ethernet / Wi-Fi','Mobile / metered','Custom'],self.data['connection_type']);self.row(lay,'Connection profile:',self.connection_type)
        self.connections=spin(self.settings.connections,1,16);self.row(lay,'Default maximum connections:',self.connections)
        self.speed=spin(self.settings.speed_limit_kbps,0,1024000);self.speed.setSuffix(' KB/s');self.row(lay,'Speed limit (0 = unlimited):',self.speed)
        lay.addWidget(QLabel('Per-server connection limits:'))
        self.rules=self.table(['Server / URL pattern','Connections']);lay.addWidget(self.rules)
        self.table_buttons(lay,self.rule_editor,lambda:self.remove_row(self.rules,self.data['connection_rules']))
        self.refresh_rules();lay.addStretch()
    def table(self,headers):
        w=QTableWidget(0,len(headers));w.setHorizontalHeaderLabels(headers);w.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);w.verticalHeader().hide();w.setSelectionBehavior(QAbstractItemView.SelectRows);w.setSelectionMode(QAbstractItemView.SingleSelection);w.setEditTriggers(QAbstractItemView.NoEditTriggers);return w
    def table_buttons(self,lay,edit,remove):
        row=QHBoxLayout()
        for text,callback in [('New',lambda:edit(False)),('Edit',lambda:edit(True)),('Remove',remove)]:
            b=QPushButton(text);b.clicked.connect(callback);row.addWidget(b)
        row.addStretch();lay.addLayout(row)
    def fill_table(self,w,rows):
        w.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate(row):w.setItem(i,j,QTableWidgetItem(str(value)))
    def refresh_rules(self):self.fill_table(self.rules,[(v['host'],v['count']) for v in self.data['connection_rules']])
    def rule_editor(self,editing):
        index=self.rules.currentRow() if editing else -1
        if editing and index<0:return
        old=self.data['connection_rules'][index] if index>=0 else {'host':'','count':2}
        d,lay,f=editor(self,'Server connection limit');host=QLineEdit(old['host']);count=spin(old['count'],1,16);f.addRow('Server / URL pattern:',host);f.addRow('Maximum connections:',count);buttons(d,lay)
        if d.exec()==QDialog.Accepted and host.text().strip():
            item={'host':host.text().strip(),'count':count.value()}
            if index<0:self.data['connection_rules'].append(item)
            else:self.data['connection_rules'][index]=item
            self.refresh_rules()
    def remove_row(self,w,items):
        n=w.currentRow()
        if n>=0:items.pop(n);w.removeRow(n)
    def proxy(self,lay):
        self.heading(lay,'Proxy / SOCKS configuration')
        self.proxy_mode=combo(['None','System','Manual'],self.data['proxy_mode']);self.row(lay,'Use proxy:',self.proxy_mode)
        self.proxy_scheme=combo(['http','socks5h'],self.data['proxy_scheme']);self.row(lay,'Proxy type:',self.proxy_scheme)
        self.proxy_host=QLineEdit(self.data['proxy_host']);self.row(lay,'Server address:',self.proxy_host)
        self.proxy_port=spin(self.data['proxy_port'],1,65535);self.row(lay,'Port:',self.proxy_port)
        self.proxy_user=QLineEdit(self.data['proxy_user']);self.row(lay,'Username:',self.proxy_user)
        self.proxy_password=QLineEdit();self.proxy_password.setEchoMode(QLineEdit.Password);self.proxy_password.setPlaceholderText('Stored password unchanged' if self.data['proxy_secret'] else 'Optional');self.row(lay,'Password:',self.proxy_password)
        self.clear_proxy=check('Clear stored proxy password',False);lay.addWidget(self.clear_proxy)
        self.proxy_exceptions=QLineEdit(self.data['proxy_exceptions']);self.row(lay,'Do not use proxy for:',self.proxy_exceptions)
        note=QLabel('System uses the configured Windows HTTP/HTTPS proxy. Automatic PAC scripts are not supported.');note.setWordWrap(True);lay.addWidget(note)
        self.proxy_mode.currentTextChanged.connect(lambda mode:[w.setEnabled(mode=='Manual') for w in (self.proxy_scheme,self.proxy_host,self.proxy_port,self.proxy_user,self.proxy_password,self.clear_proxy)])
        self.proxy_mode.currentTextChanged.emit(self.proxy_mode.currentText());lay.addStretch()
    def logins(self,lay):
        self.heading(lay,'Usernames and passwords for sites')
        self.login_table=self.table(['Site / path','Username','Password']);lay.addWidget(self.login_table)
        self.table_buttons(lay,self.login_editor,lambda:self.remove_row(self.login_table,self.data['logins']));self.refresh_logins()
        note=QLabel('Credentials apply only to the exact site and path. Saved passwords use Windows user encryption.');note.setWordWrap(True);lay.addWidget(note)
    def refresh_logins(self):self.fill_table(self.login_table,[(v['url'],v['user'],'••••••' if v['secret'] else '') for v in self.data['logins']])
    def login_editor(self,editing):
        index=self.login_table.currentRow() if editing else -1
        if editing and index<0:return
        old=self.data['logins'][index] if index>=0 else {'url':'https://','user':'','secret':''}
        d,lay,f=editor(self,'Site login');url=QLineEdit(old['url']);user=QLineEdit(old['user']);password=QLineEdit();password.setEchoMode(QLineEdit.Password);password.setPlaceholderText('Leave blank to keep stored password' if old['secret'] else '')
        f.addRow('Site / path:',url);f.addRow('Username:',user);f.addRow('Password:',password);buttons(d,lay)
        if d.exec()!=QDialog.Accepted:return
        from urllib.parse import urlsplit
        parsed=urlsplit(url.text())
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:QMessageBox.warning(self,'Site login','Enter an HTTP/HTTPS site URL without credentials.');return
        try:item={'url':url.text().strip(),'user':user.text(),'secret':protect(password.text()) if password.text() else old['secret']}
        except Exception as exc:QMessageBox.warning(self,'Password storage',str(exc));return
        if index<0:self.data['logins'].append(item)
        else:self.data['logins'][index]=item
        self.refresh_logins()
    def dialup(self,lay):
        self.heading(lay,'Windows Dial-Up / VPN')
        self.dial_enabled=check('Connect using a saved Windows connection before downloading',self.data['dial_enabled']);lay.addWidget(self.dial_enabled)
        self.dial_name=QComboBox();self.dial_name.setEditable(True)
        import re
        names=[]
        for root in (os.environ.get('APPDATA',''),os.environ.get('PROGRAMDATA','')):
            path=Path(root)/'Microsoft/Network/Connections/Pbk/rasphone.pbk'
            if path.is_file():
                raw=path.read_bytes();text=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8',errors='replace');names.extend(re.findall(r'^\[([^]]+)\]',text,re.M))
        self.dial_name.addItems(sorted(set(names)));self.dial_name.setCurrentText(self.data['dial_name']);self.row(lay,'Saved connection:',self.dial_name)
        self.dial_retries=spin(self.data['dial_retries'],0,10);self.row(lay,'Redial attempts (0 = no retries):',self.dial_retries)
        self.dial_delay=spin(self.data['dial_delay'],1,60);self.dial_delay.setSuffix(' seconds');self.row(lay,'Time between attempts:',self.dial_delay)
        note=QLabel('Uses credentials saved in Windows. Create or edit your connection in Windows settings.');note.setWordWrap(True);lay.addWidget(note)
        row=QHBoxLayout();self.dial_buttons=[]
        for title,disconnect in [('Connect',False),('Disconnect',True)]:
            b=QPushButton(title);b.clicked.connect(lambda checked=False,x=disconnect:self.run_dial(x));row.addWidget(b);self.dial_buttons.append(b)
        lay.addLayout(row);settings=QPushButton('Windows connection settings…');settings.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('ms-settings:network-vpn')));lay.addWidget(settings,0,Qt.AlignLeft)
        self.dial_status=QLabel('');self.dial_status.setWordWrap(True);lay.addWidget(self.dial_status);lay.addStretch()
    def run_dial(self,disconnect):
        data=dict(self.data,dial_name=self.dial_name.currentText());result={}
        for b in self.dial_buttons:b.setEnabled(False)
        def run():
            try:result['message']=dial_connect(data,disconnect)
            except Exception as exc:result['message']=str(exc)
        threading.Thread(target=run,daemon=True).start();timer=QTimer(self)
        def poll():
            if 'message' in result:
                timer.stop();timer.deleteLater();self.dial_status.setText(result['message'])
                for b in self.dial_buttons:b.setEnabled(True)
        timer.timeout.connect(poll);timer.start(200)
    def sounds(self,lay):
        self.heading(lay,'Sounds for download events')
        self.sound_table=self.table(['Event','Sound file']);self.events=['Download complete','Download failed','Queue started','Queue stopped'];self.sound_table.setRowCount(len(self.events))
        for i,name in enumerate(self.events):
            item=self.data['sounds'].get(name,{});label=QTableWidgetItem(name);label.setFlags(label.flags()|Qt.ItemIsUserCheckable);label.setCheckState(Qt.Checked if item.get('enabled') else Qt.Unchecked);self.sound_table.setItem(i,0,label);self.sound_table.setItem(i,1,QTableWidgetItem(item.get('path','')))
        lay.addWidget(self.sound_table);row=QHBoxLayout();browse=QPushButton('Browse…');play=QPushButton('Play');row.addWidget(browse);row.addWidget(play);row.addStretch();lay.addLayout(row)
        browse.clicked.connect(self.browse_sound);play.clicked.connect(self.play_sound);lay.addWidget(QLabel('Choose a WAV sound file; Windows / Media contains standard sounds.'))
    def browse_sound(self):
        n=self.sound_table.currentRow()
        if n<0:return
        path=QFileDialog.getOpenFileName(self,'Sound file','','Wave audio (*.wav)')[0]
        if path:self.sound_table.item(n,1).setText(path);self.sound_table.item(n,0).setCheckState(Qt.Checked)
    def play_sound(self):
        n=self.sound_table.currentRow()
        if n>=0:sound_event(self.events[n],{'sounds':{self.events[n]:{'enabled':True,'path':self.sound_table.item(n,1).text()}}})
    def keys_editor(self):
        d,lay,f=editor(self,'Using special keys');groups={}
        for key,title in [('prevent_keys','Prevent automatic capture'),('force_keys','Force capture of clicked download links')]:
            row=QHBoxLayout();groups[key]={}
            for name in ['Alt','Shift','Ctrl']:
                w=check(name,name in self.data[key]);groups[key][name]=w;row.addWidget(w)
            f.addRow(title+':',row)
        note=QLabel('Hold all selected keys while clicking a link. Browser-reserved shortcuts may take priority.');note.setWordWrap(True);lay.addWidget(note);buttons(d,lay)
        if d.exec()==QDialog.Accepted:
            for key,widgets in groups.items():self.data[key]=[name for name,w in widgets.items() if w.isChecked()]
    def progress_editor(self):
        d,lay,f=editor(self,'Customize download progress dialog');view=combo(['Normal','Minimized','Hidden','System tray'],self.data['progress_view']);f.addRow('Start view:',view)
        fields={}
        for key,text in [('progress_speed','Show Speed Limiter tab'),('progress_completion','Show Options on completion tab'),('progress_details','Show details section')]:
            fields[key]=check(text,self.data[key]);lay.addWidget(fields[key])
        buttons(d,lay)
        if d.exec()==QDialog.Accepted:
            self.data['progress_view']=view.currentText()
            for key,w in fields.items():self.data[key]=w.isChecked()
    def scanner_editor(self):
        d,lay,f=editor(self,'Virus checking');program=QLineEdit(self.data['scanner']);self.browse_row(lay,'Scanner executable:',program,filter='Programs (*.exe);;All files (*)');args=QLineEdit(self.data['scanner_args']);f.addRow('Command parameters:',args)
        note=QLabel('Use [File] for the downloaded file path. Leave the executable blank to disable scanning.');note.setWordWrap(True);lay.addWidget(note);buttons(d,lay)
        if d.exec()==QDialog.Accepted:self.data['scanner']=program.text().strip();self.data['scanner_args']=args.text()
    def apply(self):
        self.store_category();data=copy.deepcopy(self.data)
        for key in ('startup','clipboard','integration','context_menu','video_panel','show_start','show_complete','dial_enabled'):data[key]=getattr(self,key).isChecked()
        for key in ('user_agent','proxy_host','proxy_user','proxy_exceptions','temp_dir'):data[key]=getattr(self,key).text().strip()
        for key in ('file_types','excluded_sites','excluded_urls'):data[key]=getattr(self,key).toPlainText().strip()
        for key in ('proxy_mode','proxy_scheme','connection_type','dial_name'):data[key]=getattr(self,key).currentText()
        for key in ('proxy_port','dial_retries','dial_delay'):data[key]=getattr(self,key).value()
        data['browsers']=[n for n,w in self.browser_checks.items() if w.isChecked()]
        data['sounds']={n:{'enabled':self.sound_table.item(i,0).checkState()==Qt.Checked,'path':self.sound_table.item(i,1).text()} for i,n in enumerate(self.events)}
        try:
            if data['proxy_mode']=='Manual' and (not data['proxy_host'] or any(c in data['proxy_host'] for c in '/@ \t\n')):raise ValueError('Enter a proxy hostname or IP address, without a URL or spaces.')
            for item in data['categories'].values():
                if not item['folder'] or not Path(item['folder']).expanduser().is_absolute():raise ValueError('Choose an absolute download folder for each category.')
            if data['temp_dir'] and not Path(data['temp_dir']).expanduser().is_absolute():raise ValueError('Choose an absolute temporary folder.')
            if data['scanner'] and not Path(data['scanner']).is_file():raise ValueError('The selected scanner executable does not exist.')
            if self.clear_proxy.isChecked():data['proxy_secret']=''
            if self.proxy_password.text():data['proxy_secret']=protect(self.proxy_password.text())
            if data['startup']!=load_options()['startup']:apply_startup(data['startup'])
            save_options(data)
        except Exception as exc:QMessageBox.warning(self,'Options',str(exc));return False
        self.data=data;self.proxy_password.clear();self.clear_proxy.setChecked(False)
        for name,value in [('max_downloads',self.maxdl.value()),('auto_start',self.auto.isChecked()),('speed_limit_kbps',self.speed.value()),('connections',self.connections.value()),('max_retries',self.retries.value()),('notifications',self.notify.isChecked()),('minimize_to_tray',self.tray.isChecked())]:setattr(self.settings,name,value)
        self.settings.q.setValue('duplicate_action',self.duplicate.currentData());self.settings.q.sync();self.applied.emit();return True
    def accept(self):
        if self.apply():super().accept()
