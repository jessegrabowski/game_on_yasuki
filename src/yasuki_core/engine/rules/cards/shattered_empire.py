from yasuki_core import ruleset
from yasuki_core.engine.rules.abilities import (
    Ability,
    InvestAbility,
    bow_cost,
    register_ability,
    register_edict,
    register_invest,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import CreateToken, Effect
from yasuki_core.engine.rules.equip import creation_targets
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Hida Sanjiro ---

SANJIROS_ARMOR = "armor_item_plus2f"


def _hida_sanjiro_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """A +2F Armor Item, made and worn as he arrives."""
    return [CreateToken(SANJIROS_ARMOR, source.owner, source.id, attach_to=source.id)]


register_invest("hida_sanjiro", InvestAbility(amounts=(2,), effect=_hida_sanjiro_invest))


# Each prints the same entry — "Open: If you are an X Clan player, put this Edict into play."
# What they grant while in play has no handler yet.


# --- Way of the Akasha ---

register_edict("way_of_the_akasha", clan=ruleset.AKASHA)


# --- Way of the Crab (Experienced) ---

register_edict("way_of_the_crab_experienced", clan=ruleset.CRAB)


# --- Way of the Crane (Experienced) ---

register_edict("way_of_the_crane_experienced", clan=ruleset.CRANE)


# --- Way of the Dragon (Experienced) ---

register_edict("way_of_the_dragon_experienced", clan=ruleset.DRAGON)


# --- Way of the Lion (Experienced) ---

register_edict("way_of_the_lion_experienced", clan=ruleset.LION)


# --- Way of the Mantis (Experienced) ---

register_edict("way_of_the_mantis_experienced", clan=ruleset.MANTIS)


# --- Way of the Phoenix (Experienced) ---

register_edict("way_of_the_phoenix_experienced", clan=ruleset.PHOENIX)


# --- Way of the Scorpion (Experienced) ---

register_edict("way_of_the_scorpion_experienced", clan=ruleset.SCORPION)


# --- Way of the Spider (Experienced) ---

register_edict("way_of_the_spider_experienced", clan=ruleset.SPIDER)


# --- Way of the Unicorn (Experienced) ---

register_edict("way_of_the_unicorn_experienced", clan=ruleset.UNICORN)


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
