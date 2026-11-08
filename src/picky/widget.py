"""PyQt6 widget for Picky — plugin status table + live log viewer.

Dark-themed via QSS. Override ``PickyWidget.STYLESHEET`` to retheme.

Usage::

    from nara.picky.qt import QtLogger
    from nara.picky.qt_widget import PickyWidget
    qt_logger = QtLogger()
    picky.setLogger(qt_logger)
    widget = PickyWidget(picky, qt_logger)
    widget.show()

Actions (Install / Update / Cleanup) run in a QThread so pip output
streams live into the log viewer without freezing the UI.
"""
from __future__ import annotations
import os
import typing as tp

from .log import LogLevel
from .logger import QtLogger, _LogRecord

from PyQt6.QtCore import Qt, QThread, QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QSplitter,
)

# Unified palette — used for log levels AND status dots.
_PALETTE = {
    LogLevel.ERROR:   '#ef4444',
    LogLevel.WARN:    '#f59e0b',
    LogLevel.SUCCESS: '#10b981',
    LogLevel.INFO:    '#cbd5e1',
    LogLevel.DEBUG:   '#64748b',
}

# status → (dot glyph, color)
_STATUS = {
    'loaded':    ('●', '#10b981'),
    'installed': ('●', '#3b82f6'),
    'broken':    ('●', '#ef4444'),
    'missing':   ('○', '#64748b'),
}

_BUTTONS = ('btn_refresh', 'btn_install', 'btn_update', 'btn_cleanup')


class _Worker(QObject):
    """Runs a callable on a QThread; emits finished or error."""

    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, func):
        super().__init__()
        self._func = func

    def run(self):
        try:
            self._func()
        except Exception as e:
            self.error.emit(str(e))
        self.finished.emit()


class PickyWidget(QWidget):
    """Plugin manager GUI: status table + live log + action buttons."""

    # One stylesheet to style everything. Override on a subclass to retheme.
    STYLESHEET = """
        QWidget { background: #0f172a; color: #cbd5e1;
                  font-family: 'Inter','Segoe UI',sans-serif; font-size: 13px; }
        QPushButton { background: #1e293b; border: 1px solid #334155;
                      border-radius: 4px; padding: 6px 14px; }
        QPushButton:hover   { background: #334155; border-color: #475569; }
        QPushButton:pressed { background: #475569; }
        QPushButton:disabled { color: #475569; }
        QLabel#status { color: #94a3b8; padding: 0 12px; }
        QTableWidget { background: #1e293b; alternate-background-color: #243044;
                       gridline-color: #334155; border: 1px solid #334155;
                       border-radius: 4px; }
        QHeaderView::section { background: #1e293b; color: #94a3b8;
                               padding: 6px; border: none;
                               border-right: 1px solid #334155;
                               border-bottom: 1px solid #334155; font-weight: 600; }
        QPlainTextEdit { background: #0f172a; color: #cbd5e1;
                         border: 1px solid #334155; border-radius: 4px; padding: 6px; }
        QSplitter::handle { background: #334155; width: 2px; }
    """

    def __init__(self, picky, logger: QtLogger, parent=None):
        super().__init__(parent)
        self.picky = picky
        self.logger = logger
        self._thread: tp.Optional[QThread] = None
        self._worker: tp.Optional[_Worker] = None
        self._action = ''
        self.setWindowTitle('Picky — Plugin Manager')
        self.resize(1100, 700)
        self.setStyleSheet(self.STYLESHEET)
        self._build_ui()
        self._wire()
        self.refresh()

    # ── construction ───────────────────────────────────────────────────
    def _build_ui(self):
        # Toolbar
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 8, 8, 4)
        self.btn_refresh = QPushButton('↻  Refresh')
        self.btn_install = QPushButton('↓  Install')
        self.btn_update  = QPushButton('↑  Update')
        self.btn_cleanup = QPushButton('✕  Cleanup')
        self.status_label = QLabel('<span style="color:#10b981">●</span> Ready')
        self.status_label.setObjectName('status')
        for b in (self.btn_refresh, self.btn_install,
                  self.btn_update, self.btn_cleanup):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(self.status_label)

        # Status table: dot | name | ref | site-packages
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ['', 'Plugin', 'Ref', 'Site-packages'])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        hdr = self.table.horizontalHeader()
        for i in range(3):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        # Log viewer
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(10000)
        f = QFont('JetBrains Mono', 9)
        f.setStyleHint(QFont.StyleHint.Monospace)
        self.log_view.setFont(f)

        # Body
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.log_view)
        splitter.setSizes([400, 650])
        splitter.setHandleWidth(2)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(bar)
        root.addWidget(splitter, 1)

    def _wire(self):
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_install.clicked.connect(
            lambda: self._run_action('Install', self.picky.PickyInstall))
        self.btn_update.clicked.connect(
            lambda: self._run_action('Update', self.picky.PickyUpdate))
        self.btn_cleanup.clicked.connect(
            lambda: self._run_action('Cleanup', self.picky.PickyCleanup))
        self.logger.emitter.logged.connect(self._on_log_line)

    # ── status table ───────────────────────────────────────────────────
    def refresh(self):
        picks = self.picky.getPicks()
        plugman = getattr(self.picky.app, 'plugman', None)
        plugs = plugman.plugs if plugman else {}
        self.table.setRowCount(len(picks))
        for row, pick in enumerate(picks):
            name = pick['folder']
            src = os.path.join(self.picky.folder, name)
            sp = os.path.join(self.picky.req.base_dir, name)
            installed = os.path.exists(src)
            has_deps = os.path.isdir(sp) and bool(os.listdir(sp))
            loaded = installed and any(
                name.lower() in c.lower() for c in plugs)
            status = ('loaded'    if loaded else
                      'broken'    if installed else
                      'installed' if has_deps else
                      'missing')
            dot, color = _STATUS[status]
            ref = pick.get('branch') or pick.get('commit') or '—'
            sp_disp = sp if has_deps else '—'

            dot_item = QTableWidgetItem(dot)
            dot_item.setForeground(QColor(color))
            dot_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, dot_item)
            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.setItem(row, 2, QTableWidgetItem(ref))
            self.table.setItem(row, 3, QTableWidgetItem(sp_disp))

    # ── log viewer ─────────────────────────────────────────────────────
    def _on_log_line(self, rec: _LogRecord):
        line = f'{rec.timestamp:%H:%M:%S} {rec.level.name:<7}'
        if rec.plugin:
            line += f' [{rec.plugin}]'
        line += f' ({rec.stage}) {rec.message}'
        color = _PALETTE.get(rec.level, '#cbd5e1')
        safe = (line.replace('&', '&amp;')
                    .replace('<', '&lt;')
                    .replace('>', '&gt;'))
        self.log_view.appendHtml(f'<span style="color:{color}">{safe}</span>')

    # ── actions (background thread) ────────────────────────────────────
    def _run_action(self, name: str, func):
        if self._thread:
            self.logger.warn('ui', f'{name} skipped — another action running')
            return
        self._action = name
        self.status_label.setText(f'<span style="color:#f59e0b">●</span> {name}…')
        for attr in _BUTTONS:
            getattr(self, attr).setEnabled(False)
        self.logger.info('ui', f'=== {name} started ===')

        self._thread = QThread()
        self._worker = _Worker(func)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_action_finished)
        self._worker.error.connect(
            lambda msg: self.logger.error('ui', f'{name} error: {msg}'))
        self._thread.start()

    def _on_action_finished(self):
        self.logger.success('ui', f'=== {self._action} finished ===')
        self._thread.quit()
        self._thread.wait()
        self._thread = self._worker = None
        for attr in _BUTTONS:
            getattr(self, attr).setEnabled(True)
        self.status_label.setText('<span style="color:#10b981">●</span> Ready')
        self.refresh()

    def _on_action_error(self, msg: str):
        self.logger.error('ui', f'action error: {msg}')
