import os, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['LOCALAPPDATA']=tempfile.mkdtemp(prefix='idm-smoke-')
from PySide6.QtWidgets import QApplication, QMenu
from PySide6.QtCore import QPoint
import idm.main_window as module
from idm.update import newer
app=QApplication([])
w=module.MainWindow()
try:
    path=Path(os.environ['LOCALAPPDATA'])/'example.txt'
    path.write_text('test')
    rid=w.storage.add('https://example.com/file',path.name,str(path),'Completed',total=100,downloaded=100,queue_name='')
    w.load_rows();w.table.selectRow(w.row_by_id(rid))
    class CaptureMenu(QMenu):
        def exec(self,*args):
            actions={a.text():a for a in self.actions() if not a.isSeparator()}
            assert list(actions)==['Open','Open with...','Open folder','Move/Rename (Ctrl-M)','Redownload','Resume Download','Stop Download','Refresh download address','Remove','Add to queue','Delete from queue','On double click','Properties']
            assert actions['Open'].isEnabled()
            assert not actions['Resume Download'].isEnabled()
            assert not actions['Stop Download'].isEnabled()
            assert not actions['Delete from queue'].isEnabled()
    module.QMenu=CaptureMenu
    w.context_menu(QPoint(-1,-1))
    w.storage.update(rid,status='Downloading',downloaded=50,total=100)
    dlg=module.DownloadProgressDialog(w,rid)
    dlg.update_live(50,100,1000,1)
    before=dlg.done_lbl.text();dlg.sync()
    assert dlg.done_lbl.text()==before and '50.00%' in before
    dlg.sync_timer.stop();dlg.close()
    assert newer('1.5.3','1.5.2')
    assert not newer('1.5.3','1.5.3')
    assert not newer('1.5.2','1.5.3')
    print('Context menu states and version comparison passed')
finally:
    w.browser_bridge.stop();w.tray.hide();w.storage.conn.close()
