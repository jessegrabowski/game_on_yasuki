from numpy.random import default_rng

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import StrongholdPrint
from yasuki_core.game_setup import build_state_from_deck

# The only real decklist in the repo is the one the desktop client bundles. Core has no deck asset
# of its own, and inventing one to avoid the import would be a second thing to keep current.
from yasuki_gui.session import DEMO_DECK_PATH

from tests.yasuki_core.db_guard import requires_db

pytestmark = requires_db

DECKS = DEMO_DECK_PATH.parent


def _hand_ids(state, seat: PlayerId = PlayerId.P1) -> tuple[str, ...]:
    return tuple(card.id for card in state.zones[ZoneKey(seat, ZoneRole.HAND)].cards)


def _provinces(state, seat):
    return [k for k in state.zones if k.owner is seat and k.role is ZoneRole.PROVINCE]


def test_bundled_deck_deals_both_seats():
    state, _ = build_state_from_deck(DEMO_DECK_PATH, rng=default_rng(7))
    for seat in PlayerId:
        assert len(_provinces(state, seat)) == 4
        assert state.zones[ZoneKey(seat, ZoneRole.HAND)].cards
        assert state.decks[DeckKey(seat, Side.DYNASTY)].cards
        assert state.decks[DeckKey(seat, Side.FATE)].cards


def test_a_separate_opponent_deck_still_deals_both_seats():
    # The two decks resolve independently; passing the opponent path explicitly (here the same
    # bundled deck) still yields a fully dealt two-seat table.
    state, _ = build_state_from_deck(
        DEMO_DECK_PATH, opponent_deck_path=DEMO_DECK_PATH, rng=default_rng(7)
    )
    for seat in PlayerId:
        assert len(_provinces(state, seat)) == 4
        assert state.decks[DeckKey(seat, Side.DYNASTY)].cards


def test_a_mirror_match_resolves_the_deck_once(monkeypatch):
    # Both seats share a decklist, so the card lookup should happen once. Resolving twice is a
    # second round trip to the database for an answer already in hand.
    import yasuki_core.game_setup as game_setup

    real = game_setup.get_cards_by_names
    calls = []

    def counting(names):
        calls.append(names)
        return real(names)

    monkeypatch.setattr(game_setup, "get_cards_by_names", counting)
    build_state_from_deck(DEMO_DECK_PATH, opponent_deck_path=DEMO_DECK_PATH, rng=default_rng(7))

    assert len(calls) == 1


def test_bundled_deck_resolves_art_swaps():
    # The spider deck carries {art: ...} entries; resolving them against the DB attaches art_swap
    # payloads, the data the renderer needs for a custom printing.
    state, _ = build_state_from_deck(DEMO_DECK_PATH, rng=default_rng(7))
    assert any(card.art_swap for card in state.cards_by_id.values())


def test_the_same_seed_deals_the_same_board():
    first, first_leads = build_state_from_deck(DEMO_DECK_PATH, rng=default_rng(42))
    second, second_leads = build_state_from_deck(DEMO_DECK_PATH, rng=default_rng(42))

    assert _hand_ids(first) == _hand_ids(second)
    # Turn order is drawn from the same generator, so it reproduces with the hands or not at all.
    assert first_leads is second_leads


def test_a_different_seed_deals_a_different_board():
    """What a Monte Carlo run varies. Without this the harness would run the same game N times and
    report a distribution with no spread."""
    first, _ = build_state_from_deck(DEMO_DECK_PATH, rng=default_rng(42))
    second, _ = build_state_from_deck(DEMO_DECK_PATH, rng=default_rng(43))

    assert _hand_ids(first) != _hand_ids(second)


def test_dealing_without_a_seed_varies_between_games():
    """A repeated opening is a defect in a game, so the default draws from system entropy. Ten
    deals of a 40-card deck colliding by chance is far beyond negligible."""
    deals = {_hand_ids(build_state_from_deck(DEMO_DECK_PATH)[0]) for _ in range(10)}

    assert len(deals) > 1


def _stronghold(state, seat):
    return next(
        card
        for card in state.battlefield.cards
        if card.owner is seat and isinstance(card.printed, StrongholdPrint)
    )


def test_the_lower_honor_seat_goes_second_with_its_stronghold_flipped():
    """Turn order belongs to the deal, not to whichever client happens to run it, so both the
    desktop and the web surface get it from here."""
    lion = DECKS / "lion_starter.yaml"
    state, first = build_state_from_deck(
        DEMO_DECK_PATH, opponent_deck_path=lion, rng=default_rng(7)
    )

    second = PlayerId.P2 if first is PlayerId.P1 else PlayerId.P1
    assert state.seats[second].honor < state.seats[first].honor
    assert _stronghold(state, second).showing_back
    assert not _stronghold(state, first).showing_back


def test_a_mirror_match_still_settles_turn_order():
    """Equal honor is the common case for a mirror, and it is drawn rather than defaulted — so one
    seat still goes second with its stronghold flipped."""
    state, first = build_state_from_deck(
        DEMO_DECK_PATH, opponent_deck_path=DEMO_DECK_PATH, rng=default_rng(7)
    )

    second = PlayerId.P2 if first is PlayerId.P1 else PlayerId.P1
    assert state.seats[first].honor == state.seats[second].honor
    assert _stronghold(state, second).showing_back
    assert not _stronghold(state, first).showing_back
