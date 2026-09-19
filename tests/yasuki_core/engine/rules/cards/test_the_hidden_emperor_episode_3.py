from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.actions import PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import fate_card, pay, personality, put_in_play, register

P1 = PlayerId.P1
FATE = DeckKey(P1, Side.FATE)


def _shadows_game(deck: tuple[str, ...] = ("a", "b", "c", "d", "e")) -> EngineSession:
    """P1 holding Banish All Shadows, an unbowed Monk, a Shugenja, a plain Bushi, and a Fate deck
    reading ``deck`` from the top."""
    state = TableState.empty_two_seat()
    put_in_play(state, personality("monk", keywords=("Monk",)))
    put_in_play(state, personality("priest", keywords=("Shugenja",)))
    put_in_play(state, personality("bushi"))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                FatePrint,
                id="shadows",
                name="Banish All Shadows",
                printed_id="banish_all_shadows",
                side=Side.FATE,
                owner=P1,
                gold_cost=0,
                keywords=("Kiho",),
            ),
        )
    )
    state.decks[FATE].cards = [
        register(state, fate_card(card_id, P1)) for card_id in reversed(deck)
    ]
    return EngineSession.start(state, P1)


def _fate_deck(session: EngineSession) -> list[str]:
    return [card.id for card in reversed(session.game.table.decks[FATE].cards)]


def test_banish_all_shadows_targets_unbowed_monks_and_shugenja():
    session = _shadows_game()
    session.act(P1, PlayStrategy("shadows"))
    pay(session, P1)

    assert session.game.pending.candidates == ("monk", "priest")


def test_banish_all_shadows_takes_one_of_four_and_shuffles():
    session = _shadows_game()
    session.act(P1, PlayStrategy("shadows"))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("monk",)))
    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.candidates == ("a", "b", "c", "d")
    assert session.game.table.cards_by_id["monk"].bowed

    session.submit(P1, DecisionResponse(("c",)))

    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert [card.id for card in hand] == ["c"]
    assert sorted(_fate_deck(session)) == ["a", "b", "d", "e"]
    assert session.game.look is None
    assert session.game.pending is None
    assert session.log.replay() == session.game
