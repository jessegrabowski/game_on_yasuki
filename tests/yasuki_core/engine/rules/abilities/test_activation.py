from collections.abc import Callable

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import interrupts, legality
from yasuki_core.engine.rules.abilities.activation import defer_ability
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, Interrupt, Interruption, TargetGroup
from yasuki_core.engine.rules.abilities.registry import ability_for
from yasuki_core.engine.rules.board.queries import (
    opposing_units_in_battle,
    owned_personalities,
    personalities_in_play,
)
from yasuki_core.engine.rules.effects import Bow, Effect, GainHonor, GrantModifier, Move
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.turn.sequence import run_stack
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    Pass,
    PlayInterrupt,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    DecisionResponse,
    PickedTargets,
    TotalAtMost,
)
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import Location, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import (
    combat_segment,
    holding,
    personality,
    put_in_play,
    two_seat_game,
)
from tests.yasuki_core.engine.rules.conftest import probe_ability, probe_interrupt

# Imported for the ``substitute_probe`` Interrupt its module registers, which answers a
# ResolveAbility by pointing the action at another card.
from tests.yasuki_core.engine.rules.test_interrupts import _strategy

P1, P2 = PlayerId.P1, PlayerId.P2

GROUPED_PROBE = "grouped_target_probe"
HEAVY_PAIR_PROBE = "heavy_pair_probe"
HEAVY_PAIR_BOUND = 4
STALE_PROBE = "stale_bound_probe"
STALE_PENALTY = -3


def _enemy_personalities(game: GameState, source: L5RCard, picked: PickedTargets) -> list[str]:
    return [
        card.id
        for seat in game.table.seats
        if seat is not source.owner
        for card in owned_personalities(game, seat)
    ]


def _grouped_ability() -> Ability:
    """One "target" phrase declared as a group, taking one or two enemy Personalities and bowing
    them."""
    return Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: bow one or two target enemy Personalities",
        cost=lambda game, source: [],
        target_groups=(
            TargetGroup(
                candidates=_enemy_personalities,
                count=lambda game, source, picked, offered: (1, 2),
            ),
        ),
        effects=lambda game, source, target: [Bow(target.id)],
    )


def test_one_card_targeted_by_a_declared_group_is_held_as_the_actions_targeting():
    game = two_seat_game()
    source = put_in_play(game, holding("P2-src", owner=P2, printed_id=GROUPED_PROBE))
    put_in_play(game, personality("P1-victim"))
    put_in_play(game, personality("P1-stand-in"))
    _strategy(game.table, "P1-sub", "substitute_probe", P1, gold_cost=0)
    game.action = ActivateAbility(source.id)
    game.action_seat = P2

    with probe_ability(GROUPED_PROBE, _grouped_ability()):
        defer_ability(game, source, ability_for(game, source), plays_card=False)
        run_stack(game)
        submit(game, DecisionResponse(("P1-victim",)))

        assert legality.legal_actions(game, P1) == [Pass(), PlayInterrupt("P1-sub")]
        assert [effect.describe() for effect in interrupts.foreseen_now(game)] == [
            "P2-src targets P1-victim",
            "bow P1-victim",
        ]


def _stale_bound_ability() -> Ability:
    """A phrase whose ceiling is read off the source's own Force, which its cost then lowers."""
    return Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: lower this card's Force to bow a Personality it still outweighs",
        cost=lambda game, source: [
            GrantModifier(
                source.id, source.id, Stat.FORCE, STALE_PENALTY, Duration.UNTIL_END_OF_TURN
            )
        ],
        target_groups=(
            TargetGroup(
                candidates=lambda game, source, picked: [
                    card.id for card in personalities_in_play(game) if card is not source
                ],
                limits=lambda game, source, picked: (
                    TotalAtMost(
                        tuple(
                            (card.id, effective_force(game, card))
                            for card in personalities_in_play(game)
                        ),
                        effective_force(game, source) - 1,
                    ),
                ),
            ),
        ),
        effects=lambda game, source, target: [Bow(target.id)],
    )


def test_a_cost_that_lowers_the_ceiling_drops_the_candidates_it_shuts_out():
    # The candidates are fixed before the cost is paid and the limits are read after it, so asking
    # for a candidate the cost shut out would strand the seat on a question with no legal answer.
    game = two_seat_game()
    source = put_in_play(game, personality("P1-src", printed_id=STALE_PROBE, force=6))
    put_in_play(game, personality("P2-heavy", owner=P2, force=4))
    game.action = ActivateAbility(source.id)
    game.action_seat = P1

    with probe_ability(STALE_PROBE, _stale_bound_ability()):
        ability = ability_for(game, source)
        # Force 6 bounds the set at 5, so the 4F Personality is on offer when the action is
        # announced; paying leaves Force 3 and a bound of 2, which it no longer fits.
        assert legality.legal_targets(game, source, ability) == ["P2-heavy"]

        defer_ability(game, source, ability, plays_card=False)
        run_stack(game)

        assert game.pending is None
        assert not game.table.cards_by_id["P2-heavy"].bowed


def _heavy_pair_ability() -> Ability:
    """A phrase taking two Personalities whose total Force must stay under five."""
    return Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: bow two target Personalities with total Force less than 5",
        cost=lambda game, source: [],
        target_groups=(
            TargetGroup(
                candidates=_enemy_personalities,
                count=lambda game, source, picked, offered: (2, 2),
                limits=lambda game, source, picked: (
                    TotalAtMost(
                        tuple(
                            (card.id, effective_force(game, card))
                            for card in personalities_in_play(game)
                        ),
                        HEAVY_PAIR_BOUND,
                    ),
                ),
            ),
        ),
        effects=lambda game, source, target: [Bow(target.id)],
    )


def test_a_phrase_whose_limits_seat_no_pair_is_not_offered():
    # Every candidate passes the limit alone, and no pair does. Asking would put a question in
    # front of the seat with nothing it could confirm.
    game = two_seat_game()
    source = put_in_play(game, holding("P1-src", owner=P1, printed_id=HEAVY_PAIR_PROBE))
    for card_id in ("P2-one", "P2-two", "P2-three"):
        put_in_play(game, personality(card_id, owner=P2, force=3))

    with probe_ability(HEAVY_PAIR_PROBE, _heavy_pair_ability()):
        ability = ability_for(game, source)

        assert legality.legal_targets(game, source, ability) == ["P2-one", "P2-two", "P2-three"]
        assert legality.phrases_reachable(game, source, ability) is False
        assert ActivateAbility("P1-src") not in legality.legal_actions(game, P1)


def test_a_phrase_whose_limits_seat_a_pair_is_offered():
    game = two_seat_game()
    source = put_in_play(game, holding("P1-src", owner=P1, printed_id=HEAVY_PAIR_PROBE))
    put_in_play(game, personality("P2-light", owner=P2, force=1))
    put_in_play(game, personality("P2-heavy", owner=P2, force=3))  # 1 + 3 fits the bound of 4

    with probe_ability(HEAVY_PAIR_PROBE, _heavy_pair_ability()):
        ability = ability_for(game, source)

        assert legality.phrases_reachable(game, source, ability) is True
        assert ActivateAbility("P1-src") in legality.legal_actions(game, P1)


SEND_HOME = Interrupt(
    answers=Bow,
    interrupt=lambda game, source, bow: Interruption(
        bow, effects=(Move(bow.card_id, Location.home(P2)),)
    ),
)
LET_BE = Interrupt(answers=Bow, interrupt=lambda game, source, bow: Interruption(bow))


def _gain_honor(target: L5RCard) -> Effect:
    return GainHonor(P1, 1)


def _send_home(target: L5RCard) -> Effect:
    return Move(target.id, Location.home(P2))


def _bow_an_enemy(*effects_before_the_bow: Callable[[L5RCard], Effect]) -> Ability:
    return Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=lambda game, source: list(opposing_units_in_battle(game, source.owner)),
        effects=lambda game, source, target: [
            *(make(target) for make in effects_before_the_bow),
            Bow(target.id),
        ],
    )


def _interrupted_bow(ability: Ability, interrupt: Interrupt) -> EngineSession:
    """P1's raider takes ``ability`` against P2's guard, and P2 answers the Bow with
    ``interrupt``."""
    probe = L5RCard.of(
        ActionPrint,
        id="probe",
        name="probe",
        printed_id="step_e_interrupt_probe",
        side=Side.FATE,
        owner=P2,
    )
    cards = [
        personality("raider", printed_id="step_e_probe", force=3),
        personality("guard", owner=P2, force=2),
    ]
    with (
        probe_ability("step_e_probe", ability),
        probe_interrupt("step_e_interrupt_probe", interrupt),
    ):
        session = combat_segment(cards, {"raider": 0}, {"guard": 0}, in_hand=[probe])
        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("guard",)))
        session.act(P2, PlayInterrupt("probe"))
    return session


@pytest.mark.parametrize(
    ("interrupt", "bowed"), [(SEND_HOME, False), (LET_BE, True)], ids=["send_home", "let_be"]
)
def test_a_target_an_interrupt_left_illegal_stops_the_effects_that_require_it(interrupt, bowed):
    session = _interrupted_bow(_bow_an_enemy(_gain_honor), interrupt)

    game = session.game
    assert game.table.seats[P1].honor == 1
    assert game.table.cards_by_id["guard"].bowed is bowed


def test_a_target_the_action_itself_moves_still_takes_the_rest_of_its_effects():
    session = _interrupted_bow(_bow_an_enemy(_send_home), LET_BE)

    guard = session.game.table.cards_by_id["guard"]
    assert location_of(session.game.table, guard).is_home
    assert guard.bowed
