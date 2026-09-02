from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.economy import effective_gold_production
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_core.engine.builders import fate_card, holding, put_in_play, register

P1 = PlayerId.P1


def _peddler_game(*, other_production: int = 0, cards_in_deck: int = 1) -> EngineSession:
    """The Peddler in play, with an ordinary Holding beside it making ``other_production``."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("peddler", owner=P1, printed_id="traveling_peddler"))
    if other_production:
        put_in_play(state, holding("farm", owner=P1, gold_production=other_production))
    state.decks[DeckKey(P1, Side.FATE)].cards = [
        register(state, fate_card(f"fd{i}", P1)) for i in range(cards_in_deck)
    ]
    return EngineSession.start(state, P1)


def _hand(session: EngineSession) -> list[str]:
    return [card.id for card in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards]


def test_the_peddler_produces_two_gold_from_its_text():
    """ "Produce 2 Gold" is printed as text, not as a Gold Production stat, so only the handler
    delivers it — the stat on the card is blank."""
    session = _peddler_game()

    assert effective_gold_production(session.game, session.game.table.cards_by_id["peddler"]) == 2


def test_the_peddler_bows_and_pays_three_gold_to_draw():
    session = _peddler_game(other_production=3)

    session.act(P1, ActivateAbility("peddler"))
    session.submit(P1, DecisionResponse(("farm",)))  # bow the farm for its 3 gold

    assert _hand(session) == ["fd0"]
    assert session.game.table.cards_by_id["peddler"].bowed
