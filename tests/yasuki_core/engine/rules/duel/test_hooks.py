import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.duel.procedure import declare_duel
from yasuki_core.engine.rules.triggers import apply_effect, enforce_state_based_actions
from yasuki_core.engine.rules.effects import DelayedEffect, GainHonor
from yasuki_core.engine.rules.turn.structure import DUEL_CONSEQUENCES
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility
from yasuki_core.engine.rules.vocabulary.decisions import (
    STRIKE,
    DecisionResponse,
    focus_token,
)
from yasuki_core.engine.rules.vocabulary.game_events import (
    CardFocused,
    DeclaringDuel,
    DuelDeclared,
    DuelEnded,
    DuelResolved,
    FocusedCardsRevealed,
    FocusEffectsResolved,
    HonorChanged,
    StrikeDeclared,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole

from tests.yasuki_core.engine.builders import (
    focus_card,
    personality,
    put_in_play,
    register,
    two_seat_game,
)
from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.rules.duel.conftest import CHALLENGE_ABILITY, CHALLENGE_PROBE

P1, P2 = PlayerId.P1, PlayerId.P2

HOOK_PROBE = CHALLENGE_PROBE
DUEL_ABILITY = CHALLENGE_ABILITY


def _duel_game(*, chi: dict[PlayerId, int] | None = None) -> EngineSession:
    """P1's challenger and P2's rival in play with ``chi`` each, holding one card of Focus Value 1."""
    chi = {P1: 3, P2: 3} if chi is None else chi
    state = TableState.empty_two_seat()
    put_in_play(state, personality("challenger", owner=P1, printed_id=HOOK_PROBE, chi=chi[P1]))
    put_in_play(state, personality("rival", owner=P2, chi=chi[P2]))
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

        window = _events(session, DeclaringDuel)
        declared = _events(session, DuelDeclared)
        assert [(event.challenger, event.challenged) for event in window] == [(P1, P2)]
        assert [event.challenger_duelist for event in declared] == ["challenger"]
        assert declared[0].source_card_id == "challenger"
        # The window is announced first, so a card acting in it acts before the duel is declared.
        events = list(session.game.turn_events)
        assert events.index(window[0]) < events.index(declared[0])


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
    reacting(
        DeclaringDuel,
        HOOK_PROBE,
        lambda ctx: pending_when_the_window_fired.append(ctx.game.pending) or [],
    )

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
        DuelDeclared, HOOK_PROBE, lambda ctx: [DelayedEffect(GainHonor(P1, 5), DUEL_CONSEQUENCES)]
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
    "event_type",
    [
        DeclaringDuel,
        DuelDeclared,
        CardFocused,
        StrikeDeclared,
        FocusedCardsRevealed,
        FocusEffectsResolved,
        DuelResolved,
        DuelEnded,
    ],
)
def test_a_card_can_react_to_each_duel_event(reacting, event_type):
    # Every duel event has to be reachable by an ordinary @on registration, which is the only way a
    # printed card will ever read one.
    seen: list = []

    def _record_what_fired(ctx) -> list:
        seen.append(ctx.event)
        return []

    reacting(event_type, HOOK_PROBE, _record_what_fired)

    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)
        _fought(session)

    # CardFocused fires once per focus and the rest once per duel, so the claim is that the
    # registration is reached at all.
    assert seen
    assert {type(event) for event in seen} == {event_type}
