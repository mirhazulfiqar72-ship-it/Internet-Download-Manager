from PySide6.QtWidgets import QWizard,QWizardPage,QLabel,QVBoxLayout,QCheckBox,QComboBox
from PySide6.QtCore import QSettings
class FirstRunWizard(QWizard):
    def __init__(self):
        super().__init__(); self.setWindowTitle('Internet Download Manager — First Run'); self.setMinimumSize(560,360)
        p1=QWizardPage(); p1.setTitle('Welcome'); l=QVBoxLayout(p1); l.addWidget(QLabel('<h2>Welcome</h2><p>Your download manager is ready. This short setup lets you choose the basic startup behavior.</p>')); self.addPage(p1)
        p2=QWizardPage(); p2.setTitle('Startup preferences'); l=QVBoxLayout(p2); self.auto=QCheckBox('Start downloads automatically after adding'); self.auto.setChecked(True); self.tray=QCheckBox('Minimize to the system tray'); self.tray.setChecked(True); l.addWidget(self.auto); l.addWidget(self.tray); self.addPage(p2)
        p3=QWizardPage(); p3.setTitle('Ready'); l=QVBoxLayout(p3); l.addWidget(QLabel('<p>Setup is complete. You can change these settings later.</p>')); self.addPage(p3)
    def accept(self):
        s=QSettings('OriginalDownloadManager','InternetDownloadManager'); s.setValue('first_run_complete',True); s.setValue('auto_start',self.auto.isChecked()); s.setValue('minimize_to_tray',self.tray.isChecked()); super().accept()
    @staticmethod
    def should_show(): return not QSettings('OriginalDownloadManager','InternetDownloadManager').value('first_run_complete',False,type=bool)
