import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.duel.focusing import focused_cards
from yasuki_core.engine.rules.duel.procedure import (
    OfferFocusOrStrike,
    OpenDuelWindow,
    declare_duel,
)
from yasuki_core.engine.rules.duel.records import DuelWork
from yasuki_core.engine.rules.triggers import apply_effect, enforce_state_based_actions
from yasuki_core.engine.rules.effects import DelayedEffect, Destroy, Effect, GainHonor
from yasuki_core.engine.rules.turn.structure import DUEL_CONSEQUENCES, RoundKind
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility, Pass
from yasuki_core.engine.rules.vocabulary.segments import Boundary, DuelStep
from yasuki_core.engine.rules.vocabulary.decisions import (
    STRIKE,
    ChooseAbilityTarget,
    DecisionResponse,
    FocusOrStrike,
    focus_token,
)
from yasuki_core.engine.rules.vocabulary.game_events import (
    CardFocused,
    DuelDeclared,
    DuelEnded,
    DuelResolved,
    FocusedCardsRevealed,
    FocusEffectsResolved,
    HonorChanged,
    StrikeDeclared,
)
from yasuki_core.engine.rules.projection import project
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole

from tests.yasuki_core.engine.builders import (
    focus_card,
    holding,
    personality,
    put_in_play,
    register,
    two_seat_game,
)
from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.rules.duel.conftest import (
    CHALLENGE_ABILITY,
    CHALLENGE_PROBE,
    enemy_personalities,
)

P1, P2 = PlayerId.P1, PlayerId.P2

HOOK_PROBE = CHALLENGE_PROBE
DUEL_ABILITY = CHALLENGE_ABILITY


def _duel_game(
    *,
    chi: dict[PlayerId, int] | None = None,
    responder: str | None = None,
    armed: tuple[PlayerId, ...] = (P2,),
) -> EngineSession:
    """P1's challenger and P2's rival in play with ``chi`` each, each seat holding two cards of
    Focus Value 1.

    ``responder`` puts a holding each seat in ``armed`` can take a Response from into play before
    the game starts, as ``parry-<seat>``. Which seats hold one decides who a duel window opens on,
    so arming both is what tells a window that names its first actor correctly from one that does
    not.
    """
    chi = {P1: 3, P2: 3} if chi is None else chi
    state = TableState.empty_two_seat()
    put_in_play(state, personality("challenger", owner=P1, printed_id=HOOK_PROBE, chi=chi[P1]))
    put_in_play(state, personality("rival", owner=P2, chi=chi[P2]))
    if responder is not None:
        for seat in armed:
            put_in_play(state, holding(f"parry-{seat.name}", printed_id=responder, owner=seat))
    for seat in PlayerId:
        for index in range(2):
            card = register(state, focus_card(f"{seat.name}-fv{index}", seat, 1))
            state.zones[ZoneKey(seat, ZoneRole.HAND)].add(card)
    return EngineSession.start(state, P1)


def _challenge(session: EngineSession) -> None:
    """Take the probe action that puts challenger and rival in a duel."""
    session.act(P1, ActivateAbility("challenger"))
    session.submit(P1, DecisionResponse(("rival",)))


def _fought(session: EngineSession) -> None:
    """Focus one card each, then strike with P2."""
    session.submit(P2, DecisionResponse((focus_token("P2-fv0"),)))
    session.submit(P1, DecisionResponse((focus_token("P1-fv0"),)))
    session.submit(P2, DecisionResponse((STRIKE,)))


def _events(session: EngineSession, kind: type) -> list:
    return [event for event in session.game.turn_events if isinstance(event, kind)]


def test_declaring_a_duel_announces_the_window_and_then_the_duel():
    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)

        declared = _events(session, DuelDeclared)
        assert [(event.challenger, event.challenged) for event in declared] == [(P1, P2), (P1, P2)]
        assert [event.challenger_duelist for event in declared] == ["challenger"] * 2
        assert declared[0].source_card_id == "challenger"
        # The window is announced first, so a card acting in it acts before the duel is declared.
        assert [event.boundary for event in declared] == [Boundary.BEGINNING, Boundary.END]


def test_each_focus_and_the_strike_are_announced():
    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)
        _fought(session)

        assert [
            (event.seat, event.card_id, event.focused) for event in _events(session, CardFocused)
        ] == [
            (P2, "P2-fv0", 1),
            (P1, "P1-fv0", 1),
        ]
        assert [event.seat for event in _events(session, StrikeDeclared)] == [P2]


def test_the_reveal_names_both_seats_cards():
    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)
        _fought(session)

        revealed = _events(session, FocusedCardsRevealed)
        assert [event.revealed for event in revealed] == [
            frozenset({(P2, "P2-fv0"), (P1, "P1-fv0")})
        ]


def test_the_resolution_carries_the_totals():
    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game(chi={P1: 2, P2: 5})
        _challenge(session)
        _fought(session)

        resolved = _events(session, DuelResolved)[0]
        assert resolved.winners == frozenset({P2})
        assert resolved.losers == frozenset({P1})
        # One focused card worth 1 on top of each Chi.
        assert resolved.totals == frozenset({(P1, 3), (P2, 6)})


def test_the_declaration_carries_the_stats_the_duelists_entered_on():
    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game(chi={P1: 2, P2: 5})
        _challenge(session)

        declared = _events(session, DuelDeclared)[0]
        assert (declared.challenger_stat, declared.challenged_stat) == (2, 5)


def test_a_reaction_to_the_resolution_reads_the_stats_off_the_declaration(reacting):
    # What Ring of Fire does: it reacts to winning a duel and asks whether its Personality entered
    # with the lower duel stat. The record keeps no such field, so the reaction reads the duel's
    # declaration back out of the turn's own history while it resolves.
    entered: list[tuple[int, int]] = []

    def _read_the_declaration(ctx) -> list:
        declared = next(
            past for past in reversed(ctx.game.turn_events) if isinstance(past, DuelDeclared)
        )
        entered.append((declared.challenger_stat, declared.challenged_stat))
        return []

    reacting(DuelResolved, HOOK_PROBE, _read_the_declaration)

    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game(chi={P1: 2, P2: 5})
        _challenge(session)
        # The focused cards move the totals without touching what either Personality entered on.
        _fought(session)

    assert entered == [(2, 5)]
    assert session.game.duel.outcome.totals == {P1: 3, P2: 6}


def test_the_declaration_window_opens_before_the_first_option_is_put(reacting):
    # The duel queues the first option and then announces the window, so that whatever a card does
    # in the window resolves before either seat is asked to focus.
    pending_when_the_window_fired: list = []

    def _read_the_pending_request(ctx) -> list:
        pending_when_the_window_fired.append(ctx.game.pending)
        return []

    reacting(DuelDeclared, HOOK_PROBE, _read_the_pending_request, boundary=Boundary.BEGINNING)

    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)

        assert pending_when_the_window_fired == [None]
        assert session.game.pending.seat is P2


def test_a_resolved_duel_announces_its_steps_in_the_crs_order():
    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)
        _fought(session)

        ended = _events(session, DuelEnded)
        assert [event.resolved for event in ended] == [True]
        events = list(session.game.turn_events)
        order = [
            events.index(_events(session, kind)[0])
            for kind in (FocusedCardsRevealed, FocusEffectsResolved, DuelResolved, DuelEnded)
        ]
        assert order == sorted(order)


def test_a_duel_that_ends_without_resolving_says_so_in_its_end():
    # Driven without a session, because a duel paused on its focusing always has a decision pending
    # and the state-based rules refuse to run while one is.
    game = two_seat_game()
    put_in_play(game, personality("challenger", owner=P1))
    put_in_play(game, personality("rival", owner=P2))
    declare_duel(
        game,
        challenger_duelist="challenger",
        challenged_duelist="rival",
        source="challenger",
    )
    ops.remove_card(game.table, game.table.cards_by_id["rival"])

    enforce_state_based_actions(game)

    ended = [event for event in game.turn_events if isinstance(event, DuelEnded)]
    assert [event.resolved for event in ended] == [False]
    assert not [event for event in game.turn_events if isinstance(event, DuelResolved)]


def test_an_effect_delayed_to_the_duels_end_resolves_as_a_consequence(reacting):
    # How a card gives a duel a consequence: it delays an ordinary effect to the moment the duel
    # ends, which the CR puts after the outcome and before the focused cards are discarded.
    reacting(
        DuelDeclared,
        HOOK_PROBE,
        lambda ctx: [DelayedEffect(GainHonor(P1, 5), DUEL_CONSEQUENCES)],
        boundary=Boundary.END,
    )

    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)

        assert session.game.delayed == [(DUEL_CONSEQUENCES, GainHonor(P1, 5))]

        _fought(session)

    assert session.game.table.seats[P1].honor == 5
    assert session.game.delayed == []
    events = list(session.game.turn_events)
    gained = next(event for event in events if isinstance(event, HonorChanged))
    # The duel is over before its consequence resolves, and its outcome is there to be read.
    assert events.index(_events(session, DuelEnded)[0]) < events.index(gained)
    assert session.game.duel.outcome.totals


def test_a_duel_that_ends_without_resolving_drops_the_consequences_that_waited_for_it():
    # Driven without a session for the same reason as the test above. The consequence has no outcome
    # to act on, and one left held would resolve off the next duel's end.
    game = two_seat_game()
    put_in_play(game, personality("challenger", owner=P1))
    put_in_play(game, personality("rival", owner=P2))
    declare_duel(
        game,
        challenger_duelist="challenger",
        challenged_duelist="rival",
        source="challenger",
    )
    apply_effect(game, DelayedEffect(GainHonor(P1, 5), DUEL_CONSEQUENCES))
    ops.remove_card(game.table, game.table.cards_by_id["rival"])

    enforce_state_based_actions(game)

    assert game.delayed == []
    assert game.table.seats[P1].honor == 0


@pytest.mark.parametrize(
    "event_type, boundary",
    [
        (DuelDeclared, Boundary.BEGINNING),
        (DuelDeclared, Boundary.END),
        (CardFocused, None),
        (StrikeDeclared, None),
        (FocusedCardsRevealed, None),
        (FocusEffectsResolved, None),
        (DuelResolved, None),
        (DuelEnded, None),
    ],
)
def test_a_card_can_react_to_each_duel_event(reacting, event_type, boundary):
    # Every duel event has to be reachable by an ordinary @on registration, which is the only way a
    # printed card will ever read one.
    seen: list = []

    def _record_the_event(ctx) -> list:
        seen.append(ctx.event)
        return []

    reacting(event_type, HOOK_PROBE, _record_the_event, boundary=boundary)

    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)
        _fought(session)

    # CardFocused fires once per focus and the rest once per duel, so the claim is that the
    # registration is reached at all.
    assert seen
    assert {type(event) for event in seen} == {event_type}


PARRY_PROBE = "probe_respond_while_a_duel_is_being_fought"

PARRY_ABILITY = Ability(
    timings=(ActionTiming.RESPONSE,),
    label="Response: gain 1 Honor while a duel is being fought",
    cost=no_cost,
    targets=lambda game, source: [source.id] if game.duel_being_fought is not None else [],
    effects=lambda game, source, target: [GainHonor(source.owner, 1)],
    hits_every_target=True,
)

ASKING_PARRY_ABILITY = Ability(
    timings=(ActionTiming.RESPONSE,),
    label="Response: a target duelist's controller gains 1 Honor",
    cost=no_cost,
    targets=lambda game, source: [
        card.id for card in personalities_in_play(game) if game.duel_being_fought is not None
    ],
    effects=lambda game, source, target: [GainHonor(target.owner, 1)],
)


def _pass_every_open_window(session: EngineSession) -> list[PlayerId]:
    """Decline every duel window standing open, and return the seat each one named first.

    A window that has just opened stands at no passes, which is what tells one window from the next
    where closing one opens another inside the same call. Bounded, so a window that fails to close
    fails here instead of spinning until CI times out.
    """
    opened: list[PlayerId] = []
    for _ in range(64):
        round = session.game.round
        if round.kind is not RoundKind.DUEL_WINDOW:
            return opened
        if round.passes == 0:
            opened.append(round.priority)
        session.act(round.priority, Pass())
    raise AssertionError("a duel window did not close after 64 passes")


def test_a_duels_step_waits_beneath_the_window_it_opened():
    with probe_ability(HOOK_PROBE, DUEL_ABILITY), probe_ability(PARRY_PROBE, PARRY_ABILITY):
        session = _duel_game(responder=PARRY_PROBE)
        _challenge(session)

        assert session.game.round.kind is RoundKind.DUEL_WINDOW
        assert session.game.round.priority is P2
        # The first focus-or-strike option is queued and held: nobody is asked to focus until the
        # window over the declaration has closed.
        assert session.game.pending is None
        assert isinstance(session.game.stack[-1], OfferFocusOrStrike)

        session.act(P2, Pass())

        assert session.game.round.kind is RoundKind.PHASE
        assert session.game.round_stack == []
        assert isinstance(session.game.pending, FocusOrStrike)
        assert session.game.pending.seat is P2


def test_a_response_taken_in_a_duel_window_leaves_the_duel_where_it_was():
    with probe_ability(HOOK_PROBE, DUEL_ABILITY), probe_ability(PARRY_PROBE, PARRY_ABILITY):
        session = _duel_game(responder=PARRY_PROBE)
        _challenge(session)

        session.act(P2, ActivateAbility("parry-P2"))

        assert session.game.table.seats[P2].honor == 1
        # The duel picks up at the step the window stood in front of, not after the duel.
        assert isinstance(session.game.pending, FocusOrStrike)
        assert session.game.pending.seat is P2
        assert session.game.duel.step is DuelStep.FOCUSING
        assert session.game.round.kind is RoundKind.PHASE


def test_a_response_that_asks_a_question_returns_to_the_duel_once_it_is_answered():
    with probe_ability(HOOK_PROBE, DUEL_ABILITY), probe_ability(PARRY_PROBE, ASKING_PARRY_ABILITY):
        session = _duel_game(responder=PARRY_PROBE)
        _challenge(session)

        session.act(P2, ActivateAbility("parry-P2"))

        assert isinstance(session.game.pending, ChooseAbilityTarget)
        assert session.game.round.kind is RoundKind.DUEL_WINDOW

        session.submit(P2, DecisionResponse(("challenger",)))

        assert session.game.table.seats[P1].honor == 1
        assert isinstance(session.game.pending, FocusOrStrike)
        assert session.game.round.kind is RoundKind.PHASE


def test_the_window_after_the_strike_opens_before_the_focused_cards_are_revealed():
    # Concede Defeat's timing: "after a strike is declared in a duel involving one of your
    # Personalities, but before focused cards are revealed".
    with probe_ability(HOOK_PROBE, DUEL_ABILITY), probe_ability(PARRY_PROBE, PARRY_ABILITY):
        session = _duel_game(responder=PARRY_PROBE)
        _challenge(session)
        _pass_every_open_window(session)
        session.submit(P2, DecisionResponse((focus_token("P2-fv0"),)))
        _pass_every_open_window(session)
        session.submit(P1, DecisionResponse((focus_token("P1-fv0"),)))
        _pass_every_open_window(session)
        session.submit(P2, DecisionResponse((STRIKE,)))

        assert _events(session, StrikeDeclared)
        assert session.game.round.kind is RoundKind.DUEL_WINDOW
        assert not _events(session, FocusedCardsRevealed)
        assert all(
            not card.face_up for seat in PlayerId for card in focused_cards(session.game, seat)
        )

        _pass_every_open_window(session)

        assert _events(session, FocusedCardsRevealed)
        assert session.game.duel.outcome.totals
        # Every window a seat passed is on the tape, and the duel replays through all of them.
        assert replay(session.log).table == session.game.table


def test_a_duel_that_ends_early_drops_the_windows_it_had_queued():
    # Driven without a session, as the early-exit tests above are: the state-based rules refuse to
    # run while a decision is pending, and a duel paused on its focusing always has one.
    game = two_seat_game()
    put_in_play(game, personality("challenger", owner=P1))
    put_in_play(game, personality("rival", owner=P2))
    declare_duel(
        game,
        challenger_duelist="challenger",
        challenged_duelist="rival",
        source="challenger",
    )
    assert any(isinstance(item, OpenDuelWindow) for item in game.stack)

    ops.remove_card(game.table, game.table.cards_by_id["rival"])
    enforce_state_based_actions(game)

    assert [item for item in game.stack if isinstance(item, DuelWork)] == []


KILL_PROBE = "probe_destroy_a_duelist_in_a_duel_window"

KILL_ABILITY = Ability(
    timings=(ActionTiming.RESPONSE,),
    label="Response: destroy a target enemy Personality",
    cost=no_cost,
    targets=enemy_personalities,
    effects=lambda game, source, target: [Destroy(target.id, Rulebook.DUEL_RESOLUTION)],
    hits_every_target=True,
)


class _BindsToNothing:
    """What an Interrupt leaves on ``game.modifications`` for an effect the action has not reached
    yet. It answers no effect, so it is only ever spent by the action finishing."""

    def answers(self, effect: Effect) -> bool:
        return False

    def apply(self, game: GameState, effect: Effect) -> Effect:
        return effect


def test_every_duel_window_opens_on_the_first_seat_in_turn_order():
    # The seat a window names first is what decides who pre-empts whom, and a window opened as the
    # duel's last step closed used to name the wrong one: the round handed on from was re-read after
    # that step had already opened the next window.
    with probe_ability(HOOK_PROBE, DUEL_ABILITY), probe_ability(PARRY_PROBE, PARRY_ABILITY):
        session = _duel_game(responder=PARRY_PROBE, armed=(P1, P2))
        _challenge(session)

        after_declaration = _pass_every_open_window(session)
        session.submit(P2, DecisionResponse((focus_token("P2-fv0"),)))
        after_a_focus = _pass_every_open_window(session)
        session.submit(P1, DecisionResponse((focus_token("P1-fv0"),)))
        after_both_focuses = _pass_every_open_window(session)
        session.submit(P2, DecisionResponse((STRIKE,)))
        after_the_strike = _pass_every_open_window(session)

        assert session.game.duel.outcome.totals
        # P1 is the active seat and holds a Response in every window, so it acts first in every
        # window. Each of the first three opened as a decision was answered.
        assert after_declaration == [P1]
        assert after_a_focus == [P1]
        assert after_both_focuses == [P1]
        # The chain after the strike is where the duel's own steps open each other's windows, which
        # is the only place the first actor was ever wrong.
        assert len(after_the_strike) > 1
        assert after_the_strike == [P1] * len(after_the_strike)


def test_a_duel_window_does_not_spend_what_an_interrupt_bound_to_the_action():
    # `game.modifications` is spent when the action finishes. A duel window is a round the action
    # opened while still resolving, so the window opening must not count as the action finishing.
    with probe_ability(HOOK_PROBE, DUEL_ABILITY), probe_ability(PARRY_PROBE, PARRY_ABILITY):
        session = _duel_game(responder=PARRY_PROBE)
        session.act(P1, ActivateAbility("challenger"))
        session.game.modifications.append(_BindsToNothing())

        session.submit(P1, DecisionResponse(("rival",)))

        assert session.game.round.kind is RoundKind.DUEL_WINDOW
        assert len(session.game.modifications) == 1


def test_a_duel_that_ends_while_its_window_is_open_drains_the_window():
    # A Response that kills a duelist ends the duel where it stands. The window it was taken in has
    # no step left for another Response to answer, so no seat is asked to decline a time point that
    # will never arrive.
    with probe_ability(HOOK_PROBE, DUEL_ABILITY), probe_ability(KILL_PROBE, KILL_ABILITY):
        session = _duel_game(responder=KILL_PROBE, armed=(P1, P2))
        _challenge(session)
        assert session.game.round.priority is P1

        session.act(P1, ActivateAbility("parry-P1"))

        assert session.game.duel.step is DuelStep.ENDED
        # P2 still holds its own copy and is not asked to decline a duel that has ended. The flow
        # lands in the Response Step of the action that declared the duel, where it belongs.
        assert session.game.round.kind is RoundKind.RESPONSE
        assert session.game.round.priority is P2
        responding_to = project(session.game, P2).responding_to
        assert responding_to == "the ability on challenger"
