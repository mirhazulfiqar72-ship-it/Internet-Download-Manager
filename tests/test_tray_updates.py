import os, sys, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['LOCALAPPDATA']=tempfile.mkdtemp(prefix='idm-tray-')
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon
from idm.main_window import MainWindow, DownloadProgressDialog
from idm.release import VERSION
app=QApplication([])
w=MainWindow()
w.update_timer.stop()
try:
    expected=QIcon(str(Path(__file__).resolve().parents[1]/'assets/app_icon.png'))
    assert w.tray.icon().pixmap(32,32).toImage()==expected.pixmap(32,32).toImage()
    rid=w.storage.add('https://example.com/video','video.mp4',str(Path(os.environ['LOCALAPPDATA'])/'video.mp4'),'Paused')
    d=DownloadProgressDialog(w,rid);w.progress_dialogs[rid]=d
    d.show();d.minimize_to_tray()
    assert not d.isVisible() and d.download_tray.isVisible()
    w.hide();w.restore_from_tray()
    assert w.isVisible() and not d.isVisible()
    d.restore_progress()
    assert d.isVisible() and not d.download_tray.isVisible()
    d.minimize_to_tray();w.close_progress_dialog(rid)
    assert not d.download_tray.isVisible()
    w.hide();w._update_auto=True;w._update_busy=True
    with patch.object(QMessageBox,'information',side_effect=AssertionError('Automatic check must be silent')), patch.object(QMessageBox,'warning',side_effect=AssertionError('Automatic failure must be silent')):
        w.update_result({'version':VERSION})
        assert not w._update_busy and not getattr(w,'_update_dialog',None)
        w.update_failed('offline')
    url='https://example.com/setup.exe'
    w.update_result({'version':'99.0.0','installer_url':url})
    dialog=w._update_dialog
    assert dialog.isVisible() and not w.isVisible()
    w.update_result({'version':'99.0.0','installer_url':url})
    assert w._update_dialog is dialog
    with patch('PySide6.QtGui.QDesktopServices.openUrl') as opened:
        next(b for b in dialog.buttons() if b.text()=='Download update').click()
        assert opened.call_args[0][0].toString()==url
    dialog.close()
    print('Main/download tray lifecycle and silent automatic update checks passed')
finally:
    w.browser_bridge.stop();w.tray.hide();w.storage.conn.close()
