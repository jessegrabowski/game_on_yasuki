from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    InvestAbility,
    bow_cost,
    one_wealth,
    register_ability,
    register_invest,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import AdjustCounter, Banish, Choose, CreateToken, Effect
from yasuki_core.engine.rules.equip import creation_targets
from yasuki_core.engine.rules.events import CardDiscarded, EnteredPlay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import (
    TriggerContext,
    choice_resolver,
    on,
    sincerity_seed_targets,
)
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import SINCERITY


# --- Spearmen of the Akasha ---

NAGA_FOLLOWER = "naga"


@on(CardDiscarded, "spearmen_of_the_akasha")
def _spearmen_of_the_akasha_card_discarded(ctx: TriggerContext) -> list[Effect]:
    """After the Spearmen reach the discard from hand or deck, offer to banish them for a 1F Naga
    Follower on one of the seat's Naga Personalities.

    Nothing is offered with nobody to carry it. The Follower is the whole of what banishing buys, so
    a board with no Naga Personality leaves the card nothing it could do.
    """
    if ctx.event.card_id != ctx.card.id or not ctx.event.from_hand_or_deck:
        return []
    seat = ctx.card.owner
    naga = ctx.game.table.creatable_tokens[NAGA_FOLLOWER]
    bearers = tuple(
        bearer.id for bearer in creation_targets(ctx.game, seat, naga, keyword=keywords.NAGA)
    )
    if not bearers:
        return []
    return [Choose(seat, bearers, 0, 1, "spearmen_of_the_akasha", ctx.card.id)]


@choice_resolver("spearmen_of_the_akasha", prompt="Banish the Spearmen to Equip a Naga Follower")
def _resolve_spearmen_of_the_akasha(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Banishing is what buys the Follower, so declining leaves the Spearmen lying in the discard."""
    if not chosen:
        return []
    return [Banish(source_id), CreateToken(NAGA_FOLLOWER, seat, source_id, attach_to=chosen[0])]


# --- Training Court ---


@on(EnteredPlay, "training_court")
def _training_court_entered_play(ctx: TriggerContext) -> list[Effect]:
    """Political Tireless Response: after Training Court enters play, seed a Sincerity token onto one
    of its controller's token-less Sincerity cards still in a Province."""
    if ctx.event.card_id != ctx.card.id:
        return []
    targets = tuple(sincerity_seed_targets(ctx.game, ctx.card.owner))
    if not targets:
        return []
    return [Choose(ctx.card.owner, targets, 1, 1, "sincerity_seed", ctx.card.id)]


@choice_resolver("sincerity_seed", prompt="Seed a Sincerity token onto one of your Sincerity cards")
def _resolve_sincerity_seed(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [AdjustCounter(card_id, SINCERITY, 1) for card_id in chosen]


register_invest("training_court", InvestAbility(minimum=1, maximum=1, effect=one_wealth))


# --- Utaku Gorou, Stablemaster ---

CAVALRY_FOLLOWER = "cavalry"


def _utaku_gorou_stablemaster_targets(game: GameState, source: L5RCard) -> list[str]:
    cavalry = game.table.creatable_tokens[CAVALRY_FOLLOWER]
    riders = creation_targets(game, source.owner, cavalry, keyword=keywords.SAMURAI)
    return [rider.id for rider in riders]


def _utaku_gorou_stablemaster_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [CreateToken(CAVALRY_FOLLOWER, source.owner, source.id, attach_to=target.id)]


register_ability(
    "utaku_gorou_stablemaster",
    Ability(
        timing=ActionTiming.OPEN,
        label="Open: Bow to Equip a 1F Cavalry Follower to your Samurai",
        cost=bow_cost,
        targets=_utaku_gorou_stablemaster_targets,
        effects=_utaku_gorou_stablemaster_effects,
    ),
)
