from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import favor_cost_for_seat, favor_payers
from yasuki_core.engine.rules.effects import TakeFavor
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, Side
from yasuki_core.game_pieces.prints import DynastyPrint, FatePrint
from yasuki_core.game_pieces.cards import L5RCard

from tests.yasuki_core.engine.builders import put_in_play, register

P1 = PlayerId.P1
SOURCE = "rulebook"


def _game(*, holds_favor: bool = True) -> GameState:
    """Commanding Favor in play, its controller holding the Imperial Favor unless a test says not."""
    game = GameState.start(TableState.empty_two_seat(), P1, seed=0)
    game.table.creatable_tokens[IMPERIAL_FAVOR_ID] = FatePrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    put_in_play(
        game,
        register(
            game.table,
            L5RCard.of(
                DynastyPrint,
                id="event",
                name="Commanding Favor",
                printed_id="commanding_favor",
                side=Side.DYNASTY,
                owner=P1,
            ),
        ),
    )
    if holds_favor:
        TakeFavor(P1).perform(game)
    return game


def test_commanding_favor_pays_by_discarding_itself():
    """ "Before you discard the Imperial Favor for a Favor action, you may discard this Event from
    play instead." Taking it leaves the Favor where it is, which is the point of the card."""
    game = _game()

    resolve_effects(game, favor_payers(game, P1)["Commanding Favor"])

    assert game.favor_holder is P1, "the Event went instead of the Favor"
    discard = game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert [card.id for card in discard.cards] == ["event"]


def test_commanding_favor_is_offered_beside_the_favor_itself():
    """The seat picks between them the way it picks among Gold producers (CR, Action Sequence step
    B)."""
    game = _game()

    assert set(favor_payers(game, P1)) == {"Discard the Imperial Favor", "Commanding Favor"}


def test_commanding_favor_pays_for_a_seat_that_holds_no_favor():
    """It pays the cost rather than substituting for a discard, so it makes a Favor action legal for
    a seat with no Favor at all — which is what Good Faith 0.4 calls a substitute."""
    game = _game(holds_favor=False)

    assert set(favor_payers(game, P1)) == {"Commanding Favor"}
    assert all(effect.is_payable(game) for effect in favor_cost_for_seat(game, P1, SOURCE))
