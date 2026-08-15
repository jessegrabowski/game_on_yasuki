import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.decisions import Confirm, DecisionResponse
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import province_card, register

P1, P2 = PlayerId.P1, PlayerId.P2


def _panda_game(fate_cards: int = 2) -> EngineSession:
    """A session with Blessings of the Red Panda Spirit face-up in P1's Province and a stocked Fate
    deck for each seat, so both have something to draw."""
    state = TableState.empty_two_seat()
    province_card(
        state,
        "panda",
        printed_id="blessings_of_the_red_panda_spirit",
        name="Blessings of the Red Panda Spirit",
    )
    for seat in (P1, P2):
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            register(
                state,
                L5RCard.of(FatePrint, id=f"{seat.name}-f{i}", name="F", side=Side.FATE, owner=seat),
            )
            for i in range(fate_cards)
        ]
    return EngineSession.start(state, P1)


def _hand(session, seat) -> list[str]:
    return [c.id for c in session.game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards]


def _honor(session, seat) -> int:
    return session.game.table.seats[seat].honor


def test_it_is_offered_from_its_province():
    session = _panda_game()
    assert ActivateAbility("panda") in session.legal_actions(P1)


def test_every_seat_gains_honor_and_draws_not_just_the_controller():
    """ "Each player gains 1 Honor and draws a card" — the opponent benefits too, which is the
    card's whole character and the easiest half to leave out."""
    session = _panda_game()
    before = {seat: (_honor(session, seat), len(_hand(session, seat))) for seat in (P1, P2)}

    session.act(P1, ActivateAbility("panda"))

    for seat in (P1, P2):
        honor, hand = before[seat]
        assert _honor(session, seat) == honor + 1
        assert len(_hand(session, seat)) == hand + 1


def test_it_asks_whether_to_keep_the_event_rather_than_offering_it_as_a_target():
    session = _panda_game()
    session.act(P1, ActivateAbility("panda"))

    pending = session.game.pending
    assert isinstance(pending, Confirm)
    assert pending.prompt() == (
        "Shuffle Blessings of the Red Panda Spirit into your Dynasty deck instead of discarding it?"
    )


def test_answering_yes_shuffles_the_event_back_into_the_dynasty_deck():
    session = _panda_game()
    session.act(P1, ActivateAbility("panda"))
    session.submit(P1, DecisionResponse(("panda",)))

    deck = session.game.table.decks[DeckKey(P1, Side.DYNASTY)]
    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert "panda" in {card.id for card in deck.cards}
    assert "panda" not in {card.id for card in discard.cards}


def test_answering_no_discards_the_event():
    """Declining is not doing nothing: the Event is spent either way, only its destination differs."""
    session = _panda_game()
    session.act(P1, ActivateAbility("panda"))
    session.submit(P1, DecisionResponse(()))

    deck = session.game.table.decks[DeckKey(P1, Side.DYNASTY)]
    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert "panda" in {card.id for card in discard.cards}
    assert "panda" not in {card.id for card in deck.cards}


def test_the_event_leaves_its_province_either_way():
    for answer in (("panda",), ()):
        session = _panda_game()
        session.act(P1, ActivateAbility("panda"))
        session.submit(P1, DecisionResponse(answer))

        province = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)]
        assert "panda" not in {card.id for card in province.cards}


def test_using_the_blessing_replays_to_the_same_state():
    session = _panda_game()
    session.act(P1, ActivateAbility("panda"))
    session.submit(P1, DecisionResponse(("panda",)))
    assert replay(session.log) == session.game


def test_it_cannot_be_backed_out_of_once_the_opponent_has_been_given_something():
    """Every other modeled card emits at its own owner, so this is the only one whose abort can
    reach across the table — and it must not. P2 has seen the card it drew, and taking the card back
    does not take back the seeing."""
    session = _panda_game()
    session.act(P1, ActivateAbility("panda"))
    assert (_honor(session, P2), len(_hand(session, P2))) == (1, 1)  # the gift landed
    drawn = _hand(session, P2)[0]

    assert session.abort(P1) is False
    with pytest.raises(ValueError, match="nothing left to unwind"):
        session.cancel(P1)

    assert _honor(session, P2) == 1  # still theirs
    assert _hand(session, P2) == [drawn]
    assert isinstance(session.game.pending, Confirm)  # and the question is still owed
