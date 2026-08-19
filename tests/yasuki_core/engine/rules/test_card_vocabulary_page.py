import inspect
import pathlib
import re

from yasuki_core.engine.rules import decisions, effects, events, modifiers, work
from yasuki_core.game_pieces import counters

PAGE = pathlib.Path("docs/design/card_vocabulary.md")
# Entries inside an autosummary block, rather than every indented word on the page: a code sample
# indented the same way would otherwise read as a listing and hide a genuine omission.
AUTOSUMMARY = re.compile(r"^\.\. autosummary::\n\n((?:^   \w+\n)+)", re.M)
CATEGORIES = (effects, events, decisions, work, modifiers, counters)


def listed_types() -> set[str]:
    """Every name the page names, across all of its autosummary blocks."""
    return {
        name
        for block in AUTOSUMMARY.findall(PAGE.read_text(encoding="utf-8"))
        for name in block.split()
    }


def public_types(module) -> set[str]:
    """Every class the module itself defines, ignoring what it imports."""
    return {
        name
        for name, obj in vars(module).items()
        if not name.startswith("_") and inspect.isclass(obj) and obj.__module__ == module.__name__
    }


def test_the_vocabulary_page_lists_every_type_a_card_can_use():
    # The page names the whole vocabulary, and the docs build only fails on an entry naming
    # something that does not exist — so an omission is invisible, and reads to a card author as a
    # type they may not use.
    unlisted = {
        f"{module.__name__.rsplit('.', 1)[-1]}.{name}"
        for module in CATEGORIES
        for name in public_types(module) - listed_types()
    }

    assert unlisted == set()


def test_the_page_lists_nothing_the_engine_dropped():
    # The other direction: a renamed or deleted type leaves an entry pointing at nothing.
    known = {name for module in CATEGORIES for name in public_types(module)}

    assert listed_types() - known == set()


def test_the_page_has_entries_to_check():
    # Guards both tests above: a regex that matched no blocks would satisfy them vacuously.
    assert len(listed_types()) > 30
