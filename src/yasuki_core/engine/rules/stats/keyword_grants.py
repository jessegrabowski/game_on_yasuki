from yasuki_core.engine.rules.registrar import HandlerRegistry
from collections.abc import Callable, Iterator

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import KeywordGrant
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


def granted_keywords(game: GameState, card: L5RCard) -> Iterator[str]:
    """Every keyword another card's recorded grant gives ``card`` right now."""
    for grant in game.ongoing:
        if isinstance(grant, KeywordGrant) and grant.target_id == card.id:
            if grant_applies(game, grant):
                yield grant.keyword


# A keyword handler names the keywords a card carries beyond the printed ones, from the card and its
# controller's and opponents' views — the "this card has X" clauses gated on a readable condition.
KeywordHandler = Callable[[L5RCard, GameState, PlayerId], tuple[str, ...]]
KEYWORD_GRANTS: HandlerRegistry[KeywordHandler] = HandlerRegistry(
    "keyword grants", "already has a keyword grant"
)
keyword_grant = KEYWORD_GRANTS.make_decorator()


def effective_keywords(game: GameState, card: L5RCard) -> frozenset[str]:
    """``card``'s printed keywords, plus any its own ability grants under current conditions, plus
    any another card's ongoing effect has given it."""
    carried = frozenset(card.keywords).union(granted_keywords(game, card))
    handler = KEYWORD_GRANTS.get(card.printed_id)
    if handler is None:
        return carried
    granted = handler(card, game, card.owner)
    return carried.union(granted)
