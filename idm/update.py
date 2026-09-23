import json, urllib.request
from PySide6.QtCore import QObject, Signal, QRunnable
from .release import VERSION

class UpdateSignals(QObject):
    checked = Signal(object)
    failed = Signal(str)

class UpdateTask(QRunnable):
    def __init__(self, manifest_url, timeout=8):
        super().__init__(); self.url=manifest_url; self.timeout=timeout; self.signals=UpdateSignals()
    def run(self):
        try:
            req=urllib.request.Request(self.url, headers={'User-Agent':'OriginalDownloadManager/1.0'})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data=json.loads(r.read().decode('utf-8'))
            self.signals.checked.emit(data)
        except Exception as e:
            self.signals.failed.emit(str(e))

def newer(remote, current=VERSION):
    def v(s):
        try:return tuple(int(x) for x in str(s).split('.')[:3])
        except:return (0,0,0)
    return v(remote)>v(current)
