from yasuki_core.engine.registrar import HandlerRegistry
from collections.abc import Callable, Iterator
from functools import cache

from yasuki_core.engine.players import PlayerId
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


# A keyword handler names the keywords a card carries beyond the printed ones, from the card and
# its controller's and opponents' views. The "this card has X" clauses are gated on a readable
# condition.
KeywordHandler = Callable[[L5RCard, GameState, PlayerId], tuple[str, ...]]
KEYWORD_GRANTS: HandlerRegistry[KeywordHandler] = HandlerRegistry(
    "keyword grants", "already has a keyword grant"
)
keyword_grant = KEYWORD_GRANTS.make_decorator()


@cache
def _inherited_keywords(text: str) -> frozenset[str]:
    return frozenset(ability_keywords(text))


def effective_keywords(game: GameState, card: L5RCard) -> frozenset[str]:
    """``card``'s printed keywords, plus those printed on its abilities, plus any its own ability
    grants under current conditions, plus any another card's ongoing effect has given it.

    An ability's keywords are the card's too (CR, Keyword Inheritance): a Strategy printing "Terrain
    Battle:" is a Terrain.
    """
    carried = (
        frozenset(card.keywords)
        .union(_inherited_keywords(card.text))
        .union(granted_keywords(game, card))
    )
    handler = KEYWORD_GRANTS.get(card.printed_id)
    if handler is None:
        return carried
    granted = handler(card, game, card.owner)
    return carried.union(granted)
