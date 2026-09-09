from yasuki_core.engine import ops
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, RULEBOOK_PROXY_IDS


def sync_proxy(game: GameState) -> None:
    """Make the Imperial Favor's proxy card match ``favor_holder``.

    The card is a rendering of the state, never the other way round: the Favor is not a card, though
    it may be represented by one, and its abilities sit on the player rather than on it (Twenty
    Festivals CR, The Imperial Favor). So this is the only place the proxy is created or destroyed,
    and nothing else under ``rules/`` reads it to answer a question about who holds the Favor.

    Face up, because a held Favor is public: ``shown`` lets the opponent identify it where it sits,
    which a hand card is otherwise not.
    """
    _clear_proxy(game)
    if game.favor_holder is None:
        return
    printed = game.table.creatable_tokens.get(IMPERIAL_FAVOR_ID)
    if printed is None:
        return
    card = ops.spawn_token(
        game.table,
        game.mint_token_id(),
        printed,
        game.favor_holder,
        dest=ZoneKey(game.favor_holder, ZoneRole.HAND),
    )
    if card is not None:
        card.show()


def _clear_proxy(game: GameState) -> None:
    """Take every Favor proxy off the table, wherever one sits."""
    held = [
        card for card in game.table.cards_by_id.values() if card.printed_id == IMPERIAL_FAVOR_ID
    ]
    for card in held:
        ops.remove_card(game.table, card)


def is_rulebook_proxy(card: L5RCard) -> bool:
    """Whether ``card`` is a rulebook proxy rather than a card a player drew.

    Counting one toward a limit on cards would be counting something that is not a card, so the
    maximum hand size skips them.
    """
    return card.printed_id in RULEBOOK_PROXY_IDS
