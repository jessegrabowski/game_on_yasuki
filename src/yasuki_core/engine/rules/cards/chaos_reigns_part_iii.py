from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.idioms import (
    ask_who_loses_honor,
    plays_clan,
    register_entry,
)
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, InvestAbility, itself
from yasuki_core.engine.rules.abilities.registry import register_ability, register_invest
from yasuki_core.engine.rules.board.queries import (
    ATTACK_TARGET,
    attack_targets,
    owned_holdings,
    personalities_in_play,
)
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.gold.discounts import invest_discount, recruit_discount
from yasuki_core.engine.rules.gold.production import gold_handler
from yasuki_core.engine.rules.board.clans import controlled_alignments
from yasuki_core.engine.rules.board.seats import (
    cards_in_hand,
    cards_in_play,
    seat_controls_printed,
    seat_named,
)
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Arrange,
    Ask,
    AskOption,
    Choose,
    CreateToken,
    Discard,
    DiscardFromHand,
    Dishonor,
    DrawCard,
    Effect,
    EndLook,
    LookAtTop,
    GainHonor,
    GrantKeyword,
    GrantModifier,
    MeleeAttack,
    MoveToHand,
    PlaceInProvince,
    Rehonor,
    Show,
    ShuffleDeck,
)
from yasuki_core.engine.rules.rulebook.looks import PUT_ON_BOTTOM
from yasuki_core.engine.rules.rulebook.equip import creation_targets
from yasuki_core.engine.rules.vocabulary.game_events import Destroyed, Dishonored, EnteredPlay
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.board.queries import (
    has_keyword,
    province_zones,
    remaining_look,
    top_of_deck,
)
from yasuki_core.engine.rules.triggers import TriggerContext, caused_by, choice_resolver, on
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.table import DeckKey, Location, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import PersonalityPrint


# --- Bayushi Gihei ---

GIHEI_FORCE = 2
GIHEI_HONOR = 1


def _bayushi_gihei_reacts(ctx: TriggerContext, where: Location | None) -> list[Effect]:
    """After your action destroys or dishonors a card at Gihei's location, give him +2F and a
    target player loses 1 Honor. "Your action" is read off the event's cause."""
    gihei = ctx.card
    if not caused_by(ctx, gihei.owner) or where != location_of(ctx.game.table, gihei):
        return []
    return [
        GrantModifier(gihei.id, gihei.id, Stat.FORCE, GIHEI_FORCE, Duration.UNTIL_END_OF_TURN),
        ask_who_loses_honor(ctx.game, gihei.owner, GIHEI_HONOR, gihei.id),
    ]


@on(Destroyed, "bayushi_gihei")
def _bayushi_gihei_destroyed(ctx: TriggerContext) -> list[Effect]:
    return _bayushi_gihei_reacts(ctx, ctx.event.location)


@on(Dishonored, "bayushi_gihei")
def _bayushi_gihei_dishonored(ctx: TriggerContext) -> list[Effect]:
    dishonored = ctx.game.table.cards_by_id[ctx.event.card_id]
    return _bayushi_gihei_reacts(ctx, location_of(ctx.game.table, dishonored))


# --- Chuda Jomei ---


JOMEI_HONOR_LOSS = 3


@on(EnteredPlay, "chuda_jomei")
def _chuda_jomei_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After Jomei enters play, lose 3 Honor."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -JOMEI_HONOR_LOSS, source_id=ctx.card.id)]


def _chuda_jomei_targets(game: GameState, source: L5RCard) -> list[str]:
    """Every Personality on the board without the Nonhuman keyword. Human is the absence of that
    keyword rather than one a card carries (CR, Human), and it is read off the board because
    Nonhuman can be granted."""
    return [
        card.id
        for card in personalities_in_play(game)
        if keywords.NONHUMAN not in effective_keywords(game, card)
    ]


def _chuda_jomei_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Give the target Shadowlands. The card prints no duration, so the grant lasts until the end
    of the turn (CR, Duration of Effects)."""
    return [GrantKeyword(source.id, target.id, keywords.SHADOWLANDS, Duration.UNTIL_END_OF_TURN)]


register_ability(
    "chuda_jomei",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_chuda_jomei_targets,
        targeting_message="a Human Personality",
        effects=_chuda_jomei_effects,
    ),
)


# --- Comprehensive Education ---

COMPREHENSIVE_EDUCATION_LOOK = 5


def _comprehensive_education_edicts_and_kata(
    game: GameState, card_ids: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(
        card_id
        for card_id in card_ids
        if has_keyword(game, game.table.cards_by_id[card_id], keywords.EDICT)
        or has_keyword(game, game.table.cards_by_id[card_id], keywords.KATA)
    )


def _comprehensive_education_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Look at five, then the first of the two "may" questions, each skipped when it has no
    candidates. With no Edict or Kata among them the rest go straight to the bottom."""
    seat = source.owner
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(game, fate, COMPREHENSIVE_EDUCATION_LOOK)
    if not seen:
        return []
    return [
        LookAtTop(seat, fate, len(seen)),
        *_comprehensive_education_take(game, seen, seat, source.id),
    ]


def _comprehensive_education_take(
    game: GameState, seen: tuple[str, ...], seat: PlayerId, source_id: str
) -> list[Effect]:
    offered = _comprehensive_education_edicts_and_kata(game, seen)
    if not offered:
        return [_comprehensive_education_bottom(seat, seen, source_id)]
    return [Choose(seat, offered, 0, 1, "comprehensive_education_take", source_id)]


@choice_resolver(
    "comprehensive_education_take",
    prompt="You may show one that is an Edict or Kata and put it in your hand",
)
def _resolve_comprehensive_education_take(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    taken: list[Effect] = [Show(chosen[0]), MoveToHand(chosen[0], seat)] if chosen else []
    rest = tuple(card_id for card_id in remaining_look(game) if card_id not in chosen)
    discardable = _comprehensive_education_edicts_and_kata(game, rest)
    if discardable:
        next_step = Choose(
            seat, discardable, 0, len(discardable), "comprehensive_education_discard", source_id
        )
    else:
        next_step = _comprehensive_education_bottom(seat, rest, source_id)
    return [*taken, next_step]


@choice_resolver(
    "comprehensive_education_discard", prompt="You may discard any that are Edicts or Kata"
)
def _resolve_comprehensive_education_discard(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    discarded: list[Effect] = [Discard(card_id, seat) for card_id in chosen]
    rest = tuple(card_id for card_id in remaining_look(game) if card_id not in chosen)
    return [*discarded, _comprehensive_education_bottom(seat, rest, source_id)]


def _comprehensive_education_bottom(
    seat: PlayerId, rest: tuple[str, ...], source_id: str
) -> Effect:
    """ "Put the rest on the bottom of your deck in any order", or nothing left to put."""
    if not rest:
        return EndLook()
    return Arrange(seat, rest, PUT_ON_BOTTOM, source_id, to_bottom=True)


register_ability(
    "comprehensive_education",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=itself,
        hits_every_target=True,
        effects=_comprehensive_education_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Doji Maya (Experienced) ---

MAYA_MELEE = 3
MAYA_INVEST = 2
# "a Courtier or Tanuki Clan Personality": both are keywords a card carries.
MAYA_SOUGHT = (keywords.COURTIER, keywords.TANUKI_CLAN)


def _doji_maya_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [MeleeAttack(MAYA_MELEE, target.id, source.owner)]


register_ability(
    "doji_maya_experienced",
    Ability(
        timings=(ActionTiming.BATTLE,),
        keywords=frozenset({keywords.IAIJUTSU}),
        cost=no_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_doji_maya_experienced_effects,
    ),
)


def _doji_maya_experienced_search_pool(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The Personalities in ``seat``'s Dynasty deck her Invest may fetch."""
    return tuple(
        card.id
        for card in game.table.decks[DeckKey(seat, Side.DYNASTY)].cards
        if isinstance(card.printed, PersonalityPrint)
        and not effective_keywords(game, card).isdisjoint(MAYA_SOUGHT)
    )


def _doji_maya_experienced_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """Search the Dynasty deck for a Personality to refill the Province Maya just left."""
    # "If Maya entered play from a Province" needs no test: an Invest resolves only from a Recruit
    # or an Equip, and a Personality reaches play by Recruit, which is always out of a Province.
    pool = _doji_maya_experienced_search_pool(game, source.owner)
    if not pool:
        return []
    return [Choose(source.owner, pool, 1, 1, "doji_maya_experienced", source.id)]


@choice_resolver(
    "doji_maya_experienced",
    prompt="Search your Dynasty deck for a Courtier or Tanuki Clan Personality",
)
def _resolve_doji_maya_experienced(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Put the card Maya found into the Province she vacated, face-up, and shuffle the deck."""
    # Her Province is the one still short: a vacated Province's refill is deferred behind the
    # reactions to the card leaving, and an Invest resolves before that runs. Filling it here is
    # what leaves the pending refill a no-op.
    short = [key for key, zone in province_zones(game, seat) if zone.has_capacity()]
    placement = [PlaceInProvince(chosen[0], short[0])] if short else []
    return [*placement, ShuffleDeck(DeckKey(seat, Side.DYNASTY))]


register_invest(
    "doji_maya_experienced",
    InvestAbility(amounts=(MAYA_INVEST,), effect=_doji_maya_experienced_invest),
)


# --- Doji Teru ---

TERU_HONOR = 2
TERU_FORCE = 2


def _doji_teru_targets(game: GameState, source: L5RCard) -> list[str]:
    return [
        card.id
        for card in personalities_in_play(game)
        if card.owner is not source.owner and card.dishonorable
    ]


def _doji_teru_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Their controller may rehonor them. If this rehonored them, gain 2 Honor; otherwise, give
    Teru +2F. The gain names no Personality: rehonoring is one of the action's own effects, so the
    CR does not substitute it for the gain (CR, Rehonoring 0.1)."""
    return [
        Ask(
            target.owner,
            f"Rehonor {target.name}?",
            "doji_teru",
            subjects=(target.id,),
            source_id=source.id,
        )
    ]


@choice_resolver("doji_teru")
def _resolve_doji_teru(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    teru = game.table.cards_by_id[source_id]
    if chosen:
        return [Rehonor(chosen[0]), GainHonor(teru.owner, TERU_HONOR)]
    return [GrantModifier(source_id, source_id, Stat.FORCE, TERU_FORCE, Duration.UNTIL_END_OF_TURN)]


register_ability(
    "doji_teru",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_doji_teru_targets,
        targeting_message="another player's dishonorable Personality",
        effects=_doji_teru_effects,
    ),
)


# --- Hungry Moon ---

HUNGRY_MOON_HONOR = 3


def _hungry_moon_dishonor_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in personalities_in_play(game) if card.bowed]


def _hungry_moon_dishonor_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [Dishonor(target.id, source.owner)]


def _hungry_moon_wealth_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for seat in game.table.seats for card in owned_holdings(game, seat)]


def _hungry_moon_wealth_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Destroy all Wealth tokens on a target Holding. If this destroyed any Wealth tokens, choose a
    player, who loses 3 Honor. A Holding with none is a legal target the ability does nothing to."""
    held = target.counters.get(WEALTH.key, 0)
    if not held:
        return []
    return [
        AdjustCounter(target.id, WEALTH, -held),
        ask_who_loses_honor(game, source.owner, HUNGRY_MOON_HONOR, source.id),
    ]


register_ability(
    "hungry_moon",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_hungry_moon_dishonor_targets,
        targeting_message="a bowed Personality",
        effects=_hungry_moon_dishonor_effects,
        located_at=(CardLocation.HAND,),
        key="dishonor",
    ),
)

register_ability(
    "hungry_moon",
    Ability(
        printed_index=1,
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_hungry_moon_wealth_targets,
        targeting_message="a Holding",
        effects=_hungry_moon_wealth_effects,
        located_at=(CardLocation.HAND,),
        key="wealth",
    ),
)


# --- Kengun Grounds ---


ZOMBIE_FOLLOWER = "zombie_follower"
KENGUN_HONOR_LOSS = 2
UNTAINTED_HONOR_LOSS = 5


@on(EnteredPlay, "kengun_grounds")
def _kengun_grounds_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, lose 2 Honor."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -KENGUN_HONOR_LOSS, source_id=ctx.card.id)]


def _kengun_grounds_targets(game: GameState, source: L5RCard) -> list[str]:
    """Nobody while it is not the controller's turn. The ability's own condition is read before it
    is offered rather than resolving into nothing."""
    if game.active is not source.owner:
        return []
    zombie = game.table.creatable_tokens[ZOMBIE_FOLLOWER]
    return [target.id for target in creation_targets(game, source.owner, zombie)]


def _kengun_grounds_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The dead serve anyone. A Personality untouched by the Shadowlands pays for the company."""
    effects: list[Effect] = [
        CreateToken(ZOMBIE_FOLLOWER, source.owner, source.id, attach_to=target.id)
    ]
    if keywords.SHADOWLANDS not in effective_keywords(game, target):
        effects.append(GainHonor(source.owner, -UNTAINTED_HONOR_LOSS, source_id=source.id))
    return effects


register_ability(
    "kengun_grounds",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_kengun_grounds_targets,
        targeting_message="your Personality",
        effects=_kengun_grounds_effects,
    ),
)


# --- Moto Ikarichi, Bloodseeker ---


IKARICHIS_UNDEAD = "undead_cavalry_follower_2f"
KANPEKI_DYNASTY = "the_kanpeki_dynasty_hantei_xl"
IKARICHI_HONOR_LOSS = 2
IKARICHI_INVEST = 2


@invest_discount("moto_ikarichi_bloodseeker")
def _moto_ikarichi_bloodseeker_invest_discount(
    card: L5RCard, game: GameState, seat: PlayerId
) -> int:
    """His Invest costs nothing under the Kanpeki Dynasty, and its printed two Gold under any other
    Wind."""
    return (
        IKARICHI_INVEST
        if any(held.printed_id == KANPEKI_DYNASTY for held in cards_in_play(game, seat))
        else 0
    )


def _moto_ikarichi_bloodseeker_invest(
    game: GameState, source: L5RCard, amount: int
) -> list[Effect]:
    """A 2F Undead outrider, made and mounted as he arrives."""
    return [CreateToken(IKARICHIS_UNDEAD, source.owner, source.id, attach_to=source.id)]


register_invest(
    "moto_ikarichi_bloodseeker",
    InvestAbility(amounts=(IKARICHI_INVEST,), effect=_moto_ikarichi_bloodseeker_invest),
)


@on(EnteredPlay, "moto_ikarichi_bloodseeker")
def _moto_ikarichi_bloodseeker_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After Ikarichi enters play, lose 2 Honor."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -IKARICHI_HONOR_LOSS, source_id=ctx.card.id)]


IKARICHI_MELEE = 4


def _moto_ikarichi_bloodseeker_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [MeleeAttack(IKARICHI_MELEE, target.id, source.owner)]


register_ability(
    "moto_ikarichi_bloodseeker",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_moto_ikarichi_bloodseeker_effects,
    ),
)


# --- Moto Traders ---


@recruit_discount("moto_traders")
def _moto_traders_recruit_discount(card: L5RCard, game: GameState, seat: PlayerId) -> int:
    """Enters play for 1 less Gold if you control another Merchant Caravan."""
    return 1 if seat_controls_printed(game, seat, keywords.MERCHANT_CARAVAN, other_than=card) else 0


def _moto_traders_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Draw a card."""
    return [DrawCard(source.owner)]


register_ability(
    "moto_traders",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=itself,
        effects=_moto_traders_effects,
        hits_every_target=True,
    ),
)


# --- Tanuki Band ---


@gold_handler("tanuki_band")
def _tanuki_band_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
) -> int:
    """+1GP while you control two Clan Alignments, or +2GP while you control three or more."""
    controlled = len(controlled_alignments(game, seat))
    bonus = 2 if controlled >= 3 else 1 if controlled == 2 else 0
    return card.gold_production + bonus


def _tanuki_band_players(game: GameState, seat: PlayerId) -> tuple[PlayerId, ...]:
    """The players with more cards in their hand than ``seat``."""
    held = len(cards_in_hand(game, seat))
    return tuple(player for player in game.table.seats if len(cards_in_hand(game, player)) > held)


def _tanuki_band_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Band itself, while some player could be its target: an action with no legal target
    cannot be announced."""
    return [source.id] if _tanuki_band_players(game, source.owner) else []


def _tanuki_band_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Name the target player, a player with more cards in their hand than you. Nothing happens
    when no player still qualifies, since the hands can change between announcement and
    resolution."""
    names = tuple(
        game.table.seats[player].name for player in _tanuki_band_players(game, source.owner)
    )
    if not names:
        return []
    return [AskOption(source.owner, names, "Who must discard a card?", "tanuki_band", source.id)]


@choice_resolver("tanuki_band")
def _resolve_tanuki_band(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The named player must discard a card, which they choose."""
    named = seat_named(game, chosen[0])
    return [DiscardFromHand(named, 1, seat, named)]


register_ability(
    "tanuki_band",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_tanuki_band_targets,
        effects=_tanuki_band_effects,
        hits_every_target=True,
    ),
)


# --- Walk with Tengoku ---


FUSHICHO = "fushicho_personality_3_2_3"


def _walk_with_tengoku_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """A Fushicho for the turn: it burns out before the turn ends however the turn goes. The
    Ranged 3 Attack a battle lets the Shugenja bow for is not modeled."""
    return [CreateToken(FUSHICHO, source.owner, source.id, banish_at_turn_end=True)]


register_ability(
    "walk_with_tengoku",
    Ability(
        timings=(ActionTiming.BATTLE, ActionTiming.OPEN),
        cost=bow_cost,
        targets=itself,
        effects=_walk_with_tengoku_effects,
        hits_every_target=True,
    ),
)


# --- Zealotry ---

# "Open: If you are an Akasha Clan player, put this Edict into play." Its Dynasty-phase trigger has
# no handler yet.
register_entry("zealotry", clears=keywords.EDICT, condition=plays_clan(ruleset.AKASHA))
