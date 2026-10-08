from yasuki_core.engine.registrar import HandlerRegistry
from collections.abc import Callable, Iterator
from functools import cache
from itertools import chain

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

# The other half: the keywords a card's text takes away, "This Weapon is One-Handed while attached to
# a Berserker" or "this Personality loses Samurai and cannot gain it". Read the way grants are, and
# applied after them, so a keyword a card loses stays lost whatever grants it.
KEYWORD_LOSSES: HandlerRegistry[KeywordHandler] = HandlerRegistry(
    "keyword losses", "already has a keyword loss"
)
keyword_loss = KEYWORD_LOSSES.make_decorator()


@cache
def _inherited_keywords(text: str) -> frozenset[str]:
    return frozenset(ability_keywords(text))


def effective_keywords(game: GameState, card: L5RCard) -> frozenset[str]:
    """``card``'s printed keywords, plus those printed on its abilities, plus any its own text
    grants it under current conditions, plus any another card's text or ongoing effect gives it,
    less any a card's text takes away.

    An ability's keywords are the card's too (CR, Keyword Inheritance): a Strategy printing "Terrain
    Battle:" is a Terrain. A card's own text is read wherever the card is, and another card's only
    while that card is in play.
    """
    gained: set[str] = set()
    lost: set[str] = set()
    others = (holder for holder in game.table.battlefield.cards if holder is not card)
    holders = chain((card,), others)
    for holder in holders:
        grant = KEYWORD_GRANTS.get(holder.printed_id)
        if grant is not None:
            gained.update(grant(game, holder, card))
        loss = KEYWORD_LOSSES.get(holder.printed_id)
        if loss is not None:
            lost.update(loss(game, holder, card))
    carried = (
        frozenset(card.keywords)
        .union(_inherited_keywords(card.text))
        .union(granted_keywords(game, card))
        .union(gained)
    )
    return carried - lost
