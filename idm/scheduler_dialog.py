import os
from pathlib import Path

from PySide6.QtCore import QDate, QTime, Qt, QSettings
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QRadioButton, QSpinBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QTimeEdit, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QFileDialog, QInputDialog, QHeaderView, QStyle
)


class SchedulerDialog(QDialog):
    """Classic IDM-style queue scheduler dialog."""
    DEFAULT_QUEUES = [('Main download queue', 'Main'),
                      ('High Priority queue', 'High Priority'),
                      ('Later queue', 'Later'),
                      ('Synchronization queue', 'Synchronization')]

    def __init__(self, parent, storage, settings):
        super().__init__(parent)
        self.main = parent
        self.storage = storage
        self.settings = settings
        self.q = QSettings('OriginalDownloadManager', 'InternetDownloadManager')
        self.setWindowTitle('Scheduler')
        self.setFixedSize(650, 490)
        self.setObjectName('idmScheduler')

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(5)
        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        left = QWidget()
        left.setFixedWidth(180)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(self.style().standardIcon(QStyle.SP_ComputerIcon).pixmap(32, 32))
        head.addWidget(icon)
        head.addWidget(QLabel('Queues'))
        head.addStretch(1)
        left_layout.addLayout(head)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(16)
        self.tree.setObjectName('schedulerQueues')
        self._add_queues()
        limits = QTreeWidgetItem(['Download limits'])
        limits.setData(0, Qt.UserRole, ('limits', ''))
        limits.setIcon(0, self.style().standardIcon(QStyle.SP_MessageBoxWarning))
        self.tree.addTopLevelItem(limits)
        left_layout.addWidget(self.tree, 1)
        queue_buttons = QHBoxLayout()
        self.new_queue = QPushButton('New queue')
        self.delete_queue = QPushButton('Delete')
        queue_buttons.addWidget(self.new_queue)
        queue_buttons.addWidget(self.delete_queue)
        left_layout.addLayout(queue_buttons)
        body.addWidget(left)

        right = QVBoxLayout()
        right.setSpacing(5)
        self.heading = QLabel('Main download queue')
        self.heading.setAlignment(Qt.AlignHCenter)
        right.addWidget(self.heading)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._make_schedule_page(), 'Schedule')
        self.tabs.addTab(self._make_files_page(), 'Files in the queue')
        self.tabs.addTab(self._make_limits_page(), 'Download limits')
        right.addWidget(self.tabs, 1)
        body.addLayout(right, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.start_button = QPushButton('Start now')
        self.stop_button = QPushButton('Stop')
        self.help_button = QPushButton('Help')
        self.apply_button = QPushButton('Apply')
        self.close_button = QPushButton('Close')
        for b in (self.start_button, self.stop_button, self.help_button,
                  self.apply_button, self.close_button):
            b.setFixedSize(82, 26)
            footer.addWidget(b)
        root.addLayout(footer)

        self.tree.currentItemChanged.connect(self._queue_changed)
        self.new_queue.clicked.connect(self._new_queue)
        self.delete_queue.clicked.connect(self._delete_queue)
        self.start_button.clicked.connect(self._start_now)
        self.stop_button.clicked.connect(self._stop_now)
        self.help_button.clicked.connect(self._help)
        self.apply_button.clicked.connect(self.apply)
        self.close_button.clicked.connect(self.accept)
        self.tabs.currentChanged.connect(lambda *_: self._refresh_files())
        self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._style()

    def _add_queues(self):
        custom = self.q.value('scheduler/custom_queues', [], type=list)
        seen = set()
        for label, value in self.DEFAULT_QUEUES:
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.UserRole, ('queue', value))
            item.setIcon(0, self.style().standardIcon(QStyle.SP_DirClosedIcon))
            self.tree.addTopLevelItem(item)
            seen.add(value)
        for value in custom:
            value = str(value).strip()
            if value and value not in seen:
                item = QTreeWidgetItem([value + ' queue'])
                item.setData(0, Qt.UserRole, ('queue', value))
                item.setIcon(0, self.style().standardIcon(QStyle.SP_DirClosedIcon))
                self.tree.addTopLevelItem(item)
                seen.add(value)

    def _make_schedule_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(4)

        mode = QHBoxLayout()
        self.one_time = QRadioButton('One-time downloading')
        self.periodic = QRadioButton('Periodic synchronization')
        self.one_time.setChecked(True)
        mode.addWidget(self.one_time)
        mode.addStretch(1)
        mode.addWidget(self.periodic)
        outer.addLayout(mode)
        outer.addWidget(self._line())

        self.startup = QCheckBox('Start download on IDM startup')
        outer.addWidget(self.startup)

        row = QHBoxLayout()
        self.start_enabled = QCheckBox('Start download at')
        self.start_time = QTimeEdit(QTime(11, 0))
        self.start_time.setDisplayFormat('h:mm:ss AP')
        self.once_radio = QRadioButton('Once at')
        self.once_radio.setChecked(True)
        self.start_date = QDateEdit(QDate.currentDate())
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat('dddd , MMMM d, yyyy')
        row.addWidget(self.start_enabled)
        row.addStretch(1)
        row.addWidget(self.start_time)
        outer.addLayout(row)

        date_row = QHBoxLayout()
        date_row.addSpacing(8)
        date_row.addWidget(self.once_radio)
        date_row.addSpacing(16)
        date_row.addWidget(self.start_date, 1)
        outer.addLayout(date_row)

        daily_row = QHBoxLayout()
        self.daily_radio = QRadioButton('Daily')
        daily_row.addSpacing(8)
        daily_row.addWidget(self.daily_radio)
        self.days = {}
        days_layout = QVBoxLayout()
        days_layout.setSpacing(0)
        cols = []
        names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        for name in names:
            box = QCheckBox(name)
            box.setChecked(True)
            self.days[name] = box
        for offset in (0, 3, 5):
            col = QVBoxLayout()
            col.setSpacing(0)
            for name in names[offset:offset + (3 if offset < 5 else 2)]:
                col.addWidget(self.days[name])
            cols.append(col)
        for col in cols:
            daily_row.addLayout(col)
            daily_row.addStretch(1)
        outer.addLayout(daily_row)
        outer.addWidget(self._line())

        stop_row = QHBoxLayout()
        self.stop_enabled = QCheckBox('Stop download at')
        self.stop_time = QTimeEdit(QTime(7, 30))
        self.stop_time.setDisplayFormat('h:mm:ss AP')
        stop_row.addWidget(self.stop_enabled)
        stop_row.addStretch(1)
        stop_row.addWidget(self.stop_time)
        outer.addLayout(stop_row)

        retry_row = QHBoxLayout()
        self.retries_enabled = QCheckBox('Number of retries for each file if downloading failed:')
        self.retries = QSpinBox()
        self.retries.setRange(0, 10)
        self.retries.setValue(3)
        retry_row.addWidget(self.retries_enabled)
        retry_row.addStretch(1)
        retry_row.addWidget(self.retries)
        outer.addLayout(retry_row)

        self.open_done = QCheckBox('Open the following file when done:')
        outer.addWidget(self.open_done)
        open_row = QHBoxLayout()
        self.open_path = QLineEdit()
        browse = QPushButton('...')
        browse.setFixedWidth(30)
        browse.clicked.connect(self._browse_done_file)
        open_row.addWidget(self.open_path, 1)
        open_row.addWidget(browse)
        outer.addLayout(open_row)

        self.hangup = QCheckBox('Hang up modem when done')
        self.exit_when_done = QCheckBox('Exit Internet Download Manager when done')
        outer.addWidget(self.hangup)
        outer.addWidget(self.exit_when_done)

        shutdown_row = QHBoxLayout()
        self.shutdown = QCheckBox('Turn off computer when done')
        self.shutdown_action = QComboBox()
        self.shutdown_action.addItems(['Shut down', 'Restart', 'Sleep'])
        shutdown_row.addWidget(self.shutdown)
        shutdown_row.addStretch(1)
        shutdown_row.addWidget(self.shutdown_action)
        outer.addLayout(shutdown_row)
        self.force = QCheckBox('Force processes to terminate')
        self.force.setEnabled(False)
        self.shutdown.toggled.connect(self.force.setEnabled)
        outer.addSpacing(2)
        outer.addWidget(self.force)
        outer.addStretch(1)
        self.start_enabled.toggled.connect(self._sync_schedule_enabled)
        self.once_radio.toggled.connect(lambda checked: self.start_date.setEnabled(checked and self.start_enabled.isChecked()))
        self.daily_radio.toggled.connect(lambda checked: [w.setEnabled(checked and self.start_enabled.isChecked()) for w in self.days.values()])
        return page

    def _make_files_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 4, 8, 4)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(QLabel('Download'))
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 20)
        self.parallel.setValue(4)
        row.addWidget(self.parallel)
        row.addWidget(QLabel('files at the same time'))
        row.addStretch(1)
        layout.addLayout(row)
        self.files = QTableWidget(0, 4)
        self.files.setHorizontalHeaderLabels(['File Name', 'Size', 'Status', 'Time left'])
        self.files.setSelectionBehavior(QTableWidget.SelectRows)
        self.files.setSelectionMode(QTableWidget.SingleSelection)
        self.files.setEditTriggers(QTableWidget.NoEditTriggers)
        self.files.verticalHeader().setVisible(False)
        self.files.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            self.files.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        layout.addWidget(self.files, 1)
        controls = QHBoxLayout()
        self.move_down = QPushButton()
        self.move_up = QPushButton()
        self.remove_file = QPushButton()
        self.move_down.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        self.move_up.setIcon(self.style().standardIcon(QStyle.SP_ArrowUp))
        self.remove_file.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        for b in (self.move_down, self.move_up, self.remove_file):
            b.setFixedSize(24, 23)
            controls.addWidget(b)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.move_up.clicked.connect(lambda: self._move_file(-1))
        self.move_down.clicked.connect(lambda: self._move_file(1))
        self.remove_file.clicked.connect(self._remove_file)
        return page

    def _make_limits_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(QLabel('Maximum simultaneous downloads:'))
        self.max_downloads = QSpinBox()
        self.max_downloads.setRange(1, 20)
        self.max_downloads.setValue(self.settings.max_downloads)
        row.addWidget(self.max_downloads)
        row.addStretch(1)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('Maximum transfer rate:'))
        self.speed_limit = QSpinBox()
        self.speed_limit.setRange(0, 1024000)
        self.speed_limit.setValue(max(0, int(self.settings.speed_limit_kbps)))
        self.speed_limit.setSuffix(' KB/s (0 = unlimited)')
        row.addWidget(self.speed_limit)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _line(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def _queue_changed(self, item, previous=None):
        if not item:
            return
        kind, value = item.data(0, Qt.UserRole) or ('queue', 'Main')
        if kind == 'limits':
            self.heading.setText('Download limits')
            self.tabs.setTabEnabled(0, False)
            self.tabs.setTabEnabled(1, False)
            self.tabs.setCurrentIndex(2)
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.delete_queue.setEnabled(False)
            return
        self.tabs.setTabEnabled(0, True)
        self.tabs.setTabEnabled(1, True)
        self.tabs.setTabEnabled(2, True)
        self.tabs.setCurrentIndex(0)
        self.queue_name = value
        self.heading.setText(item.text())
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        is_custom = value not in [v for _, v in self.DEFAULT_QUEUES]
        self.delete_queue.setEnabled(is_custom)
        self._load_schedule()
        self._refresh_files()

    def _key(self, name):
        return 'scheduler/queues/' + self.queue_name + '/' + name

    def _load_schedule(self):
        q = self.q
        self.one_time.setChecked(q.value(self._key('one_time'), True, type=bool))
        self.periodic.setChecked(not self.one_time.isChecked())
        self.startup.setChecked(q.value(self._key('startup'), False, type=bool))
        self.start_enabled.setChecked(q.value(self._key('start_enabled'), False, type=bool))
        self.start_time.setTime(q.value(self._key('start_time'), QTime(11, 0), type=QTime))
        self.start_date.setDate(q.value(self._key('start_date'), QDate.currentDate(), type=QDate))
        self.once_radio.setChecked(q.value(self._key('once'), True, type=bool))
        self.daily_radio.setChecked(not self.once_radio.isChecked())
        for day, box in self.days.items():
            box.setChecked(q.value(self._key('day_' + day.lower()), True, type=bool))
        self.stop_enabled.setChecked(q.value(self._key('stop_enabled'), False, type=bool))
        self.stop_time.setTime(q.value(self._key('stop_time'), QTime(7, 30), type=QTime))
        self.retries_enabled.setChecked(q.value(self._key('retries_enabled'), False, type=bool))
        self.retries.setValue(q.value(self._key('retries'), 3, type=int))
        self.open_done.setChecked(q.value(self._key('open_done'), False, type=bool))
        self.open_path.setText(q.value(self._key('open_path'), '', type=str))
        self.hangup.setChecked(q.value(self._key('hangup'), False, type=bool))
        self.exit_when_done.setChecked(q.value(self._key('exit_done'), False, type=bool))
        self.shutdown.setChecked(q.value(self._key('shutdown'), False, type=bool))
        self.shutdown_action.setCurrentText(q.value(self._key('shutdown_action'), 'Shut down', type=str))
        self.force.setChecked(q.value(self._key('force'), False, type=bool))
        self.parallel.setValue(q.value(self._key('parallel'), 4, type=int))
        self._sync_schedule_enabled()

    def _sync_schedule_enabled(self):
        enabled = self.start_enabled.isChecked()
        self.start_time.setEnabled(enabled)
        self.once_radio.setEnabled(enabled)
        self.daily_radio.setEnabled(enabled)
        self.start_date.setEnabled(enabled and self.once_radio.isChecked())
        for w in self.days.values():
            w.setEnabled(enabled and self.daily_radio.isChecked())
        self.stop_time.setEnabled(self.stop_enabled.isChecked())
        self.retries.setEnabled(self.retries_enabled.isChecked())
        self.open_path.setEnabled(self.open_done.isChecked())

    def _refresh_files(self):
        if not hasattr(self, 'files') or not hasattr(self, 'queue_name'):
            return
        rows = [r for r in self.storage.all() if str(r['queue_name']) == self.queue_name]
        self.files.setRowCount(len(rows))
        for i, row in enumerate(rows):
            values = [str(row['filename']), self._size(row['total'] or row['downloaded']),
                      str(row['status']), self.main.eta_text(0)]
            for col, value in enumerate(values):
                self.files.setItem(i, col, QTableWidgetItem(value))
            self.files.item(i, 0).setData(Qt.UserRole, int(row['id']))

    @staticmethod
    def _size(n):
        n = int(n or 0)
        if not n:
            return ''
        value = float(n)
        units = ['B', 'KB', 'MB', 'GB']
        i = 0
        while value >= 1024 and i < 3:
            value /= 1024
            i += 1
        return f'{value:.2f} {units[i]}'

    def _selected_id(self):
        row = self.files.currentRow()
        item = self.files.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def _move_file(self, direction):
        row = self.files.currentRow()
        target = row + direction
        if row < 0 or target < 0 or target >= self.files.rowCount():
            return
        ids = [self.files.item(r, 0).data(Qt.UserRole) for r in range(self.files.rowCount())]
        ids[row], ids[target] = ids[target], ids[row]
        for order, rid in enumerate(ids):
            self.storage.update(rid, priority=len(ids) - order)
        self._refresh_files()
        self.files.selectRow(target)

    def _remove_file(self):
        rid = self._selected_id()
        if rid is None:
            return
        self.storage.update(rid, queue_name='')
        self._refresh_files()

    def _new_queue(self):
        name, ok = QInputDialog.getText(self, 'New queue', 'Queue name:')
        name = name.strip()
        if not ok or not name:
            return
        existing = [self.tree.topLevelItem(i).text(0).casefold() for i in range(self.tree.topLevelItemCount())]
        if (name + ' queue').casefold() in existing or name.casefold() in existing:
            QMessageBox.information(self, 'New queue', 'A queue with that name already exists.')
            return
        queues = self.q.value('scheduler/custom_queues', [], type=list)
        queues.append(name)
        self.q.setValue('scheduler/custom_queues', queues)
        item = QTreeWidgetItem([name + ' queue'])
        item.setData(0, Qt.UserRole, ('queue', name))
        item.setIcon(0, self.style().standardIcon(QStyle.SP_DirClosedIcon))
        self.tree.insertTopLevelItem(self.tree.topLevelItemCount() - 1, item)
        self.tree.setCurrentItem(item)

    def _delete_queue(self):
        item = self.tree.currentItem()
        if not item:
            return
        kind, name = item.data(0, Qt.UserRole) or ('queue', '')
        if kind != 'queue' or name in [v for _, v in self.DEFAULT_QUEUES]:
            return
        if any(str(r['queue_name']) == name for r in self.storage.all()):
            QMessageBox.warning(self, 'Delete queue', 'Move or remove its files before deleting this queue.')
            return
        queues = [v for v in self.q.value('scheduler/custom_queues', [], type=list) if v != name]
        self.q.setValue('scheduler/custom_queues', queues)
        self.q.remove('scheduler/queues/' + name)
        self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _browse_done_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Select file to open when done')
        if path:
            self.open_path.setText(path)

    def _start_now(self):
        self.apply()
        if hasattr(self, 'queue_name'):
            self.main.start_queue_named(self.queue_name)

    def _stop_now(self):
        if hasattr(self, 'queue_name'):
            self.main.stop_queue_named(self.queue_name)

    def _help(self):
        QMessageBox.information(self, 'Scheduler', 'Choose a queue, set its schedule, then select Apply. Start now and Stop control the selected queue.')

    def apply(self):
        if hasattr(self, 'queue_name'):
            q = self.q
            pairs = {
                'one_time': self.one_time.isChecked(), 'startup': self.startup.isChecked(),
                'start_enabled': self.start_enabled.isChecked(), 'start_time': self.start_time.time(),
                'start_date': self.start_date.date(), 'once': self.once_radio.isChecked(),
                'stop_enabled': self.stop_enabled.isChecked(), 'stop_time': self.stop_time.time(),
                'retries_enabled': self.retries_enabled.isChecked(), 'retries': self.retries.value(),
                'open_done': self.open_done.isChecked(), 'open_path': self.open_path.text(),
                'hangup': self.hangup.isChecked(), 'exit_done': self.exit_when_done.isChecked(),
                'shutdown': self.shutdown.isChecked(), 'shutdown_action': self.shutdown_action.currentText(),
                'force': self.force.isChecked(), 'parallel': self.parallel.value()
            }
            for key, value in pairs.items():
                q.setValue(self._key(key), value)
            for day, box in self.days.items():
                q.setValue(self._key('day_' + day.lower()), box.isChecked())
        self.settings.max_downloads = self.max_downloads.value()
        self.settings.speed_limit_kbps = self.speed_limit.value()
        self.main.max_downloads = self.settings.max_downloads
        self.main.speed_limit_kbps = self.settings.speed_limit_kbps
        self.q.sync()

    def _style(self):
        self.setStyleSheet("""
            QDialog#idmScheduler { background:#f3f3f3; color:#111; font-family:'Segoe UI'; font-size:9pt; }
            QTreeWidget { background:white; border:1px solid #a6a6a6; }
            QTreeWidget::item { height:21px; padding:1px 3px; }
            QTreeWidget::item:selected { background:#d7e8f8; color:#111; }
            QTabWidget::pane { background:#f7f7f7; border:1px solid #a6a6a6; }
            QTabBar::tab { background:#efefef; border:1px solid #aaa; padding:4px 8px; }
            QTabBar::tab:selected { background:#f7f7f7; border-bottom-color:#f7f7f7; }
            QTableWidget { background:white; border:1px solid #a6a6a6; gridline-color:#ddd; }
            QHeaderView::section { background:#f2f2f2; border:0; border-right:1px solid #bbb; border-bottom:1px solid #999; padding:3px 5px; font-weight:400; }
            QPushButton { min-height:21px; padding:2px 8px; }
            QLineEdit, QSpinBox, QTimeEdit, QDateEdit, QComboBox { background:white; min-height:20px; }
        """)
