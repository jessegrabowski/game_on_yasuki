from collections.abc import Iterable

from yasuki_core.engine.redaction import HiddenCard
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.table import ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import HoldingPrint


def in_play(view: GameView) -> Iterable[L5RCard]:
    """The viewer's own cards on the battlefield that it can identify."""
    return (
        entry.card
        for entry in view.table.battlefield
        if not isinstance(entry.card, HiddenCard) and entry.card.owner is view.viewer
    )


def identifiable(view: GameView) -> dict[str, L5RCard]:
    """Every card the viewer can name, by id: its own board and its own readable Province cards,
    which between them cover what an ability offers as a target."""
    cards: dict[str, L5RCard] = {card.id: card for card in in_play(view)}
    cards.update(readable_province_cards(view))
    return cards


def spendable(view: GameView) -> int:
    """The Gold the viewer could raise right now by bowing what is straight, plus its pool.

    Smaller than what :func:`~yasuki_core.engine.rules.gold.producers.reachable_gold` counts: this
    excludes Gold a producer would only grant at a price it sets. A policy cannot ask
    :func:`~yasuki_core.engine.rules.gold.self_grants.maximum_gold_production` either, since it
    holds a redacted :class:`~.GameView` and not the live game.
    """
    return view.gold[view.viewer] + sum(
        production(view, card) for card in in_play(view) if not card.bowed
    )


def newly_affordable(view: GameView, before: int, after: int, exclude: str | None = None) -> bool:
    """Whether any face-up Province card costs more than ``before`` and no more than ``after``,
    the test of whether extra Gold buys anything rather than merely existing.

    Pass ``exclude`` when the Gold in question comes from recruiting one of those cards, so the card
    being bought is not also counted as what the purchase pays for.
    """
    if after <= before:
        return False
    return any(
        card.face_up and card.id != exclude and before < view.stat(card, Stat.GOLD_COST) <= after
        for card in readable_province_cards(view).values()
    )


def rank(view: GameView, card: L5RCard) -> tuple[int, int, str]:
    """How a province card sorts for purchase, lowest first.

    Gold Production leads and Gold Cost breaks the tie, both negated so the larger wins. The card id
    settles anything still level, so the choice does not follow zone order. Both stats are read
    through the view, so a modified card ranks on its current value.
    """
    produced = production(view, card)
    return -produced, -view.stat(card, Stat.GOLD_COST), card.id


def readable_province_cards(view: GameView) -> dict[str, L5RCard]:
    """The viewer's province cards it can identify, by id: what a Recruit's ``card_id`` refers
    to.

    Built by scanning rather than looked up, since a redacted view carries no id index. A card the
    viewer cannot identify (a province refilled face-down, until something reveals it) is skipped
    rather than ranked, since no Recruit can name it.
    """
    return {
        card.id: card
        for key, zone in view.table.zones.items()
        if key.owner is view.viewer and key.role is ZoneRole.PROVINCE
        for card in zone.cards
        if not isinstance(card, HiddenCard)
    }


def best_production(view: GameView, cards: Iterable[L5RCard]) -> int:
    """The largest Gold Production among ``cards``, or 0 when none of them produces."""
    return max((production(view, card) for card in cards), default=0)


def production(view: GameView, card: L5RCard) -> int:
    """What ``card`` produces right now, or 0 for a card that is not a Holding at all."""
    if not isinstance(card.printed, HoldingPrint):
        return 0
    return view.stat(card, Stat.GOLD_PRODUCTION)
