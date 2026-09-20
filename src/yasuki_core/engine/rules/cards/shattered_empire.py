from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId, Trait
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.idioms import plays_clan, register_entry
from yasuki_core.engine.rules.abilities.model import Ability, InvestAbility, itself
from yasuki_core.engine.rules.abilities.registry import (
    before_entering_play,
    register_ability,
    register_cannot_attack,
    register_invest,
)
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, PlayStrategy
from yasuki_core.engine.rules.board.clans import card_alignments
from yasuki_core.engine.rules.board.queries import (
    attack_targets,
    has_keyword,
    opposed_units_in_battle,
    opposing_units_in_battle,
    owned_personalities,
    units_at,
)
from yasuki_core.engine.rules.effects import (
    Choose,
    CreateToken,
    DelayedEffect,
    Destroy,
    Dishonor,
    DrawCard,
    Effect,
    Evaluate,
    GainHonor,
    MeleeAttack,
    Rehonor,
    seppuku,
)
from yasuki_core.engine.rules.gold.discounts import recruit_discount
from yasuki_core.engine.rules.rulebook.lobby import lobby_bar
from yasuki_core.engine.rules.rulebook.recruit import proclaim_gain
from yasuki_core.engine.rules.stats.card_values import effective_chi, effective_personal_honor
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.stats.stat_grants import stat_grant
from yasuki_core.engine.rules.triggers import action_did, choice_resolver
from yasuki_core.engine.rules.turn.structure import END_OF_BATTLE
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.vocabulary.game_events import HonorChanged
from yasuki_core.engine.rules.rulebook.equip import creation_targets
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import WindPrint


# --- Daidoji Tashiko ---

TASHIKO_HONOR = 2

register_cannot_attack("daidoji_tashiko")


@stat_grant("daidoji_tashiko")
def _daidoji_tashiko_stat_grant(game: GameState, source: L5RCard, card: L5RCard, stat: Stat) -> int:
    """While opposed, a Force bonus equal to the highest Personal Honor among Courtiers in her
    army."""
    if card is not source or stat is not Stat.FORCE:
        return 0
    if source.id not in opposed_units_in_battle(game, source.owner):
        return 0
    honors = [
        effective_personal_honor(game, personality)
        for personality in units_at(game, game.attack.current, source.owner)
        if has_keyword(game, personality, keywords.COURTIER)
    ]
    return max(honors, default=0)


def _daidoji_tashiko_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DelayedEffect(Evaluate("daidoji_tashiko", source.id, source.owner), END_OF_BATTLE)]


@choice_resolver("daidoji_tashiko")
def _resolve_daidoji_tashiko(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """After the battle resolves, gain 2 Honor if its Province was not destroyed. Every battle is
    fought at a Province, so "if it was at a Province" always holds."""
    outcome = game.attack.battlefields[game.attack.current].outcome
    return [] if outcome.province_destroyed else [GainHonor(seat, TASHIKO_HONOR)]


register_ability(
    "daidoji_tashiko",
    Ability(
        timings=(ActionTiming.ENGAGE,),
        label=f"Engage: gain {TASHIKO_HONOR} Honor after this battle if its Province survives",
        cost=no_cost,
        targets=itself,
        effects=_daidoji_tashiko_effects,
        hits_every_target=True,
    ),
)


# --- Doji Meiji, Regent (Experienced) ---


@proclaim_gain("doji_meiji_regent_experienced")
def _doji_meiji_regent_experienced_proclaim_gain(game: GameState, card: L5RCard) -> int:
    """When Proclaiming Meiji, you may choose to gain Honor equal to his Chi instead of equal to
    his Personal Honor."""
    return effective_chi(game, card)


def _doji_meiji_regent_experienced_wind_of(game: GameState, seat: PlayerId) -> str | None:
    """The printed id of the Wind ``seat`` has in play, or None without one."""
    return next(
        (
            card.printed_id
            for card in game.table.battlefield.cards
            if card.owner is seat and isinstance(card.printed, WindPrint)
        ),
        None,
    )


@lobby_bar("doji_meiji_regent_experienced")
def _doji_meiji_regent_experienced_lobby_bar(
    game: GameState, card: L5RCard, seat: PlayerId
) -> bool:
    """While Meiji is unbowed, players without your Wind may not Lobby.

    "Your Wind" names a Wind his controller has, so a controller with none bars nobody; this is
    a ruling, the CR being silent. A rival with no Wind, or a different one, is without yours.
    His Political Open has no handler yet: it waits on duels and on a per-turn record of Favor
    discards.
    """
    if card.bowed or seat is card.owner:
        return False
    wind_of = _doji_meiji_regent_experienced_wind_of
    yours = wind_of(game, card.owner)
    return yours is not None and wind_of(game, seat) != yours


# --- Doji Yasuko, Soul of Doji Takeji ---

YASUKO_DISCOUNT = 2
YASUKO_COMPANIONS = (keywords.DUELIST, keywords.COURTIER)


@recruit_discount("doji_yasuko_soul_of_doji_takeji")
def _doji_yasuko_soul_of_doji_takeji_recruit_discount(
    card: L5RCard, game: GameState, seat: PlayerId
) -> int:
    """Enters play for 2 less while the seat controls a Crane Clan Duelist or Courtier."""
    for personality in owned_personalities(game, seat):
        if ruleset.CRANE not in card_alignments(personality):
            continue
        if any(word in effective_keywords(game, personality) for word in YASUKO_COMPANIONS):
            return YASUKO_DISCOUNT
    return 0


def _doji_yasuko_soul_of_doji_takeji_targets(game: GameState, source: L5RCard) -> list[str]:
    """Itself, once the action just resolved was a Strategy from which a player gained Honor."""
    if not isinstance(game.action, PlayStrategy):
        return []
    gained = any(event.amount > 0 for event in action_did(game, HonorChanged))
    return [source.id] if gained else []


def _doji_yasuko_soul_of_doji_takeji_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [DrawCard(source.owner)]


register_ability(
    "doji_yasuko_soul_of_doji_takeji",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        keywords=frozenset({keywords.POLITICAL}),
        label="Political Response: after a Strategy gained a player Honor, draw a card",
        cost=no_cost,
        targets=_doji_yasuko_soul_of_doji_takeji_targets,
        effects=_doji_yasuko_soul_of_doji_takeji_effects,
        hits_every_target=True,
    ),
)


# --- Hida Sanjiro ---

SANJIROS_ARMOR = "armor_item_plus2f"


def _hida_sanjiro_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """A +2F Armor Item, made and worn as he arrives."""
    return [CreateToken(SANJIROS_ARMOR, source.owner, source.id, attach_to=source.id)]


register_invest("hida_sanjiro", InvestAbility(amounts=(2,), effect=_hida_sanjiro_invest))


# --- Matsu Gonshiro, Soul of Matsu Shimei ---

GONSHIRO_UNIT_COST = 9


@before_entering_play("matsu_gonshiro_soul_of_matsu_shimei")
def _matsu_gonshiro_soul_of_matsu_shimei_before_entering_play(
    game: GameState, card: L5RCard
) -> list[Effect]:
    """Before Gonshiro enters play, dishonor him. "You must assign Gonshiro to a battlefield
    whenever legal" is a restriction on the seat and is not modeled."""
    return [Dishonor(card.id, Trait(card.id))]


def _matsu_gonshiro_soul_of_matsu_shimei_unit_gold_cost(
    game: GameState, personality: L5RCard
) -> int:
    return sum(card.gold_cost or 0 for card in (personality, *attachments_of(game, personality)))


def _matsu_gonshiro_soul_of_matsu_shimei_targets(game: GameState, source: L5RCard) -> list[str]:
    """The enemy Personalities at this battle whose unit's total Gold Cost is 9 or less."""
    return [
        card_id
        for card_id in opposing_units_in_battle(game, source.owner)
        if _matsu_gonshiro_soul_of_matsu_shimei_unit_gold_cost(
            game, game.table.cards_by_id[card_id]
        )
        <= GONSHIRO_UNIT_COST
    ]


def _matsu_gonshiro_soul_of_matsu_shimei_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Rehonor Gonshiro: unpayable, so the ability is withheld, while he is honorable."""
    return [Rehonor(source.id)]


def _matsu_gonshiro_soul_of_matsu_shimei_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Destroy the target's unit, and after this battle ends Gonshiro commits seppuku."""
    return [
        Destroy(target.id, source.owner),
        *(DelayedEffect(effect, END_OF_BATTLE) for effect in seppuku(source.id, source.owner)),
    ]


register_ability(
    "matsu_gonshiro_soul_of_matsu_shimei",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle: Rehonor Gonshiro to destroy a target enemy unit costing "
        f"{GONSHIRO_UNIT_COST} or less, and commit seppuku after the battle",
        cost=_matsu_gonshiro_soul_of_matsu_shimei_cost,
        targets=_matsu_gonshiro_soul_of_matsu_shimei_targets,
        effects=_matsu_gonshiro_soul_of_matsu_shimei_effects,
    ),
)


# --- Shinjo Mayuko, Soul of Shinjo Wei ---

MAYUKO_FIRST_MELEE = 4
MAYUKO_SECOND_MELEE = 3


def _shinjo_mayuko_soul_of_shinjo_wei_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Dishonor Mayuko: unpayable, so the ability is withheld, once she is dishonorable."""
    return [Dishonor(source.id, source.owner)]


def _shinjo_mayuko_soul_of_shinjo_wei_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """A Melee 4, then a Melee 3 with its own target. The second is chosen once the first has
    resolved, and the first target is left out of it: a survivor of Melee 4 is beyond Melee 3."""
    others = tuple(card_id for card_id in attack_targets(game, source) if card_id != target.id)
    second = (
        [Choose(source.owner, others, 1, 1, "shinjo_mayuko_second_melee", source.id)]
        if others
        else []
    )
    return [MeleeAttack(MAYUKO_FIRST_MELEE, target.id, source.owner), *second]


@choice_resolver("shinjo_mayuko_second_melee", prompt=f"Melee {MAYUKO_SECOND_MELEE} Attack")
def _resolve_shinjo_mayuko_second_melee(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [MeleeAttack(MAYUKO_SECOND_MELEE, chosen[0], seat)] if chosen else []


register_ability(
    "shinjo_mayuko_soul_of_shinjo_wei",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle: Dishonor Mayuko to make a Melee {MAYUKO_FIRST_MELEE}, then a Melee "
        f"{MAYUKO_SECOND_MELEE}",
        cost=_shinjo_mayuko_soul_of_shinjo_wei_cost,
        targets=attack_targets,
        effects=_shinjo_mayuko_soul_of_shinjo_wei_effects,
    ),
)


# Each prints the same entry. "Open: If you are an X Clan player, put this Edict into play."
# What they grant while in play has no handler yet.


# --- Way of the Akasha ---

register_entry("way_of_the_akasha", clears=keywords.EDICT, condition=plays_clan(ruleset.AKASHA))


# --- Way of the Crab (Experienced) ---

register_entry(
    "way_of_the_crab_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.CRAB)
)


# --- Way of the Crane (Experienced) ---

register_entry(
    "way_of_the_crane_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.CRANE)
)


# --- Way of the Dragon (Experienced) ---

register_entry(
    "way_of_the_dragon_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.DRAGON)
)


# --- Way of the Lion (Experienced) ---

register_entry(
    "way_of_the_lion_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.LION)
)


# --- Way of the Mantis (Experienced) ---

register_entry(
    "way_of_the_mantis_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.MANTIS)
)


# --- Way of the Phoenix (Experienced) ---

register_entry(
    "way_of_the_phoenix_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.PHOENIX)
)


# --- Way of the Scorpion (Experienced) ---

register_entry(
    "way_of_the_scorpion_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.SCORPION)
)


# --- Way of the Spider (Experienced) ---

register_entry(
    "way_of_the_spider_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.SPIDER)
)


# --- Way of the Unicorn (Experienced) ---

register_entry(
    "way_of_the_unicorn_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.UNICORN)
)


# --- Weapon Artist ---

FINE_SWORD = "weapon_item_sword_plus2f_plus1c"


def _weapon_artist_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Personalities with room for the sword. It is a One-Handed Weapon, so a Personality
    already carrying a Weapon has nowhere to put it."""
    sword = game.table.creatable_tokens[FINE_SWORD]
    return [target.id for target in creation_targets(game, source.owner, sword)]


def _weapon_artist_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [CreateToken(FINE_SWORD, source.owner, source.id, attach_to=target.id)]


register_ability(
    "weapon_artist",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: Bow to Equip a +2F/+1C One-Handed Sword to a Personality",
        cost=bow_cost,
        targets=_weapon_artist_targets,
        effects=_weapon_artist_effects,
    ),
)
