from pathlib import Path

from yasuki_core.paths import (
    BUNDLED_IMAGES_DIR,
    DEFAULT_HOLDING,
    DYNASTY_BACK,
    SETS_DIR,
    default_personality_image,
    resolve_card_image_path,
)


def test_a_cards_own_art_resolves_against_the_set_images():
    assert resolve_card_image_path("sets/roj/farm.png") == SETS_DIR / "roj/farm.png"


def test_bundled_art_resolves_against_the_bundled_images():
    assert resolve_card_image_path(DEFAULT_HOLDING) == BUNDLED_IMAGES_DIR / DEFAULT_HOLDING
    assert resolve_card_image_path(DYNASTY_BACK).exists()


def test_an_already_resolved_path_is_left_alone():
    """A caller may hold a path it resolved itself — the GUI caches them — so resolving twice has
    to be harmless rather than prefixing the image root a second time."""
    resolved = resolve_card_image_path(DYNASTY_BACK)

    assert resolve_card_image_path(resolved) == resolved


def test_no_path_resolves_to_nothing():
    assert resolve_card_image_path(None) is None
    assert resolve_card_image_path("") is None


def test_the_paths_a_card_carries_are_relative():
    """An absolute path here ends up inside every snapshot and logged spawn, which ties a saved
    game to the machine that wrote it."""
    absolute = [
        p
        for p in (DYNASTY_BACK, DEFAULT_HOLDING, default_personality_image(["Crab"]))
        if Path(p).is_absolute()
    ]

    assert absolute == []
