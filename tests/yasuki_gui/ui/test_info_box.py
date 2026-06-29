from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.intents import Draw, MoveCard
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.ui.info_box import PlayerInfoBox


def test_cell_counts_mirror_the_table(root, loaded):
    field, state = loaded
    box = PlayerInfoBox(root, field, PlayerId.P1)
    counts = box.cell_counts()
    assert counts["fate_deck"] == len(state.decks[DeckKey(PlayerId.P1, Side.FATE)].cards)
    assert counts["dynasty_deck"] == len(state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards)
    assert counts["hand"] == len(state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards)
    assert counts["fate_discard"] == 0  # nothing discarded yet


def test_discard_count_tracks_a_move(root, loaded):
    field, state = loaded
    box = PlayerInfoBox(root, field, PlayerId.P1)
    field.dispatch(Draw(DeckKey(PlayerId.P1, Side.DYNASTY)))
    card = state.battlefield.cards[-1]
    field.dispatch(MoveCard(card.id, ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)))
    box.refresh()
    assert box.cell_counts()["dynasty_discard"] == 1


def test_box_reads_its_own_seats_piles(root, loaded):
    field, state = loaded
    box = PlayerInfoBox(root, field, PlayerId.P2)  # the opponent's box
    counts = box.cell_counts()
    assert counts["fate_deck"] == len(state.decks[DeckKey(PlayerId.P2, Side.FATE)].cards)
    assert counts["hand"] == len(state.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].cards)


class _Wheel:
    def __init__(self, delta):
        self.delta = delta


def test_human_box_adjust_dispatches_set_honor(root, loaded):
    field, state = loaded  # human is P1
    box = PlayerInfoBox(root, field, PlayerId.P1)
    start = state.seats[PlayerId.P1].honor

    box._adjust(1)
    assert state.seats[PlayerId.P1].honor == start + 1
    assert box._honor_text.get() == f"Honor {start + 1}"

    box._adjust(-1)
    assert state.seats[PlayerId.P1].honor == start


def test_human_box_wheel_adjusts(root, loaded):
    field, state = loaded
    box = PlayerInfoBox(root, field, PlayerId.P1)
    start = state.seats[PlayerId.P1].honor

    box._on_wheel(_Wheel(delta=120))
    assert state.seats[PlayerId.P1].honor == start + 1
    box._on_wheel(_Wheel(delta=-120))
    assert state.seats[PlayerId.P1].honor == start


def test_opponent_box_honor_is_read_only(root, loaded):
    field, state = loaded
    box = PlayerInfoBox(root, field, PlayerId.P2)
    start = state.seats[PlayerId.P2].honor

    box._adjust(1)
    assert state.seats[PlayerId.P2].honor == start


def test_editability_follows_the_acting_seat(root, loaded):
    # The debug seat toggle makes the other box editable; refresh() must pick that up.
    field, state = loaded
    box = PlayerInfoBox(root, field, PlayerId.P2)
    field.seat = PlayerId.P2
    box.refresh()

    start = state.seats[PlayerId.P2].honor
    box._adjust(1)
    assert state.seats[PlayerId.P2].honor == start + 1
