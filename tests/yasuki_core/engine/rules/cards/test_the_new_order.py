from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.actions import Recruit
from yasuki_core.engine.rules.vocabulary.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side

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


def test_plain_library_enters_play_bowed_and_looks_at_three_after_the_recruit():
    session = _library_game()
    session.act(P1, Recruit("library"))

    pay(session, P1)

    assert session.game.table.cards_by_id["library"].bowed
    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.candidates == ("a", "b", "c")
    assert pending.minimum == 0 and pending.maximum == 2
    assert session.game.look.card_ids == ("a", "b", "c")


def test_plain_library_places_the_picked_cards_at_the_bottom_in_pick_order():
    session = _library_game()
    session.act(P1, Recruit("library"))
    pay(session, P1)

    session.submit(P1, DecisionResponse(("c", "a")))

    assert _fate_deck(session) == ["b", "d", "c", "a"]
    assert session.game.look is None
    assert session.game.pending is None
    assert session.log.replay() == session.game


def test_plain_library_may_place_nothing():
    session = _library_game()
    session.act(P1, Recruit("library"))
    pay(session, P1)

    session.submit(P1, DecisionResponse(()))

    assert _fate_deck(session) == ["a", "b", "c", "d"]
    assert session.game.look is None
