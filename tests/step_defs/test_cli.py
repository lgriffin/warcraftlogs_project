"""Step definitions for CLI feature."""

from pytest_bdd import parsers, scenarios, then, when

from warcraftlogs_client.cli import create_parser

scenarios("cli.feature")


@when(parsers.parse('the CLI is invoked with "{args}"'), target_fixture="parsed")
def parse_args(args):
    parser = create_parser()
    return {"args": parser.parse_args(args.split())}


@then(parsers.parse('the parsed command should be "{command}"'))
def check_command(parsed, command):
    assert parsed["args"].command == command


@then("the md flag should be true")
def check_md(parsed):
    assert parsed["args"].md is True


@then("the save flag should be true")
def check_save(parsed):
    assert parsed["args"].save is True


@then(parsers.parse('the report_id should be "{rid}"'))
def check_report_id(parsed, rid):
    assert parsed["args"].report_id == rid


@then(parsers.parse('the raid_ids should contain "{id1}" and "{id2}" and "{id3}"'))
def check_raid_ids(parsed, id1, id2, id3):
    assert parsed["args"].raid_ids == [id1, id2, id3]


@then(parsers.parse('the character_name should be "{name}"'))
def check_character_name(parsed, name):
    assert parsed["args"].character_name == name


@then("the verbose flag should be true")
def check_verbose(parsed):
    assert parsed["args"].verbose is True


@then("the debug flag should be true")
def check_debug(parsed):
    assert parsed["args"].debug is True
