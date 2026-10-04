"""The shared logging setup in `wcl_core.common.log`: one way to get a logger, one format, one console."""

import logging
import re
from pathlib import Path

import pytest
from wcl_core.common import log

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [
    *(ROOT / "warcraftlogs_client").rglob("*.py"),
    *(ROOT / "packages").rglob("src/**/*.py"),
    ROOT / "manage_spells.py",
    ROOT / "launcher.py",
]


@pytest.fixture
def root_logger():
    """Restore the root logger's handlers and level after a test that configures logging."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield root
    root.handlers[:] = handlers
    root.setLevel(level)


def test_get_logger_names_the_logger_after_the_module():
    assert log.get_logger("wcl_core.client") is logging.getLogger("wcl_core.client")


def test_console_prints_the_bare_message_on_stdout(capsys):
    log.get_console().info("Raids tracked: %d", 2)
    log.get_console().error("Error: boom")
    assert capsys.readouterr() == ("Raids tracked: 2\nError: boom\n", "")


def test_console_output_stays_out_of_the_diagnostic_stream():
    log.get_console()
    console = log.get_console()
    assert not console.propagate
    assert sum(isinstance(h, log._CurrentStream) for h in console.handlers) == 1


def test_configure_logging_shows_this_project_at_the_level_and_others_from_warning(root_logger, capsys):
    log.configure_logging(logging.INFO)
    log.get_logger("wcl_app.badges").info("ours at info")
    log.get_logger("wcl_core.client").debug("ours at debug")
    logging.getLogger("urllib3.connectionpool").info("theirs at info")
    logging.getLogger("urllib3.connectionpool").warning("theirs at warning")
    err = capsys.readouterr().err
    assert re.search(r"^\d\d:\d\d:\d\d INFO    wcl_app\.badges: ours at info$", err, re.MULTILINE)
    assert "ours at debug" not in err and "theirs at info" not in err
    assert "WARNING urllib3.connectionpool: theirs at warning" in err


def test_configure_logging_replaces_its_own_handler(root_logger):
    log.configure_logging()
    log.configure_logging(logging.DEBUG)
    assert sum(isinstance(h, log._CurrentStream) for h in root_logger.handlers) == 1


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(ROOT)))
def test_modules_take_their_logger_from_the_shared_setup(path):
    """`get_logger(__name__)` and `get_console()` only: no ad hoc named loggers or basicConfig calls (the root
    logger itself stays reachable, for handlers such as the desktop console)."""
    if path.name == "log.py" and path.parent.name == "common":
        return
    source = path.read_text(encoding="utf-8")
    assert not re.search(r"logging\.getLogger\(\s*[^)\s]", source), "use wcl_core.common.log.get_logger(__name__)"
    assert "logging.basicConfig" not in source, "use wcl_core.common.log.configure_logging"
