import os, sys, tempfile
from pathlib import Path
root=tempfile.mkdtemp(prefix='idm-options-')
os.environ['LOCALAPPDATA']=root; os.environ['XDG_CONFIG_HOME']=root
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from idm.main_window import MainWindow
from idm.options_dialog import SettingsDialog
from idm.options_config import load_options, category_settings, request_kwargs
app=QApplication([])
w=MainWindow(); w.update_timer.stop()
try:
    d=SettingsDialog(w,w.settings)
    assert d.pages.count()==9
    assert [b.text() for b in d.nav]==['General','File types','Save to','Downloads','Connection','Proxy / Socks','Sites Logins','Dial Up / VPN','Sounds']
    d.connections.setValue(8); d.speed.setValue(0); d.show_complete.setChecked(False); d.apply()
    saved=load_options(); assert saved['show_complete'] is False
    assert w.settings.connections==8
    assert category_settings('Video',saved)['folder']
    assert 'headers' not in request_kwargs('https://example.com',saved)
    d.close()
    print('Nine-tab Options dialog, persistence and settings helpers passed')
finally:
    w.browser_bridge.stop(); w.tray.hide(); w.storage.conn.close()
