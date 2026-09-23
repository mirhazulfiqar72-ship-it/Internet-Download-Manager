from PySide6.QtCore import QSettings
from .release import UPDATE_MANIFEST_URL
class AppSettings:
    def __init__(self): self.q=QSettings('OriginalDownloadManager','InternetDownloadManager')
    def _get(self,k,d,typ=int): return self.q.value(k,d,type=typ)
    max_downloads=property(lambda s:max(1,min(20,int(s.q.value('max_downloads',3)))),lambda s,v:s.q.setValue('max_downloads',max(1,min(20,int(v)))))
    auto_start=property(lambda s:s.q.value('auto_start',True,type=bool),lambda s,v:s.q.setValue('auto_start',bool(v)))
    speed_limit_kbps=property(lambda s:int(s.q.value('speed_limit_kbps',0)),lambda s,v:s.q.setValue('speed_limit_kbps',int(v)))
    notifications=property(lambda s:s.q.value('notifications',True,type=bool),lambda s,v:s.q.setValue('notifications',bool(v)))
    connections=property(lambda s:max(1,min(16,int(s.q.value('connections',4)))),lambda s,v:s.q.setValue('connections',max(1,min(16,int(v)))))
    max_retries=property(lambda s:int(s.q.value('max_retries',3)),lambda s,v:s.q.setValue('max_retries',int(v)))
    minimize_to_tray=property(lambda s:s.q.value('minimize_to_tray',True,type=bool),lambda s,v:s.q.setValue('minimize_to_tray',bool(v)))
    update_url=property(lambda s:str(s.q.value('update_url',UPDATE_MANIFEST_URL)),lambda s,v:s.q.setValue('update_url',str(v)))
