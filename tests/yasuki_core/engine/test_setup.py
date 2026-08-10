from yasuki_core.engine.setup import (
    setup_seat,
    flip_second_player_stronghold,
    PREGAME_UNPLACED,
)
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from numpy.random import default_rng

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.economy import active_modifiers, effective_gold_production
from yasuki_core.engine.rules.flow import begin_game
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.legality import gold_producers
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyCard
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.game_pieces.pregame import StrongholdCard, SenseiCard
from yasuki_core.game_pieces.factory import ResolvedDeck


def _resolved(owner=PlayerId.P1, dynasty_n=10, fate_n=10):
    dynasty = [
        DynastyCard(id=f"{owner.name}-d{i}", name=f"D{i}", side=Side.DYNASTY, owner=owner)
        for i in range(dynasty_n)
    ]
    fate = [
        FateCard(id=f"{owner.name}-f{i}", name=f"F{i}", side=Side.FATE, owner=owner)
        for i in range(fate_n)
    ]
    return ResolvedDeck(dynasty=dynasty, fate=fate)


def _setup(owner=PlayerId.P1, seed=1):
    state = TableState.empty_two_seat()
    setup_seat(state, owner, _resolved(owner), rng=default_rng(seed))
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

    # Ten of each, less the four dealt to provinces and the five drawn to the opening hand.
    assert len(dynasty.cards) == 6 and len(fate.cards) == 5
    assert all(not card.face_up for card in dynasty.cards + fate.cards)
    assert all(card.id in state.cards_by_id for card in dynasty.cards + fate.cards)


def test_a_deck_without_a_stronghold_opens_and_fills_the_default_four_provinces():
    state = _setup()
    provinces = _provinces(state)
    assert len(provinces) == 4
    # Every province starts full, face-down, from the dynasty deck.
    assert all(len(province.cards) == 1 and not province.cards[0].face_up for province in provinces)


def test_province_count_comes_from_the_stronghold():
    state = TableState.empty_two_seat()
    resolved = _resolved()
    resolved.pre_game.append(
        StrongholdCard(id="sh", name="Wall", side=Side.STRONGHOLD, province_count=5)
    )
    setup_seat(state, PlayerId.P1, resolved, rng=default_rng(1))
    assert len(_provinces(state)) == 5


def test_discards_and_banishes_start_empty():
    state = _setup()
    for role in (
        ZoneRole.FATE_DISCARD,
        ZoneRole.FATE_BANISH,
        ZoneRole.DYNASTY_DISCARD,
        ZoneRole.DYNASTY_BANISH,
    ):
        assert state.zones[ZoneKey(PlayerId.P1, role)].cards == []


def test_the_opening_hand_is_drawn_face_up():
    state = _setup()
    hand = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    # The default starting hand is five fate cards, dealt face up to their owner.
    assert len(hand.cards) == 5
    assert all(card.side is Side.FATE and card.face_up for card in hand.cards)


def test_starting_hand_size_comes_from_the_stronghold():
    state = TableState.empty_two_seat()
    resolved = _resolved()
    resolved.pre_game.append(
        StrongholdCard(id="sh", name="Wall", side=Side.STRONGHOLD, starting_hand_size=3)
    )
    setup_seat(state, PlayerId.P1, resolved, rng=default_rng(1))
    assert len(state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards) == 3


def test_shuffle_order_is_reproducible_for_a_seed():
    assert _dynasty_order(_setup(seed=7)) == _dynasty_order(_setup(seed=7))


def test_pre_game_cards_are_dealt_face_up_as_loose_battlefield_cards():
    state = TableState.empty_two_seat()
    resolved = _resolved()
    stronghold = StrongholdCard(id="sh", name="Kyuden", side=Side.STRONGHOLD, owner=PlayerId.P1)
    sensei = SenseiCard(id="se", name="Sensei", side=Side.FATE, owner=PlayerId.P1)
    resolved.pre_game.extend([stronghold, sensei])

    setup_seat(state, PlayerId.P1, resolved, rng=default_rng(1))

    assert stronghold in state.battlefield.cards and sensei in state.battlefield.cards
    assert stronghold.face_up and sensei.face_up
    # The client lays each one out beside the dynasty deck, so they start at the unplaced sentinel.
    assert state.positions["sh"] == PREGAME_UNPLACED and state.positions["se"] == PREGAME_UNPLACED
    deck_cards = [card for deck in state.decks.values() for card in deck.cards]
    assert stronghold not in deck_cards and sensei not in deck_cards
    state.validate()  # raises on any structural violation


def _granted(game: GameState, card, stat: Stat) -> int:
    """The total a card's modifiers add to ``stat``. Province Strength has no effective-read
    function yet — nothing asks for it until battle exists — so a grant over it is only assertable
    here, which is weaker coverage than the Gold Production cases get."""
    return sum(m.amount for m in active_modifiers(game, card, stat))


def _begun(state) -> GameState:
    """The game the rules layer sees, with the game-start pass run — which is where a sensei's
    characteristics are granted to the stronghold."""
    game = GameState.start(state, PlayerId.P1)
    begin_game(game)
    return game


def _setup_with_pregame(*pre_game):
    state = TableState.empty_two_seat()
    resolved = _resolved()
    resolved.pre_game.extend(pre_game)
    setup_seat(state, PlayerId.P1, resolved, rng=default_rng(1))
    return state


def test_starting_honor_sums_stronghold_and_sensei():
    state = _setup_with_pregame(
        StrongholdCard(id="sh", name="Kyuden", side=Side.STRONGHOLD, starting_honor=10),
        SenseiCard(id="se", name="Sensei", side=Side.FATE, starting_honor=5),
    )
    assert state.seats[PlayerId.P1].honor == 15


def test_a_stronghold_without_a_sensei_starts_unattached():
    state = _setup_with_pregame(
        StrongholdCard(id="sh", name="Kyuden", side=Side.STRONGHOLD, owner=PlayerId.P1),
    )
    assert state.attachments == {}
    state.validate()


def test_a_sensei_without_a_stronghold_is_not_attached():
    # No stronghold to hang on: the sensei is left loose rather than attached to nothing (a crash).
    state = _setup_with_pregame(
        SenseiCard(id="se", name="Sensei", side=Side.FATE, owner=PlayerId.P1),
    )
    assert state.attachments == {}
    state.validate()


def test_starting_honor_from_a_stronghold_alone_is_its_base():
    state = _setup_with_pregame(
        StrongholdCard(id="sh", name="Kyuden", side=Side.STRONGHOLD, starting_honor=10)
    )
    assert state.seats[PlayerId.P1].honor == 10


def test_a_deck_without_a_stronghold_starts_at_zero_honor():
    assert _setup().seats[PlayerId.P1].honor == 0


def test_a_negative_sensei_delta_lowers_what_the_stronghold_reads():
    stronghold = StrongholdCard(
        id="sh",
        name="Kyuden",
        side=Side.STRONGHOLD,
        gold_production=8,
        province_strength=5,
        owner=PlayerId.P1,
    )
    sensei = SenseiCard(
        id="se",
        name="Sensei",
        side=Side.FATE,
        gold_production=-1,
        province_strength=1,
        owner=PlayerId.P1,
    )
    state = _setup_with_pregame(stronghold, sensei)
    game = _begun(state)

    assert (stronghold.gold_production, stronghold.province_strength) == (
        8,
        5,
    )  # printed, untouched
    assert effective_gold_production(game, stronghold) == 7
    assert _granted(game, stronghold, Stat.PROVINCE_STRENGTH) == 1


def test_every_sensei_characteristic_reaches_the_seat():
    stronghold = StrongholdCard(
        id="sh",
        name="Kyuden",
        side=Side.STRONGHOLD,
        starting_honor=10,
        gold_production=3,
        province_strength=4,
        owner=PlayerId.P1,
    )
    sensei = SenseiCard(
        id="se",
        name="Sensei",
        side=Side.FATE,
        starting_honor=5,
        gold_production=2,
        province_strength=1,
        owner=PlayerId.P1,
    )
    state = _setup_with_pregame(stronghold, sensei)

    assert state.seats[PlayerId.P1].honor == 15
    # Nothing is written to a printed stat any more: honor is summed into the seat, and the other
    # two arrive as modifiers, so both cards keep exactly what they were printed with.
    assert (stronghold.starting_honor, sensei.starting_honor) == (10, 5)
    assert (stronghold.gold_production, sensei.gold_production) == (3, 2)
    assert (stronghold.province_strength, sensei.province_strength) == (4, 1)
    game = _begun(state)
    assert effective_gold_production(game, stronghold) == 5
    assert _granted(game, stronghold, Stat.PROVINCE_STRENGTH) == 1


def test_several_senseis_all_contribute():
    """Deck legality is not enforced here, so both the sum and the grant have to cover every sensei
    they are handed rather than the one the rules would allow."""
    stronghold = StrongholdCard(
        id="sh",
        name="Kyuden",
        side=Side.STRONGHOLD,
        starting_honor=10,
        gold_production=3,
        owner=PlayerId.P1,
    )
    senseis = [
        SenseiCard(
            id="se1",
            name="One",
            side=Side.FATE,
            starting_honor=5,
            gold_production=2,
            owner=PlayerId.P1,
        ),
        SenseiCard(
            id="se2",
            name="Two",
            side=Side.FATE,
            starting_honor=1,
            gold_production=4,
            owner=PlayerId.P1,
        ),
    ]
    state = _setup_with_pregame(stronghold, *senseis)

    assert state.seats[PlayerId.P1].honor == 16
    assert stronghold.starting_honor == 10  # printed, untouched
    assert effective_gold_production(_begun(state), stronghold) == 9


def test_a_sensei_is_not_a_second_gold_producer():
    """A sensei's printed Gold Production is a delta the stronghold receives, not gold the sensei
    makes — offering it as a source to bow would pay the seat twice for one characteristic."""
    stronghold = StrongholdCard(
        id="sh", name="Kyuden", side=Side.STRONGHOLD, gold_production=3, owner=PlayerId.P1
    )
    sensei = SenseiCard(
        id="se", name="Sensei", side=Side.FATE, gold_production=2, owner=PlayerId.P1
    )
    state = _setup_with_pregame(stronghold, sensei)

    assert gold_producers(GameState.start(state, PlayerId.P1), PlayerId.P1) == [stronghold]


def test_a_sensei_with_no_stronghold_contributes_nothing():
    """A sensei modifies a stronghold; with none to modify it contributes nothing, and that holds
    for honor as much as for the two characteristics that arrive as grants."""
    sensei = SenseiCard(
        id="se",
        name="Sensei",
        side=Side.FATE,
        starting_honor=5,
        gold_production=2,
        province_strength=1,
        owner=PlayerId.P1,
    )
    state = _setup_with_pregame(sensei)

    assert state.seats[PlayerId.P1].honor == 0
    assert _begun(state).modifiers == []


def test_a_stronghold_without_a_sensei_keeps_its_printed_stats():
    stronghold = StrongholdCard(
        id="sh", name="Kyuden", side=Side.STRONGHOLD, gold_production=8, province_strength=5
    )
    _setup_with_pregame(stronghold)
    assert stronghold.gold_production == 8
    assert stronghold.province_strength == 5


def test_the_table_validates_after_setup():
    state = _setup()
    state.validate()  # raises on any structural violation


def _two_seat_table(p1_honor, p2_honor, *, p2_has_back=True):
    state = TableState.empty_two_seat()
    state.seats[PlayerId.P1].honor = p1_honor
    state.seats[PlayerId.P2].honor = p2_honor
    p1_sh = StrongholdCard(
        id="p1sh", name="Front1", side=Side.STRONGHOLD, owner=PlayerId.P1, back_card_id="p1sh__back"
    )
    p2_sh = StrongholdCard(
        id="p2sh",
        name="Front2",
        side=Side.STRONGHOLD,
        owner=PlayerId.P2,
        back_card_id="p2sh__back" if p2_has_back else None,
    )
    for card in (p1_sh, p2_sh):
        state.battlefield.add(card)
        state.cards_by_id[card.id] = card
    return state, p1_sh, p2_sh


def test_lower_honor_player_goes_second_and_their_stronghold_flips():
    state, p1_sh, p2_sh = _two_seat_table(10, 4)

    second = flip_second_player_stronghold(state, (PlayerId.P1, PlayerId.P2))

    assert second is PlayerId.P2  # lower honor → second
    assert p2_sh.showing_back is True
    assert p1_sh.showing_back is False  # the first player's stronghold stays front-up


def test_an_honor_tie_flips_no_stronghold():
    state, p1_sh, p2_sh = _two_seat_table(7, 7)

    assert flip_second_player_stronghold(state, (PlayerId.P1, PlayerId.P2)) is None
    assert p1_sh.showing_back is False and p2_sh.showing_back is False


def test_a_single_faced_second_player_stronghold_is_dealt_front_up():
    # The lower-honor seat goes second, but a stronghold with no back face is left front-up.
    state, _, p2_sh = _two_seat_table(10, 4, p2_has_back=False)

    second = flip_second_player_stronghold(state, (PlayerId.P1, PlayerId.P2))

    assert second is PlayerId.P2
    assert p2_sh.showing_back is False


def test_the_fate_shuffle_does_not_move_when_the_dynasty_deck_changes_size():
    """What splitting the streams buys. Sharing one generator would make the dynasty shuffle's
    length shift the fate shuffle, so adding a dynasty card would silently change opening hands."""

    def fate_order(dynasty_n: int) -> list[str]:
        state = TableState.empty_two_seat()
        setup_seat(state, PlayerId.P1, _resolved(dynasty_n=dynasty_n), rng=default_rng(11))
        return [card.id for card in state.decks[DeckKey(PlayerId.P1, Side.FATE)].cards]

    assert fate_order(10) == fate_order(14)


def test_a_sensei_leaving_play_takes_its_gold_with_it():
    """What a modifier buys over a baked stat: the grant is sourced from the sensei, so it lasts
    exactly as long as the sensei is on the table. Nothing removes a sensei today, which is why this
    asserts through the modifier rather than through a rule."""
    stronghold = StrongholdCard(
        id="sh", name="Kyuden", side=Side.STRONGHOLD, gold_production=3, owner=PlayerId.P1
    )
    sensei = SenseiCard(
        id="se", name="Sensei", side=Side.FATE, gold_production=2, owner=PlayerId.P1
    )
    game = _begun(_setup_with_pregame(stronghold, sensei))
    assert effective_gold_production(game, stronghold) == 5

    game.table.battlefield.remove(sensei)

    assert effective_gold_production(game, stronghold) == 3
