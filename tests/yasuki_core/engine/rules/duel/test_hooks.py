import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.duel.procedure import declare_duel
from yasuki_core.engine.rules.triggers import enforce_state_based_actions
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.effects import StartDuel
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility
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
    StrikeDeclared,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
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

HOOK_PROBE = "probe_challenge_for_the_duel_events"


def _enemy_personalities(game, source):
    return [card.id for card in personalities_in_play(game) if card.owner is not source.owner]


DUEL_ABILITY = Ability(
    timings=(ActionTiming.OPEN,),
    label="Open: challenge a target enemy Personality to a duel",
    cost=no_cost,
    targets=_enemy_personalities,
    effects=lambda game, source, target: [StartDuel(source.id, target.id, source.id)],
)


def _duel_game(*, chi: dict[PlayerId, int] | None = None) -> EngineSession:
    """P1's challenger and P2's rival in play with ``chi`` each, holding one card of Focus Value 1."""
    chi = {P1: 3, P2: 3} if chi is None else chi
    state = TableState.empty_two_seat()
    put_in_play(state, personality("challenger", owner=P1, printed_id=HOOK_PROBE, chi=chi[P1]))
    put_in_play(state, personality("rival", owner=P2, chi=chi[P2]))
    for seat in PlayerId:
        for index in range(2):
            card = register(
                state,
                L5RCard.of(
                    FatePrint,
                    id=f"{seat.name}-fv{index}",
                    name=f"{seat.name}-fv{index}",
                    side=Side.FATE,
                    owner=seat,
                    focus=1,
                ),
            )
            state.zones[ZoneKey(seat, ZoneRole.HAND)].add(card)
    return EngineSession.start(state, P1)


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
        session.act(P1, ActivateAbility("challenger"))
        session.submit(P1, DecisionResponse(("rival",)))

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
        session.act(P1, ActivateAbility("challenger"))
        session.submit(P1, DecisionResponse(("rival",)))
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
        session.act(P1, ActivateAbility("challenger"))
        session.submit(P1, DecisionResponse(("rival",)))
        _fought(session)

        revealed = _events(session, FocusedCardsRevealed)
        assert [event.revealed for event in revealed] == [
            frozenset({(P2, "P2-fv0"), (P1, "P1-fv0")})
        ]


def test_the_resolution_carries_the_totals_and_the_stats_the_duel_began_on():
    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game(chi={P1: 2, P2: 5})
        session.act(P1, ActivateAbility("challenger"))
        session.submit(P1, DecisionResponse(("rival",)))
        _fought(session)

        resolved = _events(session, DuelResolved)[0]
        assert resolved.winner is P2
        assert resolved.losers == frozenset({P1})
        assert resolved.totals == frozenset({(P1, 3), (P2, 6)})
        # The focused card is worth 1 to each seat, so the entry stats are the Chi alone.
        assert resolved.entry_stats == frozenset({(P1, 2), (P2, 5)})


def test_a_resolved_duel_announces_its_end_after_its_outcome():
    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game()
        session.act(P1, ActivateAbility("challenger"))
        session.submit(P1, DecisionResponse(("rival",)))
        _fought(session)

        ended = _events(session, DuelEnded)
        assert [event.resolved for event in ended] == [True]
        events = list(session.game.turn_events)
        assert events.index(_events(session, DuelResolved)[0]) < events.index(ended[0])


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


@pytest.mark.parametrize(
    "event_type",
    [DeclaringDuel, DuelDeclared, CardFocused, StrikeDeclared, FocusedCardsRevealed, DuelResolved],
)
def test_a_card_can_react_to_each_duel_event(reacting, event_type):
    # Every duel event has to be reachable by an ordinary @on registration, which is the only way a
    # printed card will ever read one.
    seen: list = []
    reacting(event_type, HOOK_PROBE, lambda ctx: seen.append(ctx.event) or [])

    with probe_ability(HOOK_PROBE, DUEL_ABILITY):
        session = _duel_game()
        session.act(P1, ActivateAbility("challenger"))
        session.submit(P1, DecisionResponse(("rival",)))
        _fought(session)

    # CardFocused fires once per focus and the rest once per duel, so the claim is that the
    # registration is reached at all.
    assert seen
    assert {type(event) for event in seen} == {event_type}
