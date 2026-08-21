import collections
import pathlib

import pytest

from yasuki_core.install.card_index import DEFAULT_CARDS_PATH, iter_set_entries, read_index

from tests.yasuki_core.engine.rules.card_modules import card_modules, created_tokens


def creations_by_card(cards_dir: pathlib.Path = DEFAULT_CARDS_PATH) -> dict[str, set[str]]:
    """Each card id to the tokens its ``creates:`` entries name, pooled across its printings the way
    the install pipeline pools them."""
    creates: dict[str, set[str]] = collections.defaultdict(set)
    for entry in iter_set_entries(cards_dir):
        creates[entry.card_id].update(entry.creates)
    return creates


def named_tokens() -> list[tuple[str, str, str]]:
    """Every ``(module, card id, token id)`` the card modules name."""
    return [
        (module.stem, card_id, token)
        for module in card_modules()
        for card_id, token in created_tokens(module)
    ]


def test_every_token_a_card_names_is_a_real_card():
    # A token id is a card id, and a misspelled one is not a rule that fails loudly at import the way
    # a misspelled handler id does — it survives until someone activates the ability in a game whose
    # deck loaded that template, and dies there with a KeyError.
    known = read_index()
    invented = [
        f"{module}: {card_id} creates {token!r}"
        for module, card_id, token in named_tokens()
        if token not in known
    ]

    assert invented == []


def test_every_token_a_card_names_is_one_that_card_creates():
    # The database says which token each card makes, and several cards offer more than one candidate
    # (Colonial Farm names three Ashigaru). Picking one is a judgement call; picking one from the
    # wrong card is a bug, and only the data can tell them apart.
    creates = creations_by_card()
    mismatched = [
        f"{module}: {card_id} names {token!r}, which it does not create"
        for module, card_id, token in named_tokens()
        if token not in creates.get(card_id, set())
    ]

    assert mismatched == []


def test_the_scan_finds_the_tokens_the_engine_creates():
    # Guards both tests above: a scan that silently found nothing would pass them vacuously. The
    # count is a floor rather than an exact number so implementing a card does not fail this test.
    assert len(named_tokens()) >= 12


@pytest.mark.parametrize(
    "module, card_id, token",
    [
        ("shattered_empire", "weapon_artist", "weapon_item_sword_plus2f_plus1c"),
        ("shattered_empire", "hida_sanjiro", "armor_item_plus2f"),
        ("rise_of_jigoku", "mishime_sensei", "oni_personality_variable_chi"),
        ("rise_of_otosan_uchi", "culling_grounds", "expendable_personality_0_2_1"),
    ],
)
def test_the_scan_attributes_a_token_to_the_card_whose_block_names_it(module, card_id, token):
    # The attribution is by source position, so a module holding several creating cards is where it
    # would go wrong — and every module above holds at least two.
    assert (module, card_id, token) in named_tokens()
