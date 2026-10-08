"""My Character shows the main and claimed alts, opens the main on sign-in and jumps between favourites."""

import json

import pytest

pytest.importorskip("PySide6")

from wcl_app.my_characters import LOCAL, MemoryMyCharactersStore, MyCharacters, MyCharactersService

from warcraftlogs_client.gui import character_view
from warcraftlogs_client.gui.my_characters_bar import MyCharactersBar
from warcraftlogs_client.services import PlayerRef

MAIN = PlayerRef.create("Hadur", "spineshatter", "eu")
ALT = PlayerRef.create("Toadly", "spineshatter", "eu")


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(character_view, "CONFIG_PATH", str(path))
    return path


@pytest.fixture
def fetched(monkeypatch):
    names: list[str] = []
    monkeypatch.setattr(
        character_view.CharacterView, "_fetch_profile", lambda self: names.append(self._char_name_input.text())
    )
    return names


def _labels(bar: MyCharactersBar) -> list[str]:
    return [b.text() for b in bar._buttons]


@pytest.mark.gui
class TestMyCharactersBar:
    def test_shows_the_main_first_and_who_is_signed_in(self, qtbot):
        store = MemoryMyCharactersStore({"42": MyCharacters(main=MAIN, alts=(ALT,))})
        bar = MyCharactersBar(lambda: MyCharactersService(store, owner="42", owner_name="Leigh"))
        qtbot.addWidget(bar)
        bar.reload()
        assert _labels(bar) == ["★ Hadur", "Toadly"] and bar._owner_label.text() == "Signed in as Leigh"
        assert bar.owner == "42" and bar._empty_label.isHidden()

    def test_signed_out_with_nothing_claimed(self, qtbot):
        bar = MyCharactersBar(lambda: MyCharactersService(MemoryMyCharactersStore()))
        qtbot.addWidget(bar)
        assert bar.owner is None
        bar.reload()
        assert _labels(bar) == [] and "Not signed in" in bar._owner_label.text() and bar.owner == LOCAL
        assert not bar._empty_label.isHidden()

    def test_claim_set_main_and_release_the_character_on_screen(self, qtbot):
        store = MemoryMyCharactersStore()
        bar = MyCharactersBar(lambda: MyCharactersService(store, owner="42"))
        qtbot.addWidget(bar)
        messages: list[str] = []
        bar.status_message.connect(messages.append)
        bar.reload()
        bar.set_current(MAIN)
        assert bar._main_btn.isEnabled() and not bar._claim_btn.isEnabled() and not bar._release_btn.isEnabled()
        bar._main_btn.click()
        bar.set_current(ALT)
        assert bar._claim_btn.isEnabled()
        bar._claim_btn.click()
        assert store.load("42") == MyCharacters(main=MAIN, alts=(ALT,)) and _labels(bar) == ["★ Hadur", "Toadly"]
        assert bar._buttons[1].isChecked() and not bar._buttons[0].isChecked()
        bar._main_btn.click()
        assert _labels(bar) == ["★ Toadly", "Hadur"]
        bar._release_btn.click()
        assert _labels(bar) == ["★ Hadur"]
        assert messages == [
            "Hadur is now your main",
            "Claimed Toadly as an alt",
            "Toadly is now your main",
            "Released Toadly",
        ]

    def test_clicking_a_favourite_chooses_it(self, qtbot):
        store = MemoryMyCharactersStore({LOCAL: MyCharacters(main=MAIN, alts=(ALT,))})
        bar = MyCharactersBar(lambda: MyCharactersService(store))
        qtbot.addWidget(bar)
        bar.reload()
        chosen: list[PlayerRef] = []
        bar.character_chosen.connect(chosen.append)
        bar._buttons[1].click()
        assert chosen == [ALT] and bar._buttons[1].isChecked()

    def test_a_failed_save_says_so(self, qtbot):
        class Broken(MemoryMyCharactersStore):
            def save(self, owner, characters):
                raise OSError("disk full")

        bar = MyCharactersBar(lambda: MyCharactersService(Broken()))
        qtbot.addWidget(bar)
        messages: list[str] = []
        bar.status_message.connect(messages.append)
        bar.set_current(MAIN)
        bar._main_btn.click()
        assert messages == ["Could not save your characters: disk full"] and _labels(bar) == []


@pytest.mark.gui
class TestCharacterViewOpensTheMain:
    def test_the_config_character_is_the_main_after_signing_in(self, qtbot, config_path, fetched):
        config_path.write_text(json.dumps({"character_name": "Hadur", "character_server": "spineshatter"}))
        view = character_view.CharacterView(
            my_characters=MyCharactersService(
                MemoryMyCharactersStore(), owner="42", config=json.loads(config_path.read_text())
            )
        )
        qtbot.addWidget(view)
        assert _labels(view._my_characters_bar) == ["★ Hadur"]
        assert view._my_characters_bar._buttons[0].isChecked()

    def test_the_saved_main_opens_and_a_favourite_jumps(self, qtbot, config_path, fetched):
        store = MemoryMyCharactersStore({"42": MyCharacters(main=ALT, alts=(MAIN,))})
        view = character_view.CharacterView(my_characters=MyCharactersService(store, owner="42"))
        qtbot.addWidget(view)
        assert view._char_name_input.text() == "Toadly"
        view._my_characters_bar._buttons[1].click()
        assert view._char_name_input.text() == "Hadur" and fetched == ["Hadur"]

    def test_the_default_service_follows_the_desktop_sign_in(self, qtbot, config_path, tmp_path, monkeypatch):
        from wcl_core import paths

        identity = tmp_path / "identity.json"
        identity.write_text(json.dumps({"user": {"id": "42", "username": "leigh"}}))
        monkeypatch.setattr(paths, "get_discord_identity_path", lambda: identity)
        config_path.write_text(json.dumps({"character_name": "Hadur", "character_server": "spineshatter"}))
        view = character_view.CharacterView()
        qtbot.addWidget(view)
        assert view._my_characters_bar.owner == "42" and _labels(view._my_characters_bar) == ["★ Hadur"]

    def test_a_favourite_clicked_while_a_fetch_runs_is_ignored(self, qtbot, config_path, fetched):
        class Running:
            def isRunning(self):
                return True

        store = MemoryMyCharactersStore({"42": MyCharacters(main=ALT, alts=(MAIN,))})
        view = character_view.CharacterView(my_characters=MyCharactersService(store, owner="42"))
        qtbot.addWidget(view)
        view._worker = Running()
        messages: list[str] = []
        view.status_message.connect(messages.append)
        view._my_characters_bar._buttons[1].click()
        assert fetched == [] and view._char_name_input.text() == "Toadly"
        assert messages == ["Still loading the last character; try again in a moment"]
        assert view._my_characters_bar._buttons[0].isChecked() and not view._my_characters_bar._buttons[1].isChecked()
        view._worker = None
