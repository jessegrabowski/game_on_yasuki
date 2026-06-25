from yasuki_core.engine.setup import setup_seat
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.engine.players import PlayerId
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyCard
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.game_pieces.pregame import StrongholdCard, SenseiCard
from yasuki_core.game_pieces.factory import ResolvedDeck


def _resolved(owner=PlayerId.P1, dynasty_n=5, fate_n=4):
    dynasty = [
        DynastyCard(id=f"{owner.name}-d{i}", name=f"D{i}", side=Side.DYNASTY, owner=owner)
        for i in range(dynasty_n)
    ]
    fate = [
        FateCard(id=f"{owner.name}-f{i}", name=f"F{i}", side=Side.FATE, owner=owner)
        for i in range(fate_n)
    ]
    return ResolvedDeck(dynasty=dynasty, fate=fate)


def _setup(owner=PlayerId.P1, dynasty_seed=1, fate_seed=2):
    state = TableState.empty_two_seat()
    setup_seat(state, owner, _resolved(owner), dynasty_seed=dynasty_seed, fate_seed=fate_seed)
    return state


def _provinces(state, owner=PlayerId.P1):
    return [
        zone
        for key, zone in state.zones.items()
        if key.owner == owner and key.role is ZoneRole.PROVINCE
    ]


def _dynasty_order(state):
    return [card.id for card in state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards]


def test_decks_are_loaded_face_down_and_registered():
    state = _setup()
    dynasty = state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)]
    fate = state.decks[DeckKey(PlayerId.P1, Side.FATE)]

    assert len(dynasty.cards) == 5 and len(fate.cards) == 4
    assert all(not card.face_up for card in dynasty.cards + fate.cards)
    assert all(card.id in state.cards_by_id for card in dynasty.cards + fate.cards)


def test_a_deck_without_a_stronghold_opens_the_default_four_provinces():
    state = _setup()
    provinces = _provinces(state)
    assert len(provinces) == 4
    assert all(province.cards == [] for province in provinces)


def test_province_count_comes_from_the_stronghold():
    state = TableState.empty_two_seat()
    resolved = _resolved()
    resolved.pre_game.append(
        StrongholdCard(id="sh", name="Wall", side=Side.STRONGHOLD, province_count=5)
    )
    setup_seat(state, PlayerId.P1, resolved, dynasty_seed=1, fate_seed=2)
    assert len(_provinces(state)) == 5


def test_hand_discards_and_banishes_start_empty():
    state = _setup()
    for role in (
        ZoneRole.HAND,
        ZoneRole.FATE_DISCARD,
        ZoneRole.FATE_BANISH,
        ZoneRole.DYNASTY_DISCARD,
        ZoneRole.DYNASTY_BANISH,
    ):
        assert state.zones[ZoneKey(PlayerId.P1, role)].cards == []


def test_shuffle_order_is_reproducible_for_a_seed():
    assert _dynasty_order(_setup(dynasty_seed=7)) == _dynasty_order(_setup(dynasty_seed=7))


def test_pre_game_cards_are_dealt_face_up_to_the_battlefield():
    state = TableState.empty_two_seat()
    resolved = _resolved()
    stronghold = StrongholdCard(id="sh", name="Kyuden", side=Side.STRONGHOLD, owner=PlayerId.P1)
    sensei = SenseiCard(id="se", name="Sensei", side=Side.FATE, owner=PlayerId.P1)
    resolved.pre_game.extend([stronghold, sensei])

    setup_seat(state, PlayerId.P1, resolved, dynasty_seed=1, fate_seed=2)

    assert stronghold in state.battlefield.cards and sensei in state.battlefield.cards
    assert stronghold.face_up and sensei.face_up
    assert all(card.id in state.positions for card in (stronghold, sensei))
    deck_cards = [card for deck in state.decks.values() for card in deck.cards]
    assert stronghold not in deck_cards and sensei not in deck_cards
    state.validate()  # raises on any structural violation


def _setup_with_pregame(*pre_game):
    state = TableState.empty_two_seat()
    resolved = _resolved()
    resolved.pre_game.extend(pre_game)
    setup_seat(state, PlayerId.P1, resolved, dynasty_seed=1, fate_seed=2)
    return state


def test_starting_honor_sums_stronghold_and_sensei():
    state = _setup_with_pregame(
        StrongholdCard(id="sh", name="Kyuden", side=Side.STRONGHOLD, starting_honor=10),
        SenseiCard(id="se", name="Sensei", side=Side.FATE, starting_honor=5),
    )
    assert state.seats[PlayerId.P1].honor == 15


def test_starting_honor_from_a_stronghold_alone_is_its_base():
    state = _setup_with_pregame(
        StrongholdCard(id="sh", name="Kyuden", side=Side.STRONGHOLD, starting_honor=10)
    )
    assert state.seats[PlayerId.P1].honor == 10


def test_a_deck_without_a_stronghold_starts_at_zero_honor():
    assert _setup().seats[PlayerId.P1].honor == 0


def test_the_table_validates_after_setup():
    state = _setup()
    state.validate()  # raises on any structural violation
