"""Logger abstraction. LogLevel + Logger ABC + NullLogger + PrintLogger."""
import enum
import sys
import typing as tp


class LogLevel(enum.IntEnum):
    DEBUG = 10
    INFO = 20
    SUCCESS = 25
    WARN = 30
    ERROR = 40


class Logger:
    """Abstract logger. Subclasses implement ``log``; convenience methods
    come for free."""

    def log(self, level: LogLevel, stage: str, message: str,
            plugin: tp.Optional[str] = None) -> None:
        raise NotImplementedError

    def debug(self, stage, message, plugin=None):
        self.log(LogLevel.DEBUG, stage, message, plugin)

    def info(self, stage, message, plugin=None):
        self.log(LogLevel.INFO, stage, message, plugin)

    def success(self, stage, message, plugin=None):
        self.log(LogLevel.SUCCESS, stage, message, plugin)

    def warn(self, stage, message, plugin=None):
        self.log(LogLevel.WARN, stage, message, plugin)

    def error(self, stage, message, plugin=None):
        self.log(LogLevel.ERROR, stage, message, plugin)


class NullLogger(Logger):
    """No-op. Use when you really want silence."""

    def log(self, level, stage, message, plugin=None):
        pass


class PrintLogger(Logger):
    """Default logger for CLI / interactive use. Writes to stderr."""

    def log(self, level, stage, message, plugin=None):
        tag = level.name if isinstance(level, LogLevel) else str(level)
        prefix = f'[{plugin}] ' if plugin else ''
        # ERROR / WARN → stderr; everything else → stdout.
        stream = sys.stderr if level in (LogLevel.ERROR, LogLevel.WARN) \
            else sys.stdout
        stream.write(f'[{tag:>7}] {prefix}({stage}) {message}\n')
        stream.flush()
