from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.effects import RefillProvince
from yasuki_core.engine.rules.events import Revealed, TurnStarted
from yasuki_core.engine.rules.flow import begin_game
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import DynastyPrint

from tests.yasuki_core.engine.builders import holding, province_card, put_in_play, two_seat_game

P1 = PlayerId.P1
PROVINCE = ZoneKey(P1, ZoneRole.PROVINCE, 0)


def _watching_game():
    """A two-seat game with a card in play whose printed id carries the tests' probe triggers."""
    game = two_seat_game()
    put_in_play(game, holding("P1-eyes", owner=P1, printed_id="reveal_probe"))
    return game


def test_the_turn_start_sweep_raises_revealed_for_each_card_it_turns(reacting):
    seen = []
    reacting(Revealed, "reveal_probe", lambda ctx: seen.append(ctx.event.card_id) or [])
    game = _watching_game()
    province_card(game, "P1-a", seat=P1, face_up=False, index=0)
    province_card(game, "P1-b", seat=P1, face_up=False, index=1)

    begin_game(game)

    # Sorted because which Province the sweep walks first is zone insertion order, not a rule.
    assert sorted(seen) == ["P1-a", "P1-b"]


def test_a_card_already_face_up_is_not_revealed_again(reacting):
    # The event names the turn, not the state, so a card the sweep leaves alone raises nothing —
    # otherwise every subscriber would fire again on each of the owner's turns.
    seen = []
    reacting(Revealed, "reveal_probe", lambda ctx: seen.append(ctx.event.card_id) or [])
    game = _watching_game()
    province_card(game, "P1-open", seat=P1, face_up=True, index=0)

    begin_game(game)

    assert seen == []


def test_a_card_arriving_face_up_is_not_a_reveal(reacting):
    # Renew refills its Province face-up, and the card arrives in that state rather than being
    # turned into it. This is the distinction the event exists to draw, and the only thing keeping
    # a refill from looking identical to a reveal is that the refill never raises one.
    seen = []
    reacting(Revealed, "reveal_probe", lambda ctx: seen.append(ctx.event.card_id) or [])
    game = _watching_game()
    game.table.zones[PROVINCE] = ProvinceZone(owner=P1)
    arriving = L5RCard.of(
        DynastyPrint, id="P1-renewed", name="Renewed", side=Side.DYNASTY, owner=P1
    )
    game.table.cards_by_id[arriving.id] = arriving
    game.table.decks[DeckKey(P1, Side.DYNASTY)].cards = [arriving]

    triggers.resolve_effects(game, [RefillProvince(PROVINCE, face_up=True)])

    assert arriving.face_up is True  # it really did arrive face-up, so the assertion below bites
    assert seen == []


def test_the_sweep_leaves_the_other_seat_alone(reacting):
    seen = []
    reacting(Revealed, "reveal_probe", lambda ctx: seen.append(ctx.event.card_id) or [])
    game = _watching_game()
    province_card(game, "P1-mine", seat=P1, face_up=False, index=0)
    province_card(game, "P2-theirs", seat=PlayerId.P2, face_up=False, index=0)

    begin_game(game)

    assert seen == ["P1-mine"]


def test_every_reveal_resolves_before_the_turn_has_started(reacting):
    # A reaction to the reveal acts during the sweep, so it must not see a board where the turn is
    # already under way — and the last card turned still precedes the turn starting.
    order = []
    reacting(Revealed, "reveal_probe", lambda ctx: order.append("revealed") or [])
    reacting(TurnStarted, "reveal_probe", lambda ctx: order.append("turn-started") or [])
    game = _watching_game()
    province_card(game, "P1-a", seat=P1, face_up=False, index=0)
    province_card(game, "P1-b", seat=P1, face_up=False, index=1)

    begin_game(game)

    assert order == ["revealed", "revealed", "turn-started"]
