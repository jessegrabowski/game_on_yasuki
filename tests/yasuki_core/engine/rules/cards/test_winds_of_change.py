import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.rulebook.favor_payment import (
    favor_cost_for_seat,
    favor_payment_options,
)
from yasuki_core.engine.rules.effects import TakeFavor
from yasuki_core.engine.rules.vocabulary.actions import (
    ActivateAbility,
    DeclareAttack,
    Pass,
    PlayStrategy,
)
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import Phase
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, Side
from yasuki_core.game_pieces.prints import ActionPrint, DynastyPrint, FatePrint
from yasuki_core.game_pieces.cards import L5RCard

from tests.yasuki_core.engine.builders import (
    end_phase,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
    terrain_at,
)

P1, P2 = PlayerId.P1, PlayerId.P2
SOURCE = "rulebook"


def _game(*, holds_favor: bool = True) -> GameState:
    """Commanding Favor in play, its controller holding the Imperial Favor unless a test says
    not."""
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

    resolve_effects(game, favor_payment_options(game, P1)["Commanding Favor"])

    assert game.favor_holder is P1, "the Event went instead of the Favor"
    discard = game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert [card.id for card in discard.cards] == ["event"]


def test_commanding_favor_is_offered_beside_the_favor_itself():
    """The seat picks between them the way it picks among Gold producers (CR, Action Sequence step
    B)."""
    game = _game()

    assert set(favor_payment_options(game, P1)) == {
        "Discard the Imperial Favor",
        "Commanding Favor",
    }


def test_commanding_favor_pays_for_a_seat_that_holds_no_favor():
    """It pays the cost rather than substituting for a discard, so it makes a Favor action legal
    for a seat with no Favor at all: what Good Faith 0.4 calls a substitute."""
    game = _game(holds_favor=False)

    assert set(favor_payment_options(game, P1)) == {"Commanding Favor"}
    assert all(effect.is_payable(game) for effect in favor_cost_for_seat(game, P1, SOURCE))


def _event_in_province() -> EngineSession:
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
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    assert session.game.phase is Phase.DYNASTY
    return session


def test_commanding_favor_leaves_its_province_for_the_battlefield():
    """RtR: "Dynasty: Put this Event into play." It leaves the Province it sits in, which refills
    behind it."""
    session = _event_in_province()

    session.act(P1, ActivateAbility("event"))

    game = session.game
    assert "event" in {card.id for card in game.table.battlefield.cards}
    province = game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)]
    assert [card.id for card in province.cards] == ["next"], "the Province refilled behind it"


def test_commanding_favor_is_offered_from_the_province_it_sits_in():
    """The ability has to declare the Province as where it is activated from, since the default is
    the battlefield."""
    session = _event_in_province()

    assert ActivateAbility("event") in session.legal_actions(P1)


def _well_prepared_in_combat(*, terrain_owner: PlayerId | None) -> EngineSession:
    """P1's ``a`` attacks P2's ``d``, with Well Prepared in P1's hand and a Terrain at the
    battlefield owned by ``terrain_owner``, or none. Paused in the Combat Segment with P1 holding
    the opportunity."""
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=P2, index=0)
    province_card(state, "def-prov1", seat=P2, index=1)
    province_card(state, "atk-prov0", seat=P1, index=0)
    put_in_play(state, personality("a", owner=P1, force=3))
    put_in_play(state, personality("d", owner=P2, force=3))
    if terrain_owner is not None:
        terrain_at(state, "ground", battlefield=0, owner=terrain_owner)
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                ActionPrint,
                id="prepared",
                name="Well Prepared",
                printed_id="well_prepared",
                side=Side.FATE,
                owner=P1,
                gold_cost=0,
            ),
        )
    )
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("a@0",)))
    session.submit(P2, DecisionResponse(("d@0",)))
    session.submit(P1, DecisionResponse(("0",)))
    for _ in range(4):
        if session.game.attack.battle_segment is BattleSegment.COMBAT:
            break
        session.act(session.game.round.priority, Pass())
    else:
        raise AssertionError("the battle never reached its Combat Segment")
    session.act(P2, Pass())
    return session


def _play_well_prepared_on(session: EngineSession, target_id: str) -> None:
    session.act(P1, PlayStrategy("prepared"))
    pay(session, P1)
    session.submit(P1, DecisionResponse((target_id,)))


@pytest.mark.parametrize("terrain_owner", [None, P2], ids=["no-terrain", "enemy-terrain"])
def test_well_prepared_is_not_offered_without_a_terrain_of_your_own(terrain_owner):
    session = _well_prepared_in_combat(terrain_owner=terrain_owner)

    assert PlayStrategy("prepared") not in session.legal_actions(P1)


def test_well_prepared_bows_a_standing_target():
    session = _well_prepared_in_combat(terrain_owner=P1)

    _play_well_prepared_on(session, "d")

    assert session.game.table.cards_by_id["d"].bowed


def test_well_prepared_straightens_a_bowed_target():
    session = _well_prepared_in_combat(terrain_owner=P1)
    session.game.table.cards_by_id["d"].bow()

    _play_well_prepared_on(session, "d")

    assert not session.game.table.cards_by_id["d"].bowed
