from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Cycle
from yasuki_core.engine.rules.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.rules.events import Revealed
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyCard

from tests.yasuki_core.engine.builders import end_phase, holding, put_in_play, register

P1 = PlayerId.P1
P2 = PlayerId.P2


def _table(*, provinces: int = 3, deck: int = 3, second_seat_provinces: int = 0) -> TableState:
    """A two-seat table with face-down Provinces over a dynasty deck of ``deck`` cards.

    The turn-start sweep turns the Provinces face-up, which is what makes them Cycle candidates, so
    a test wanting a face-down candidate has to arrange it after the game begins.
    """
    state = TableState.empty_two_seat()
    for seat, count in ((P1, provinces), (P2, second_seat_provinces)):
        for index in range(count):
            card = register(
                state,
                DynastyCard(id=f"{seat.name}-pv{index}", name="P", side=Side.DYNASTY, owner=seat),
            )
            card.turn_face_down()
            state.zones[ops.create_province(state, seat)].add(card)
        state.decks[DeckKey(seat, Side.DYNASTY)].cards = [
            register(
                state,
                DynastyCard(id=f"{seat.name}-dd{index}", name="D", side=Side.DYNASTY, owner=seat),
            )
            for index in range(deck)
        ]
    return state


def _session(**kwargs) -> EngineSession:
    """A session parked at the start of P1's first turn, in the Action phase where Cycle lives."""
    return EngineSession.start(_table(**kwargs), P1, seed=7)


def _end_turn(session: EngineSession, seat: PlayerId) -> None:
    for _ in range(3):  # Action -> Battle -> Dynasty -> next turn
        end_phase(session)


def _deck_order(session: EngineSession, seat: PlayerId = P1) -> list[str]:
    """The seat's dynasty deck bottom-first, which is the order the engine list itself keeps."""
    return [card.id for card in session.game.table.decks[DeckKey(seat, Side.DYNASTY)].cards]


def _province_cards(session: EngineSession, seat: PlayerId = P1) -> list[list[str]]:
    """One entry per Province, holding its face-up card ids — so an empty Province reads as []."""
    provinces = [
        (key.idx, zone)
        for key, zone in session.game.table.zones.items()
        if key.owner is seat and key.role is ZoneRole.PROVINCE
    ]
    return [
        [card.id for card in zone.cards if card.face_up]
        for _, zone in sorted(provinces, key=lambda province: province[0])
    ]


def test_cycle_is_offered_on_a_seats_opening_turn():
    assert Cycle() in _session().legal_actions(P1)


def test_cycle_is_not_offered_once_the_first_turn_has_passed():
    # "Your first turn" is the whole gate on the action; nothing else stops a seat taking it again
    # on turn three and thinning its deck for free.
    session = _session(second_seat_provinces=3)
    _end_turn(session, P1)
    _end_turn(session, P2)

    assert session.game.turn == 3
    assert Cycle() not in session.legal_actions(P1)


def test_the_second_seat_opens_on_turn_two():
    # The turn counter advances while the active seat alternates, so reading "first turn" as turn 1
    # would deny the second player the action entirely.
    session = _session(second_seat_provinces=3)
    _end_turn(session, P1)

    assert session.game.turn == 2
    assert Cycle() in session.legal_actions(P2)


def test_cycle_is_not_offered_outside_the_action_phase():
    session = _session()
    end_phase(session)  # Action -> Battle

    assert Cycle() not in session.legal_actions(P1)


def test_cycle_is_not_offered_with_nothing_face_up_to_put_back():
    # The rule is "one or more", so a seat with no face-up Province card is not offered the action
    # rather than offered it and forced to pick nothing.
    assert Cycle() not in _session(provinces=0).legal_actions(P1)


def test_cycle_is_not_offered_again_once_taken():
    session = _session()
    session.act(P1, Cycle())
    session.submit(P1, DecisionResponse(("P1-pv0",)))

    assert Cycle() not in session.legal_actions(P1)


def test_cycle_asks_for_at_least_one_card_and_offers_every_face_up_province():
    session = _session()
    session.act(P1, Cycle())

    pending = session.game.pending
    assert isinstance(pending, ChooseCards)
    assert pending.minimum == 1  # declining means not taking the action at all
    assert set(pending.candidates) == {"P1-pv0", "P1-pv1", "P1-pv2"}
    assert pending.prompt() == (
        "Put face-up Province cards on the bottom of your deck — your last pick ends up lowest"
    )


def test_the_last_card_picked_ends_up_at_the_very_bottom():
    # The order is the player's and it is load-bearing. Each card goes under the one before it, so
    # the pick order reads back reversed from the bottom of the deck.
    session = _session()
    session.act(P1, Cycle())

    session.submit(P1, DecisionResponse(("P1-pv2", "P1-pv0", "P1-pv1")))

    assert _deck_order(session)[:3] == ["P1-pv1", "P1-pv0", "P1-pv2"]


def test_a_vacated_province_refills_and_the_whole_row_ends_face_up():
    session = _session()
    session.act(P1, Cycle())

    session.submit(P1, DecisionResponse(("P1-pv0",)))

    # P1-pv0's Province took the top of the deck; the other two kept the cards they already held.
    assert _province_cards(session) == [["P1-dd2"], ["P1-pv1"], ["P1-pv2"]]


def test_a_face_down_province_is_not_a_candidate_but_is_revealed_by_the_cycle():
    # Two halves of the same rule: only face-up cards may be put back, and the reveal at the end
    # turns everything in the row face-up regardless of what left.
    session = _session()
    hidden = session.game.table.cards_by_id["P1-pv2"]
    hidden.turn_face_down()
    session.act(P1, Cycle())

    assert "P1-pv2" not in session.game.pending.candidates

    session.submit(P1, DecisionResponse(("P1-pv0",)))

    assert hidden.face_up is True


def test_the_reveal_announces_each_card_it_turns(reacting):
    # The reason Cycle is built as a cascade rather than a straight line: every occurrence it
    # performs is announced where it happens, so a card can react to the reveal itself. The
    # refilled card is the one turned here — the others were already face-up and stay silent.
    seen = []
    reacting(Revealed, "cycle_probe", lambda ctx: seen.append(ctx.event.card_id) or [])
    session = _session()
    put_in_play(session.game, holding("P1-eyes", owner=P1, printed_id="cycle_probe"))
    session.act(P1, Cycle())

    session.submit(P1, DecisionResponse(("P1-pv0",)))

    assert seen == ["P1-dd2"]


def test_putting_a_card_into_an_empty_deck_hands_it_straight_back():
    # The refill draws from the deck the move just fed, so a seat cycling against an empty deck
    # gets the same card back. Cycle moves no card out of the seat's own cards, which is why a
    # Province can never be left empty by it however many go back.
    session = _session(deck=0)
    session.act(P1, Cycle())

    session.submit(P1, DecisionResponse(("P1-pv0",)))

    assert _province_cards(session) == [["P1-pv0"], ["P1-pv1"], ["P1-pv2"]]
    assert _deck_order(session) == []


def test_putting_the_whole_row_back_refills_it_from_the_top_of_the_deck():
    # Sending everything back is the case where the two orderings meet: the picks stack downward
    # from the bottom while the refills come off the top, and both have to be right for the row and
    # the deck to read as they do here.
    session = _session()
    session.act(P1, Cycle())

    session.submit(P1, DecisionResponse(("P1-pv0", "P1-pv1", "P1-pv2")))

    assert _province_cards(session) == [["P1-dd2"], ["P1-dd1"], ["P1-dd0"]]
    assert _deck_order(session) == ["P1-pv2", "P1-pv1", "P1-pv0"]
