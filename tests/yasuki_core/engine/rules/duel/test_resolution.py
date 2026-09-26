import pytest

from dataclasses import replace

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.duel import procedure, resolution
from yasuki_core.engine.rules.duel.records import DuelStep
from yasuki_core.engine import ops
from yasuki_core.engine.rules import state_based_actions
from yasuki_core.engine.rules.effects import Ask, StartDuel
from yasuki_core.engine.rules.triggers import (
    CHOICE_RESOLVERS,
    choice_resolver,
    enforce_state_based_actions,
)
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility
from yasuki_core.engine.rules.vocabulary.game_events import CardDiscarded
from yasuki_core.engine.rules.vocabulary.decisions import (
    DECK_TOP,
    STRIKE,
    DecisionResponse,
    focus_token,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import (
    personality,
    put_in_play,
    register,
    two_seat_game,
)
from tests.yasuki_core.engine.rules.conftest import probe_ability

P1, P2 = PlayerId.P1, PlayerId.P2

DUEL_PROBE = "probe_challenge_to_a_duel_resolution"
REFUSABLE_PROBE = "probe_challenge_that_may_be_refused"


def _enemy_personalities(game, source):
    return [card.id for card in personalities_in_play(game) if card.owner is not source.owner]


DUEL_ABILITY = Ability(
    timings=(ActionTiming.OPEN,),
    label="Open: challenge a target enemy Personality to a duel",
    cost=no_cost,
    targets=_enemy_personalities,
    effects=lambda game, source, target: [StartDuel(source.id, target.id, source.id)],
)

REFUSABLE_ABILITY = Ability(
    timings=(ActionTiming.OPEN,),
    label="Open: challenge a target enemy Personality, who may refuse",
    cost=no_cost,
    targets=_enemy_personalities,
    effects=lambda game, source, target: [
        Ask(
            seat=target.owner,
            question=f"Accept {source.name}'s challenge?",
            resolver="probe_accept_challenge",
            subjects=(target.id,),
            source_id=source.id,
        )
    ],
)


def _focus_card(card_id: str, owner: PlayerId, focus: int) -> L5RCard:
    return L5RCard.of(FatePrint, id=card_id, name=card_id, side=Side.FATE, owner=owner, focus=focus)


def _duel_game(
    *,
    chi: dict[PlayerId, int] | None = None,
    force: dict[PlayerId, int] | None = None,
    duelist: tuple[PlayerId, ...] = (),
    held: tuple[L5RCard, ...] = (),
    deck: tuple[L5RCard, ...] = (),
    probe: str = DUEL_PROBE,
) -> EngineSession:
    """P1's challenger and P2's rival in play, with ``chi`` and ``force`` each, the seats in
    ``duelist`` carrying the keyword, and ``held`` and ``deck`` filed by each card's owner."""
    chi = {P1: 3, P2: 3} if chi is None else chi
    force = {P1: 2, P2: 2} if force is None else force
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        personality(
            "challenger",
            owner=P1,
            printed_id=probe,
            chi=chi[P1],
            force=force[P1],
            keywords=(keywords.DUELIST,) if P1 in duelist else (),
        ),
    )
    put_in_play(
        state,
        personality(
            "rival",
            owner=P2,
            chi=chi[P2],
            force=force[P2],
            keywords=(keywords.DUELIST,) if P2 in duelist else (),
        ),
    )
    for card in held:
        state.zones[ZoneKey(card.owner, ZoneRole.HAND)].add(register(state, card))
    for card in deck:
        state.decks[DeckKey(card.owner, Side.FATE)].cards.append(register(state, card))
    return EngineSession.start(state, P1)


def _challenge(session: EngineSession) -> None:
    session.act(P1, ActivateAbility("challenger"))
    session.submit(P1, DecisionResponse(("rival",)))


def _strike_out(session: EngineSession) -> None:
    """Strike with whichever seat is being asked, until nobody is."""
    while session.game.pending is not None:
        session.submit(session.game.pending.seat, DecisionResponse((STRIKE,)))


def test_the_higher_total_wins_the_duel():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(held=(_focus_card("P2-fv3", P2, 3),))
        _challenge(session)

        session.submit(P2, DecisionResponse((focus_token("P2-fv3"),)))
        _strike_out(session)

        outcome = session.game.duel.outcome
        assert outcome.resolved
        assert outcome.totals == {P1: 3, P2: 6}
        assert outcome.winner is P2
        assert outcome.losers == (P1,)


def test_a_tie_is_lost_by_both_personalities():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)
        _strike_out(session)

        outcome = session.game.duel.outcome
        assert outcome.totals == {P1: 3, P2: 3}
        assert outcome.winner is None
        assert set(outcome.losers) == {P1, P2}


def test_a_duelist_wins_a_tie_against_a_non_duelist():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(duelist=(P2,))
        _challenge(session)
        _strike_out(session)

        outcome = session.game.duel.outcome
        assert outcome.winner is P2
        assert outcome.losers == (P1,)


def test_two_duelists_tie_and_both_lose():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(duelist=(P1, P2))
        _challenge(session)
        _strike_out(session)

        outcome = session.game.duel.outcome
        assert outcome.winner is None
        assert set(outcome.losers) == {P1, P2}


def test_the_duel_stat_is_chi_and_a_modified_chi_counts():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(chi={P1: 5, P2: 2})
        _challenge(session)
        _strike_out(session)

        assert session.game.duel.outcome.totals == {P1: 5, P2: 2}
        assert session.game.duel.outcome.winner is P1


def test_the_duel_stat_comes_from_the_ruleset(monkeypatch):
    # A duel of Force is the CR's own example of a duel comparing another stat, and the arc's default
    # is where the engine reads it from.
    monkeypatch.setattr(ruleset, "ACTIVE", replace(ruleset.ACTIVE, duel_stat_default=Stat.FORCE))
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(chi={P1: 9, P2: 1}, force={P1: 1, P2: 4})
        _challenge(session)
        _strike_out(session)

        assert session.game.duel.outcome.totals == {P1: 1, P2: 4}
        assert session.game.duel.outcome.winner is P2


def test_the_outcome_is_recorded_while_the_focused_cards_are_still_focused():
    # The CR discards the focused cards as the duel's last step, after its outcome and after the
    # consequences that may alter it, so a consequence reads a card that is still in the area.
    game = _duel_on_a_bare_game()
    card = register(game.table, _focus_card("P2-fv1", P2, 1))
    game.table.zones[ZoneKey(P2, ZoneRole.HAND)].add(card)
    procedure.focus(game, P2, focus_token("P2-fv1"))
    procedure.strike(game, P2)

    game.stack.pop().resume(game)  # reveal
    game.stack.pop().resume(game)  # decide

    outcome = game.duel.outcome
    assert outcome.resolved and outcome.winner is P2
    assert [held.id for held in procedure.focused_cards(game, P2)] == ["P2-fv1"]
    assert game.duel.step is DuelStep.RESOLUTION

    game.stack.pop().resume(game)  # end

    assert game.duel.step is DuelStep.ENDED
    assert game.duel.outcome == outcome
    assert procedure.focused_cards(game, P2) == ()


def test_the_strike_reveals_both_stacks_before_they_are_discarded():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(
            held=(_focus_card("P2-fv1", P2, 1),), deck=(_focus_card("P1-fv2", P1, 2),)
        )
        _challenge(session)
        session.submit(P2, DecisionResponse((focus_token("P2-fv1"),)))
        session.submit(P1, DecisionResponse((DECK_TOP,)))
        _strike_out(session)

        table = session.game.table
        for card_id, seat in (("P2-fv1", P2), ("P1-fv2", P1)):
            card = table.cards_by_id[card_id]
            assert card.face_up
            assert card.peekers == frozenset()
            assert card in table.zones[ZoneKey(seat, ZoneRole.FATE_DISCARD)].cards
        assert not [key for key in table.zones if key.role is ZoneRole.FOCUS]


def test_the_discard_names_the_duels_resolution_rather_than_a_seat():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(held=(_focus_card("P2-fv1", P2, 1),))
        _challenge(session)
        session.submit(P2, DecisionResponse((focus_token("P2-fv1"),)))
        _strike_out(session)

        discards = [
            event
            for event in session.game.turn_events
            if isinstance(event, CardDiscarded) and event.card_id == "P2-fv1"
        ]
        assert [event.cause for event in discards] == [Rulebook.DUEL_RESOLUTION]


def _duel_on_a_bare_game():
    """A duel in progress on a game driven directly, with no decision pending: the state a
    state-based rule is asked about."""
    game = two_seat_game()
    put_in_play(game, personality("challenger", owner=P1))
    put_in_play(game, personality("rival", owner=P2))
    procedure.declare_duel(
        game,
        challenger_duelist="challenger",
        challenged_duelist="rival",
        source="challenger",
    )
    return game


def test_a_duelist_off_the_board_ends_the_duel_without_resolution():
    game = _duel_on_a_bare_game()
    ops.remove_card(game.table, game.table.cards_by_id["rival"])

    enforce_state_based_actions(game)

    duel = game.duel
    assert duel.step is DuelStep.ENDED
    assert duel.outcome == (None, (), {}, False)
    # The focusing loop does not pick up again on a duel that has ended.
    assert game.stack == []
    assert not [key for key in game.table.zones if key.role is ZoneRole.FOCUS]


def test_a_duel_both_duelists_are_still_in_demands_nothing():
    game = _duel_on_a_bare_game()

    assert state_based_actions.duelist_left_play(game) == []


def test_an_ended_duel_demands_nothing_further():
    game = _duel_on_a_bare_game()
    ops.remove_card(game.table, game.table.cards_by_id["rival"])
    enforce_state_based_actions(game)

    assert state_based_actions.duelist_left_play(game) == []


def test_a_duel_that_ended_early_drops_its_own_steps_and_nothing_else():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(held=(_focus_card("P2-fv1", P2, 1),))
        _challenge(session)
        # A step of the action that created the duel, stacked above the duel's own work.
        marker = object()
        session.game.stack.append(marker)

        resolution.end_without_resolution(session.game)

        assert session.game.stack == [marker]


def test_a_refused_challenge_starts_no_duel():
    @choice_resolver("probe_accept_challenge")
    def _accept(game, source_id, chosen, seat):
        return [StartDuel(source_id, chosen[0], source_id)] if chosen else []

    try:
        with probe_ability(REFUSABLE_PROBE, REFUSABLE_ABILITY):
            session = _duel_game(probe=REFUSABLE_PROBE)
            _challenge(session)

            session.submit(P2, DecisionResponse(()))

            assert session.game.duel is None
            assert not [key for key in session.game.table.zones if key.role is ZoneRole.FOCUS]
    finally:
        CHOICE_RESOLVERS.pop("probe_accept_challenge", None)


def test_an_accepted_challenge_opens_the_focusing():
    @choice_resolver("probe_accept_challenge")
    def _accept(game, source_id, chosen, seat):
        return [StartDuel(source_id, chosen[0], source_id)] if chosen else []

    try:
        with probe_ability(REFUSABLE_PROBE, REFUSABLE_ABILITY):
            session = _duel_game(probe=REFUSABLE_PROBE, held=(_focus_card("P2-fv1", P2, 1),))
            _challenge(session)

            session.submit(P2, DecisionResponse(("rival",)))

            assert session.game.duel is not None
            assert session.game.duel.step is DuelStep.FOCUSING
    finally:
        CHOICE_RESOLVERS.pop("probe_accept_challenge", None)


def test_a_duel_step_outside_a_duel_is_refused():
    session = _duel_game()

    with pytest.raises(RuntimeError, match="no duel"):
        resolution.DecideTheDuel().resume(session.game)


def test_a_duel_step_is_refused_once_the_duel_has_ended():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)
        _strike_out(session)

        # The record stays on the game, so a step that escaped the early exit would otherwise find
        # a duel to act on and overwrite its outcome.
        with pytest.raises(RuntimeError, match="no duel"):
            resolution.EndTheDuel().resume(session.game)
