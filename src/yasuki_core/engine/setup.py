from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey, BoardPos
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.factory import ResolvedDeck
from yasuki_core.game_pieces.pregame import StrongholdCard, SenseiCard

# Pre-game permanents start as loose, face-up battlefield cards at a negative sentinel position; the
# client recognises an unplaced pre-game card and lays it out next to that seat's dynasty deck, after
# which a drag gives it a real on-board position.
PREGAME_UNPLACED = BoardPos(-1.0, -1.0)


def setup_seat(
    state: TableState,
    seat: PlayerId,
    resolved: ResolvedDeck,
    *,
    dynasty_seed: int,
    fate_seed: int,
) -> None:
    """Build ``seat``'s table slice from its resolved deck and deal its opening table.

    Load the dynasty and fate cards into their decks face-down, shuffling each with the given seed,
    open the stronghold's provinces and fill each one face-down from the dynasty deck, draw the
    stronghold's ``starting_hand_size`` fate cards face-up into the hand, fold each sensei's
    gold-production and province-strength deltas into the stronghold, deal the pre-game permanents
    (stronghold, sensei, wind) face-up onto the battlefield as loose cards, set the seat's starting
    honor from its stronghold and sensei, and register every card in the table's identity map. The
    discards and banishes stay empty, and no deck legality is enforced (a manual sandbox).

    Parameters
    ----------
    state : TableState
        The table to populate in place.
    seat : PlayerId
        The seat being set up.
    resolved : ResolvedDeck
        The seat's cards, as produced by ``resolve_decklist``.
    dynasty_seed : int
        Seed for the dynasty deck shuffle.
    fate_seed : int
        Seed for the fate deck shuffle.
    """
    _load_deck(state, DeckKey(seat, Side.DYNASTY), resolved.dynasty, dynasty_seed)
    _load_deck(state, DeckKey(seat, Side.FATE), resolved.fate, fate_seed)
    for idx in range(_province_count(resolved)):
        state.zones[ZoneKey(seat, ZoneRole.PROVINCE, idx)] = ProvinceZone(owner=seat)
    _apply_sensei_modifiers(resolved)
    _place_pregame(state, seat, resolved.pre_game)
    state.seats[seat].honor = _starting_honor(resolved)
    _fill_provinces(state, seat)
    _draw_starting_hand(state, seat, _starting_hand_size(resolved))


def _stronghold(resolved: ResolvedDeck) -> StrongholdCard | None:
    """The deck's stronghold pre-game card, or None if it has none."""
    return next((card for card in resolved.pre_game if isinstance(card, StrongholdCard)), None)


def _province_count(resolved: ResolvedDeck) -> int:
    """The stronghold's province count, or the class default when there's no stronghold."""
    stronghold = _stronghold(resolved)
    if stronghold is not None:
        return stronghold.province_count
    return StrongholdCard.__dataclass_fields__["province_count"].default


def _starting_honor(resolved: ResolvedDeck) -> int:
    return sum(
        card.starting_honor
        for card in resolved.pre_game
        if isinstance(card, (StrongholdCard, SenseiCard))
    )


def _apply_sensei_modifiers(resolved: ResolvedDeck) -> None:
    """Fold each sensei's gold-production and province-strength deltas into the stronghold, so every
    downstream consumer reads the stronghold's effective characteristics with no sensei awareness.
    Starting honor is a seat scalar and is summed separately by :func:`_starting_honor`.

    TODO: migrate these deltas to WHILE_SOURCE_IN_PLAY modifiers (engine/rules/modifiers.py) once an
    attachment model exists — the Sensei is a live battlefield card, so it should be a modifier
    source like any attachment rather than a baked printed-stat mutation."""
    stronghold = _stronghold(resolved)
    if stronghold is None:
        return
    senseis = [card for card in resolved.pre_game if isinstance(card, SenseiCard)]
    gold = sum(sensei.gold_production for sensei in senseis)
    province = sum(sensei.province_strength for sensei in senseis)
    if gold:
        object.__setattr__(stronghold, "gold_production", stronghold.gold_production + gold)
    if province:
        object.__setattr__(stronghold, "province_strength", stronghold.province_strength + province)


def _starting_hand_size(resolved: ResolvedDeck) -> int:
    """The stronghold's starting hand size, or the class default when there's no stronghold."""
    stronghold = _stronghold(resolved)
    if stronghold is not None:
        return stronghold.starting_hand_size
    return StrongholdCard.__dataclass_fields__["starting_hand_size"].default


def _fill_provinces(state: TableState, seat: PlayerId) -> None:
    """Fill every empty province face-down from the seat's dynasty deck."""
    dynasty = state.decks[DeckKey(seat, Side.DYNASTY)]
    for key, zone in state.zones.items():
        if key.owner == seat and key.role is ZoneRole.PROVINCE and zone.has_capacity():
            card = dynasty.draw_one()
            if card is None:
                break
            card.turn_face_down()
            zone.add(card)


def _draw_starting_hand(state: TableState, seat: PlayerId, count: int) -> None:
    """Draw ``count`` fate cards face-up into the seat's hand, stopping if the deck runs dry."""
    fate = state.decks[DeckKey(seat, Side.FATE)]
    hand = state.zones[ZoneKey(seat, ZoneRole.HAND)]
    for _ in range(count):
        card = fate.draw_one()
        if card is None:
            break
        card.turn_face_up()
        hand.add(card)


def flip_second_player_stronghold(
    state: TableState, seats: tuple[PlayerId, PlayerId]
) -> PlayerId | None:
    """Resolve turn order by honor and flip the second player's stronghold to its back face.

    The lower-honor seat goes second; flip its stronghold to the back side, but only when that
    stronghold actually has a back face (single-faced strongholds are left front-up). On an honor
    tie, no seat is demoted and nothing is flipped. Return the seat that goes second, or None on a
    tie.

    Parameters
    ----------
    state : TableState
        The table, already set up for both seats.
    seats : tuple of PlayerId
        The two seated players to compare.
    """
    first, second = seats
    honor_first, honor_second = state.seats[first].honor, state.seats[second].honor
    if honor_first == honor_second:
        return None
    loser = first if honor_first < honor_second else second
    stronghold = _find_stronghold(state, loser)
    if stronghold is not None and stronghold.back_card_id is not None:
        stronghold.flip_face()
    return loser


def _find_stronghold(state: TableState, seat: PlayerId) -> L5RCard | None:
    """The seat's stronghold among its loose battlefield cards, or None."""
    return next(
        (
            card
            for card in state.battlefield.cards
            if isinstance(card, StrongholdCard) and card.owner == seat
        ),
        None,
    )


def _place_pregame(state: TableState, seat: PlayerId, cards: list[L5RCard]) -> None:
    for card in cards:
        card.turn_face_up()
        state.cards_by_id[card.id] = card
        state.battlefield.add(card)
        state.positions[card.id] = PREGAME_UNPLACED


def _load_deck(state: TableState, key: DeckKey, cards: list[L5RCard], seed: int) -> None:
    for card in cards:
        card.turn_face_down()
        state.cards_by_id[card.id] = card
    deck = state.decks[key]
    deck.cards = list(cards)
    deck.shuffle(seed)
