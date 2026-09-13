from yasuki_core.engine.registrar import FlagRegistry
from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.units.membership import attached_to, attachments_of
from yasuki_core.engine.rules.effects import (
    Ask,
    Bow,
    Effect,
    Unpayable,
)
from yasuki_core.engine.rules.state import GameState, claim_once_per_turn, used_this_turn
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.game_pieces.cards import L5RCard


# A cost is the effects paid to activate an ability, applied before the ability's own effects. Bow /
# destroy / spend-a-token are all just effects targeting a card, so costs and effects share one
# vocabulary: there is no separate cost taxonomy. What a card calls a cost is one here only when it
# must be paid before resolution; anything the card's own text sequences is an effect. A cost takes
# the board as well as the source because it may be paid by a card the source did not choose: an
# attachment's cost is usually paid by the Personality it hangs on, which only the graph can name.
# A builder lives here only when more than one card uses it; a cost one card charges lives with that
# card as ``_<card id>_cost``, beside its targets and effects.
Cost = Callable[[GameState, L5RCard], list[Effect]]


def no_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """An ability that costs nothing to announce."""
    return []


# Attachments offering the Personality they are on a once-per-turn waiver of the cost of bowing to
# pay for one of his own abilities, keyed on the attachment's printed id.
BOW_WAIVERS = FlagRegistry("bow waivers", "already waives a bow cost")
register_bow_waiver = BOW_WAIVERS.make_register()
WAIVER_TAG = "register_bow_waiver"


def _waiver_on(game: GameState, card: L5RCard) -> L5RCard | None:
    """An attachment on ``card`` whose bow waiver is still unspent this turn, or None for none."""
    for attached in attachments_of(game, card):
        if attached.printed_id in BOW_WAIVERS and not used_this_turn(game, attached, WAIVER_TAG):
            return attached
    return None


def bow_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow ``source`` to pay for its own ability, offering any waiver it carries first.

    The waiver is only worth asking about while ``source`` still stands: what it buys is a
    Personality who has not bowed, and one already bowed cannot pay a bow cost at all (CR, Costs).
    """
    waiver = _waiver_on(game, source)
    if waiver is None or source.bowed:
        return [Bow(source.id)]
    return [
        Ask(
            source.owner,
            f"Ignore the cost of bowing {source.name}?",
            WAIVER_TAG,
            subjects=(waiver.id,),
            source_id=source.id,
        )
    ]


@choice_resolver(WAIVER_TAG)
def _resolve_bow_waiver(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Taking the waiver spends it and nothing bows. Declining pays the cost as printed."""
    if not chosen:
        return [Bow(source_id)]
    claim_once_per_turn(game, game.table.cards_by_id[chosen[0]], WAIVER_TAG)
    return []


def bow_parent_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow the Personality ``source`` is attached to. Unpayable while it is attached to none."""
    parent = attached_to(game, source)
    if parent is None:
        return [Unpayable(f"{source.id} is attached to no Personality")]
    return [Bow(parent.id)]


def can_pay(game: GameState, card: L5RCard, cost: Cost) -> bool:
    """Whether ``card`` can pay ``cost``: every effect it spends is payable against the current
    state. Each effect owns its own precondition, so a new cost effect needs no change here.

    Judged whole rather than effect by effect, because a cost's parts compete for the same cards:
    one that bows a Gold producer leaves it unable to bow again to pay the cost's own Gold half.
    """
    effects = cost(game, card)
    bowed = frozenset(effect.card_id for effect in effects if isinstance(effect, Bow))
    return all(effect.is_payable(game, bowed_by_cost=bowed) for effect in effects)
