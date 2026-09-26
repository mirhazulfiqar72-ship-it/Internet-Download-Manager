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
    w.load_rows()
    assert w.table.columnCount()==9
    assert 'Save To' not in [w.table.horizontalHeaderItem(i).text() for i in range(w.table.columnCount())]
    assert w.table.item(w.row_by_id(rid),3).text()=='Complete'
    w.table.selectRow(w.row_by_id(rid))
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
    w.update_row(rid,downloaded=50,total=100,status='Downloading')
    assert w.table.item(w.row_by_id(rid),3).text()=='50%'
    w.update_row(rid,downloaded=100,total=100,status='Downloading')
    assert w.table.item(w.row_by_id(rid),3).text()=='Complete'
    w.update_row(rid,downloaded=50,total=100,status='Downloading')
    dlg=module.DownloadProgressDialog(w,rid)
    assert dlg.width()==512 and dlg.height()==448
    dlg.update_live(50,100,1000,1)
    before=dlg.done_lbl.text();dlg.sync()
    assert dlg.done_lbl.text()==before and '50.00%' in before
    dlg.sync_timer.stop();dlg.close()

    # Download File Info must expose native close/minimize/maximize controls,
    # while fixed size keeps maximize non-functional and minimize available.
    info=module.AddDialog(w,'https://example.com/new-file.bin')
    info._remote_probe_timer.stop()
    flags=info.windowFlags()
    assert flags & Qt.WindowMinimizeButtonHint
    assert flags & Qt.WindowMaximizeButtonHint
    assert flags & Qt.WindowCloseButtonHint
    assert info.minimumSize()==info.maximumSize()
    info.close()
    doc_info=module.AddDialog(w,'https://example.com/quarterly-report.docx')
    doc_info._remote_probe_timer.stop()
    assert doc_info.category.currentText()=='Documents'
    assert Path(doc_info.save_as.text()).parent.name.lower()=='docoments'
    assert not doc_info.file_icon.pixmap(48,48).isNull()
    doc_info.close()
    program_info=module.AddDialog(w,'https://example.com/installer.exe')
    program_info._remote_probe_timer.stop()
    assert program_info.category.currentText()=='Programs'
    assert Path(program_info.save_as.text()).parent.name.lower()=='program'
    assert not program_info.file_icon.pixmap(48,48).isNull()
    program_info._apply_remote_metadata({
        'url':'https://example.com/installer.exe','size':87400000,
        'filename':'InternetDownloadManager_Setup.exe','content_type':'application/octet-stream'
    })
    assert program_info.file_size.text()!='--'
    assert Path(program_info.save_as.text()).parent.name.lower()=='program'
    program_info.close()
    picture_info=module.AddDialog(w,'https://example.com/download?id=42')
    picture_info._remote_probe_timer.stop()
    assert picture_info.category.currentText()=='Pictures'
    assert Path(picture_info.save_as.text()).parent.name.lower()=='pictures'
    assert not picture_info.file_icon.pixmap(48,48).isNull()
    assert Path(picture_info.save_as.text()).parent.name.lower()=='pictures'
    picture_info._apply_remote_metadata({
        'url':'https://example.com/download?id=42','size':123456,
        'filename':'downloaded-image.png','content_type':'image/png'
    })
    assert picture_info.file_size.text()!='--'
    picture_info.close()

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
