"""
The project's one logging setup.

Every module takes its logger from here, so names, format and levels are the same everywhere:

    from wcl_core.common.log import get_logger

    logger = get_logger(__name__)

Diagnostics go to that logger and stay silent until a frontend calls `configure_logging` once at startup (the CLI
with ``-v`` / ``--debug``, the desktop app at DEBUG). Library code never configures logging itself.

What a command prints for the person running it (tables, reports, "Saved." and "Error: ..." lines) is output, not
a diagnostic: it goes through `get_console()`, a logger that writes the bare message to stdout whether or not
logging was configured, and that never mixes with the diagnostic stream.
"""

import logging
import sys

#: The packages whose loggers `configure_logging` turns up; everything else (requests, urllib3, Qt) stays at WARNING.
PACKAGES = ("wcl_core", "wcl_store", "wcl_app", "warcraftlogs_client")

#: The format every diagnostic line uses.
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"

#: The logger behind `get_console`; it does not propagate, so output never reaches the diagnostic handlers.
CONSOLE_LOGGER = "warcraftlogs.console"


def get_logger(name: str) -> logging.Logger:
    """The logger for a module: call it with ``__name__``."""
    return logging.getLogger(name)


class _CurrentStream(logging.Handler):
    """Writes each record to whatever ``sys.stdout`` / ``sys.stderr`` is at the time, so redirects and captured
    output see it and a replaced stream is never written to after it closes."""

    def __init__(self, stream: str) -> None:
        super().__init__()
        self._stream = stream

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stream = getattr(sys, self._stream)
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:  # noqa: BLE001 - logging.Handler's contract: report through handleError, never raise
            self.handleError(record)


class _ProjectLevel(logging.Filter):
    """Passes this project's records from ``level`` up and everyone else's from WARNING up."""

    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        ours = record.name.split(".", 1)[0] in PACKAGES
        return record.levelno >= (self.level if ours else logging.WARNING)


def get_console() -> logging.Logger:
    """The logger for user-facing output: ``console.info(...)`` prints the message as is on stdout."""
    console = logging.getLogger(CONSOLE_LOGGER)
    if not any(isinstance(h, _CurrentStream) for h in console.handlers):
        handler = _CurrentStream("stdout")
        handler.setFormatter(logging.Formatter("%(message)s"))
        console.addHandler(handler)
        console.setLevel(logging.INFO)
        console.propagate = False
    return console


def configure_logging(level: int = logging.WARNING) -> None:
    """Send diagnostics to stderr in the shared format: this project's from ``level`` up, other libraries' from
    WARNING up.

    Frontends call this once at startup. Calling it again replaces the handler it added rather than adding another.
    """
    root = logging.getLogger()
    for old in [h for h in root.handlers if isinstance(h, _CurrentStream)]:
        root.removeHandler(old)
    handler = _CurrentStream("stderr")
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    handler.addFilter(_ProjectLevel(level))
    root.addHandler(handler)
    root.setLevel(min(level, logging.WARNING))
