from pathlib import Path

import pytest
from numpy.random import default_rng

from yasuki_core.engine.players import PlayerId
from yasuki_core.game_pieces.prints import StrongholdPrint
from yasuki_gui.services.game_host import GameHost
from yasuki_gui.session import DEMO_DECK_PATH

# The bundled Spider deck opens at -2 Family Honor and the Crane deck at 5, so a pairing of the two
# decides turn order outright rather than drawing for it.
LOW_HONOR = DEMO_DECK_PATH
HIGH_HONOR = DEMO_DECK_PATH.parent / "crane_dishonor.yaml"
MISSING = DEMO_DECK_PATH.parent / "no_such_deck.yaml"


def _host(human: Path = LOW_HONOR, opponent: Path = HIGH_HONOR) -> GameHost:
    return GameHost(human, opponent, rng=default_rng(7))


def _stronghold_name(host: GameHost, seat: PlayerId) -> str:
    return next(
        card.name
        for card in host.session.game.table.battlefield.cards
        if card.owner is seat and isinstance(card.printed, StrongholdPrint)
    )


def test_it_deals_a_game_on_construction():
    host = _host()

    assert host.runner is not None
    assert host.session.game.table.battlefield


def test_the_higher_honor_deck_takes_the_first_turn():
    host = _host(human=HIGH_HONOR, opponent=LOW_HONOR)

    assert host.session.game.first_player is host.human_seat


def test_loading_a_deck_deals_a_new_game_from_it():
    host = _host()
    before = _stronghold_name(host, PlayerId.P2)

    host.load_opponent_deck(LOW_HONOR)

    assert _stronghold_name(host, PlayerId.P2) != before


def test_loading_a_deck_replaces_the_runner():
    host = _host()
    before = host.runner

    host.load_human_deck(HIGH_HONOR)

    assert host.runner is not before


def test_a_deck_that_cannot_be_read_leaves_the_game_running():
    host = _host()
    before = host.runner

    with pytest.raises(FileNotFoundError):
        host.load_opponent_deck(MISSING)

    assert host.runner is before


def test_a_failed_load_does_not_strand_the_next_one_on_the_bad_deck():
    """The slot rolls back, so a later reload of the other seat deals the pairing that was there
    before rather than retrying the deck that failed."""
    host = _host()

    with pytest.raises(FileNotFoundError):
        host.load_opponent_deck(MISSING)
    host.load_human_deck(HIGH_HONOR)

    # The opponent is back on the Crane deck it held before the failed load, not on the missing one.
    assert _stronghold_name(host, PlayerId.P2) == _stronghold_name(host, PlayerId.P1)


def test_an_unreadable_opening_falls_back_to_the_placeholder_decks():
    """The client still has to open without a database, so the opening deal degrades where a
    deliberate deck load raises."""
    host = GameHost(MISSING, MISSING, rng=default_rng(7))

    assert _stronghold_name(host, PlayerId.P1) == "P1 Stronghold"


class _BrokenRng:
    """A generator that fails the way a defect does rather than the way a missing database does."""

    def spawn(self, count):
        raise TypeError("not a real generator")


def test_a_defect_in_the_deal_is_not_hidden_by_the_fallback():
    """The opening deal degrades for an unreachable database or an unreadable decklist and for
    nothing else, so a broken deal surfaces instead of opening on placeholder cards."""
    with pytest.raises(TypeError):
        GameHost(LOW_HONOR, HIGH_HONOR, rng=_BrokenRng())
