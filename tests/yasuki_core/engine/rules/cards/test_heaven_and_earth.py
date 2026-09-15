from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.effects import AttachCard, Dishonor
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility, Equip
from yasuki_core.engine.rules.vocabulary.decisions import ChooseInterrupt, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    holding,
    pay,
    personality,
    put_in_play,
    register,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2

DISHONOR_PROBE = "probe_open_dishonor_an_enemy"


DISHONOR_ABILITY = Ability(
    timings=(ActionTiming.OPEN,),
    label="Open: dishonor a target enemy Personality",
    cost=no_cost,
    targets=lambda game, source: [
        card.id for card in personalities_in_play(game) if card.owner is not source.owner
    ],
    effects=lambda game, source, target: [Dishonor(target.id, source.owner)],
)


def _blessed_sword():
    return attachment(
        "sword",
        printed_id="blessed_sword",
        attachment_type=AttachmentType.ITEM,
        force_modifier=1,
        gold_cost=2,
        keywords=("Weapon", "One-Handed", "Sword"),
    )


def test_equipping_the_sword_gains_an_honor():
    state = TableState.empty_two_seat()
    put_in_play(state, personality("bearer"))
    put_in_play(state, holding("mine", gold_production=2))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, _blessed_sword()))
    session = EngineSession.start(state, P1)

    session.act(P1, Equip("sword"))
    session.submit(P1, DecisionResponse(("bearer",)))
    pay(session, P1)

    assert session.game.table.seats[P1].honor == 1


def test_equipping_the_sword_to_a_dishonorable_bearer_rehonors_him_instead():
    # CR, Rehonoring 0.2: attaching to a dishonorable Personality substitutes his rehonoring for
    # the Honor gain.
    state = TableState.empty_two_seat()
    put_in_play(state, personality("bearer")).dishonor()
    put_in_play(state, holding("mine", gold_production=2))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, _blessed_sword()))
    session = EngineSession.start(state, P1)

    session.act(P1, Equip("sword"))
    session.submit(P1, DecisionResponse(("bearer",)))
    pay(session, P1)

    assert not session.game.table.cards_by_id["bearer"].dishonorable
    assert session.game.table.seats[P1].honor == 0


def test_the_sword_is_destroyed_to_negate_its_bearers_dishonoring():
    with probe_ability(DISHONOR_PROBE, DISHONOR_ABILITY):
        state = TableState.empty_two_seat()
        put_in_play(state, personality("bearer"))
        attached(state, _blessed_sword(), "bearer")
        put_in_play(state, personality("courtier", owner=P2, printed_id=DISHONOR_PROBE))
        session = EngineSession.start(state, P2)
        session.act(P2, ActivateAbility("courtier"))
        session.submit(P2, DecisionResponse(("bearer",)))
        assert isinstance(session.game.pending, ChooseInterrupt)
        assert session.game.pending.seat is P1

        session.submit(P1, DecisionResponse(("sword",)))

        game = session.game
        assert game.table.cards_by_id["bearer"].dishonorable is False
        assert "sword" not in {card.id for card in game.table.battlefield.cards}
        assert game.pending is None


def test_the_sword_is_not_offered_against_another_personalitys_dishonoring():
    with probe_ability(DISHONOR_PROBE, DISHONOR_ABILITY):
        state = TableState.empty_two_seat()
        put_in_play(state, personality("bearer"))
        attached(state, _blessed_sword(), "bearer")
        put_in_play(state, personality("bystander"))
        put_in_play(state, personality("courtier", owner=P2, printed_id=DISHONOR_PROBE))
        session = EngineSession.start(state, P2)
        session.act(P2, ActivateAbility("courtier"))

        session.submit(P2, DecisionResponse(("bystander",)))

        assert session.game.pending is None
        assert session.game.table.cards_by_id["bystander"].dishonorable is True


def test_a_sword_attached_by_an_effect_gains_nothing():
    # "After you Equip this Item": an attachment an effect makes is not an Equip.
    game = two_seat_game()
    put_in_play(game, personality("bearer"))
    sword = register(game.table, _blessed_sword())

    resolve_effects(game, [AttachCard(sword.id, "bearer")])

    assert game.table.seats[P1].honor == 0
