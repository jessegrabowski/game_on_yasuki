from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.actions import ActionTiming, Inheritance
from yasuki_core.engine.rules.decisions import ChooseInheritanceTarget, DecisionResponse
from yasuki_core.engine.rules.economy import effective_gold_production
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.state import Phase
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import StrongholdPrint

from tests.yasuki_core.engine.builders import end_phase, end_turn, holding, put_in_play

P1, P2 = PlayerId.P1, PlayerId.P2


def _stronghold(seat: PlayerId, *, two_faced: bool = True) -> L5RCard:
    """A Stronghold with a Sun front and a Moon back — the shape the second player is dealt."""
    back = (
        StrongholdPrint(name="Moon", side=Side.STRONGHOLD, printed_id=f"{seat.name}-SH__back")
        if two_faced
        else None
    )
    return L5RCard.of(
        StrongholdPrint,
        id=f"{seat.name}-SH",
        name="Sun",
        side=Side.STRONGHOLD,
        owner=seat,
        gold_production=1,
        back_card_id=f"{seat.name}-SH__back" if two_faced else None,
        back_printed=back,
    )


def _second_players_turn(
    *, phase: Phase = Phase.DYNASTY, two_faced: bool = True, p2_holding: bool = True
) -> EngineSession:
    """A session parked in ``phase`` of the second player's turn, Dynasty by default, which is where
    Inheritance is on offer.

    ``EngineSession.start`` rebuilds the table from a snapshot, so read cards back through
    ``session.game.table`` rather than through the table handed in.
    """
    table = TableState.empty_two_seat()
    for seat in (P1, P2):
        put_in_play(table, _stronghold(seat, two_faced=two_faced or seat is P1))
        if seat is P1 or p2_holding:
            put_in_play(table, holding(f"{seat.name}-farm", owner=seat, gold_production=1))
    table.cards_by_id["P2-SH"].flip_face()  # the second player is dealt onto its Moon side
    session = EngineSession.start(table, P1, seed=1)
    while not (session.game.active is P2 and session.game.phase is phase):
        end_phase(session)
    return session


def _offered(session: EngineSession, seat: PlayerId) -> bool:
    return any(isinstance(action, Inheritance) for action in session.legal_actions(seat))


def test_the_second_player_is_offered_inheritance():
    assert _offered(_second_players_turn(), P2)


def test_the_first_player_is_never_offered_inheritance():
    table = TableState.empty_two_seat()
    for seat in (P1, P2):
        put_in_play(table, _stronghold(seat))
        put_in_play(table, holding(f"{seat.name}-farm", owner=seat, gold_production=1))
    session = EngineSession.start(table, P1, seed=1)
    end_phase(session)
    end_phase(session)  # P1's own Dynasty phase

    assert not _offered(session, P1)


def test_a_flipped_stronghold_does_not_grant_inheritance_to_the_first_player():
    """Shrine of Courtesy can turn a Stronghold over, so the flipped state occurs in real play."""
    table = TableState.empty_two_seat()
    for seat in (P1, P2):
        put_in_play(table, _stronghold(seat))
        put_in_play(table, holding(f"{seat.name}-farm", owner=seat, gold_production=1))
    session = EngineSession.start(table, P1, seed=1)
    session.game.table.cards_by_id["P1-SH"].flip_face()  # first player, showing its back
    end_phase(session)
    end_phase(session)

    assert not _offered(session, P1)


def test_it_turns_the_stronghold_over_and_raises_the_chosen_holding():
    session = _second_players_turn()
    live = session.game.table.cards_by_id
    assert live["P2-SH"].active_face.name == "Moon"

    session.act(P2, Inheritance())
    session.submit(P2, DecisionResponse(("P2-farm",)))

    assert live["P2-SH"].active_face.name == "Sun"
    assert effective_gold_production(session.game, live["P2-farm"]) == 4


def test_the_target_choice_offers_the_seats_own_holdings():
    session = _second_players_turn()

    session.act(P2, Inheritance())

    pending = session.game.pending
    assert isinstance(pending, ChooseInheritanceTarget)
    assert pending.seat is P2
    assert pending.candidates == ("P2-farm",)  # not the opponent's


def test_it_is_offered_only_once_per_game():
    session = _second_players_turn()
    session.act(P2, Inheritance())
    session.submit(P2, DecisionResponse(("P2-farm",)))

    assert not _offered(session, P2)
    end_turn(session)
    for _ in range(5):  # round to P2's Dynasty phase on the next turn
        end_phase(session)
    assert not _offered(session, P2)


def test_the_grant_lasts_until_the_turn_ends():
    session = _second_players_turn()
    live = session.game.table.cards_by_id
    session.act(P2, Inheritance())
    session.submit(P2, DecisionResponse(("P2-farm",)))
    assert effective_gold_production(session.game, live["P2-farm"]) == 4

    end_turn(session)

    assert effective_gold_production(session.game, live["P2-farm"]) == 1


def test_a_single_faced_stronghold_cannot_be_turned_over():
    """Turning the Stronghold over is what pays for the grant, so a Stronghold with no back face
    cannot take the ability rather than taking it for free."""
    assert not _offered(_second_players_turn(two_faced=False), P2)


def test_it_is_not_offered_with_no_holding_to_raise():
    assert not _offered(_second_players_turn(p2_holding=False), P2)


def test_the_action_and_its_answer_survive_a_replay():
    session = _second_players_turn()
    session.act(P2, Inheritance())
    session.submit(P2, DecisionResponse(("P2-farm",)))

    rebuilt = replay(session.log)

    assert rebuilt.table.cards_by_id["P2-SH"].showing_back is False
    assert effective_gold_production(rebuilt, rebuilt.table.cards_by_id["P2-farm"]) == 4


def test_inheritance_is_taken_under_the_dynasty_designator():
    session = _second_players_turn()

    assert legality.timing_of(session.game, Inheritance()) is ActionTiming.DYNASTY


def test_it_is_not_offered_outside_the_dynasty_phase():
    """A Dynasty designator, so the seat cannot spend it in its Action phase."""
    session = _second_players_turn(phase=Phase.ACTION)

    assert not _offered(session, P2)


def test_backing_out_leaves_the_ability_unspent():
    """Backing out of the target picker unwinds the whole action, so a misclick does not burn a
    once-per-game ability."""
    session = _second_players_turn()
    session.act(P2, Inheritance())

    session.cancel(P2)

    assert session.game.pending is None
    assert _offered(session, P2)
