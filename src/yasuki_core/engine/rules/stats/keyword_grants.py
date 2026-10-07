from yasuki_core.engine.registrar import HandlerRegistry
from collections.abc import Callable, Iterator
from functools import cache

from yasuki_core.engine.rules.vocabulary.modifiers import KeywordGrant
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.text_split import ability_keywords


def granted_keywords(game: GameState, card: L5RCard) -> Iterator[str]:
    """Every keyword another card's recorded grant gives ``card`` right now."""
    for grant in game.ongoing:
        if isinstance(grant, KeywordGrant) and grant.target_id == card.id:
            if grant_applies(game, grant):
                yield grant.keyword


# What a card gives a card for its keywords by its own text, read on every keyword read. The handler
# decides whom it reaches: itself ("Renew while it holds any Sincerity token"), wherever it is, or,
# while it is in play, any card the text names ("Your Personalities have Siege while opposed"). Keyed
# by printed id like the other per-card registries, and shaped as ``@stat_grant`` is.
KeywordHandler = Callable[[GameState, L5RCard, L5RCard], tuple[str, ...]]
KEYWORD_GRANTS: HandlerRegistry[KeywordHandler] = HandlerRegistry(
    "keyword grants", "already has a keyword grant"
)
keyword_grant = KEYWORD_GRANTS.make_decorator()


@cache
def _inherited_keywords(text: str) -> frozenset[str]:
    return frozenset(ability_keywords(text))


def effective_keywords(game: GameState, card: L5RCard) -> frozenset[str]:
    """``card``'s printed keywords, plus those printed on its abilities, plus any its own text
    grants it under current conditions, plus any another card's text or ongoing effect gives it.

    An ability's keywords are the card's too (CR, Keyword Inheritance): a Strategy printing "Terrain
    Battle:" is a Terrain. A card's own grant is read wherever the card is, and another card's only
    while that card is in play.
    """
    carried = (
        frozenset(card.keywords)
        .union(_inherited_keywords(card.text))
        .union(granted_keywords(game, card))
    )
    own = KEYWORD_GRANTS.get(card.printed_id)
    if own is not None:
        carried = carried.union(own(game, card, card))
    for granting in game.table.battlefield.cards:
        if granting is card:
            continue
        handler = KEYWORD_GRANTS.get(granting.printed_id)
        if handler is not None:
            carried = carried.union(handler(game, granting, card))
    return carried
