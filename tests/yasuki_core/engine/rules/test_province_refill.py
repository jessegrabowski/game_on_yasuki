import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.effects import RefillProvince
from yasuki_core.engine.rules.events import CardDiscarded, EnteredPlay
from yasuki_core.engine.rules.flow import dynasty_discard, recruit, run_stack, submit
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyCard

from tests.yasuki_core.engine.builders import holding, province_card, put_in_play, two_seat_game

P1 = PlayerId.P1
PROVINCE = ZoneKey(P1, ZoneRole.PROVINCE, 0)
DYNASTY = DeckKey(P1, Side.DYNASTY)


@pytest.fixture
def reacting():
    """Register triggers for one test and clear them afterwards.

    `_TRIGGERS` is module-global and appends, so a leaked registration fires in every later test in
    the process. The fixture owns that hygiene; each test still writes its own reaction inline.
    """
    registered: list[tuple[type, str]] = []

    def _register(event: type, printed_id: str, trigger):
        triggers.on(event, printed_id)(trigger)
        registered.append((event, printed_id))

    yield _register
    for event, printed_id in registered:
        triggers._TRIGGERS[event].pop(printed_id, None)


def _game(spares: int = 1):
    """A seat with one card in Province 0, a watcher in play, and ``spares`` in the dynasty deck."""
    game = two_seat_game()
    put_in_play(game, holding("P1-eyes", owner=P1, printed_id="refill_probe"))
    province_card(game, "P1-victim", seat=P1, gold_cost=0)
    deck = [
        DynastyCard(id=f"P1-spare{index}", name="Spare", side=Side.DYNASTY, owner=P1)
        for index in range(spares)
    ]
    game.table.decks[DYNASTY].cards = deck
    game.table.cards_by_id.update({card.id: card for card in deck})
    return game


def test_a_reaction_to_a_discard_sees_the_province_still_empty(reacting):
    """The rules resolve what the card leaving triggered before refilling, so a reaction that reads
    the Province must not already see its replacement."""
    seen = []
    reacting(CardDiscarded, "refill_probe", lambda ctx: seen.append(_held(ctx)) or [])
    game = _game()

    dynasty_discard(game, "P1-victim")
    run_stack(game)

    assert seen == [0]


def test_a_reaction_to_entering_play_sees_the_province_still_empty(reacting):
    """The same ordering on the recruit path, which drains through `submit` rather than `perform`
    and announces entering play rather than a discard."""
    seen = []
    reacting(EnteredPlay, "entering_probe", lambda ctx: seen.append(_held(ctx)) or [])
    game = two_seat_game()  # not _game(): its watcher would react to this card entering too
    province_card(game, "P1-bought", seat=P1, printed_id="entering_probe", gold_cost=0)

    recruit(game, "P1-bought")
    submit(game, DecisionResponse(()))

    assert seen == [0]


def test_the_province_refills_once_the_reactions_are_done():
    game = _game()

    dynasty_discard(game, "P1-victim")
    run_stack(game)

    assert [card.id for card in game.table.zones[PROVINCE].cards] == ["P1-spare0"]
    assert game.table.decks[DYNASTY].cards == []


def test_a_reaction_that_refills_first_leaves_nothing_to_refill(reacting):
    """ "Unless something else has refilled it" — the refill is conditional, so a reaction that
    filled the gap itself is not doubled up on."""
    reacting(CardDiscarded, "refill_probe", lambda ctx: [RefillProvince(PROVINCE)])
    game = _game(spares=2)

    dynasty_discard(game, "P1-victim")
    run_stack(game)

    assert len(game.table.zones[PROVINCE].cards) == 1  # not two
    assert len(game.table.decks[DYNASTY].cards) == 1  # only one card was drawn


def _held(ctx) -> int:
    return len(ctx.game.table.zones[PROVINCE].cards)
