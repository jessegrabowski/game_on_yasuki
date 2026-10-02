import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility, Recruit
from yasuki_core.engine.rules.vocabulary.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint, RingPrint

from tests.yasuki_core.engine.builders import (
    end_phase,
    fate_card,
    holding,
    pay,
    put_in_play,
    register,
    stronghold,
)

P1 = PlayerId.P1
FATE = DeckKey(P1, Side.FATE)


def _library_game(deck=("a", "b", "c", "d")) -> EngineSession:
    """Plain Library face-up in P1's first Province with gold enough to Recruit it, in the Dynasty
    phase, over a Fate deck reading ``deck`` from the top."""
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1, gold_production=8))
    library = register(
        state,
        holding(
            "library",
            printed_id="plain_library",
            gold_cost=3,
            gold_production=3,
            keywords=("Expendable", "Fortification", "Library"),
        ),
    )
    library.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(library)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    state.decks[FATE].cards = [
        register(state, fate_card(card_id, P1)) for card_id in reversed(deck)
    ]
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    return session


def _fate_deck(session: EngineSession) -> list[str]:
    return [card.id for card in reversed(session.game.table.decks[FATE].cards)]


def test_recruiting_plain_library_offers_its_look_as_a_response_rather_than_taking_it():
    """The after-Recruit text is a Response the seat takes or declines, as with Courts of Otosan
    Uchi. Nothing has been looked at until it is taken."""
    session = _library_game()
    session.act(P1, Recruit("library"))

    pay(session, P1)

    assert session.game.table.cards_by_id["library"].bowed
    assert session.game.pending is None
    assert session.game.look is None
    assert ActivateAbility("library") in session.legal_actions(P1)


def _recruit_and_respond(session: EngineSession) -> None:
    session.act(P1, Recruit("library"))
    pay(session, P1)
    session.act(P1, ActivateAbility("library"))


def test_plain_library_looks_at_three_when_taken():
    session = _library_game()

    _recruit_and_respond(session)

    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.candidates == ("a", "b", "c")
    assert pending.minimum == 0 and pending.maximum == 2
    assert session.game.look.card_ids == ("a", "b", "c")


def test_plain_library_places_the_picked_cards_at_the_bottom_in_pick_order():
    session = _library_game()
    _recruit_and_respond(session)

    session.submit(P1, DecisionResponse(("c", "a")))

    assert _fate_deck(session) == ["b", "d", "c", "a"]
    assert session.game.look is None
    assert session.game.pending is None
    assert session.log.replay() == session.game


def test_plain_library_may_place_nothing():
    session = _library_game()
    _recruit_and_respond(session)

    session.submit(P1, DecisionResponse(()))

    assert _fate_deck(session) == ["a", "b", "c", "d"]
    assert session.game.look is None


def test_plain_library_is_not_offered_after_another_recruit():
    session = _library_game()
    session.act(P1, Recruit("library"))
    pay(session, P1)
    session.act(P1, ActivateAbility("library"))
    session.submit(P1, DecisionResponse(()))

    assert ActivateAbility("library") not in session.legal_actions(P1)


# --- Remote Temple ---


def _temple_game(*deck: L5RCard) -> EngineSession:
    """Remote Temple in P1's play, "held" in P1's hand, and ``deck`` as P1's Fate deck."""
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1))
    put_in_play(state, register(state, holding("temple", printed_id="remote_temple")))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, fate_card("held", P1)))
    state.decks[FATE].cards = [register(state, card) for card in deck]
    return EngineSession.start(state, P1)


def _ring(card_id: str) -> L5RCard:
    return L5RCard.of(
        RingPrint, id=card_id, printed_id=card_id, name=card_id, side=Side.FATE, owner=P1
    )


def _way_of_the_dragon(card_id: str) -> L5RCard:
    return L5RCard.of(
        ActionPrint,
        id=card_id,
        printed_id="way_of_the_dragon_experienced",
        name="Way of the Dragon",
        side=Side.FATE,
        owner=P1,
    )


def _hand(session: EngineSession) -> set[str]:
    return {card.id for card in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards}


def _discarded(session: EngineSession, role: ZoneRole) -> set[str]:
    return {card.id for card in session.game.table.zones[ZoneKey(P1, role)].cards}


@pytest.mark.parametrize(
    "found", [_ring("ring"), _way_of_the_dragon("ring")], ids=["ring", "dragon"]
)
def test_remote_temple_takes_a_ring_then_discards_a_card_and_destroys_itself(found):
    session = _temple_game(fate_card("plain", P1), found)

    session.act(P1, ActivateAbility("temple"))
    assert session.game.pending.candidates == ("ring",)
    session.submit(P1, DecisionResponse(("ring",)))
    session.submit(P1, DecisionResponse(("held",)))

    assert _hand(session) == {"ring"}
    assert _discarded(session, ZoneRole.FATE_DISCARD) == {"held"}
    assert _discarded(session, ZoneRole.DYNASTY_DISCARD) == {"temple"}
    assert [card.id for card in session.game.table.decks[FATE].cards] == ["plain"]


def test_remote_temple_finding_no_ring_still_discards_and_destroys_itself():
    session = _temple_game(fate_card("plain", P1))

    session.act(P1, ActivateAbility("temple"))

    assert _hand(session) == set()
    assert _discarded(session, ZoneRole.FATE_DISCARD) == {"held"}
    assert _discarded(session, ZoneRole.DYNASTY_DISCARD) == {"temple"}
