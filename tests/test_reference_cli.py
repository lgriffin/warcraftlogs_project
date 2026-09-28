"""The ``reference`` CLI subcommand: a thin adapter over ReferenceService and the console renderer."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest
from wcl_app import AppContext, ReferenceAuthRequired

from warcraftlogs_client import cli
from warcraftlogs_client.models import EncounterPerformance, EncounterSummary

OURS = "OursOursOursOurs"
THEIRS = "TheirsTheirsThei"
START = int(datetime(2026, 9, 21, 20, 0).timestamp() * 1000)


@pytest.fixture
def db_path(tmp_path, monkeypatch, build_analysis):
    path = str(tmp_path / "cli.db")
    monkeypatch.setattr(cli, "_reference_context", lambda action: AppContext(config={}, db_path=path))
    boss = EncounterSummary(
        1, "Gruul", START + 60_000, START + 300_000, 240_000, [EncounterPerformance("S", "Rogue", 3, "melee", 5, 5)]
    )
    ours = build_analysis(report_id=OURS, title="Toads Gruul", start_time=START, encounters=[boss])
    theirs = build_analysis(report_id=THEIRS, title="Best Gruul", start_time=START, encounters=[boss])
    with AppContext(config={}, db_path=path).repository() as db:
        db.import_raid(ours)
        db.import_raid(theirs, source="reference")
    return path


def _run(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["warcraftlogs", "reference", *argv])
    return cli.main()


def test_list_references_and_guild_raids(db_path, monkeypatch, capsys):
    assert _run(monkeypatch, "label", THEIRS, "World first") == 0
    assert _run(monkeypatch, "list") == 0
    out = capsys.readouterr().out
    assert THEIRS in out and "[World first]" in out and OURS not in out

    assert _run(monkeypatch, "list", "--guild", "--json") == 0
    assert [r["report_id"] for r in json.loads(capsys.readouterr().out)] == [OURS]


def test_compare_prints_both_sides(db_path, monkeypatch, capsys):
    assert _run(monkeypatch, "compare", OURS, THEIRS) == 0
    out = capsys.readouterr().out
    assert "Toads Gruul" in out and "Best Gruul" in out and "Total healing" in out and "Gruul" in out

    assert _run(monkeypatch, "compare", OURS, THEIRS, "--json") == 0
    assert json.loads(capsys.readouterr().out)["reference"]["report_id"] == THEIRS


def test_refusals_print_an_error(db_path, monkeypatch, capsys):
    assert _run(monkeypatch, "delete", OURS) == 1
    assert "not a reference raid" in capsys.readouterr().out
    assert _run(monkeypatch, "delete", THEIRS) == 0
    assert _run(monkeypatch, "list") == 0
    assert "No reference raids yet" in capsys.readouterr().out


def test_import_without_sign_in_says_where_to_sign_in(db_path, monkeypatch, capsys):
    with patch("wcl_app.reference.ReferenceService.import_reference", side_effect=ReferenceAuthRequired("x")):
        assert _run(monkeypatch, "import", "NewNewNewNewNewN", "--label", "x") == 1
    assert "Sign in to Warcraft Logs first" in capsys.readouterr().out


def test_import_reports_the_title(db_path, monkeypatch, capsys, build_analysis):
    analysis = build_analysis(report_id="NewNewNewNewNewN", title="Imported run")
    with patch("wcl_app.reference.ReferenceService.import_reference", return_value=analysis):
        assert _run(monkeypatch, "import", "NewNewNewNewNewN") == 0
    assert "Imported 'Imported run'" in capsys.readouterr().out


def test_no_action_prints_the_actions(monkeypatch, capsys):
    assert _run(monkeypatch) == 1
    assert "list, import, label, delete or compare" in capsys.readouterr().out
