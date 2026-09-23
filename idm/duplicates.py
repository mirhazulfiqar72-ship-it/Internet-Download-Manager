"""Duplicate URL choices and safe output-name reservation."""
import os
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QLabel,QRadioButton,QPushButton,QCheckBox
from .media_selection import unpack_selector


def url_key(url):
    p=urlsplit(url)
    host=(p.hostname or '').lower()
    if host=='youtu.be': return 'youtube:'+p.path.strip('/')
    if host=='youtube.com' or host.endswith('.youtube.com'):
        video=parse_qs(p.query).get('v',[''])[0]
        if not video and p.path.startswith(('/shorts/','/embed/')): video=p.path.split('/')[2]
        if video: return 'youtube:'+video
    return url.split('#',1)[0]


def same_selection(first,second):
    if not first or not second: return not first and not second
    a=unpack_selector(first); b=unpack_selector(second)
    if a and b: return (a['quality'],a['kind'])==(b['quality'],b['kind'])
    return first==second


def path_key(path):
    return os.path.normcase(os.path.abspath(str(path)))


def numbered_path(path,rows,force=False):
    path=Path(path); used={path_key(r['path']) for r in rows}
    candidate=path; n=1
    while force or candidate.exists() or path_key(candidate) in used:
        candidate=path.with_name(f'{path.stem} ({n}){path.suffix}');n+=1;force=False
    return candidate


class DuplicateDownloadDialog(QDialog):
    def __init__(self,parent,url,active=False):
        super().__init__(parent)
        self.setWindowTitle('Duplicate download link')
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setFixedSize(570,275)
        root=QVBoxLayout(self);root.setContentsMargins(11,9,11,9);root.setSpacing(7)
        address=QLineEdit(url);address.setReadOnly(True);address.selectAll();address.setFixedHeight(23);root.addWidget(address)
        text=QLabel('This file already exists in your download list. You may choose one of the following options, or press Cancel to skip the download of this file.');text.setWordWrap(True);text.setMaximumHeight(36);root.addWidget(text)
        self.choices={}
        labels=[('number','Add the duplicate with a numbered file name'),('overwrite','Add the duplicate and overwrite the existing file'),('resume','If existing file is complete, show download complete dialog; otherwise resume it.')]
        for action,label in labels:
            radio=QRadioButton(label);radio.setFixedHeight(22);radio.setStyleSheet('font-size:11px');root.addWidget(radio);self.choices[action]=radio
        self.choices['resume'].setChecked(True)
        self.choices['overwrite'].setEnabled(not active)
        if active:self.choices['overwrite'].setToolTip('Pause or stop the existing download before overwriting it.')
        buttons=QHBoxLayout();buttons.addStretch();ok=QPushButton('OK');cancel=QPushButton('Cancel')
        for button in (ok,cancel):button.setFixedSize(88,25);buttons.addWidget(button)
        buttons.setSpacing(18);buttons.addStretch();root.addLayout(buttons)
        ok.setDefault(True);ok.clicked.connect(self.accept);cancel.clicked.connect(self.reject)
        self.remember=QCheckBox("Remember my selection and don't show this dialog again.");self.remember.setFixedHeight(22);root.addWidget(self.remember)
        note=QLabel('You may change this in Download Settings later.');note.setStyleSheet('color:#6b7280;font-size:11px');root.addWidget(note)
    def choice(self):
        return next(k for k,v in self.choices.items() if v.isChecked())
