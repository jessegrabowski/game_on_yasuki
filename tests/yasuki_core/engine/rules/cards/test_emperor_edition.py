from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.cards.emperor_edition import (
    SANCTIONED_DUEL_ACCEPT,
    SANCTIONED_DUEL_REFUSE,
)
from yasuki_core.engine.rules.vocabulary.actions import PlayStrategy
from yasuki_core.engine.rules.vocabulary.game_events import Destroyed
from yasuki_core.engine.rules.vocabulary.decisions import (
    STRIKE,
    ChooseOption,
    DecisionResponse,
    FocusOrStrike,
    focus_token,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import (
    focus_card,
    personality,
    put_in_play,
    register,
    stronghold,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Sanctioned Duel ---


def _sanctioned_duel_game(*, chi: dict[PlayerId, int] | None = None) -> EngineSession:
    """Sanctioned Duel in P1's hand, P1's unbowed Personality and P2's rival in play with ``chi``
    each, and one card of Focus Value 1 in each hand to focus with."""
    chi = {P1: 3, P2: 3} if chi is None else chi
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1)))
    put_in_play(state, register(state, personality("mine", owner=P1, chi=chi[P1])))
    put_in_play(state, register(state, personality("theirs", owner=P2, chi=chi[P2])))
    strategy = register(
        state,
        L5RCard.of(
            FatePrint,
            id="duel",
            printed_id="sanctioned_duel",
            name="Sanctioned Duel",
            side=Side.FATE,
            owner=P1,
            gold_cost=0,
        ),
    )
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(strategy)
    for seat in PlayerId:
        card = register(state, focus_card(f"{seat.name}-fv", seat, 1))
        state.zones[ZoneKey(seat, ZoneRole.HAND)].add(card)
    return EngineSession.start(state, P1)


def _in_play(session: EngineSession) -> set[str]:
    """The ids on the battlefield. ``cards_by_id`` indexes the discard piles too, so it never
    reports a destruction."""
    return {card.id for card in session.game.table.battlefield.cards}


def _challenge(session: EngineSession) -> None:
    """Play the Strategy, target the challenger, and pick whom it challenges."""
    session.act(P1, PlayStrategy("duel"))
    session.submit(P1, DecisionResponse(("mine",)))
    session.submit(P1, DecisionResponse(("theirs",)))


def test_sanctioned_duel_offers_the_challenged_seat_the_choice_to_refuse():
    session = _sanctioned_duel_game()

    _challenge(session)

    pending = session.game.pending
    assert isinstance(pending, ChooseOption)
    assert pending.seat is P2
    assert pending.candidates == (SANCTIONED_DUEL_REFUSE, SANCTIONED_DUEL_ACCEPT)
    # A refused challenge creates no duel, so nothing is on the game until the answer comes back.
    assert session.game.duel is None


def test_refusing_sanctioned_duel_dishonors_him_and_creates_no_duel():
    session = _sanctioned_duel_game()
    _challenge(session)

    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_REFUSE,)))

    assert session.game.table.cards_by_id["theirs"].dishonorable is True
    assert session.game.table.seats[P1].honor == 2
    # "The duel doesn't happen" (CR, Challenge): no record, and both Personalities stay.
    assert session.game.duel is None
    assert {"mine", "theirs"} <= _in_play(session)


def test_accepting_sanctioned_duel_fights_it_and_destroys_the_loser():
    session = _sanctioned_duel_game(chi={P1: 5, P2: 2})
    _challenge(session)

    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_ACCEPT,)))

    assert isinstance(session.game.pending, FocusOrStrike)
    session.submit(P2, DecisionResponse((STRIKE,)))

    assert session.game.duel.outcome.winners == (P1,)
    assert "theirs" not in _in_play(session)
    # Nothing happens to the winner, and the refusal branch did not run.
    assert "mine" in _in_play(session)
    assert session.game.table.cards_by_id["mine"].dishonorable is False
    assert session.game.table.seats[P1].honor == 0


def test_sanctioned_duels_loser_is_read_when_the_duel_ends_not_when_it_is_declared():
    # The Chi the duelists enter on is reversed by what each focuses, so a destruction decided at
    # declaration would kill the wrong Personality.
    session = _sanctioned_duel_game(chi={P1: 2, P2: 3})
    _challenge(session)
    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_ACCEPT,)))
    session.submit(P2, DecisionResponse((focus_token("P2-fv"),)))

    session.submit(P1, DecisionResponse((focus_token("P1-fv"),)))

    # Neither seat has a second card to focus, so the duel strikes without being asked again.
    assert session.game.duel.outcome.totals == {P1: 3, P2: 4}
    assert "mine" not in _in_play(session)
    assert "theirs" in _in_play(session)


def test_sanctioned_duel_replays_after_refusing():
    session = _sanctioned_duel_game()
    _challenge(session)

    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_REFUSE,)))

    assert replay(session.log).table == session.game.table


def test_sanctioned_duel_replays_after_accepting():
    session = _sanctioned_duel_game()
    _challenge(session)
    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_ACCEPT,)))

    session.submit(P2, DecisionResponse((STRIKE,)))

    assert replay(session.log).table == session.game.table


def test_sanctioned_duel_records_the_challengers_controller_as_destroying_the_loser():
    # The seat answering the refuse-or-accept question is the challenged one, so a destruction
    # attributed to the answerer would read as the loser destroying its own Personality.
    session = _sanctioned_duel_game(chi={P1: 5, P2: 2})
    _challenge(session)
    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_ACCEPT,)))

    session.submit(P2, DecisionResponse((STRIKE,)))

    destroyed = [event for event in session.game.turn_events if isinstance(event, Destroyed)]
    assert [(event.card_id, event.cause) for event in destroyed] == [("theirs", P1)]


def test_sanctioned_duel_is_not_offered_with_no_personality_to_challenge():
    # Both targets have to exist, and the challenged one is picked after the card is played, so an
    # ability offered on the challenger alone strands the seat on a choice with no candidates.
    session = _sanctioned_duel_game()
    ops.remove_card(session.game.table, session.game.table.cards_by_id["theirs"])

    assert PlayStrategy("duel") not in session.legal_actions(P1)


def test_sanctioned_duel_does_not_target_a_bowed_challenger():
    session = _sanctioned_duel_game()
    session.game.table.cards_by_id["mine"].bow()

    assert PlayStrategy("duel") not in session.legal_actions(P1)


def test_sanctioned_duel_challenges_only_another_players_personality():
    session = _sanctioned_duel_game()
    put_in_play(session.game, register(session.game.table, personality("second", owner=P1)))

    session.act(P1, PlayStrategy("duel"))
    session.submit(P1, DecisionResponse(("mine",)))

    # "another player's target Personality": your own second Personality is not a candidate, and a
    # challenge between two of your own would not happen at all (CR, Challenge).
    assert session.game.pending.candidates == ("theirs",)


def test_sanctioned_duel_destroys_both_personalities_when_neither_wins():
    # Equal totals that the Duelist tiebreak cannot separate are lost by both (CR, Duel), and the
    # card destroys the loser rather than a single loser.
    session = _sanctioned_duel_game(chi={P1: 3, P2: 3})
    _challenge(session)
    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_ACCEPT,)))

    session.submit(P2, DecisionResponse((STRIKE,)))

    assert session.game.duel.outcome.winners == ()
    assert set(session.game.duel.outcome.losers) == {P1, P2}
    assert {"mine", "theirs"} & _in_play(session) == set()
