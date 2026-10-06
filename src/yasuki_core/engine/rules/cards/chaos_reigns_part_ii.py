from yasuki_core.engine.players import PlayerId, Trait
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords, keyword_grant
from yasuki_core.engine.rules.board.seats import opposing_seats, seat_controls_printed
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.idioms import (
    YuWidening,
    register_granted_yu,
    register_terrain,
    register_yu,
    register_yu_widening,
)
from yasuki_core.engine.rules.abilities.model import (
    Ability,
    CardLocation,
    InvestAbility,
    TargetGroup,
)
from yasuki_core.engine.rules.abilities.registry import (
    granted_ability,
    register_ability,
    register_cannot_attack,
    register_invest,
)
from yasuki_core.engine.rules.board.queries import (
    in_army_with,
    army_at,
    owned_carrying,
    ATTACK_TARGET,
    attack_targets,
    has_keyword,
    opposed_units_in_battle,
    opposing_units_in_battle,
    owned_holdings,
    owned_personalities,
    personalities_in_play,
    rings_in_play,
    terrains_at,
    units_at,
)
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
    AskOption,
    Banish,
    Bow,
    Choose,
    CreateToken,
    Destroy,
    DrawCard,
    Fear,
    Effect,
    Evaluate,
    GainHonor,
    GrantAbility,
    GrantKeyword,
    GrantModifier,
    MeleeAttack,
    MoveToDeck,
    MoveToHand,
    RangedAttack,
    Show,
    ShuffleDeck,
    Simultaneously,
    SpendOncePerTurn,
    Straighten,
    TakeFavor,
    To,
)
from yasuki_core.engine.rules.board.counts_as import Asking
from yasuki_core.engine.rules.legality import location_permits
from yasuki_core.engine.rules.rulebook.equip import creation_targets, is_spell
from yasuki_core.engine.rules.units.composition import followers_of, is_follower
from yasuki_core.engine.rules.units.membership import attached_to, attachments_of
from yasuki_core.engine.rules.vocabulary.segments import Boundary
from yasuki_core.engine.rules.vocabulary.game_events import (
    Assigned,
    Bowed,
    CounterChanged,
    Destroyed,
    EnteredPlay,
    TurnBoundary,
)
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.state import used_this_turn
from yasuki_core.engine.rules.vocabulary.decisions import PickedTargets
from yasuki_core.engine.rules.triggers import (
    TriggerContext,
    action_did,
    at_cap,
    choice_resolver,
    given_by_effect,
    on,
)
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole, location_of
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.counters import PLUS_1F_PLUS_1C, WEALTH, counter_from_key
from yasuki_core.game_pieces.prints import (
    ActionPrint,
    AttachmentPrint,
    HoldingPrint,
    PersonalityPrint,
)


# --- Akodo Iori ---

IORI_INVEST = 1


def _akodo_iori_sought(game: GameState, card: L5RCard) -> bool:
    """A Bushido Virtue, or a Strategy carrying Tactical."""
    carried = effective_keywords(game, card)
    if keywords.BUSHIDO_VIRTUE in carried:
        return True
    return isinstance(card.printed, ActionPrint) and keywords.TACTICAL in carried


def _akodo_iori_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """Search the Fate deck, where every card the text may find is kept."""
    deck = game.table.decks[DeckKey(source.owner, Side.FATE)].cards
    pool = tuple(card.id for card in deck if _akodo_iori_sought(game, card))
    return [Choose(source.owner, pool, 1, 1, "akodo_iori_invest", source.id)] if pool else []


register_invest("akodo_iori", InvestAbility((IORI_INVEST,), _akodo_iori_invest))


@choice_resolver(
    "akodo_iori_invest", prompt="Akodo Iori's Invest: choose a Bushido Virtue or Tactical Strategy"
)
def _resolve_akodo_iori_invest(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Show(chosen[0]), MoveToHand(chosen[0], seat), ShuffleDeck(DeckKey(seat, Side.FATE))]


def _akodo_iori_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Permanently give your target Personality Tactician." Your Personalities at Iori's
    battlefield, Iori among them, since a targeted Yu reaches only that battlefield (ShE datasheet,
    The Yu Trait)."""
    battlefield = ctx.event.location.battlefield
    if battlefield is None:
        return []
    targets = tuple(card.id for card in units_at(ctx.game, battlefield, ctx.card.owner))
    return [Choose(ctx.card.owner, targets, 1, 1, "akodo_iori_yu", ctx.card.id)] if targets else []


register_yu("akodo_iori", _akodo_iori_yu)


@choice_resolver(
    "akodo_iori_yu", prompt="Akodo Iori's Yu: choose your Personality to give Tactician"
)
def _resolve_akodo_iori_yu(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [GrantKeyword(source_id, chosen[0], keywords.TACTICIAN, Duration.PERMANENT)]


# --- Burnt Offering ---

BURNT_OFFERING_BONUS = 2


def _burnt_offering_attachments(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The enemy attachments the action may target where they stand."""
    return tuple(
        card.id
        for card in game.table.battlefield.cards
        if card.owner is not seat
        and isinstance(card.printed, AttachmentPrint)
        and attached_to(game, card) is not None
        and location_permits(game, card)
    )


def _burnt_offering_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your unbowed Monks, once there is an enemy attachment to destroy."""
    if not _burnt_offering_attachments(game, source.owner):
        return []
    return [card.id for card in owned_carrying(game, source.owner, keywords.MONK) if not card.bowed]


def _burnt_offering_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """ "If you control a Ring, give them +2C" reads nothing the destruction changes, so it is
    settled here. The targeted Monk stands as the choice's source so the later steps can name
    him."""
    attachments = _burnt_offering_attachments(game, source.owner)
    chosen = Choose(source.owner, attachments, 1, 1, "burnt_offering", target.id)
    if not rings_in_play(game, source.owner, Asking.action(source)):
        return [chosen]
    chi = GrantModifier(
        source.id, target.id, Stat.CHI, BURNT_OFFERING_BONUS, Duration.UNTIL_END_OF_TURN
    )
    return [chi, chosen]


@choice_resolver("burnt_offering", prompt="Destroy a target enemy attachment")
def _resolve_burnt_offering(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Destroy the attachment, then read its Personality once the destruction has resolved."""
    destroyed = Destroy(chosen[0], seat)
    personality = attached_to(game, game.table.cards_by_id[chosen[0]])
    if personality is None:
        return [destroyed]
    after = Evaluate("burnt_offering_followers", source_id, seat, (personality.id,))
    return [destroyed, after]


@choice_resolver("burnt_offering_followers")
def _resolve_burnt_offering_followers(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """ "If its Personality now has no Followers, give your targeted Monk +2F." """
    personality = game.table.cards_by_id[chosen[0]]
    if followers_of(game, personality):
        return []
    return [
        GrantModifier(
            source_id, source_id, Stat.FORCE, BURNT_OFFERING_BONUS, Duration.UNTIL_END_OF_TURN
        )
    ]


register_ability(
    "burnt_offering",
    Ability(
        timings=(ActionTiming.BATTLE,),
        keywords=frozenset({keywords.KIHO}),
        cost=no_cost,
        targets=_burnt_offering_targets,
        targeting_message="your unbowed Monk",
        effects=_burnt_offering_effects,
        located_at=(CardLocation.HAND,),
    ),
)


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
def _daidoji_kaede_granted_ability(
    game: GameState, kaede: L5RCard, context: tuple[str, ...]
) -> Ability:
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


# --- Desperate Ground ---


def _desperate_ground_reaches(game: GameState, ground: L5RCard, card: L5RCard) -> bool:
    """Your Followers and Personalities at this battlefield."""
    personality = isinstance(card.printed, PersonalityPrint)
    return (personality or is_follower(card)) and in_army_with(game, ground, card)


def _desperate_ground_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Destroy a target enemy card without attachments." Enemy cards at the dying card's
    battlefield, since a targeted Yu reaches only that battlefield (ShE datasheet, The Yu Trait):
    the enemy's Personalities carrying nothing, every card attached to the enemy's units, and the
    enemy's Terrain."""
    battlefield = ctx.event.location.battlefield
    if battlefield is None:
        return []
    game, owner = ctx.game, ctx.card.owner
    enemies = [seat for seat in game.table.seats if seat is not owner]
    units = [unit for seat in enemies for unit in units_at(game, battlefield, seat)]
    attached = [card for unit in units for card in attachments_of(game, unit)]
    targets = (
        *(unit.id for unit in units if not attachments_of(game, unit)),
        *(card.id for card in attached),
        *(card.id for card in terrains_at(game, battlefield) if card.owner is not owner),
    )
    return [Choose(owner, targets, 1, 1, "desperate_ground", ctx.card.id)] if targets else []


register_granted_yu("desperate_ground", _desperate_ground_reaches, _desperate_ground_yu)


@choice_resolver(
    "desperate_ground", prompt="Desperate Ground's Yu: choose an enemy card without attachments"
)
def _resolve_desperate_ground(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Destroy(chosen[0], Trait(source_id))]


register_terrain("desperate_ground", ability_keywords=frozenset({keywords.TERRAIN}))


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


# --- Isawa Eijiri, Warmonger ---

EIJIRI_FORCE = 2


def _isawa_eijiri_warmonger_spell(game: GameState, eijiri: L5RCard, card: L5RCard) -> bool:
    """Whether ``card`` is one of Eijiri's Spells."""
    return is_spell(card) and attached_to(game, card) is eijiri


def _isawa_eijiri_warmonger_reaches(game: GameState, eijiri: L5RCard, card: L5RCard) -> bool:
    """Eijiri's :fire: Spells."""
    return _isawa_eijiri_warmonger_spell(game, eijiri, card) and has_keyword(
        game, card, keywords.FIRE
    )


def _isawa_eijiri_warmonger_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Give your :fire: Shugenja +2F and Conqueror." Every one in play, since the effect
    names no target."""
    game, source = ctx.game, ctx.card
    shugenja = (
        card
        for card in game.table.battlefield.cards
        if card.owner is source.owner
        and has_keyword(game, card, keywords.FIRE)
        and has_keyword(game, card, keywords.SHUGENJA)
    )
    return [
        effect
        for card in shugenja
        for effect in (
            GrantModifier(source.id, card.id, Stat.FORCE, EIJIRI_FORCE, Duration.UNTIL_END_OF_TURN),
            GrantKeyword(source.id, card.id, keywords.CONQUEROR, Duration.UNTIL_END_OF_TURN),
        )
    ]


register_granted_yu(
    "isawa_eijiri_warmonger", _isawa_eijiri_warmonger_reaches, _isawa_eijiri_warmonger_yu
)
register_yu_widening(
    "isawa_eijiri_warmonger",
    YuWidening(covers=_isawa_eijiri_warmonger_spell, chosen=True),
)


# --- Matsu Kurutta ---

# "Kurutta has +1F while attacking and +2F while actions are resolving" has no handler. The second
# clause needs a read of an action resolving that the engine does not have, and the two land together.
KURUTTA_TOKEN = counter_from_key("plus1f")


def _matsu_kurutta_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Give your target Deathseeker a +1F token." Your Deathseekers at Kurutta's battlefield,
    Kurutta among them, since a targeted Yu reaches only that battlefield (ShE datasheet, The Yu
    Trait)."""
    battlefield = ctx.event.location.battlefield
    if battlefield is None:
        return []
    targets = tuple(
        card.id
        for card in units_at(ctx.game, battlefield, ctx.card.owner)
        if has_keyword(ctx.game, card, keywords.DEATHSEEKER)
    )
    return [Choose(ctx.card.owner, targets, 1, 1, "matsu_kurutta", ctx.card.id)] if targets else []


register_yu("matsu_kurutta", _matsu_kurutta_yu)


@choice_resolver(
    "matsu_kurutta", prompt="Matsu Kurutta's Yu: choose your Deathseeker to get a +1F token"
)
def _resolve_matsu_kurutta(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [AdjustCounter(chosen[0], KURUTTA_TOKEN, 1)]


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


@on(TurnBoundary, "rice_farm", boundary=Boundary.BEGINNING)
def _rice_farm_turn_boundary(ctx: TriggerContext) -> list[Effect]:
    """After your turn begins, give this Holding a +1GP Wealth token (max four)."""
    if ctx.card.owner is not ctx.event.seat or at_cap(ctx.card, WEALTH, 4):
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


# --- Shosuro Aoki / Yoritomo Kayoko (Experienced) ---


AOKI_DRAW = "aoki_draw"


@on(CounterChanged, "shosuro_aoki_yoritomo_kayoko_experienced")
def _shosuro_aoki_yoritomo_kayoko_experienced_counter_changed(ctx: TriggerContext) -> list[Effect]:
    """After your Holding gains any Wealth tokens, once per turn, draw a card."""
    if ctx.event.counter is not WEALTH or ctx.event.amount <= 0:
        return []
    gainer = ctx.game.table.cards_by_id[ctx.event.card_id]
    if not isinstance(gainer.printed, HoldingPrint) or gainer.owner is not ctx.card.owner:
        return []
    if used_this_turn(ctx.game, ctx.card, AOKI_DRAW):
        return []
    return [SpendOncePerTurn(ctx.card.id, AOKI_DRAW), DrawCard(ctx.card.owner)]


# --- Tarkasha ---


NAGA_FOLLOWER = "naga"


def _tarkasha_fallen_naga_followers(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The Naga Followers in ``seat``'s Fate discard, which is the only pile a Follower reaches."""
    return tuple(
        card.id
        for card in game.table.zones[ZoneKey(seat, ZoneRole.FATE_DISCARD)].cards
        if is_follower(card) and keywords.NAGA in card.keywords
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
    claws = (
        CreateToken(HIYAMAKOS_CLAW, ctx.card.owner, ctx.card.id, attach_to=ctx.card.id)
        for _ in range(CLAW_COUNT)
    )
    return [Simultaneously(tuple(claws))]


# --- The First Kengun ---

KENGUN_RECRUIT = counter_from_key("recruit")
# "may target Spells and Items": the attachments its Fear reaches beyond a Fear's own targets.
KENGUN_ALSO_TARGETS = (AttachmentType.SPELL, AttachmentType.ITEM)


def _the_first_kengun_reaches(game: GameState, kengun: L5RCard, card: L5RCard) -> bool:
    """Your Followers in this army."""
    return is_follower(card) and in_army_with(game, kengun, card)


def _the_first_kengun_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Give a target Obsidian Legion Follower a +1F Recruit token." Either side's Obsidian
    Legion Followers at the dying card's battlefield, since a targeted Yu reaches only that
    battlefield (ShE datasheet, The Yu Trait)."""
    battlefield = ctx.event.location.battlefield
    if battlefield is None:
        return []
    game = ctx.game
    targets = tuple(
        card.id
        for seat in game.table.seats
        for card in army_at(game, battlefield, seat)
        if is_follower(card) and has_keyword(game, card, keywords.OBSIDIAN_LEGION)
    )
    return (
        [Choose(ctx.card.owner, targets, 1, 1, "the_first_kengun", ctx.card.id)] if targets else []
    )


register_granted_yu("the_first_kengun", _the_first_kengun_reaches, _the_first_kengun_yu)


@choice_resolver(
    "the_first_kengun",
    prompt="The First Kengun's Yu: choose an Obsidian Legion Follower for a +1F Recruit token",
)
def _resolve_the_first_kengun(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [AdjustCounter(chosen[0], KENGUN_RECRUIT, 1)]


def _the_first_kengun_targets(game: GameState, source: L5RCard) -> list[str]:
    """What a Fear targets, and the enemy army's Spells and Items besides."""
    attack = game.attack
    if attack is None or attack.current is None:
        return []
    attachments = (
        card.id
        for card in army_at(game, attack.current, attack.enemy_of(source.owner))
        if isinstance(card.printed, AttachmentPrint)
        and card.printed.attachment_type in KENGUN_ALSO_TARGETS
    )
    return [*attack_targets(game, source), *attachments]


def _the_first_kengun_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Fear 0 with +1 strength per Recruit token, which destroys a Follower, Spell or Item it bows."""
    strength = source.counters.get(KENGUN_RECRUIT.key, 0)
    bowed = Bow(target.id)
    if isinstance(target.printed, AttachmentPrint):
        outcome = (bowed, Destroy(target.id, source.owner))
    else:
        outcome = (bowed,)
    return [Fear(strength, target.id, source.owner, outcome=outcome)]


register_ability(
    "the_first_kengun",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_the_first_kengun_targets,
        targeting_message=f"{ATTACK_TARGET}, or an enemy Spell or Item",
        effects=_the_first_kengun_effects,
    ),
)


# --- The Head of My Enemy (Experienced) ---

HEAD_HONOR = 2


def _the_head_of_my_enemy_experienced_dead(
    game: GameState, source: L5RCard, picked: PickedTargets
) -> list[str]:
    """Another player's dead or discarded Personalities, both of which lie in a Dynasty discard."""
    return [
        card.id
        for seat in opposing_seats(game, source.owner)
        for card in game.table.zones[ZoneKey(seat, ZoneRole.DYNASTY_DISCARD)].cards
        if isinstance(card.printed, PersonalityPrint)
    ]


def _the_head_of_my_enemy_experienced_yours(
    game: GameState, source: L5RCard, picked: PickedTargets
) -> list[str]:
    return [card.id for card in owned_personalities(game, source.owner)]


def _the_head_of_my_enemy_experienced_banish_effects(
    game: GameState, source: L5RCard, groups: tuple[tuple[L5RCard, ...], ...]
) -> list[Effect]:
    """ "Banish another player's target dead or discarded Personality to give your target
    Personality a +1F/+1C token." """
    (dead,), (yours,) = groups
    return [To(Banish(dead.id), (AdjustCounter(yours.id, PLUS_1F_PLUS_1C, 1),))]


register_ability(
    "the_head_of_my_enemy_experienced",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        target_groups=(
            TargetGroup(
                candidates=_the_head_of_my_enemy_experienced_dead,
                targeting_message="another player's dead or discarded Personality",
            ),
            TargetGroup(
                candidates=_the_head_of_my_enemy_experienced_yours,
                targeting_message="your Personality",
            ),
        ),
        effects_for_groups=_the_head_of_my_enemy_experienced_banish_effects,
        located_at=(CardLocation.HAND,),
        key="banish",
    ),
)


def _the_head_of_my_enemy_experienced_yu_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in personalities_in_play(game)]


def _the_head_of_my_enemy_experienced_yu_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """ "Give a target Personality, 'Yu: ...'" until the turn ends."""
    return [GrantAbility(source.id, target.id, (), Duration.UNTIL_END_OF_TURN)]


register_ability(
    "the_head_of_my_enemy_experienced",
    Ability(
        timings=(ActionTiming.ENGAGE,),
        cost=no_cost,
        targets=_the_head_of_my_enemy_experienced_yu_targets,
        targeting_message="a Personality",
        effects=_the_head_of_my_enemy_experienced_yu_effects,
        located_at=(CardLocation.HAND,),
        key="yu",
        printed_index=1,
    ),
)


def _the_head_of_my_enemy_experienced_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: The enemy leader takes :favor: and gains 2 Honor." The enemy leader is the dying
    Personality's opponent in the battle."""
    attack = ctx.game.attack
    if attack is None:
        return []
    leader = attack.enemy_of(ctx.card.owner)
    return [TakeFavor(leader), GainHonor(leader, HEAD_HONOR, source_id=ctx.card.id)]


register_granted_yu(
    "the_head_of_my_enemy_experienced", given_by_effect, _the_head_of_my_enemy_experienced_yu
)


# --- Togashi Bairei ---


def _togashi_bairei_bowed_an_enemy_here(game: GameState, source: L5RCard) -> bool:
    """ "If the action was yours and bowed an enemy Personality at this battlefield." """
    here = location_of(game.table, source).battlefield
    if here is None or game.action_seat is not source.owner:
        return False
    bowed = (game.table.cards_by_id.get(event.card_id) for event in action_did(game, Bowed))
    return any(
        card is not None
        and card.owner is not source.owner
        and isinstance(card.printed, PersonalityPrint)
        and location_of(game.table, card).battlefield == here
        for card in bowed
    )


def _togashi_bairei_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your Monks, Followers among them, bowed or not: the text asks for no more."""
    if not _togashi_bairei_bowed_an_enemy_here(game, source):
        return []
    return [card.id for card in owned_carrying(game, source.owner, keywords.MONK)]


def _togashi_bairei_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Straighten(target.id)]


register_ability(
    "togashi_bairei",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        cost=no_cost,
        targets=_togashi_bairei_targets,
        targeting_message="your Monk",
        effects=_togashi_bairei_effects,
        tireless=True,
    ),
)


# --- Togashi Chiyo ---

CHIYO_MELEE = 2


def _togashi_chiyo_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The Melee 2, then a reading of whether it destroyed anything, once the Melee and the
    destruction it causes have resolved."""
    return [
        MeleeAttack(CHIYO_MELEE, target.id, source.owner),
        Evaluate("togashi_chiyo_destroyed", source.id, source.owner),
    ]


@choice_resolver("togashi_chiyo_destroyed")
def _resolve_togashi_chiyo_destroyed(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """ "If this destroyed any cards, you may bow Chiyo to make a Melee 2." Chiyo is asked only
    when he is unbowed and the second Melee has something to reach."""
    chiyo = game.table.cards_by_id[source_id]
    if not action_did(game, Destroyed) or chiyo.bowed or not attack_targets(game, chiyo):
        return []
    question = f"Bow {chiyo.name} to make a Melee {CHIYO_MELEE}?"
    return [Ask(seat, question, "togashi_chiyo_bow", subjects=(source_id,), source_id=source_id)]


@choice_resolver("togashi_chiyo_bow")
def _resolve_togashi_chiyo_bow(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    if not chosen:
        return []
    reachable = tuple(attack_targets(game, game.table.cards_by_id[source_id]))
    return [Bow(source_id), Choose(seat, reachable, 1, 1, "togashi_chiyo_second_melee", source_id)]


@choice_resolver("togashi_chiyo_second_melee", prompt=f"Melee {CHIYO_MELEE} Attack")
def _resolve_togashi_chiyo_second_melee(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [MeleeAttack(CHIYO_MELEE, chosen[0], seat)]


register_ability(
    "togashi_chiyo",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_togashi_chiyo_effects,
    ),
)


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
    return [Simultaneously(tuple(AdjustCounter(card_id, WEALTH, 1) for card_id in chosen))]


# --- Wrath of the Shattered Star ---

WRATH_MELEE = 3
WRATH_FORCE_BONUS = 2
WRATH_MELEE_MODE = "Make a Melee 3"
WRATH_FIRE_MODE = "Give one or two opposed Personalities Fire and +2F"
WRATH_MOST_OPPOSED = 2


def _wrath_of_the_shattered_star_modes(game: GameState, source: L5RCard) -> tuple[str, ...]:
    """The halves of the text the board leaves something to do with."""
    offered = (
        (WRATH_MELEE_MODE, attack_targets(game, source)),
        (WRATH_FIRE_MODE, opposed_units_in_battle(game, source.owner)),
    )
    return tuple(mode for mode, reachable in offered if reachable)


def _wrath_of_the_shattered_star_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your Monks, bowed or not, once either half of the text has something to act on."""
    if not _wrath_of_the_shattered_star_modes(game, source):
        return []
    return [card.id for card in owned_carrying(game, source.owner, keywords.MONK)]


def _wrath_of_the_shattered_star_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """The bow is what does either ("bow ... to make ... or to give"), so a Monk already bowed does
    nothing (CR, To)."""
    if target.bowed:
        return []
    modes = _wrath_of_the_shattered_star_modes(game, source)
    return [
        Bow(target.id),
        AskOption(
            source.owner,
            modes,
            "Bow the Monk to do which?",
            "wrath_of_the_shattered_star",
            source.id,
        ),
    ]


@choice_resolver("wrath_of_the_shattered_star")
def _resolve_wrath_of_the_shattered_star(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    if chosen[0] == WRATH_MELEE_MODE:
        reachable = tuple(attack_targets(game, game.table.cards_by_id[source_id]))
        return [Choose(seat, reachable, 1, 1, "wrath_of_the_shattered_star_melee", source_id)]
    opposed = opposed_units_in_battle(game, seat)
    most = min(WRATH_MOST_OPPOSED, len(opposed))
    return [Choose(seat, opposed, 1, most, "wrath_of_the_shattered_star_fire", source_id)]


@choice_resolver("wrath_of_the_shattered_star_melee", prompt="Target of the Melee 3")
def _resolve_wrath_of_the_shattered_star_melee(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [MeleeAttack(WRATH_MELEE, chosen[0], seat)]


@choice_resolver(
    "wrath_of_the_shattered_star_fire",
    prompt="Give one or two of your opposed Personalities Fire and +2F",
)
def _resolve_wrath_of_the_shattered_star_fire(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The text gives no duration, so both last until the end of the turn (CR, Ongoing)."""
    return [
        effect
        for card_id in chosen
        for effect in (
            GrantKeyword(source_id, card_id, keywords.FIRE, Duration.UNTIL_END_OF_TURN),
            GrantModifier(
                source_id, card_id, Stat.FORCE, WRATH_FORCE_BONUS, Duration.UNTIL_END_OF_TURN
            ),
        )
    ]


register_ability(
    "wrath_of_the_shattered_star",
    Ability(
        timings=(ActionTiming.BATTLE,),
        keywords=frozenset({keywords.KIHO}),
        cost=no_cost,
        targets=_wrath_of_the_shattered_star_targets,
        targeting_message="your Monk",
        effects=_wrath_of_the_shattered_star_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Yabe no Oni, Blessed Abomination (Experienced) ---

LESSER_ONI = "oni_personality_2_1"
YABE_HONOR_LOSS = 6
YABE_YU_ONI_COUNT = 2


@on(EnteredPlay, "yabe_no_oni_blessed_abomination_experienced")
def _yabe_no_oni_blessed_abomination_experienced_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After Yabe no Oni enters play, lose 6 Honor."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -YABE_HONOR_LOSS, source_id=ctx.card.id)]


@on(Destroyed, "yabe_no_oni_blessed_abomination_experienced")
def _yabe_no_oni_blessed_abomination_experienced_destroyed(ctx: TriggerContext) -> list[Effect]:
    """After a non-Oni Personality is destroyed, create a 2F/1C Nonhuman Oni Shadowlands
    Personality in your home. A created Personality leaves the table as it is destroyed, so its
    destruction is not read here."""
    destroyed = ctx.game.table.cards_by_id.get(ctx.event.card_id)
    if destroyed is None or not isinstance(destroyed.printed, PersonalityPrint):
        return []
    if has_keyword(ctx.game, destroyed, keywords.ONI):
        return []
    return [CreateToken(LESSER_ONI, ctx.card.owner, ctx.card.id)]


def _yabe_no_oni_blessed_abomination_experienced_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Create two 2F/1C Nonhuman Oni Shadowlands Personalities in your home." """
    oni = (CreateToken(LESSER_ONI, ctx.card.owner, ctx.card.id) for _ in range(YABE_YU_ONI_COUNT))
    return [Simultaneously(tuple(oni))]


register_yu(
    "yabe_no_oni_blessed_abomination_experienced", _yabe_no_oni_blessed_abomination_experienced_yu
)
