from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    TableState,
    DeckKey,
    Shuffle,
    apply_intent,
)
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.fate import FateCard


def _table_with_fate_deck(n: int = 20) -> TableState:
    table = TableState.empty_two_seat()
    deck = table.decks[DeckKey(PlayerId.P1, Side.FATE)]
    for i in range(n):
        card = FateCard(id=f"f{i}", name=f"f{i}", side=Side.FATE, owner=PlayerId.P1)
        table.cards_by_id[card.id] = card
        deck.cards.append(card)
    return table


def _order(table: TableState) -> list[str]:
    return [c.id for c in table.decks[DeckKey(PlayerId.P1, Side.FATE)].cards]


def test_same_seed_yields_same_order():
    a = _table_with_fate_deck()
    b = _table_with_fate_deck()

    apply_intent(a, PlayerId.P1, Shuffle(DeckKey(PlayerId.P1, Side.FATE), seed=12345))
    apply_intent(b, PlayerId.P1, Shuffle(DeckKey(PlayerId.P1, Side.FATE), seed=12345))

    assert _order(a) == _order(b)


def test_different_seeds_yield_different_order():
    a = _table_with_fate_deck()
    b = _table_with_fate_deck()

    apply_intent(a, PlayerId.P1, Shuffle(DeckKey(PlayerId.P1, Side.FATE), seed=1))
    apply_intent(b, PlayerId.P1, Shuffle(DeckKey(PlayerId.P1, Side.FATE), seed=2))

    assert _order(a) != _order(b)


def test_shuffle_records_seed_in_event():
    table = _table_with_fate_deck()

    events = apply_intent(table, PlayerId.P1, Shuffle(DeckKey(PlayerId.P1, Side.FATE), seed=99))

    assert events[0].intent.seed == 99
    assert table.seq == 1


def test_replaying_recorded_seed_reproduces_order():
    # The event's seed is enough to reproduce the order on a fresh deck — the basis for replay.
    live = _table_with_fate_deck()
    events = apply_intent(live, PlayerId.P1, Shuffle(DeckKey(PlayerId.P1, Side.FATE), seed=4242))

    replay = _table_with_fate_deck()
    apply_intent(replay, PlayerId.P1, events[0].intent)

    assert _order(replay) == _order(live)
