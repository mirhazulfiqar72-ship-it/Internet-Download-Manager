import os, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['LOCALAPPDATA']=tempfile.mkdtemp(prefix='idm-smoke-')
from PySide6.QtWidgets import QApplication, QMenu, QDialog
from PySide6.QtCore import QPoint, Qt
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

    # Download File Info must expose native close/minimize/maximize controls,
    # while fixed size keeps maximize non-functional and minimize available.
    info=module.AddDialog(w,'https://example.com/new-file.bin')
    flags=info.windowFlags()
    assert flags & Qt.WindowMinimizeButtonHint
    assert flags & Qt.WindowMaximizeButtonHint
    assert flags & Qt.WindowCloseButtonHint
    assert info.minimumSize()==info.maximumSize()
    info.close()

    # A stale/deleted record that is not in the downloader table must not
    # trigger the duplicate dialog.  A current table row must still do so.
    stale_path=Path(os.environ['LOCALAPPDATA'])/'stale.bin'
    stale_id=w.storage.add('https://example.com/stale',stale_path.name,str(stale_path),'Completed')
    w.settings.q.setValue('duplicate_action','ask')
    original_show=w._show_browser_dialog
    try:
        w._show_browser_dialog=lambda dialog: (_ for _ in ()).throw(AssertionError('stale record opened duplicate dialog'))
        assert w._duplicate_target('https://example.com/stale',stale_path)==stale_path
    finally:
        w._show_browser_dialog=original_show
    w.insert_row(w.storage.get(stale_id))
    calls=[]
    w._show_browser_dialog=lambda dialog:(calls.append(dialog),QDialog.Rejected)[1]
    assert w._duplicate_target('https://example.com/stale',stale_path) is None
    assert len(calls)==1
    w._show_browser_dialog=original_show
    w.storage.update(stale_id,status='Replaced');w.update_row(stale_id,status='Replaced')
    calls=[]
    w._show_browser_dialog=lambda dialog:(calls.append(dialog),QDialog.Rejected)[1]
    assert w._duplicate_target('https://example.com/stale',stale_path)==stale_path
    assert not calls
    w._show_browser_dialog=original_show

    assert newer('1.5.3','1.5.2')
    assert not newer('1.5.3','1.5.3')
    assert not newer('1.5.2','1.5.3')
    print('Context menu states and version comparison passed')
finally:
    w.browser_bridge.stop();w.tray.hide();w.storage.conn.close()
