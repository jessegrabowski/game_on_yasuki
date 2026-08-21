import ast
import pathlib

from yasuki_core.engine.rules import cards
from yasuki_core.game_pieces import keywords
from yasuki_core.install.card_index import DEFAULT_CARDS_PATH, iter_set_entries

# Derived from the imported package rather than written as a path from the repository root: a
# relative path resolves against the working directory, and pytest run from anywhere else would
# scan nothing and pass every check below without reading a line.
RULES_DIR = pathlib.Path(cards.__file__).parent.parent


def engine_keywords() -> dict[str, str]:
    """Every keyword the vocabulary names, by the constant naming it."""
    return {
        name: value
        for name, value in vars(keywords).items()
        if name.isupper() and isinstance(value, str)
    }


def printed_keywords(cards_dir: pathlib.Path = DEFAULT_CARDS_PATH) -> set[str]:
    return {keyword for entry in iter_set_entries(cards_dir) for keyword in entry.keywords}


def test_every_keyword_the_engine_names_is_printed_on_a_card():
    # A keyword is card text, so a misspelling here is a rule that never fires and never errors —
    # the same silent death a misspelled card id dies, and caught the same way.
    printed = printed_keywords()
    unprinted = {name: value for name, value in engine_keywords().items() if value not in printed}

    assert unprinted == {}


def rules_constants() -> list[tuple[str, int, str, str]]:
    """Every module-level ``NAME = "literal"`` under the rules layer, as (module, line, name,
    value)."""
    found = []
    for path in sorted(RULES_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                continue
            if not isinstance(node.value.value, str):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.append(
                        (
                            path.relative_to(RULES_DIR).as_posix(),
                            node.lineno,
                            target.id,
                            node.value.value,
                        )
                    )
    return found


def test_no_rules_module_spells_a_keyword_for_itself():
    # The vocabulary is only one module for as long as nothing else writes its own copy, and the
    # copy need not be named for what it is: a bare SAMURAI = "Samurai" scatters the vocabulary just
    # as surely as SAMURAI_KEYWORD did. The card data decides — a constant whose value is a printed
    # keyword is one, whatever it is called. Token ids and card ids are lowercase slugs and no
    # printed keyword is, so neither can be mistaken for one.
    printed = printed_keywords()
    offenders = [
        f"{module}:{line} {name} = {value!r}"
        for module, line, name, value in rules_constants()
        if value in printed
    ]

    assert offenders == []


def test_the_constant_scan_reads_the_rules_layer():
    # Guards the test above: an empty scan finds no offenders and reports success, so the scan has
    # to be shown to have read something. Anchored on the layer rather than on any one card, so
    # implementing or removing a card cannot silence it.
    assert len(list(RULES_DIR.rglob("*.py"))) > 20
    assert any(module.startswith("cards/") for module, _, _, _ in rules_constants())


def test_no_clan_word_is_named_without_saying_which_sense_it_means():
    # "Dragon" the keyword is the creature; "Dragon Clan" is the clan, and the clans column spells
    # that one plainly as "Dragon" — the two columns read the same word the opposite way round. A
    # rule keyed on the bare word would quietly match 70 Nonhuman dragons instead of 409 clan cards.
    printed = printed_keywords()
    conflatable = {
        f"{name} = {value!r}"
        for name, value in engine_keywords().items()
        if f"{value} Clan" in printed
    }

    assert conflatable == set(), "spell the clan sense in full, and name the constant for it"


def test_the_vocabulary_has_keywords_to_check():
    # Guards the checks above: an empty vocabulary would satisfy them vacuously.
    assert len(engine_keywords()) > 10
