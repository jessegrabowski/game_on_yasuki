from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.decisions import (
    ChooseAbilityTarget,
    DecisionResponse,
)
from yasuki_core.engine.rules.economy import effective_gold_production
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import Side


from tests.yasuki_core.engine.builders import (
    fate_card,
    holding,
    put_in_play,
    register,
)

P1 = PlayerId.P1


def _otokoshi_game():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("oto", printed_id="otokoshi_district", gold_production=2))
    put_in_play(state, holding("mkt", printed_id="market", keywords=("Market",), gold_production=1))
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card("fd", P1))]
    return EngineSession.start(state, P1)


def test_otokoshi_destroys_itself_to_draw_and_seed_a_market():
    session = _otokoshi_game()
    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)]
    before = len(hand.cards)

    session.act(P1, ActivateAbility("oto"))
    session.submit(P1, DecisionResponse(("mkt",)))

    table = session.game.table
    discard = table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert "oto" in {c.id for c in discard.cards}  # destroyed itself as the cost
    assert len(hand.cards) == before + 1  # drew a card
    assert table.cards_by_id["mkt"].counters.get("wealth") == 1  # market seeded a wealth token


def test_otokoshi_is_not_activatable_without_a_market():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("oto", printed_id="otokoshi_district", gold_production=2))
    session = EngineSession.start(state, P1)
    assert ActivateAbility("oto") not in session.legal_actions(P1)


def test_otokoshi_activation_replays_to_the_same_state():
    session = _otokoshi_game()
    session.act(P1, ActivateAbility("oto"))
    session.submit(P1, DecisionResponse(("mkt",)))
    assert replay(session.log) == session.game


def test_a_non_bow_ability_is_activatable_while_bowed():
    # Tireless: a destroy/spend cost does not require an unbowed card (unlike a bow cost).
    session = _otokoshi_game()
    session.game.table.cards_by_id["oto"].bow()
    assert ActivateAbility("oto") in session.legal_actions(P1)


def _ichiba_game(fate_cards: int = 1, ports: int = 1) -> EngineSession:
    state = TableState.empty_two_seat()
    put_in_play(
        state, holding("ich", printed_id="ichiba_district", keywords=("Market",), gold_production=1)
    )
    for i in range(ports):
        put_in_play(
            state,
            holding(f"port{i}", printed_id="island_wharf", keywords=("Port",), gold_production=2),
        )
    state.decks[DeckKey(P1, Side.FATE)].cards = [
        register(state, fate_card(f"fd{i}", P1)) for i in range(fate_cards)
    ]
    return EngineSession.start(state, P1)


def test_ichiba_banishes_the_top_fate_card_then_boosts_a_target_port():
    session = _ichiba_game(fate_cards=2, ports=1)
    session.act(P1, ActivateAbility("ich"))

    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget) and pending.candidates == ("port0",)
    table = session.game.table
    banished = table.zones[ZoneKey(P1, ZoneRole.FATE_BANISH)]
    assert [c.id for c in banished.cards] == ["fd1"]  # the top (drawn end), not the bottom
    assert [c.id for c in table.decks[DeckKey(P1, Side.FATE)].cards] == ["fd0"]  # the rest

    session.submit(P1, DecisionResponse(("port0",)))
    assert effective_gold_production(session.game, table.cards_by_id["port0"]) == 3  # base 2 + 1


def test_ichiba_is_not_activatable_with_an_empty_fate_deck():
    session = _ichiba_game(fate_cards=0, ports=1)
    assert ActivateAbility("ich") not in session.legal_actions(P1)


def test_ichiba_is_not_activatable_without_a_port():
    session = _ichiba_game(fate_cards=1, ports=0)
    assert ActivateAbility("ich") not in session.legal_actions(P1)


def test_ichiba_activation_replays_to_the_same_state():
    session = _ichiba_game(fate_cards=2, ports=1)
    session.act(P1, ActivateAbility("ich"))
    session.submit(P1, DecisionResponse(("port0",)))
    assert replay(session.log) == session.game
