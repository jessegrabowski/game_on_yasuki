from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId, Trait
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.costs import declare_amount
from yasuki_core.engine.rules.abilities.idioms import (
    declarable_gold,
    register_event_entry,
    register_granted_yu,
    register_terrain,
    register_yu,
)
from yasuki_core.engine.rules.abilities.model import (
    Ability,
    CardLocation,
    Interrupt,
    Interruption,
)
from yasuki_core.engine.rules.abilities.registry import register_ability, register_interrupt
from yasuki_core.engine.rules.board.queries import (
    in_army_with,
    ATTACK_TARGET,
    attack_targets,
    has_keyword,
    owned_personalities,
    personalities_in_play,
    province_zones,
    units_at,
)
from yasuki_core.engine.rules.stats.card_values import effective_chi, effective_force
from yasuki_core.engine.rules.stats.keyword_grants import keyword_grant
from yasuki_core.engine.rules.gold.cost import effective_gold_cost, unit_gold_cost
from yasuki_core.engine.rules.gold.discounts import recruit_discount
from yasuki_core.engine.rules.gold.production import gold_handler
from yasuki_core.engine.rules.board.seats import (
    cards_in_play,
    has_compassion,
    seat_named,
    seat_wind,
    went_second,
)
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
    AskOption,
    AttachCard,
    Banish,
    Bow,
    Choose,
    CreateToken,
    DelayedEffect,
    Destroy,
    DestroyProvince,
    Discard,
    DiscardFavor,
    Effect,
    Evaluate,
    GainHonor,
    GainProvince,
    GrantCompassion,
    GrantNegation,
    MeleeAttack,
    Move,
    MoveToDeck,
    Negated,
    PayGold,
    PlaceInProvince,
    PlaceOnDeck,
    ShuffleDeck,
    Simultaneously,
    Unpayable,
)
from yasuki_core.engine.rules.vocabulary.game_events import (
    Destroyed,
    EnteredPlay,
    NextTime,
    ProvinceDestroyed,
    TurnBoundary,
)
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.decisions import OneGroup, PickLimit, TotalAtMost
from yasuki_core.engine.rules.rulebook.recruit import proclaim_gain
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.units.composition import followers_of, is_follower, unit_force
from yasuki_core.engine.rules.units.membership import attached_to, attachments_of
from yasuki_core.engine.rules.turn.structure import END_OF_TURN, Boundary
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.engine.rules.board.queries import rightmost_province, sincerity_seed_targets
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.board.clans import card_alignments
from yasuki_core.engine.rules.rulebook.equip import equip_discount
from yasuki_core.engine.rules.vocabulary.modifiers import CompassionGrant, Duration, Negation
from yasuki_core.engine.table import DeckKey, Location, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import EventPrint
from yasuki_core.game_pieces.counters import FIRE, SINCERITY, Counter, counter_from_key


# --- Decree of the Hantei ---

KANPEKI_DYNASTY = "the_kanpeki_dynasty_hantei_xl"

register_event_entry("decree_of_the_hantei", ability_keywords=frozenset({keywords.POLITICAL}))


@on(ProvinceDestroyed, "decree_of_the_hantei")
def _decree_of_the_hantei_province_destroyed(ctx: TriggerContext) -> list[Effect]:
    """Compassion: After your Province is destroyed, banish this Event from play to destroy a target
    player's rightmost Province. The trait names the player, so the owner is asked whose."""
    event = ctx.event
    if not isinstance(event, ProvinceDestroyed) or event.province.owner is not ctx.card.owner:
        return []
    if not has_compassion(ctx.game, ctx.card.owner, ctx.card):
        return []
    players = tuple(
        info.name
        for seat, info in ctx.game.table.seats.items()
        if rightmost_province(ctx.game, seat) is not None
    )
    if not players:
        return []
    question = "Destroy whose rightmost Province?"
    return [AskOption(ctx.card.owner, players, question, "decree_of_the_hantei", ctx.card.id)]


@choice_resolver("decree_of_the_hantei")
def _resolve_decree_of_the_hantei(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Banish the Event to destroy the chosen player's rightmost Province, then, under The Kanpeki
    Dynasty, offer the Imperial Favor for a Province."""
    province = rightmost_province(game, seat_named(game, chosen[0]))
    destroyed = [] if province is None else [DestroyProvince(seat, province)]
    wind = seat_wind(game, seat)
    under_kanpeki = wind is not None and wind.printed_id == KANPEKI_DYNASTY
    offer = under_kanpeki and game.favor_holder is seat
    question = "Discard the Imperial Favor to gain a Province?"
    favor = [Ask(seat, question, "decree_of_the_hantei_favor", subjects=(source_id,))]
    return [Banish(source_id), *destroyed, *(favor if offer else [])]


@choice_resolver("decree_of_the_hantei_favor")
def _resolve_decree_of_the_hantei_favor(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """You may discard the Imperial Favor to gain a Province."""
    if not chosen:
        return []
    return [DiscardFavor(seat), GainProvince(seat)]


# --- Hida O-Win (Experienced) ---

O_WIN_EQUIP_DISCOUNT = 1
O_WIN_MELEE = 3


@equip_discount("hida_o_win_experienced")
def _hida_o_win_experienced_equip_discount(
    game: GameState, personality: L5RCard, card: L5RCard
) -> int:
    """ "O-Win Equips Jade cards for 1 less." """
    return O_WIN_EQUIP_DISCOUNT if has_keyword(game, card, keywords.JADE) else 0


def _hida_o_win_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """ "Melee 3, with +1 strength if the target is a non-Spider Clan Shadowlands card", read off
    the target as the ability resolves."""
    tainted = has_keyword(game, target, keywords.SHADOWLANDS)
    strength = O_WIN_MELEE + int(tainted and ruleset.SPIDER not in card_alignments(target))
    return [MeleeAttack(strength, target.id, source.owner)]


register_ability(
    "hida_o_win_experienced",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_hida_o_win_experienced_effects,
    ),
)


# --- Hida Yamadera, Dark Human (Experienced 2) ---

YAMADERA_MOST_FORCE = 4
YAMADERA_HONOR_LOSS = 1


def _hida_yamadera_dark_human_experienced_2_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Destroy a target Personality without attachments and 4 or less Force, or any number of
    target attachments with total Gold cost less than Yamadera's Force; after Yamadera is
    destroyed, put him on top of your Dynasty deck and lose 1 Honor." Targets at his battlefield,
    since a targeted Yu reaches only that battlefield (ShE datasheet, The Yu Trait)."""
    game, yamadera = ctx.game, ctx.card
    after = Evaluate("hida_yamadera_dark_human_experienced_2_after", yamadera.id, yamadera.owner)
    return [
        *_hida_yamadera_dark_human_experienced_2_ask(game, yamadera),
        DelayedEffect(after, NextTime(Destroyed, yamadera.id)),
    ]


register_yu("hida_yamadera_dark_human_experienced_2", _hida_yamadera_dark_human_experienced_2_yu)


def _hida_yamadera_dark_human_experienced_2_ask(game: GameState, yamadera: L5RCard) -> list[Effect]:
    """One question over both halves of the text, where the first card picked settles which half
    was taken. Each Personality is its own group, so taking one leaves no second on offer, while
    the attachments are one group that takes any number of them."""
    personalities = _hida_yamadera_dark_human_experienced_2_personalities(game, yamadera)
    attachments = _hida_yamadera_dark_human_experienced_2_attachments(game, yamadera)
    if not personalities and not attachments:
        return []
    groups = tuple((card_id,) for card_id in personalities)
    budget: tuple[PickLimit, ...] = ()
    if attachments:
        groups = (*groups, attachments)
        budget = (_hida_yamadera_dark_human_experienced_2_budget(game, yamadera, attachments),)
    return [
        Choose(
            yamadera.owner,
            (*personalities, *attachments),
            minimum=1,
            maximum=max(1, len(attachments)),
            resolver="hida_yamadera_dark_human_experienced_2",
            source_id=yamadera.id,
            limits=(OneGroup(groups), *budget),
        )
    ]


def _hida_yamadera_dark_human_experienced_2_units(
    game: GameState, yamadera: L5RCard
) -> list[L5RCard]:
    battlefield = location_of(game.table, yamadera).battlefield
    if battlefield is None:
        return []
    return [card for seat in game.table.seats for card in units_at(game, battlefield, seat)]


def _hida_yamadera_dark_human_experienced_2_personalities(
    game: GameState, yamadera: L5RCard
) -> tuple[str, ...]:
    return tuple(
        card.id
        for card in _hida_yamadera_dark_human_experienced_2_units(game, yamadera)
        if not attachments_of(game, card) and effective_force(game, card) <= YAMADERA_MOST_FORCE
    )


def _hida_yamadera_dark_human_experienced_2_attachments(
    game: GameState, yamadera: L5RCard
) -> tuple[str, ...]:
    """The attachments at his battlefield whose own Gold cost stays under his Force. One that
    breaks the total by itself is in no legal answer, so it is never offered."""
    budget = effective_force(game, yamadera)
    return tuple(
        attachment.id
        for card in _hida_yamadera_dark_human_experienced_2_units(game, yamadera)
        for attachment in attachments_of(game, card)
        if effective_gold_cost(game, attachment) < budget
    )


def _hida_yamadera_dark_human_experienced_2_budget(
    game: GameState, yamadera: L5RCard, attachments: tuple[str, ...]
) -> TotalAtMost:
    """ "total Gold cost less than Yamadera's Force": one short of his Force is the most the
    attachments picked together may carry."""
    weights = tuple(
        (card_id, effective_gold_cost(game, game.table.cards_by_id[card_id]))
        for card_id in attachments
    )
    return TotalAtMost(weights, effective_force(game, yamadera) - 1, unit="GC")


@choice_resolver(
    "hida_yamadera_dark_human_experienced_2",
    prompt="Hida Yamadera's Yu: destroy a Personality, or any number of attachments",
)
def _resolve_hida_yamadera_dark_human_experienced_2(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """One phrase destroys them, so they go at once."""
    return [Simultaneously(tuple(Destroy(card_id, Trait(source_id)) for card_id in chosen))]


@choice_resolver("hida_yamadera_dark_human_experienced_2_after")
def _resolve_hida_yamadera_dark_human_experienced_2_after(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [
        PlaceOnDeck((source_id,), DeckKey(seat, Side.DYNASTY)),
        GainHonor(seat, -YAMADERA_HONOR_LOSS, source_id=source_id),
    ]


# --- Matsu Chizuki (Experienced) ---

CHIZUKI_MELEE = 3


def _matsu_chizuki_experienced_reaches(game: GameState, chizuki: L5RCard, card: L5RCard) -> bool:
    """Your Berserkers at Chizuki's battlefield."""
    return has_keyword(game, card, keywords.BERSERKER) and in_army_with(game, chizuki, card)


def _matsu_chizuki_experienced_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Destroy a target enemy Personality whose unit has lower total Force than this unit."
    Enemy Personalities at the dying card's battlefield, since a targeted Yu reaches only that
    battlefield (ShE datasheet, The Yu Trait), weighed against the unit the dying card is in."""
    battlefield = ctx.event.location.battlefield
    if battlefield is None:
        return []
    game, berserker = ctx.game, ctx.card
    own = unit_force(game, attached_to(game, berserker) or berserker)
    targets = tuple(
        unit.id
        for seat in game.table.seats
        if seat is not berserker.owner
        for unit in units_at(game, battlefield, seat)
        if unit_force(game, unit) < own
    )
    if not targets:
        return []
    return [Choose(berserker.owner, targets, 1, 1, "matsu_chizuki_experienced", berserker.id)]


register_granted_yu(
    "matsu_chizuki_experienced", _matsu_chizuki_experienced_reaches, _matsu_chizuki_experienced_yu
)


@choice_resolver(
    "matsu_chizuki_experienced",
    prompt="Matsu Chizuki's Yu: choose an enemy Personality to destroy",
)
def _resolve_matsu_chizuki_experienced(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Destroy(chosen[0], Trait(source_id))]


def _matsu_chizuki_experienced_targets(game: GameState, source: L5RCard) -> list[str]:
    """What a Melee Attack targets, while you are the Attacker."""
    attack = game.attack
    if attack is None or attack.attacker is not source.owner:
        return []
    return attack_targets(game, source)


def _matsu_chizuki_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [MeleeAttack(CHIZUKI_MELEE, target.id, source.owner)]


register_ability(
    "matsu_chizuki_experienced",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_matsu_chizuki_experienced_targets,
        targeting_message=ATTACK_TARGET,
        effects=_matsu_chizuki_experienced_effects,
    ),
)


# --- Ninube Aitso, "Doji Yeiko" (Experienced) ---

AITSO_PROCLAIM = 3


@proclaim_gain("ninube_aitso_doji_yeiko_experienced")
def _ninube_aitso_doji_yeiko_experienced_proclaim_gain(game: GameState, card: L5RCard) -> int:
    """When Proclaiming Aitso, you may gain 3 Honor instead of her Personal Honor."""
    return AITSO_PROCLAIM


def _ninube_aitso_doji_yeiko_experienced_applies(
    game: GameState, source: L5RCard, effect: Destroy
) -> bool:
    target = game.table.cards_by_id.get(effect.card_id)
    return target is not None and target in owned_personalities(game, source.owner)


def _ninube_aitso_doji_yeiko_experienced_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Reshuffle Aitso into her owner's Dynasty deck."""
    deck = DeckKey(source.owner, Side.DYNASTY)
    return [MoveToDeck(source.id, deck, from_top=0), ShuffleDeck(deck)]


def _ninube_aitso_doji_yeiko_experienced_interrupt(
    game: GameState, source: L5RCard, effect: Destroy
) -> Interruption:
    return Interruption(Negated(effect))


register_interrupt(
    "ninube_aitso_doji_yeiko_experienced",
    Interrupt(
        answers=Destroy,
        interrupt=_ninube_aitso_doji_yeiko_experienced_interrupt,
        applies=_ninube_aitso_doji_yeiko_experienced_applies,
        located_at=(CardLocation.BATTLEFIELD,),
        cost=_ninube_aitso_doji_yeiko_experienced_cost,
    ),
)


# --- Ruby of Iuchiban (Experienced 2) ---


RUBY_HONOR_LOSS = 3


@on(EnteredPlay, "ruby_of_iuchiban_experienced_2")
def _ruby_of_iuchiban_experienced_2_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After the Ruby enters play, lose 3 Honor."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -RUBY_HONOR_LOSS, source_id=ctx.card.id)]


def _ruby_of_iuchiban_experienced_2_lowest(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """``seat``'s Personalities tied for the lowest Chi, which is every one of them when they all
    stand level."""
    held = owned_personalities(game, seat)
    if not held:
        return ()
    lowest = min(effective_chi(game, card) for card in held)
    return tuple(card.id for card in held if effective_chi(game, card) == lowest)


@on(TurnBoundary, "ruby_of_iuchiban_experienced_2", boundary=Boundary.BEGINNING)
def _ruby_of_iuchiban_experienced_2_turn_boundary(ctx: TriggerContext) -> list[Effect]:
    """Every turn costs the active player their lowest-Chi Personality, whoever controls the Ruby.
    A tie is theirs to break."""
    event = ctx.event
    if not isinstance(event, TurnBoundary):
        return []
    lowest = _ruby_of_iuchiban_experienced_2_lowest(ctx.game, event.seat)
    if not lowest:
        return []
    if len(lowest) == 1:
        return [Destroy(lowest[0], Trait(ctx.card.id))]
    return [Choose(event.seat, lowest, 1, 1, "ruby_of_iuchiban_experienced_2_tie", ctx.card.id)]


@choice_resolver(
    "ruby_of_iuchiban_experienced_2_tie",
    prompt="Choose which of your Personalities the Ruby takes",
)
def _resolve_ruby_of_iuchiban_experienced_2_tie(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Destroy(chosen[0], Trait(source_id))]


# --- Sasada, Pearl Champion (Experienced) ---


SASADAS_OROCHI = "orochi_follower_2f"


@on(EnteredPlay, "sasada_pearl_champion_experienced")
def _sasada_pearl_champion_experienced_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After Sasada enters play, create and attach a 2F Orochi Follower to her."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [CreateToken(SASADAS_OROCHI, ctx.card.owner, ctx.card.id, attach_to=ctx.card.id)]


# --- Shiba Kintaro, the Remembered (Experienced) ---

KINTARO_HONOR = 1


def _shiba_kintaro_the_remembered_experienced_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: After Kintaro is destroyed, discard a card in one of your Provinces, refill it with
    Kintaro face-up, and gain 1 Honor." """
    after = Evaluate("shiba_kintaro_the_remembered_experienced_after", ctx.card.id, ctx.card.owner)
    return [DelayedEffect(after, NextTime(Destroyed, ctx.card.id))]


register_yu(
    "shiba_kintaro_the_remembered_experienced", _shiba_kintaro_the_remembered_experienced_yu
)


@choice_resolver("shiba_kintaro_the_remembered_experienced_after")
def _resolve_shiba_kintaro_the_remembered_experienced_after(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Ask which card in the seat's Provinces makes room for Kintaro, or only gain the Honor when
    they hold none."""
    held = tuple(card.id for _, zone in province_zones(game, seat) for card in zone.cards)
    if not held:
        return [GainHonor(seat, KINTARO_HONOR, source_id=source_id)]
    return [Choose(seat, held, 1, 1, "shiba_kintaro_the_remembered_experienced_discard", source_id)]


@choice_resolver(
    "shiba_kintaro_the_remembered_experienced_discard",
    prompt="Shiba Kintaro's Yu: choose a card in your Provinces to discard",
)
def _resolve_shiba_kintaro_the_remembered_experienced_discard(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    province = next(
        key
        for key, zone in province_zones(game, seat)
        if any(card.id == chosen[0] for card in zone.cards)
    )
    return [
        Discard(chosen[0], Trait(source_id)),
        PlaceInProvince(source_id, province),
        GainHonor(seat, KINTARO_HONOR, source_id=source_id),
    ]


# --- Shrine of Compassion (Experienced) ---

SHRINE_OF_COMPASSION_GOLD = 1


@gold_handler("shrine_of_compassion_experienced")
def _shrine_of_compassion_experienced_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
) -> int:
    """Compassion: This Holding has +1GP."""
    bonus = SHRINE_OF_COMPASSION_GOLD if has_compassion(game, card.owner, card) else 0
    return card.gold_production + bonus


def _shrine_of_compassion_experienced_targets(game: GameState, source: L5RCard) -> list[str]:
    """The non-Event cards you control."""
    return [
        card.id
        for card in cards_in_play(game, source.owner)
        if not isinstance(card.printed, EventPrint)
    ]


def _shrine_of_compassion_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Effects from or upon the target are treated as if you have Compassion."""
    grant = CompassionGrant(source.id, source.owner, Duration.UNTIL_END_OF_TURN, target.id)
    return [GrantCompassion(grant)]


register_ability(
    "shrine_of_compassion_experienced",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_shrine_of_compassion_experienced_targets,
        targeting_message="a non-Event card you control",
        effects=_shrine_of_compassion_experienced_effects,
    ),
)


def _shrine_of_compassion_experienced_interrupt(
    game: GameState, source: L5RCard, effect: Effect
) -> Interruption:
    """You have Compassion while the action is resolving and, if it brings any cards into play,
    until after they enter."""
    grant = CompassionGrant(source.id, source.owner, Duration.UNTIL_ACTION_RESOLVES)
    return Interruption(replacement=effect, effects=(GrantCompassion(grant),))


# The Interrupt answers the action rather than one of its effects, so it is taken against every
# effect at once and asks the seat to pick none of them.
register_interrupt(
    "shrine_of_compassion_experienced",
    Interrupt(
        answers=Effect,
        interrupt=_shrine_of_compassion_experienced_interrupt,
        located_at=(CardLocation.BATTLEFIELD,),
        cost=bow_cost,
        answers_every=True,
        printed_index=1,
    ),
)


# --- Shrine of Courtesy ---


@recruit_discount("shrine_of_courtesy")
def _shrine_of_courtesy_recruit_discount(card: L5RCard, game: GameState, seat: PlayerId) -> int:
    """Courtesy grants -3 Gold Cost while you are the second player (you did not go first)."""
    return 3 if went_second(game, seat) else 0


@keyword_grant("shrine_of_courtesy")
def _shrine_of_courtesy_keywords(
    game: GameState, shrine: L5RCard, card: L5RCard
) -> tuple[str, ...]:
    """The same Courtesy clause grants Legacy, so a second player can search this Holding out."""
    if card is not shrine:
        return ()
    return (keywords.LEGACY,) if went_second(game, shrine.owner) else ()


# --- Shrine of Sincerity ---


@gold_handler("shrine_of_sincerity")
def _shrine_of_sincerity_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP when paying for a Sincerity card that still carries Sincerity tokens."""
    bonus = (
        1
        if any(
            keywords.SINCERITY in target.keywords and target.counters.get(SINCERITY.key, 0) > 0
            for target in targets
        )
        else 0
    )
    return card.gold_production + bonus


def _shrine_of_sincerity_targets(game: GameState, card: L5RCard) -> list[str]:
    return sincerity_seed_targets(game, card.owner)


def _shrine_of_sincerity_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [AdjustCounter(target.id, SINCERITY, 1)]


register_ability(
    "shrine_of_sincerity",
    Ability(
        timings=(ActionTiming.DYNASTY,),
        cost=bow_cost,
        targets=_shrine_of_sincerity_targets,
        targeting_message="a Sincerity card in your Province",
        effects=_shrine_of_sincerity_effects,
    ),
)


# --- Struggle On ---


def _struggle_on_reaches(game: GameState, terrain: L5RCard, card: L5RCard) -> bool:
    """Your Followers at this battlefield."""
    return is_follower(card) and in_army_with(game, terrain, card)


def _struggle_on_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Negate this Follower's destruction, bow it, and transfer it to one of your
    Personalities who must be at home unless this Follower is Courage."

    A Follower leaving play with its Personality's unit is saved by the transfer, which takes it out
    of that unit before the destruction commits. One the destruction names is saved by a negation,
    which a Follower with nowhere to go still has, and keeps its Personality.
    """
    game, follower = ctx.game, ctx.card
    effects: list[Effect] = []
    if ctx.event.leaves_with is None:
        negation = Negation(
            follower.id,
            Duration.UNTIL_END_OF_TURN,
            effect_kind=Destroy,
            subject_id=follower.id,
            once=True,
        )
        effects.append(GrantNegation(negation))
    effects.append(Bow(follower.id))
    bearers = _struggle_on_bearers(game, follower)
    if bearers:
        effects.append(Choose(follower.owner, bearers, 1, 1, "struggle_on", follower.id))
    return effects


def _struggle_on_bearers(game: GameState, follower: L5RCard) -> tuple[str, ...]:
    """Your Personalities other than the Follower's own, at home unless it is Courage."""
    bearer = attached_to(game, follower)
    anywhere = has_keyword(game, follower, keywords.COURAGE)
    return tuple(
        card.id
        for card in owned_personalities(game, follower.owner)
        if card is not bearer and (anywhere or location_of(game.table, card).is_home)
    )


register_granted_yu("struggle_on", _struggle_on_reaches, _struggle_on_yu)


@choice_resolver(
    "struggle_on", prompt="Struggle On's Yu: choose your Personality to take the Follower"
)
def _resolve_struggle_on(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [AttachCard(source_id, chosen[0])]


register_terrain("struggle_on", ability_keywords=frozenset({keywords.TERRAIN}))


# --- The Bad Death of Hida Daizu ---


def _the_bad_death_of_hida_daizu_amounts(game: GameState, source: L5RCard) -> tuple[int, ...]:
    """Every amount the seat could spend, from nothing up to what it can declare.

    The card reads "equal to or less than", so one amount reaches every unit at or under it and the
    same target is reachable at many amounts. Spending more than the target costs is legal and
    remains the seat's choice.

    A board with no Personality on it offers no amount at all: nothing there can be targeted, and a
    cost with no amount to choose is not payable (CR, Good Faith).
    """
    if not personalities_in_play(game):
        return ()
    return tuple(range(declarable_gold(game, source) + 1))


def _the_bad_death_of_hida_daizu_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """The amount is the cost block, settled before the target is chosen, since the legal targets
    are shaped by it (CR, Action Sequence steps B and C)."""
    return [
        declare_amount(
            source,
            _the_bad_death_of_hida_daizu_amounts(game, source),
            "How much Gold do you spend on The Bad Death of Hida Daizu?",
        )
    ]


def _the_bad_death_of_hida_daizu_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Personalities whose unit costs no more than the amount paid. An amount below every unit
    reaches none, and the card does nothing more (CR, Action Sequence step E)."""
    if game.amount_declared is None:
        return []
    return [
        card.id
        for card in personalities_in_play(game)
        if unit_gold_cost(game, card) <= game.amount_declared
    ]


def _the_bad_death_of_hida_daizu_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """The target stays in play until the turn ends, and the card banishes itself rather than
    reaching the discard through step F."""
    return [DelayedEffect(Banish(target.id), END_OF_TURN), Banish(source.id)]


register_ability(
    "the_bad_death_of_hida_daizu",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=_the_bad_death_of_hida_daizu_cost,
        targets=_the_bad_death_of_hida_daizu_targets,
        effects=_the_bad_death_of_hida_daizu_effects,
        located_at=(CardLocation.HAND,),
        targeting_message="a Personality to banish at the end of the turn",
        targets_after_cost=True,
    ),
)


# --- Togashi Noritada, Defender of the High House (Experienced) ---

NORITADA_MOVE_HOME = "Move Noritada home"


@on(EnteredPlay, "togashi_noritada_defender_of_the_high_house_experienced")
def _togashi_noritada_defender_of_the_high_house_experienced_entered_play(
    ctx: TriggerContext,
) -> list[Effect]:
    """Sincerity: Give Noritada a +1F Fire token for each token removed."""
    if ctx.event.card_id != ctx.card.id:
        return []
    sincerity = ctx.card.counters.get(SINCERITY.key, 0)
    if sincerity == 0:
        return []
    return [AdjustCounter(ctx.card.id, FIRE, sincerity)]


def _togashi_noritada_defender_of_the_high_house_experienced_destroy_options(
    noritada: L5RCard,
) -> dict[str, Counter]:
    """Each token Noritada holds, keyed by the option that destroys one of it."""
    held = (counter_from_key(key) for key, count in sorted(noritada.counters.items()) if count > 0)
    return {f"Destroy one of his {counter.name} tokens": counter for counter in held}


def _togashi_noritada_defender_of_the_high_house_experienced_cost(
    game: GameState, source: L5RCard
) -> list[Effect]:
    """Ask to move Noritada home or destroy one of his tokens, offering only what he can pay."""
    options = list(_togashi_noritada_defender_of_the_high_house_experienced_destroy_options(source))
    if not location_of(game.table, source).is_home:
        options.insert(0, NORITADA_MOVE_HOME)
    if not options:
        return [Unpayable("Noritada is home and holds no tokens")]
    question = "Move Noritada home, or destroy one of his tokens?"
    return [AskOption(source.owner, tuple(options), question, "togashi_noritada_cost", source.id)]


@choice_resolver("togashi_noritada_cost")
def _resolve_togashi_noritada_cost(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    noritada = game.table.cards_by_id[source_id]
    if chosen[0] == NORITADA_MOVE_HOME:
        return [Move(source_id, Location.home(noritada.owner))]
    options = _togashi_noritada_defender_of_the_high_house_experienced_destroy_options(noritada)
    return [AdjustCounter(source_id, options[chosen[0]], -1)]


def _togashi_noritada_defender_of_the_high_house_experienced_targets(
    game: GameState, source: L5RCard
) -> list[str]:
    """Enemy Personalities with lower Chi than Noritada."""
    chi = effective_chi(game, source)
    return [
        card.id
        for card in personalities_in_play(game)
        if card.owner is not source.owner and effective_chi(game, card) < chi
    ]


def _togashi_noritada_defender_of_the_high_house_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [Bow(target.id)]


register_ability(
    "togashi_noritada_defender_of_the_high_house_experienced",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=_togashi_noritada_defender_of_the_high_house_experienced_cost,
        targets=_togashi_noritada_defender_of_the_high_house_experienced_targets,
        targeting_message="an enemy Personality with lower Chi",
        effects=_togashi_noritada_defender_of_the_high_house_experienced_effects,
    ),
)


# --- Veteran of Thunder ---

THUNDER_VETERAN = "mantis_samurai_naval_personality_2_1_2"


def _veteran_of_thunder_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Create a 2F/1C/2PH Samurai Naval Mantis Clan Personality." """
    return [CreateToken(THUNDER_VETERAN, ctx.card.owner, ctx.card.id)]


register_yu("veteran_of_thunder", _veteran_of_thunder_yu)


# --- Yoritomo Robusuta, Master of Gaijin Pepper ---

EXPLOSIVE = counter_from_key("explosive")
ROBUSUTA_GOLD = 2


def _yoritomo_robusuta_master_of_gaijin_pepper_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Target an enemy Personality with an Explosive token and destroy a Follower in their
    unit, or them if they have no Followers." An enemy at Robusuta's battlefield, since a targeted
    Yu reaches only that battlefield (ShE datasheet, The Yu Trait)."""
    battlefield = ctx.event.location.battlefield
    if battlefield is None:
        return []
    targets = tuple(
        card.id
        for card in personalities_in_play(ctx.game)
        if card.owner is not ctx.card.owner
        and card.counters.get(EXPLOSIVE.key, 0) > 0
        and location_of(ctx.game.table, card).battlefield == battlefield
    )
    if not targets:
        return []
    resolver = "yoritomo_robusuta_master_of_gaijin_pepper_yu"
    return [Choose(ctx.card.owner, targets, 1, 1, resolver, ctx.card.id)]


register_yu(
    "yoritomo_robusuta_master_of_gaijin_pepper", _yoritomo_robusuta_master_of_gaijin_pepper_yu
)


@choice_resolver(
    "yoritomo_robusuta_master_of_gaijin_pepper_yu",
    prompt="Yoritomo Robusuta's Yu: choose an enemy Personality with an Explosive token",
)
def _resolve_yoritomo_robusuta_master_of_gaijin_pepper_yu(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Destroy a Follower in the target's unit, asking which when there are several, or the target
    when it has none."""
    target = game.table.cards_by_id[chosen[0]]
    followers = tuple(follower.id for follower in followers_of(game, target))
    if not followers:
        return [Destroy(target.id, Trait(source_id))]
    if len(followers) == 1:
        return [Destroy(followers[0], Trait(source_id))]
    return [
        Choose(
            seat, followers, 1, 1, "yoritomo_robusuta_master_of_gaijin_pepper_follower", source_id
        )
    ]


@choice_resolver(
    "yoritomo_robusuta_master_of_gaijin_pepper_follower",
    prompt="Yoritomo Robusuta's Yu: choose a Follower to destroy",
)
def _resolve_yoritomo_robusuta_master_of_gaijin_pepper_follower(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Destroy(chosen[0], Trait(source_id))]


def _yoritomo_robusuta_master_of_gaijin_pepper_cost(
    game: GameState, source: L5RCard
) -> list[Effect]:
    return [PayGold(source.owner, ROBUSUTA_GOLD, source.name)]


def _yoritomo_robusuta_master_of_gaijin_pepper_targets(
    game: GameState, source: L5RCard
) -> list[str]:
    return [card.id for card in personalities_in_play(game) if card.owner is not source.owner]


def _yoritomo_robusuta_master_of_gaijin_pepper_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [AdjustCounter(target.id, EXPLOSIVE, 1)]


register_ability(
    "yoritomo_robusuta_master_of_gaijin_pepper",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=_yoritomo_robusuta_master_of_gaijin_pepper_cost,
        targets=_yoritomo_robusuta_master_of_gaijin_pepper_targets,
        targeting_message="another player's Personality",
        effects=_yoritomo_robusuta_master_of_gaijin_pepper_effects,
    ),
)
