from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    InvestAbility,
    invest_amounts,
    bow_cost,
    no_cost,
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
    action_did,
    choice_resolver,
    on,
    sincerity_seed_targets,
)
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import SINCERITY


# --- Kitsu Hayako ---

LION_ANCESTOR = "lion_ancestor"
ONE_ANCESTOR = 2
TWO_ANCESTORS = 6


def _kitsu_hayako_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """One 2F/2C/3PH Lion Ancestor for the lower of his two prices, and a second for the higher.

    Which price was paid, not how much: a discount moves both prices down together, so the second
    Ancestor goes with whichever price is higher at the time.

    Both come from the one proxy: each creation mints its own card, so the pair are two Ancestors
    rather than one counted twice.
    """
    ancestors = 2 if amount == max(invest_amounts(game, source)) else 1
    return [CreateToken(LION_ANCESTOR, source.owner, source.id) for _ in range(ancestors)]


register_invest(
    "kitsu_hayako",
    InvestAbility(amounts=(ONE_ANCESTOR, TWO_ANCESTORS), effect=_kitsu_hayako_invest),
)


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


def _training_court_targets(game: GameState, source: L5RCard) -> list[str]:
    """The controller's token-less Sincerity cards still in a Province, once the action just
    resolved was the one that Recruited this Holding."""
    if not any(event.card_id == source.id for event in action_did(game, EnteredPlay)):
        return []
    return sincerity_seed_targets(game, source.owner)


def _training_court_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [AdjustCounter(target.id, SINCERITY, 1)]


register_ability(
    "training_court",
    Ability(
        # Tireless, so it asks nothing of the Holding it is on: a Response costs no bow, and this
        # one is taken in the Step that follows the Recruit which brought the Holding into play.
        timings=(ActionTiming.RESPONSE,),
        label="Response: seed a Sincerity token onto one of your Sincerity cards",
        cost=no_cost,
        targets=_training_court_targets,
        effects=_training_court_effects,
        tireless=True,
    ),
)

register_invest("training_court", InvestAbility(amounts=(1,), effect=one_wealth))


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
        timings=(ActionTiming.OPEN,),
        label="Open: Bow to Equip a 1F Cavalry Follower to your Samurai",
        cost=bow_cost,
        targets=_utaku_gorou_stablemaster_targets,
        effects=_utaku_gorou_stablemaster_effects,
    ),
)
