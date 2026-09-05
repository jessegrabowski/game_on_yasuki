from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import favor_cost_for_seat, favor_payers
from yasuki_core.engine.rules.effects import TakeFavor
from yasuki_core.engine.rules import flow, legality
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.state import PHASE_TIMINGS, ActionRound, GameState, Phase
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, Side
from yasuki_core.game_pieces.prints import DynastyPrint, FatePrint
from yasuki_core.game_pieces.cards import L5RCard

from tests.yasuki_core.engine.builders import province_card, put_in_play, register

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


def _event_in_province() -> GameState:
    """Commanding Favor face-up in P1's first Province, with a card behind it to refill from."""
    state = TableState.empty_two_seat()
    event = register(
        state,
        L5RCard.of(
            DynastyPrint,
            id="event",
            name="Commanding Favor",
            printed_id="commanding_favor",
            side=Side.DYNASTY,
            owner=P1,
        ),
    )
    event.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(event)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(state, province_card(state, "next", seat=P1, index=1))
    ]
    return GameState.start(state, P1, seed=0)


def test_commanding_favor_leaves_its_province_for_the_battlefield():
    """RtR: "Dynasty: Put this Event into play." An Event is played from the Province it sits in, so
    entering play is a move out of that Province rather than out of hand, and the Province it
    vacates refills behind it like any other."""
    game = _event_in_province()

    flow.perform(game, ActivateAbility("event"))

    assert "event" in {card.id for card in game.table.battlefield.cards}
    province = game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)]
    assert [card.id for card in province.cards] == ["next"], "the Province refilled behind it"


def test_commanding_favor_is_offered_from_the_province_it_sits_in():
    """An Event is activated where it sits, face-up in a Province, so its ability has to say so —
    the default is the battlefield, where an Event on offer never is, and the action would simply
    never appear."""
    game = _event_in_province()
    game.phase = Phase.DYNASTY
    game.round = ActionRound(timings=PHASE_TIMINGS[Phase.DYNASTY], priority=P1)

    assert ActivateAbility("event") in legality.legal_actions(game, P1)
