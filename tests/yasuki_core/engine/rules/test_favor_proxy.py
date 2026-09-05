from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.redaction import HiddenCard, redact
from yasuki_core.engine.rules.effects import DiscardFavor, TakeFavor
from yasuki_core.engine.rules.decisions import DiscardToHandSize
from yasuki_core.engine.rules.flow import MAX_HAND_SIZE, _end_turn
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, Side
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import fate_card, register


def _game() -> GameState:
    """A game whose table carries the Favor proxy template, as a dealt one does."""
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=0)
    game.table.creatable_tokens[IMPERIAL_FAVOR_ID] = FatePrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    return game


def _hand(game: GameState, seat: PlayerId):
    return game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards


def _proxies(game: GameState) -> list[str]:
    return [
        card_id
        for card_id, card in game.table.cards_by_id.items()
        if card.printed_id == IMPERIAL_FAVOR_ID
    ]


def test_taking_the_favor_puts_its_proxy_in_the_holders_hand():
    game = _game()

    TakeFavor(PlayerId.P1).perform(game)

    assert [card.printed_id for card in _hand(game, PlayerId.P1)] == [IMPERIAL_FAVOR_ID]


def test_the_proxy_follows_the_favor_to_its_new_holder():
    """One player controls the Favor at a time, so one proxy exists and it sits with whoever holds
    it (Twenty Festivals CR, The Imperial Favor)."""
    game = _game()
    TakeFavor(PlayerId.P1).perform(game)

    TakeFavor(PlayerId.P2).perform(game)

    assert len(_proxies(game)) == 1
    assert _hand(game, PlayerId.P1) == []
    assert [card.printed_id for card in _hand(game, PlayerId.P2)] == [IMPERIAL_FAVOR_ID]


def test_discarding_the_favor_leaves_no_proxy_anywhere():
    game = _game()
    TakeFavor(PlayerId.P1).perform(game)

    DiscardFavor(PlayerId.P1).perform(game)

    assert _proxies(game) == []


def test_the_opponent_can_identify_the_favor_among_backs():
    """A hand is private to its owner, so the Favor being public is what ``shown`` buys."""
    game = _game()
    hand = ZoneKey(PlayerId.P1, ZoneRole.HAND)
    game.table.zones[hand].add(register(game.table, fate_card("secret", PlayerId.P1)))
    TakeFavor(PlayerId.P1).perform(game)

    seen = redact(game.table, PlayerId.P2).zones[hand].cards

    named = [card.name for card in seen if not isinstance(card, HiddenCard)]
    assert named == ["The Imperial Favor"]
    assert sum(isinstance(card, HiddenCard) for card in seen) == 1


def _fill_hand(game: GameState, count: int) -> None:
    hand = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for index in range(count):
        hand.add(register(game.table, fate_card(f"card{index}", PlayerId.P1)))


def test_a_full_hand_plus_the_favor_discards_nothing():
    """The proxy is outside the limit rather than merely tolerated by it: a holder at the limit ends
    its turn without being asked to discard, exactly as a non-holder would."""
    game = _game()
    _fill_hand(game, MAX_HAND_SIZE)  # exactly at the limit, before the Favor arrives
    TakeFavor(PlayerId.P1).perform(game)

    _end_turn(game)

    assert not isinstance(game.pending, DiscardToHandSize), "counting the proxy would ask for one"


def test_the_favor_is_never_offered_as_a_discard_to_hand_size():
    """It is not a card, so it cannot be the thing discarded to get back under the limit."""
    game = _game()
    _fill_hand(game, MAX_HAND_SIZE + 1)
    TakeFavor(PlayerId.P1).perform(game)

    _end_turn(game)

    assert isinstance(game.pending, DiscardToHandSize)
    proxy = _proxies(game)[0]
    assert proxy not in game.pending.candidates
    # One real card over the limit. Counting the proxy would make it two.
    assert game.pending.count == 1


def test_the_favor_holder_is_authoritative_over_the_proxy_card():
    """Delete the card and the seat still holds the Favor.

    The Favor is not a card, though it may be represented by one, and its abilities sit on the player
    rather than on it (Twenty Festivals CR, The Imperial Favor). ``favor_holder`` is the truth and the
    proxy renders it, so tampering with the card cannot make the two disagree.
    """
    game = _game()
    TakeFavor(PlayerId.P1).perform(game)
    proxy = game.table.cards_by_id[_proxies(game)[0]]

    ops.remove_card(game.table, proxy)

    assert game.favor_holder is PlayerId.P1


def test_a_proxy_nobody_should_hold_does_not_confer_the_favor():
    """The other direction: a card sitting in a hand is not what makes a seat the holder."""
    game = _game()
    printed = game.table.creatable_tokens[IMPERIAL_FAVOR_ID]
    ops.spawn_token(
        game.table,
        game.mint_token_id(),
        printed,
        PlayerId.P2,
        dest=ZoneKey(PlayerId.P2, ZoneRole.HAND),
    )

    assert game.favor_holder is None
