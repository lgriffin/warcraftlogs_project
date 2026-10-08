"""A user's main character and claimed alts (``wcl_app.my_characters``), kept per Discord identity."""

import json

import pytest
from wcl_app.my_characters import (
    LOCAL,
    JsonMyCharactersStore,
    MemoryMyCharactersStore,
    MyCharacters,
    MyCharactersService,
    legacy_main,
)

from warcraftlogs_client.services import PlayerRef

MAIN = PlayerRef.create("Hadur", "Spineshatter", "eu")
ALT = PlayerRef.create("Toadly", "Spineshatter", "eu")
ALT2 = PlayerRef.create("Hopper", "Thunderstrike", "eu")
LEGACY = {"character_name": "hadur", "character_server": "spineshatter", "character_region": "EU"}


@pytest.fixture
def store():
    return MemoryMyCharactersStore()


class TestClaiming:
    def test_the_first_claim_is_the_main_and_later_ones_are_alts(self, store):
        service = MyCharactersService(store, owner="42")
        service.claim(MAIN)
        mine = service.claim(ALT)
        assert mine == MyCharacters(main=MAIN, alts=(ALT,))
        assert store.load("42") == mine and mine.favourites == (MAIN, ALT)

    def test_claiming_twice_changes_nothing(self, store):
        service = MyCharactersService(store, owner="42")
        service.claim(MAIN)
        service.claim(ALT)
        assert service.claim(ALT) == service.claim(MAIN) == MyCharacters(main=MAIN, alts=(ALT,))

    def test_a_new_main_keeps_the_old_one_as_an_alt(self, store):
        service = MyCharactersService(store, owner="42")
        service.claim(MAIN)
        service.claim(ALT)
        assert service.set_main(ALT) == MyCharacters(main=ALT, alts=(MAIN,))
        assert service.set_main(ALT2) == MyCharacters(main=ALT2, alts=(ALT, MAIN))
        assert service.set_main(ALT2).main == ALT2

    def test_releasing_the_main_promotes_the_first_alt(self, store):
        service = MyCharactersService(store, owner="42")
        for ref in (MAIN, ALT, ALT2):
            service.claim(ref)
        assert service.release(MAIN) == MyCharacters(main=ALT, alts=(ALT2,))
        assert service.release(ALT2) == MyCharacters(main=ALT)
        assert service.release(ALT2) == MyCharacters(main=ALT)  # not claimed: no-op
        assert service.release(ALT) == MyCharacters()


class TestWhoseCharacters:
    def test_each_identity_keeps_its_own(self, store):
        MyCharactersService(store, owner="42").claim(MAIN)
        MyCharactersService(store, owner="43").claim(ALT)
        assert MyCharactersService(store, owner="42").current().main == MAIN
        assert MyCharactersService(store, owner="43").current().main == ALT

    def test_signing_in_takes_over_what_was_claimed_while_signed_out(self, store):
        MyCharactersService(store).claim(MAIN)
        assert store.load(LOCAL) == MyCharacters(main=MAIN)
        signed_in = MyCharactersService(store, owner="42", owner_name="Leigh")
        assert signed_in.current() == MyCharacters(main=MAIN)
        assert signed_in.claim(ALT) == MyCharacters(main=MAIN, alts=(ALT,))
        assert store.load("42") == MyCharacters(main=MAIN, alts=(ALT,))
        assert signed_in.owner_name == "Leigh" and MyCharactersService(store, owner_name="x").owner_name is None

    def test_the_config_character_is_the_main_until_anything_is_claimed(self, store):
        service = MyCharactersService(store, owner="42", config=LEGACY)
        assert service.current() == MyCharacters(main=MAIN)
        assert service.claim(ALT) == MyCharacters(main=MAIN, alts=(ALT,))

    def test_an_incomplete_config_character_is_no_main(self):
        assert legacy_main({"character_name": "Hadur"}) is None
        assert legacy_main(None) is None
        assert legacy_main({"character_name": "Hadur", "character_server": "Spineshatter"}) == MAIN


class TestJsonStore:
    def test_round_trip_per_owner(self, tmp_path):
        store = JsonMyCharactersStore(tmp_path / "sub" / "mine.json")
        assert store.load("42") is None
        store.save("42", MyCharacters(main=MAIN, alts=(ALT,)))
        store.save(LOCAL, MyCharacters(main=ALT2))
        again = JsonMyCharactersStore(tmp_path / "sub" / "mine.json")
        assert again.load("42") == MyCharacters(main=MAIN, alts=(ALT,))
        assert again.load(LOCAL) == MyCharacters(main=ALT2)
        assert json.loads((tmp_path / "sub" / "mine.json").read_text())["version"] == 1

    def test_unreadable_files_and_entries_mean_nothing_saved(self, tmp_path):
        path = tmp_path / "mine.json"
        path.write_text("not json")
        assert JsonMyCharactersStore(path).load("42") is None
        path.write_text(json.dumps({"owners": []}))
        assert JsonMyCharactersStore(path).load("42") is None
        path.write_text(json.dumps({"owners": {"42": "x"}}))
        assert JsonMyCharactersStore(path).load("42") is None

    def test_bad_and_repeated_characters_are_dropped(self):
        data = {
            "main": {"name": "Hadur", "server": "Spineshatter", "region": "eu"},
            "alts": [
                {"name": "", "server": "x", "region": "eu"},
                "junk",
                {"name": "Hadur", "server": "spineshatter", "region": "EU"},
                {"name": "Toadly", "server": "Spineshatter", "region": "eu"},
                {"name": "toadly", "server": "spineshatter", "region": "eu"},
            ],
        }
        assert MyCharacters.from_dict(data) == MyCharacters(main=MAIN, alts=(ALT,))
        assert MyCharacters.from_dict({}) == MyCharacters()

    def test_the_desktop_reads_the_linked_identity(self, tmp_path, monkeypatch):
        from wcl_core import paths

        identity = tmp_path / "identity.json"
        identity.write_text(json.dumps({"user": {"id": "42", "username": "leigh", "global_name": "Leigh"}}))
        monkeypatch.setattr(paths, "get_discord_identity_path", lambda: identity)
        service = MyCharactersService.desktop(LEGACY)
        assert (service.owner, service.owner_name, service.current().main) == ("42", "Leigh", MAIN)
        service.claim(ALT)
        assert JsonMyCharactersStore(paths.get_my_characters_path()).load("42") == MyCharacters(main=MAIN, alts=(ALT,))
        identity.unlink()
        signed_out = MyCharactersService.desktop()
        assert (signed_out.owner, signed_out.owner_name, signed_out.current()) == (LOCAL, None, MyCharacters())


def test_the_desktop_keeps_them_next_to_the_profiles(monkeypatch):
    from wcl_core import paths

    monkeypatch.undo()  # the autouse fixture points both at tmp_path; read the real locations, writing nothing
    assert paths.get_my_characters_path() == paths.get_profiles_path().with_name("my_characters.json")
