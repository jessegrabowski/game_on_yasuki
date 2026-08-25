from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.economy import PlayerState, effective_keywords, keyword_grant
from yasuki_core.engine.rules.abilities import (
    Ability,
    bow_cost,
    no_cost,
    owned_holdings,
    register_ability,
)
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Choose,
    CreateToken,
    DrawCard,
    Effect,
    GrantModifier,
    MoveToDeck,
    ShuffleDeck,
)
from yasuki_core.engine.rules.equip import creation_targets
from yasuki_core.engine.rules.events import CounterGained, EnteredPlay, TurnStarted
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.state import once_per_turn
from yasuki_core.engine.rules.triggers import (
    TriggerContext,
    at_cap,
    choice_resolver,
    on,
)
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.prints import AttachmentPrint, HoldingPrint


# --- Fortified Farmlands ---


@keyword_grant("fortified_farmlands")
def _fortified_farmlands_keywords(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]
) -> tuple[str, ...]:
    """Grant Renew while its controller has another Farm Holding in play.

    Read whenever the keyword is asked for, so it comes and goes with the other Farm rather than
    being granted once. The card's Response half is not modeled: no Action Round opens a Response
    step for it to be taken in.
    """
    return ("Renew",) if me.controls("Farm", other_than=card) else ()


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
        timing=ActionTiming.OPEN,
        label="Bow: give a Farm +2 Gold Production",
        cost=bow_cost,
        targets=_millet_farm_targets,
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
    if not once_per_turn(ctx.game, ctx.card, "aoki_draw"):
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
        timing=ActionTiming.OPEN,
        label="Open: Reshuffle a fallen Naga to Equip a 1F Naga Follower to your Commander",
        cost=no_cost,
        targets=_tarkasha_targets,
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
    card text beats the rules (CR, Cardinal Rule 1) — which is also why they are attached rather
    than Equipped: the Weapon limit belongs to Equip's legality, and nothing here is Equipping.
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
    """After this Holding enters play, let its controller give zero to two other Farms they control a
    +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    others = tuple(
        card.id
        for card in ctx.game.table.battlefield.cards
        if card.owner is ctx.card.owner
        and card is not ctx.card
        and isinstance(card.printed, HoldingPrint)
        and keywords.FARM in effective_keywords(ctx.game, card)
    )
    if not others:
        return []
    return [Choose(ctx.card.owner, others, 0, min(2, len(others)), "wheat_farm", ctx.card.id)]


@choice_resolver("wheat_farm", prompt="Give a Wealth token to other Farms you control")
def _resolve_wheat_farm(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [AdjustCounter(card_id, WEALTH, 1) for card_id in chosen]
