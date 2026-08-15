from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.effects import DestroyProvince, Discard, RefillProvince
from yasuki_core.engine.rules.events import CardDiscarded, EnteredPlay
from yasuki_core.engine.rules.flow import dynasty_discard, recruit, run_stack, submit
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import DynastyPrint

from tests.yasuki_core.engine.builders import holding, province_card, put_in_play, two_seat_game

P1 = PlayerId.P1
PROVINCE = ZoneKey(P1, ZoneRole.PROVINCE, 0)
DYNASTY = DeckKey(P1, Side.DYNASTY)


def _game(spares: int = 1):
    """A seat with one card in Province 0, a watcher in play, and ``spares`` in the dynasty deck."""
    game = two_seat_game()
    put_in_play(game, holding("P1-eyes", owner=P1, printed_id="refill_probe"))
    province_card(game, "P1-victim", seat=P1, gold_cost=0)
    deck = [
        L5RCard.of(DynastyPrint, id=f"P1-spare{index}", name="Spare", side=Side.DYNASTY, owner=P1)
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


def test_a_province_emptied_by_an_effect_refills_without_being_asked():
    """The refill is a property of the settled board, not a step each effect remembers: an effect
    that simply takes the card out of a Province — no flow path, nothing queuing a refill — leaves
    the Province short, and short Provinces refill."""
    game = _game()

    triggers.resolve_effects(game, [Discard("P1-victim", P1)])
    run_stack(game)

    assert [card.id for card in game.table.zones[PROVINCE].cards] == ["P1-spare0"]
    assert not game.table.zones[PROVINCE].cards[0].face_up


def test_a_province_stays_short_when_the_dynasty_deck_cannot_fill_it():
    """ "When possible" is the whole rule — an exhausted Dynasty deck leaves the Province empty
    rather than raising."""
    game = _game(spares=0)

    triggers.resolve_effects(game, [Discard("P1-victim", P1)])
    run_stack(game)

    assert game.table.zones[PROVINCE].cards == []


def test_both_seats_provinces_refill_not_only_the_active_one():
    """The sweep reads the board, not the turn: a Province the opponent had emptied is as short as
    the active seat's, and leaving it for the opponent's own turn would strand it whenever an
    effect on the human's turn emptied it."""
    game = _game()
    opponent_spare = L5RCard.of(
        DynastyPrint, id="P2-spare", name="Spare", side=Side.DYNASTY, owner=PlayerId.P2
    )
    game.table.decks[DeckKey(PlayerId.P2, Side.DYNASTY)].cards = [opponent_spare]
    game.table.cards_by_id[opponent_spare.id] = opponent_spare
    province_card(game, "P2-victim", seat=PlayerId.P2, gold_cost=0)
    opponents_province = ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0)

    triggers.resolve_effects(game, [Discard("P1-victim", P1), Discard("P2-victim", PlayerId.P2)])
    run_stack(game)

    assert [card.id for card in game.table.zones[PROVINCE].cards] == ["P1-spare0"]
    assert [card.id for card in game.table.zones[opponents_province].cards] == ["P2-spare"]


def test_a_destroyed_province_is_not_refilled_back_into_existence():
    """A destroyed Province is gone rather than short, so the sweep has no zone to fill."""
    game = _game()

    triggers.resolve_effects(game, [DestroyProvince(P1, PROVINCE)])
    run_stack(game)

    assert PROVINCE not in game.table.zones
    assert [card.id for card in game.table.decks[DYNASTY].cards] == ["P1-spare0"]


def _held(ctx) -> int:
    return len(ctx.game.table.zones[PROVINCE].cards)
