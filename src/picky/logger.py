"""Qt-based logger for Picky — emits log lines as Qt signals.

Only requires PyQt6.QtCore (no libEGL / no GUI). Use this to route
Picky's log output to a Qt signal so any QObject slot can subscribe.

For the GUI widget itself, see :mod:`nara.picky.qt_widget`.
"""
from __future__ import annotations
import datetime
import typing as tp

from .log import Logger, LogLevel

from PyQt6.QtCore import QObject, pyqtSignal


class _LogRecord:
    """Carrier object emitted via Qt signal. Same shape as LogLine."""

    __slots__ = ('level', 'stage', 'message', 'plugin', 'timestamp')

    def __init__(self, level, stage, message, plugin=None):
        self.level = level
        self.stage = stage
        self.message = message
        self.plugin = plugin
        self.timestamp = datetime.datetime.now()


class QtLogEmitter(QObject):
    """QObject that emits a Qt signal per log line. Thread-safe —
    emitting from any thread delivers to the connected slot on the
    receiver's thread via Qt's event loop (when one is running)."""

    logged = pyqtSignal(object)


class QtLogger(Logger):
    """Logger that emits Qt signals. Plug into Picky via ``setLogger()``.

    The widget subscribes to ``logger.emitter.logged`` to receive lines.

    Example::

        from nara.picky.qt import QtLogger
        qt_logger = QtLogger()
        picky.setLogger(qt_logger)
        qt_logger.emitter.logged.connect(some_slot)
    """

    def __init__(self):
        self.emitter = QtLogEmitter()

    def log(self, level, stage, message, plugin=None):
        self.emitter.logged.emit(
            _LogRecord(level, stage, message, plugin))
