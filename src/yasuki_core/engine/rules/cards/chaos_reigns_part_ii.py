from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.keyword_grants import keyword_grant
from yasuki_core.engine.rules.board.seats import seat_controls_printed
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import (
    granted_ability,
    register_ability,
    register_cannot_attack,
)
from yasuki_core.engine.rules.board.queries import (
    attack_targets,
    opposed_units_in_battle,
    opposing_units_in_battle,
    owned_holdings,
    personalities_in_play,
)
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Choose,
    CreateToken,
    DrawCard,
    Effect,
    GrantAbility,
    GrantModifier,
    MoveToDeck,
    RangedAttack,
    ShuffleDeck,
)
from yasuki_core.engine.rules.rulebook.equip import creation_targets
from yasuki_core.engine.rules.vocabulary.game_events import (
    Assigned,
    CounterGained,
    EnteredPlay,
    TurnStarted,
)
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.state import claim_once_per_turn
from yasuki_core.engine.rules.triggers import (
    TriggerContext,
    at_cap,
    choice_resolver,
    on,
)
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.prints import AttachmentPrint, HoldingPrint


# --- Daidoji Kaede ---

KAEDE_ASSIGNED_FORCE = 1
KAEDE_RANGED = 3

register_cannot_attack("daidoji_kaede")


@on(Assigned, "daidoji_kaede")
def _daidoji_kaede_assigned(ctx: TriggerContext) -> list[Effect]:
    """After Kaede assigns to a battlefield, give her +1F. Only ever as a defender, since she cannot
    attack."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [
        GrantModifier(
            ctx.card.id, ctx.card.id, Stat.FORCE, KAEDE_ASSIGNED_FORCE, Duration.UNTIL_END_OF_TURN
        )
    ]


def _daidoji_kaede_opposition_targets(game: GameState, source: L5RCard) -> list[str]:
    """Enemy Personalities, the only ones that can come to oppose Kaede (CR, Opposed)."""
    return [card.id for card in personalities_in_play(game) if card.owner is not source.owner]


def _daidoji_kaede_opposition_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [GrantAbility(source.id, source.id, (target.id,), Duration.UNTIL_END_OF_TURN)]


register_ability(
    "daidoji_kaede",
    Ability(
        timings=(ActionTiming.OPEN,),
        key="opposition",
        cost=no_cost,
        targets=_daidoji_kaede_opposition_targets,
        targeting_message="a Personality",
        effects=_daidoji_kaede_opposition_effects,
    ),
)


@granted_ability("daidoji_kaede")
def _daidoji_kaede_granted_ability(context: tuple[str, ...]) -> Ability:
    """The "Battle: Ranged 3" her Open gives her, usable while the Personality it named opposes
    her at the battle being fought."""
    opposing_id = context[0]

    def targets(game: GameState, source: L5RCard) -> list[str]:
        opposed = source.id in opposed_units_in_battle(game, source.owner)
        opposes = opposing_id in opposing_units_in_battle(game, source.owner)
        return attack_targets(game, source) if opposed and opposes else []

    def effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
        return [RangedAttack(KAEDE_RANGED, target.id, source.owner)]

    return Ability(
        timings=(ActionTiming.BATTLE,),
        key="ranged",
        label=f"Battle: Ranged {KAEDE_RANGED} Attack",
        cost=no_cost,
        targets=targets,
        effects=effects,
    )


# --- Fortified Farmlands ---


@keyword_grant("fortified_farmlands")
def _fortified_farmlands_keywords(
    card: L5RCard, game: GameState, seat: PlayerId
) -> tuple[str, ...]:
    """Grant Renew while its controller has another Farm Holding in play.

    Read whenever the keyword is asked for, so it comes and goes with the other Farm rather than
    being granted once. The card's Response half is not modeled: no Action Round opens a Response
    step for it to be taken in.
    """
    return ("Renew",) if seat_controls_printed(game, seat, "Farm", other_than=card) else ()


# --- Millet Farm ---


def _millet_farm_targets(game: GameState, card: L5RCard) -> list[str]:
    return [farm.id for farm in owned_holdings(game, card.owner, keywords.FARM)]


def _millet_farm_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(source.id, target.id, Stat.GOLD_PRODUCTION, 2, Duration.UNTIL_END_OF_TURN)
    ]


register_ability(
    "millet_farm",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_millet_farm_targets,
        targeting_message="your Farm",
        effects=_millet_farm_effects,
    ),
)


# --- Rice Farm ---


@on(TurnStarted, "rice_farm")
def _rice_farm_turn_started(ctx: TriggerContext) -> list[Effect]:
    """After your turn begins, give this Holding a +1GP Wealth token (max four)."""
    if ctx.card.owner is not ctx.event.seat or at_cap(ctx.card, WEALTH, 4):
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


# --- Shosuro Aoki / Yoritomo Kayoko (Experienced) ---


@on(CounterGained, "shosuro_aoki_yoritomo_kayoko_experienced")
def _shosuro_aoki_yoritomo_kayoko_experienced_counter_gained(ctx: TriggerContext) -> list[Effect]:
    """After your Holding gains any Wealth tokens, once per turn, draw a card."""
    if ctx.event.counter is not WEALTH:
        return []
    gainer = ctx.game.table.cards_by_id[ctx.event.card_id]
    if not isinstance(gainer.printed, HoldingPrint) or gainer.owner is not ctx.card.owner:
        return []
    if not claim_once_per_turn(ctx.game, ctx.card, "aoki_draw"):
        return []
    return [DrawCard(ctx.card.owner)]


# --- Tarkasha ---


NAGA_FOLLOWER = "naga"


def _tarkasha_fallen_naga_followers(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The Naga Followers in ``seat``'s Fate discard, which is the only pile a Follower reaches."""
    return tuple(
        card.id
        for card in game.table.zones[ZoneKey(seat, ZoneRole.FATE_DISCARD)].cards
        if isinstance(card.printed, AttachmentPrint)
        and card.printed.attachment_type is AttachmentType.FOLLOWER
        and keywords.NAGA in card.keywords
    )


@choice_resolver("tarkasha", prompt="Reshuffle a Naga Follower into your Fate deck")
def _resolve_tarkasha(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    deck = DeckKey(seat, Side.FATE)
    return [MoveToDeck(chosen[0], deck, from_top=0), ShuffleDeck(deck)]


def _tarkasha_targets(game: GameState, source: L5RCard) -> list[str]:
    naga = game.table.creatable_tokens[NAGA_FOLLOWER]
    commanders = creation_targets(game, source.owner, naga, keyword=keywords.COMMANDER)
    return [commander.id for commander in commanders]


def _tarkasha_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Reshuffle one of the fallen, then raise a new one onto the Commander.

    The reshuffle is written into the card's text rather than printed in its cost block, so it is an
    effect and not a cost (CR, Action Sequence: only the bowing and Gold icons are costs). With none
    to reshuffle the effects stop there and nothing is raised.
    """
    fallen = _tarkasha_fallen_naga_followers(game, source.owner)
    if not fallen:
        return []
    return [
        Choose(source.owner, fallen, 1, 1, "tarkasha", source.id),
        CreateToken(NAGA_FOLLOWER, source.owner, source.id, attach_to=target.id),
    ]


register_ability(
    "tarkasha",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_tarkasha_targets,
        targeting_message="your Commander",
        effects=_tarkasha_effects,
    ),
)


# --- Tetsuo Hiyamako (Experienced) ---


HIYAMAKOS_CLAW = "weapon_item_claw_plus1f"
CLAW_COUNT = 2


@on(EnteredPlay, "tetsuo_hiyamako_experienced")
def _tetsuo_hiyamako_experienced_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After Hiyamako enters play, create two +1F Claws and attach them to her.

    Two Weapons on one Personality, where the rules allow one (CR, Weapon). Her text says so, and
    card text beats the rules (CR, Cardinal Rule 1), which is also why they are attached rather
    than Equipped. The Weapon limit belongs to Equip's legality, and nothing here is Equipping.
    """
    if ctx.event.card_id != ctx.card.id:
        return []
    return [
        CreateToken(HIYAMAKOS_CLAW, ctx.card.owner, ctx.card.id, attach_to=ctx.card.id)
        for _ in range(CLAW_COUNT)
    ]


# --- Wheat Farm ---


@on(EnteredPlay, "wheat_farm")
def _wheat_farm_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, let its controller give zero to two other Farms they
    control a +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    others = tuple(
        card.id
        for card in owned_holdings(ctx.game, ctx.card.owner, keywords.FARM)
        if card is not ctx.card
    )
    if not others:
        return []
    return [Choose(ctx.card.owner, others, 0, min(2, len(others)), "wheat_farm", ctx.card.id)]


@choice_resolver("wheat_farm", prompt="Give a Wealth token to other Farms you control")
def _resolve_wheat_farm(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [AdjustCounter(card_id, WEALTH, 1) for card_id in chosen]
