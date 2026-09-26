from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.rulebook.favor_payment import favor_payer
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.idioms import (
    ask_whose_honor_moves,
    declarable_gold,
    register_entry,
    register_event_entry,
    register_ring,
)
from yasuki_core.engine.rules.abilities.model import (
    Ability,
    CardLocation,
    Interrupt,
    Interruption,
    InvestAbility,
    itself,
)
from yasuki_core.engine.rules.abilities.registry import (
    EntryState,
    entry_state,
    register_interrupt,
    register_may_remain_bowed,
    register_ability,
    register_invest,
)
from yasuki_core.engine.rules.board.queries import (
    ATTACK_TARGET,
    attack_targets,
    phase_history,
    has_keyword,
    owned_holdings,
    owned_personalities,
    personalities_in_play,
    province_zones,
    top_of_deck,
    units_at,
)
from yasuki_core.engine.rules.board.seats import (
    cards_in_hand,
    cards_in_play,
    opposing_seats,
    seat_named,
)
from yasuki_core.engine.rules.rulebook.looks import TAKE_ONE_AND_SHUFFLE
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, BattleDesignator
from yasuki_core.engine.rules.attack_effects import attack_strength_against
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
    AskAmount,
    AskOption,
    AttackEffect,
    Banish,
    Bow,
    Choose,
    CreateToken,
    DelayStraighten,
    Destroy,
    Discard,
    DiscardFromHand,
    DrawCard,
    Effect,
    Fear,
    GainHonor,
    GrantProvinceStrength,
    LookAtTop,
    MeleeAttack,
    Move,
    MoveToDeck,
    Negated,
    ReshuffleFromHand,
    ShuffleDeck,
    SpendOncePerTurn,
    Then,
    Unpayable,
)
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.stats.card_values import effective_chi, effective_force
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.rulebook.equip import creation_targets
from yasuki_core.engine.rules.board.clans import seat_alignment_name
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.turn.structure import BEGINNING_OF_ACTION_PHASE
from yasuki_core.engine.rules.action_record import action_round
from yasuki_core.engine.rules.legality import permitted_timings_in
from yasuki_core.engine.rules.units.membership import attached_to, attachments_of, unit_of
from yasuki_core.engine.rules.state import GameState, used_this_turn
from yasuki_core.engine.rules.state_based_actions import register_no_enlightenment
from yasuki_core.engine.rules.stats.province_strength import effective_province_strength
from yasuki_core.engine.rules.units.composition import followers_of
from yasuki_core.engine.rules.vocabulary.game_events import (
    Bowed,
    CardDiscarded,
    Destroyed,
    EnteredPlay,
    Straightened,
)
from yasuki_core.engine.rules.triggers import TriggerContext, action_did, choice_resolver, on
from yasuki_core.engine.table import DeckKey, Location, ZoneKey, ZoneRole, location_of
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint, RingPrint
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH


# --- Aseth's Legion ---

ASETHS_LEGION_MELEE = 2
# "Fear effects targeting this Follower have -2 strength."
ASETHS_LEGION_FEAR_PENALTY = -2


@attack_strength_against("aseths_legion")
def _aseths_legion_attack_strength(
    game: GameState, card: L5RCard, target: L5RCard, attack: AttackEffect
) -> int:
    """The phrase "targeting this Follower" means she shields herself alone, and only against
    Fear."""
    if target is not card or not isinstance(attack, Fear):
        return 0
    return ASETHS_LEGION_FEAR_PENALTY


def _aseths_legion_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [MeleeAttack(ASETHS_LEGION_MELEE, target.id, source.owner)]


register_ability(
    "aseths_legion",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_aseths_legion_effects,
    ),
)


# --- Blessings of the Red Panda Spirit ---


@choice_resolver("red_panda_spirit_keep")
def _resolve_red_panda_spirit_keep(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Reshuffle the Event into its owner's Dynasty deck, or discard it. Declining is not doing
    nothing. The Event leaves its Province either way, and only where it goes is the seat's."""
    if not chosen:
        return [Discard(source_id, seat)]
    deck = DeckKey(seat, Side.DYNASTY)
    return [MoveToDeck(source_id, deck, from_top=0), ShuffleDeck(deck)]


def _blessings_of_the_red_panda_spirit_targets(game: GameState, card: L5RCard) -> list[str]:
    """The Event itself. The ability names no card at all, but an ability whose candidates are empty
    is never offered, so it stands as its own target, paired with ``hits_every_target`` so the seat
    is not asked to pick the only thing there is."""
    return [card.id]


def _blessings_of_the_red_panda_spirit_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """A gift to the table, then a question. Every seat gains and draws in seat order. The reshuffle
    is deferred so it follows the draws, which is the order the card states."""
    gifts: list[Effect] = []
    for seat in game.table.seats:
        gifts.append(GainHonor(seat, 1))
        gifts.append(DrawCard(seat))
    question = f"Shuffle {source.name} into your Dynasty deck instead of discarding it?"
    return [
        *gifts,
        Then(
            (
                Ask(
                    source.owner,
                    question,
                    "red_panda_spirit_keep",
                    subjects=(source.id,),
                    source_id=source.id,
                ),
            )
        ),
    ]


register_ability(
    "blessings_of_the_red_panda_spirit",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_blessings_of_the_red_panda_spirit_targets,
        effects=_blessings_of_the_red_panda_spirit_effects,
        hits_every_target=True,
        located_at=(CardLocation.PROVINCE,),
    ),
)


# --- Bound in Blood ---


HORROR = "horror_shadowlands_personality"
GOLD_PER_SACRIFICE = 2
MOST_SACRIFICES = 4


def _bound_in_blood_amounts(game: GameState, source: L5RCard) -> tuple[int, ...]:
    """The sums worth spending: two Gold buys one Personality and every two more buys another, up to
    four or however many the seat has, and never more than it can declare.

    Nothing smaller is offered. An action whose targeting is priced by a variable Gold cost may only
    be announced for an amount that buys a legal target (CR, Good Faith).
    """
    seat = source.owner
    bodies = min(MOST_SACRIFICES, len(owned_personalities(game, seat)))
    affordable = declarable_gold(game, source) // GOLD_PER_SACRIFICE
    return tuple(count * GOLD_PER_SACRIFICE for count in range(1, min(bodies, affordable) + 1))


def _bound_in_blood_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow the Spell, then settle the :X:. Both are printed in the cost block, so both are paid
    before the Personalities are chosen (CR, Action Sequence)."""
    return [
        Bow(source.id),
        AskAmount(
            source.owner,
            _bound_in_blood_amounts(game, source),
            "How much Gold do you spend on Bound in Blood?",
            "bound_in_blood",
            source.id,
        ),
    ]


@choice_resolver("bound_in_blood")
def _resolve_bound_in_blood(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Take the bodies the declared amount bought."""
    spent = int(chosen[0])
    bodies = min(MOST_SACRIFICES, spent // GOLD_PER_SACRIFICE)
    offered = tuple(card.id for card in owned_personalities(game, seat))
    return [
        Choose(seat, offered, bodies, bodies, "bound_in_blood_sacrifice", source_id),
    ]


@choice_resolver("bound_in_blood_sacrifice", prompt="Choose the Personalities to target")
def _resolve_bound_in_blood_sacrifice(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The Horror is measured against the bound before they are banished, since it is made of what
    they were."""
    bound = [game.table.cards_by_id[card_id] for card_id in chosen]
    horror = CreateToken(
        HORROR,
        seat,
        source_id,
        stats=(
            (Stat.GOLD_COST, sum(effective_gold_cost(game, card) for card in bound)),
            (Stat.FORCE, sum(effective_chi(game, card) for card in bound)),
            (Stat.CHI, len(bound)),
        ),
    )
    return [horror, *(Banish(card.id) for card in bound), Destroy(source_id, seat)]


register_ability(
    "bound_in_blood",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=_bound_in_blood_cost,
        targets=itself,
        effects=lambda game, source, target: [],
        hits_every_target=True,
    ),
)


# --- Courts of Otosan Uchi ---


COURTIER = "courtier_personality_0_2_2"


def _courts_of_otosan_uchi_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """A Wealth token and a Courtier who joins the Clan the Holding's controller plays."""
    return [
        AdjustCounter(source.id, WEALTH, 1),
        CreateToken(
            COURTIER, source.owner, source.id, clan=seat_alignment_name(game, source.owner)
        ),
    ]


COURTS_HONOR = 1


def _courts_of_otosan_uchi_courtiers(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The seat's unbowed Courtiers (the ones that still have a bow to spend)."""
    return tuple(
        personality.id
        for personality in owned_personalities(game, seat)
        if not personality.bowed and keywords.COURTIER in effective_keywords(game, personality)
    )


def _courts_of_otosan_uchi_targets(game: GameState, source: L5RCard) -> list[str]:
    """The controller's unbowed Courtiers, once the action just resolved was the one that Recruited
    this Holding. Bowing one is what the Honor swing costs, so a bowed Courtier is no Courtier.

    The Courtier this Holding's own Invest buys is among them: a Response is taken after the action
    has finished resolving, and the Invest resolves inside it.
    """
    if not any(event.card_id == source.id for event in action_did(game, EnteredPlay)):
        return []
    return list(_courts_of_otosan_uchi_courtiers(game, source.owner))


def _courts_of_otosan_uchi_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Bow the named Courtier, then ask whose Honor moves. A target player is named first, then the
    direction, as the card is written."""
    return [Bow(target.id), ask_whose_honor_moves(game, source.owner, COURTS_HONOR, source.id)]


register_ability(
    "courts_of_otosan_uchi",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        cost=no_cost,
        targets=_courts_of_otosan_uchi_targets,
        targeting_message="your Courtier",
        effects=_courts_of_otosan_uchi_effects,
        tireless=True,
    ),
)


register_invest(
    "courts_of_otosan_uchi",
    InvestAbility(amounts=(2,), effect=_courts_of_otosan_uchi_invest),
)


# --- Culling Grounds ---


EXPENDABLE_SERVANT = "expendable_personality_0_2_1"


register_may_remain_bowed("culling_grounds")


@on(Straightened, "culling_grounds")
def _culling_grounds_straightened(ctx: TriggerContext) -> list[Effect]:
    """Until the game ends, if this Holding is ever unbowed, banish the Personality.

    Banishes only the servant currently created by this Holding. One already lost is not chased.
    """
    if ctx.event.card_id != ctx.card.id:
        return []
    return [Banish(created) for created in ctx.game.creations_of(ctx.card.id)]


def _culling_grounds_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Create and Recruit the servant, ignoring Gold Cost. Nothing is paid for it, so there is no
    payment to raise. The Honor is the price."""
    return [
        CreateToken(EXPENDABLE_SERVANT, source.owner, source.id),
        GainHonor(source.owner, -1, source_id=source.id),
    ]


register_ability(
    "culling_grounds",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=itself,
        effects=_culling_grounds_effects,
        hits_every_target=True,
    ),
)


# --- Dark Ring of Air (Experienced) ---

DARK_AIR_HONOR_LOSS = 3
DARK_AIR_BOWED = 3


def _dark_ring_of_air_experienced_condition(game: GameState, source: L5RCard) -> bool:
    """ "If each player controls three or more bowed Personalities." """
    return all(
        sum(
            1
            for card in cards_in_play(game, seat)
            if card.bowed and isinstance(card.printed, PersonalityPrint)
        )
        >= DARK_AIR_BOWED
        for seat in game.table.seats
    )


def _dark_ring_of_air_experienced_entry_effects(game: GameState, source: L5RCard) -> list[Effect]:
    return [GainHonor(source.owner, -DARK_AIR_HONOR_LOSS, source_id=source.id)]


register_entry(
    "dark_ring_of_air_experienced",
    condition=_dark_ring_of_air_experienced_condition,
    extra_effects=_dark_ring_of_air_experienced_entry_effects,
    key="enter",
)
register_no_enlightenment("dark_ring_of_air_experienced")


def _dark_ring_of_air_experienced_targets(game: GameState, source: L5RCard) -> list[str]:
    """Every Personality in play, on your turn. The card does not ask for an unbowed one."""
    if game.active is not source.owner:
        return []
    return [card.id for card in personalities_in_play(game)]


def _dark_ring_of_air_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Bow the target, who will not straighten until their controller's next Action Phase
    begins."""
    return [Bow(target.id), DelayStraighten(target.id, until=BEGINNING_OF_ACTION_PHASE)]


register_ring(
    "dark_ring_of_air_experienced",
    ability=Ability(
        printed_index=1,
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_dark_ring_of_air_experienced_targets,
        effects=_dark_ring_of_air_experienced_effects,
        key="air",
        keywords=frozenset({keywords.AIR}),
    ),
    pitch=None,
)


# --- Dark Ring of Earth (Experienced) ---

DARK_EARTH_HONOR_LOSS = 3
DARK_EARTH_PROVINCES = 6
DARK_EARTH_CHI = 9


def _dark_ring_of_earth_experienced_condition(game: GameState, source: L5RCard) -> bool:
    """ "If there are 6 or fewer total Provinces among all players." """
    standing = sum(1 for seat in game.table.seats for _ in province_zones(game, seat))
    return standing <= DARK_EARTH_PROVINCES


def _dark_ring_of_earth_experienced_entry_effects(game: GameState, source: L5RCard) -> list[Effect]:
    return [GainHonor(source.owner, -DARK_EARTH_HONOR_LOSS, source_id=source.id)]


register_entry(
    "dark_ring_of_earth_experienced",
    condition=_dark_ring_of_earth_experienced_condition,
    extra_effects=_dark_ring_of_earth_experienced_entry_effects,
    key="enter",
)
register_no_enlightenment("dark_ring_of_earth_experienced")


def _dark_ring_of_earth_experienced_army(game: GameState, source: L5RCard) -> list[L5RCard]:
    """The attacking army's Personalities at the current battlefield, while the Ring's owner is the
    Defender there."""
    attack = game.attack
    if attack is None or attack.current is None or attack.defender is not source.owner:
        return []
    return units_at(game, attack.current, attack.attacker)


def _dark_ring_of_earth_experienced_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow the Ring and lower the current Province's strength to 0 until the end of the turn, by a
    penalty of its present strength (CR, Setting Stats to Values). The lowering is written as "X to
    Y" after the colon, which this engine reads as part of the cost."""
    attack = game.attack
    if attack is None or attack.current is None:
        return [Unpayable("no battle is being fought")]
    province = attack.current_province
    strength = effective_province_strength(game, province)
    lowered = GrantProvinceStrength(source.id, province, -strength, Duration.UNTIL_END_OF_TURN)
    return [*bow_cost(game, source), lowered]


def _dark_ring_of_earth_experienced_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Ring itself, while you defend against an army of 9 or less total Chi."""
    army = _dark_ring_of_earth_experienced_army(game, source)
    if not army or sum(effective_chi(game, card) for card in army) > DARK_EARTH_CHI:
        return []
    return [source.id]


def _dark_ring_of_earth_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Move home every unit in the attacking army, bowing every card in it as it moves (CR,
    Unit)."""
    return [
        effect
        for personality in _dark_ring_of_earth_experienced_army(game, source)
        for effect in (
            Move(personality.id, Location.home(personality.owner)),
            *(Bow(card.id) for card in unit_of(game, personality)),
        )
    ]


register_ring(
    "dark_ring_of_earth_experienced",
    ability=Ability(
        printed_index=1,
        timings=(ActionTiming.BATTLE,),
        cost=_dark_ring_of_earth_experienced_cost,
        targets=_dark_ring_of_earth_experienced_targets,
        effects=_dark_ring_of_earth_experienced_effects,
        hits_every_target=True,
        key="earth",
        keywords=frozenset({keywords.EARTH}),
    ),
    pitch=None,
)


# --- Dark Ring of Fire (Experienced) ---

DARK_FIRE_HONOR_LOSS = 3
DARK_FIRE_DESTROYED = 2


def _dark_ring_of_fire_experienced_condition(game: GameState, source: L5RCard) -> bool:
    """ "If two or more Personalities have been destroyed this phase by their controller's
    actions." A destruction the rulebook or a trait causes is no action's."""
    by_id = game.table.cards_by_id
    destroyed = [
        event
        for event in phase_history(game)
        if isinstance(event, Destroyed)
        and isinstance(event.cause, PlayerId)
        and event.cause is event.controller
        and (card := by_id.get(event.card_id)) is not None
        and isinstance(card.printed, PersonalityPrint)
    ]
    return len(destroyed) >= DARK_FIRE_DESTROYED


def _dark_ring_of_fire_experienced_entry_effects(game: GameState, source: L5RCard) -> list[Effect]:
    return [GainHonor(source.owner, -DARK_FIRE_HONOR_LOSS, source_id=source.id)]


register_entry(
    "dark_ring_of_fire_experienced",
    timing=(ActionTiming.BATTLE, ActionTiming.OPEN),
    condition=_dark_ring_of_fire_experienced_condition,
    extra_effects=_dark_ring_of_fire_experienced_entry_effects,
    key="enter",
)
register_no_enlightenment("dark_ring_of_fire_experienced")


def _dark_ring_of_fire_experienced_targets(game: GameState, source: L5RCard) -> list[str]:
    """Each card without attachments in the unit of a Personality the action bowed who stands at
    a battlefield. The action's bows include those paid as its cost, as "the action bowed" reads."""
    by_id = game.table.cards_by_id
    targets: list[str] = []
    for event in action_did(game, Bowed):
        bowed = by_id.get(event.card_id)
        if bowed is None or not isinstance(bowed.printed, PersonalityPrint):
            continue
        if location_of(game.table, bowed).battlefield is None:
            continue
        for card in unit_of(game, bowed):
            if card.id not in targets and not attachments_of(game, card):
                targets.append(card.id)
    return targets


def _dark_ring_of_fire_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [Destroy(target.id, source.owner)]


register_ring(
    "dark_ring_of_fire_experienced",
    ability=Ability(
        printed_index=1,
        timings=(ActionTiming.RESPONSE,),
        cost=bow_cost,
        targets=_dark_ring_of_fire_experienced_targets,
        effects=_dark_ring_of_fire_experienced_effects,
        key="fire",
        keywords=frozenset({keywords.FIRE}),
    ),
    pitch=None,
)


# --- Dark Ring of the Void (Experienced) ---

DARK_VOID_HONOR_LOSS = 3
DARK_VOID_BANISHED = 2


def _dark_ring_of_the_void_experienced_condition(game: GameState, source: L5RCard) -> bool:
    """ "If this is the only card in your hand when announcing this action." Read as no other card
    in hand, since once announced the Ring is in the resolution area rather than the hand."""
    return all(card.id == source.id for card in cards_in_hand(game, source.owner))


def _dark_ring_of_the_void_experienced_entry_effects(
    game: GameState, source: L5RCard
) -> list[Effect]:
    return [GainHonor(source.owner, -DARK_VOID_HONOR_LOSS, source_id=source.id)]


register_entry(
    "dark_ring_of_the_void_experienced",
    condition=_dark_ring_of_the_void_experienced_condition,
    extra_effects=_dark_ring_of_the_void_experienced_entry_effects,
    key="enter",
)
register_no_enlightenment("dark_ring_of_the_void_experienced")


def _dark_ring_of_the_void_experienced_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow the Ring and banish two cards from either of your discard piles. The banish is written
    as "X to Y" after the colon, which this engine reads as part of the cost."""
    piles = tuple(
        card.id
        for role in (ZoneRole.FATE_DISCARD, ZoneRole.DYNASTY_DISCARD)
        for card in game.table.zones[ZoneKey(source.owner, role)].cards
    )
    return [
        *bow_cost(game, source),
        Choose(
            source.owner,
            piles,
            DARK_VOID_BANISHED,
            DARK_VOID_BANISHED,
            "dark_ring_of_the_void_experienced_banish",
            source.id,
        ),
    ]


@choice_resolver("dark_ring_of_the_void_experienced_banish", prompt="Banish two cards")
def _resolve_dark_ring_of_the_void_experienced_banish(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Banish(card_id) for card_id in chosen]


def _dark_ring_of_the_void_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Name the target player."""
    names = tuple(info.name for info in game.table.seats.values())
    return [
        AskOption(
            source.owner,
            names,
            "Who discards a card at random?",
            "dark_ring_of_the_void_experienced",
            source.id,
        )
    ]


@choice_resolver("dark_ring_of_the_void_experienced")
def _resolve_dark_ring_of_the_void_experienced(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    named = seat_named(game, chosen[0])
    return [DiscardFromHand(named, 1, seat, None)]


register_ring(
    "dark_ring_of_the_void_experienced",
    ability=Ability(
        timings=(ActionTiming.OPEN,),
        cost=_dark_ring_of_the_void_experienced_cost,
        targets=itself,
        effects=_dark_ring_of_the_void_experienced_effects,
        hits_every_target=True,
        key="void",
        keywords=frozenset({keywords.VOID}),
    ),
    pitch=None,
)


# --- Doji Yuten ---


def _doji_yuten_applies(game: GameState, source: L5RCard, effect: Bow | Move) -> bool:
    """A Battle action's bowing or moving of one of Yuten's controller's other Personalities.
    A Move names any card in the unit, so the Personality is read off the unit. "Yuten cannot
    attack" is not modeled."""
    if ActionTiming.BATTLE not in permitted_timings_in(game, action_round(game), source.owner):
        return False
    card = game.table.cards_by_id.get(effect.card_id)
    if card is None:
        return False
    personality = card if isinstance(card.printed, PersonalityPrint) else attached_to(game, card)
    return (
        personality is not None
        and personality.id != source.id
        and personality.owner is source.owner
    )


def _doji_yuten_interrupt(game: GameState, source: L5RCard, effect: Bow | Move) -> Interruption:
    attack = game.attack
    defending = attack is not None and attack.defender is source.owner
    gained = (GainHonor(source.owner, 1),) if defending else ()
    return Interruption(Negated(effect), effects=gained)


register_interrupt(
    "doji_yuten",
    Interrupt(
        answers=Bow | Move,
        interrupt=_doji_yuten_interrupt,
        applies=_doji_yuten_applies,
        located_at=(CardLocation.BATTLEFIELD,),
    ),
)


# --- Iweko Miaka, Princess of Rokugan (Experienced) ---

MIAKA_PAYMENT = "iweko_miaka_favor_payment"


@favor_payer("iweko_miaka_princess_of_rokugan_experienced")
def _iweko_miaka_princess_of_rokugan_experienced_favor_payer(
    game: GameState, card: L5RCard
) -> list[Effect] | None:
    """ "Once per turn, you may pay your action's :favor: costs."

    A trait that fires while the cost is being paid, which is how the CR has a card contribute to
    somebody's payment (CR, Paying Gold Costs and Special Triggered Traits). Her limit is the whole
    price, so taking her offer costs nothing else and the Favor stays where it is.
    """
    if used_this_turn(game, card, MIAKA_PAYMENT):
        return None
    return [SpendOncePerTurn(card.id, MIAKA_PAYMENT)]


# --- Kisada's Funeral (Experienced) ---

register_event_entry("kisadas_funeral_experienced", timing=ActionTiming.DYNASTY)


# --- Kitsu Watanabe (Experienced) ---


LION_ANCESTOR = "lion_ancestor"


def _kitsu_watanabe_experienced_targets(game: GameState, source: L5RCard) -> list[str]:
    return [holding.id for holding in owned_holdings(game, source.owner)]


def _kitsu_watanabe_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """The Holding is spent on the summons, so it goes before the Ancestor answers. The additional
    action a Battle-taken summons earns for destroying a Fortification has no effect to name it."""
    return [
        Destroy(target.id, source.owner),
        CreateToken(LION_ANCESTOR, source.owner, source.id),
    ]


register_ability(
    "kitsu_watanabe_experienced",
    Ability(
        timings=(ActionTiming.BATTLE, ActionTiming.OPEN),
        cost=no_cost,
        targets=_kitsu_watanabe_experienced_targets,
        targeting_message="your Holding",
        effects=_kitsu_watanabe_experienced_effects,
    ),
)


# --- Legacy of Fudo ---

FUDO_HONOR_LOSS = 1
FUDO_RESHUFFLED = 1
FUDO_DRAWN = 2
FUDO_PITCH = (
    "Discard this Ring from your hand to target a player with at least one card in their hand."
)


def _legacy_of_fudo_condition(game: GameState, source: L5RCard) -> bool:
    """ "If your opponent has no cards in their hand." """
    return not any(cards_in_hand(game, seat) for seat in opposing_seats(game, source.owner))


def _legacy_of_fudo_entry_effects(game: GameState, source: L5RCard) -> list[Effect]:
    """The Honor lost when its own action puts it into play."""
    return [GainHonor(source.owner, -FUDO_HONOR_LOSS, source_id=source.id)]


register_entry(
    "legacy_of_fudo",
    timing=(ActionTiming.OPEN, ActionTiming.DYNASTY),
    condition=_legacy_of_fudo_condition,
    extra_effects=_legacy_of_fudo_entry_effects,
    key="enter",
)
register_no_enlightenment("legacy_of_fudo")


@on(CardDiscarded, "legacy_of_fudo")
def _legacy_of_fudo_card_discarded(ctx: TriggerContext) -> list[Effect]:
    """After an action discards this Ring, lose 1 Honor. A discard the rulebook or a trait causes is
    no action's."""
    if ctx.event.card_id != ctx.card.id or not isinstance(ctx.event.cause, PlayerId):
        return []
    return [GainHonor(ctx.card.owner, -FUDO_HONOR_LOSS, source_id=ctx.card.id)]


def _legacy_of_fudo_players(game: GameState) -> tuple[PlayerId, ...]:
    """The players with at least one card in their hand."""
    return tuple(seat for seat in game.table.seats if cards_in_hand(game, seat))


def _legacy_of_fudo_targets(game: GameState, source: L5RCard) -> list[str]:
    return [source.id] if _legacy_of_fudo_players(game) else []


def _legacy_of_fudo_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Name the target player, one with at least one card in their hand."""
    names = tuple(game.table.seats[seat].name for seat in _legacy_of_fudo_players(game))
    if not names:
        return []
    return [
        AskOption(
            source.owner, names, "Who reshuffles a card and draws two?", "legacy_of_fudo", source.id
        )
    ]


@choice_resolver("legacy_of_fudo")
def _resolve_legacy_of_fudo(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    named = seat_named(game, chosen[0])
    return [
        ReshuffleFromHand(named, FUDO_RESHUFFLED),
        *(DrawCard(named) for _ in range(FUDO_DRAWN)),
    ]


register_ring(
    "legacy_of_fudo",
    ability=Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_legacy_of_fudo_targets,
        effects=_legacy_of_fudo_effects,
        hits_every_target=True,
        key="fudo",
    ),
    pitch=FUDO_PITCH,
)


# --- Man the Walls! ---


def _man_the_walls_targets(game: GameState, source: L5RCard) -> list[str]:
    """The seat's own unbowed Followers and Personalities, wherever they stand.

    The card says "at any location," so targets are not limited to the current battle's
    battlefield.
    """
    offered: list[str] = []
    for personality in owned_personalities(game, source.owner):
        if not personality.bowed:
            offered.append(personality.id)
        offered.extend(
            follower.id for follower in followers_of(game, personality) if not follower.bowed
        )
    return offered


def _man_the_walls_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Bow the target, and give the Province the battle is at a bonus equal to its Force.

    The Force is read as the bonus is laid down, so bowing the target, or anything that happens to
    it later, leaves the Province as strong as it was made.
    """
    province = game.attack.current_province
    bonus = effective_force(game, target)
    return [
        Bow(target.id),
        GrantProvinceStrength(source.id, province, bonus, Duration.UNTIL_END_OF_TURN),
    ]


register_ability(
    "man_the_walls",
    Ability(
        printed_index=1,
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_man_the_walls_targets,
        targeting_message="your Follower or Personality at any location",
        effects=_man_the_walls_effects,
        located_at=(CardLocation.HAND,),
        battle_designators=frozenset({BattleDesignator.ABSENT}),
        targets_any_location=True,
    ),
)


# --- Master Your Thoughts ---


def _master_your_thoughts_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your Monk and Shugenja Personalities, bowed or not: the text asks for no more."""
    return [
        card.id
        for card in owned_personalities(game, source.owner)
        if has_keyword(game, card, keywords.MONK) or has_keyword(game, card, keywords.SHUGENJA)
    ]


def _master_your_thoughts_rings(game: GameState, seat: PlayerId) -> int:
    return sum(isinstance(card.printed, RingPrint) for card in cards_in_play(game, seat))


def _master_your_thoughts_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """The bow is what lets the seat look ("bow ... to look"), so a target already bowed bows
    nothing and looks at nothing (CR, To)."""
    if target.bowed:
        return []
    seat = source.owner
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(game, fate, _master_your_thoughts_rings(game, seat) + 1)
    if not seen:
        return [Bow(target.id)]
    return [
        Bow(target.id),
        LookAtTop(seat, fate, len(seen)),
        Choose(seat, seen, 1, 1, TAKE_ONE_AND_SHUFFLE, source.id),
    ]


register_ability(
    "master_your_thoughts",
    Ability(
        timings=(ActionTiming.OPEN,),
        keywords=frozenset({keywords.KIHO}),
        cost=no_cost,
        targets=_master_your_thoughts_targets,
        targeting_message="your Monk or Shugenja Personality",
        effects=_master_your_thoughts_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Matsu Gakuya (Experienced) ---


@entry_state("matsu_gakuya_experienced")
def _matsu_gakuya_experienced_entry_state(game: GameState, card: L5RCard) -> EntryState:
    """Gakuya enters play dishonorable. His Response, which reads what the action destroyed or put
    into play, is not modeled."""
    return EntryState(dishonorable=True)


# --- Rebuilt Harbor ---


def _rebuilt_harbor_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """One +1GP Wealth token per gold invested (Rebuilt Harbor's variable payoff)."""
    return [AdjustCounter(source.id, WEALTH, amount)]


register_invest("rebuilt_harbor", InvestAbility(amounts=(1, 2, 3), effect=_rebuilt_harbor_invest))


# --- Shinjo Saeki, Clan Champion (Experienced 2) ---


CAVALRY_FOLLOWER = "cavalry"


@on(EnteredPlay, "shinjo_saeki_clan_champion_experienced_2")
def _shinjo_saeki_clan_champion_experienced_2_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After Saeki enters play, create and Equip a 1F Cavalry Follower to each of your Cavalry
    Personalities, himself included, since he carries the keyword."""
    if ctx.event.card_id != ctx.card.id:
        return []
    cavalry = ctx.game.table.creatable_tokens[CAVALRY_FOLLOWER]
    return [
        CreateToken(CAVALRY_FOLLOWER, ctx.card.owner, ctx.card.id, attach_to=rider.id)
        for rider in creation_targets(ctx.game, ctx.card.owner, cavalry, keyword=keywords.CAVALRY)
    ]
