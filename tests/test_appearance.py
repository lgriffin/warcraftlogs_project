"""Each user's theme (``wcl_app.appearance``): dark or light, and a class theme that follows their main by default."""

import json

import pytest
from wcl_app import Palette, Theme
from wcl_app.appearance import (
    FOLLOW_MAIN,
    NO_CLASS,
    Appearance,
    AppearanceService,
    JsonAppearanceStore,
    MemoryAppearanceStore,
    main_class_from,
)
from wcl_app.my_characters import LOCAL, MemoryMyCharactersStore, MyCharacters, MyCharactersService
from wcl_store import StorageError

from warcraftlogs_client.services import AppContext, PlayerRef, build_palette


@pytest.fixture
def store():
    return MemoryAppearanceStore()


class TestAppearance:
    def test_the_default_is_dark_following_the_main(self):
        assert Appearance() == Appearance("dark", FOLLOW_MAIN)

    def test_unknown_modes_and_classes_are_refused(self):
        with pytest.raises(ValueError, match="Unknown theme mode"):
            Appearance("sepia")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="not a vanilla class"):
            Appearance("dark", "Monk")

    def test_reading_back_forgives_bad_fields_one_at_a_time(self):
        assert Appearance.from_dict({"mode": "light", "class_theme": "warlock"}) == Appearance("light", "Warlock")
        assert Appearance.from_dict({"mode": "neon", "class_theme": "none"}) == Appearance("dark", NO_CLASS)
        assert Appearance.from_dict({"class_theme": "Death Knight"}) == Appearance()
        assert Appearance.from_dict("garbage") == Appearance()


class TestTheme:
    def test_following_the_main_uses_their_class(self, store):
        theme = AppearanceService(store, main_class=lambda: "mage").theme()
        assert theme.wow_class == theme.main_class == "Mage" and theme.follows_main
        assert theme.palette == build_palette("dark", "Mage")
        assert theme.label == "Mage dark (your main)"
        assert isinstance(theme, Theme) and isinstance(theme.palette, Palette)

    def test_following_a_main_with_no_known_class_is_the_classic_look(self, store):
        theme = AppearanceService(store).theme()
        assert theme.wow_class is None and theme.palette == build_palette("dark")
        assert theme.label == "Classic dark"

    def test_a_picked_class_or_none_overrides_the_main(self, store):
        service = AppearanceService(store, main_class=lambda: "Mage")
        picked = service.theme(Appearance("light", "Druid"))
        assert picked.wow_class == "Druid" and picked.main_class == "Mage" and not picked.follows_main
        assert picked.label == "Druid light"
        assert service.theme(Appearance("light", NO_CLASS)).wow_class is None

    def test_saving_keeps_the_choice_per_owner(self, store):
        AppearanceService(store, owner="42").save(Appearance("light", "Rogue"))
        assert AppearanceService(store, owner="42").current() == Appearance("light", "Rogue")
        assert AppearanceService(store, owner="7").current() == Appearance()
        assert AppearanceService(store).owner == LOCAL and AppearanceService(store).current() == Appearance()


class TestJsonStore:
    def test_round_trips_every_owner(self, tmp_path):
        path = tmp_path / "nested" / "appearance.json"
        store = JsonAppearanceStore(path)
        store.save("42", Appearance("light", "Paladin"))
        store.save(LOCAL, Appearance("dark", NO_CLASS))
        assert store.load("42") == Appearance("light", "Paladin")
        assert store.load(LOCAL) == Appearance("dark", NO_CLASS)
        assert store.load("nobody") is None
        assert json.loads(path.read_text())["version"] == 1

    @pytest.mark.parametrize("content", ["not json", "[]", '{"owners": []}'])
    def test_an_unreadable_file_means_nothing_is_saved(self, tmp_path, content):
        path = tmp_path / "appearance.json"
        path.write_text(content)
        assert JsonAppearanceStore(path).load(LOCAL) is None
        assert JsonAppearanceStore(tmp_path / "missing.json").load(LOCAL) is None


MAIN = PlayerRef.create("Hadur", "Spineshatter", "eu")


class _History:
    def __init__(self, player_class):
        self.player_class = player_class


class _Repo:
    def __init__(self, history=None, error=None):
        self.history, self.error = history, error

    def __enter__(self):
        if self.error:
            raise self.error
        return self

    def __exit__(self, *exc):
        return False

    def get_character_history(self, name):
        assert name == MAIN.name
        return self.history


def _mine(main=MAIN):
    return MyCharactersService(MemoryMyCharactersStore({LOCAL: MyCharacters(main=main)}))


class TestMainClass:
    def test_reads_the_mains_class_from_stored_raids(self):
        ctx = AppContext(config={}, storage=lambda: _Repo(_History("Warlock")))
        assert main_class_from(ctx, _mine()) == "Warlock"

    def test_no_main_no_history_or_no_storage_means_unknown(self):
        assert main_class_from(AppContext(config={}, storage=lambda: _Repo(_History("Mage"))), _mine(None)) is None
        assert main_class_from(AppContext(config={}, storage=lambda: _Repo(None)), _mine()) is None
        broken = AppContext(config={}, storage=lambda: _Repo(error=StorageError("down")))
        assert main_class_from(broken, _mine()) is None

    def test_a_class_outside_vanilla_is_unknown(self):
        ctx = AppContext(config={}, storage=lambda: _Repo(_History("Monk")))
        assert main_class_from(ctx, _mine()) is None


class TestDesktop:
    def test_keeps_the_signed_out_choice_in_the_user_data_dir(self, tmp_path, monkeypatch):
        from wcl_core import paths

        monkeypatch.setattr(paths, "get_user_data_dir", lambda: tmp_path)
        # Nothing signed in: no discord_identity.json in the user data dir.
        service = AppearanceService.desktop(AppContext(config={}, storage=lambda: _Repo(None)))
        service.save(Appearance("light", "Shaman"))
        assert service.owner == LOCAL
        assert JsonAppearanceStore(tmp_path / "appearance.json").load(LOCAL) == Appearance("light", "Shaman")
        assert service.main_class() is None
