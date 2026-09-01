from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    fate_card,
    holding,
    pay,
    personality,
    put_in_play,
    register,
)

P1 = PlayerId.P1


def _tome_game(*, production: int = 3, fate_deck: int = 1) -> EngineSession:
    """Ancient Tome attached to a Personality, with ``production`` gold to reach its cost."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("sh", printed_id="plain_stronghold", gold_production=production))
    put_in_play(state, personality("bearer", owner=P1, chi=3))
    attached(state, attachment("tome", printed_id="ancient_tome", gold_cost=2), "bearer")
    state.decks[DeckKey(P1, Side.FATE)].cards = [
        register(state, fate_card(f"P1-fd{index}", P1)) for index in range(fate_deck)
    ]
    return EngineSession.start(state, P1)


def _hand(session: EngineSession) -> list[str]:
    return [card.id for card in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards]


def test_ancient_tome_draws_a_card_for_its_gold_and_its_bow():
    session = _tome_game()

    session.act(P1, ActivateAbility("tome"))
    pay(session, P1)

    assert _hand(session) == ["P1-fd0"]
    assert session.game.table.cards_by_id["tome"].bowed
    assert session.game.gold[P1] == 0  # 3 produced, 3 spent


def test_a_bowed_tome_is_not_offered():
    """The bow is half its cost, and a bowed card cannot pay one (CR, Costs)."""
    session = _tome_game()
    session.game.table.cards_by_id["tome"].bow()

    assert ActivateAbility("tome") not in session.legal_actions(P1)


def test_a_tome_its_seat_cannot_pay_for_is_not_offered():
    session = _tome_game(production=2)

    assert ActivateAbility("tome") not in session.legal_actions(P1)


def test_an_empty_fate_deck_still_costs_the_gold_and_the_bow():
    """Drawing from an exhausted deck draws nothing; the cost is paid all the same (CR, Costs)."""
    session = _tome_game(fate_deck=0)

    session.act(P1, ActivateAbility("tome"))
    pay(session, P1)

    assert _hand(session) == []
    assert session.game.table.cards_by_id["tome"].bowed
