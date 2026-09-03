from collections.abc import Callable

from yasuki_core import ruleset
from yasuki_core.engine.players import Rulebook
from yasuki_core.engine.rules.economy import effective_chi
from yasuki_core.engine.rules.effects import Destroy, Discard, Effect, LoseGame, WinGame
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.victory import VictoryRule
from yasuki_core.engine.table import ZoneRole
from yasuki_core.game_pieces.prints import AttachmentPrint, PersonalityPrint

# A state rule reads the board and returns the effects the rules demand of it. Unlike a trigger it
# answers to no event: the CR states these as conditions that hold at all times rather than as
# consequences of something happening, so a rule fires however the board came to break it. The
# Chi Death Rule is the one modeled here; a seat losing its last Province, a seat controlling five
# Rings of different elements, and a destroyed Province ending its battlefield are the same shape.
StateRule = Callable[[GameState], list[Effect]]

# The cards whose own text exempts them from the Chi Death Rule, by printed id. Each says so
# plainly — "Stone Breaker will not be destroyed for having 0 Chi" — which the CR permits as a
# continuous effect. Listed here rather than registered from the set modules because it is data
# about a card rather than behavior; it belongs on the print, alongside the Chi it qualifies.
#
# Two cards that mention 0 Chi are deliberately absent. Moto Chagatai and Moto Soro read "unless
# his Chi is 0 after all penalties that last until your turn ends wear off" — a deferred check
# this rule cannot express, so they take the rule as written rather than a wrong exemption. Shuten
# Doji asks for a window before the destruction, which is a replacement rather than an exemption.
CHI_DEATH_EXEMPT: frozenset[str] = frozenset(
    {
        "bayushi_baku",
        "corpse_monstrosity",
        "daigotsu_endo",
        "earthen_golem",
        "hida_kanjouteki_experienced",
        "stone_breaker",
        "the_cursed_dead",
    }
)


def chi_death(game: GameState) -> list[Effect]:
    """Destroy every Personality in play whose Chi is zero (CR, Chi Death Rule).

    Zero is the whole condition: the stat floors there, so a Personality penalised past zero reads
    zero and dies. A card whose own text exempts it is skipped, which the CR permits because that
    text is a continuous effect and only those work against Chi death.
    """
    return [
        Destroy(card.id, Rulebook.CHI_DEATH)
        for card in game.table.battlefield.cards
        if isinstance(card.printed, PersonalityPrint)
        and effective_chi(game, card) == 0
        and not _exempt_from_chi_death(card)
    ]


def _exempt_from_chi_death(card: L5RCard) -> bool:
    """Whether ``card``'s own text spares it the Chi Death Rule."""
    return card.printed_id in CHI_DEATH_EXEMPT


def orphaned_attachments(game: GameState) -> list[Effect]:
    """Discard every attachment in play that is attached to no Personality (CR, Attachments).

    A Follower, Item or Spell exists in play only as part of a unit, so one left on the battlefield
    without a Personality is not a board state the rules allow. The destruction cascade already takes
    a unit with its Personality; this catches every other route by which a card comes loose.
    """
    # No card is spared this yet. Street to Street will be the first: it detaches every Follower at a
    # battlefield and leaves them in play "though not in units" until the Terrain goes or the Combat
    # Segment ends. That is a granted, time-bounded suspension of the rule rather than a property of
    # a card, so it needs a duration vocabulary this layer does not have, and it needs battle.
    return [
        Discard(card.id, Rulebook.ORPHANED_ATTACHMENT)
        for card in game.table.battlefield.cards
        if isinstance(card.printed, AttachmentPrint) and card.id not in game.table.units
    ]


def lost_last_province(game: GameState) -> list[Effect]:
    """Lose the game for a seat with no Provinces remaining (CR, Military Loss/Victory).

    The CR loses it immediately rather than at any particular step, so a Province destroyed by a
    card ends the game exactly as one destroyed by an army does.

    Only seats held to :attr:`~yasuki_core.engine.rules.victory.VictoryRule.MILITARY_LOSS` lose
    this way, which is what excuses a seat a card has spared and a board that was never dealt
    Provinces to lose.
    """
    if game.loser is not None:
        return []
    holders = {key.owner for key in game.table.zones if key.role is ZoneRole.PROVINCE}
    return [
        LoseGame(seat, "no Provinces remaining", "Military Victory")
        for seat, rules in game.active_rules.items()
        if VictoryRule.MILITARY_LOSS in rules and seat not in holders
    ]


# The rulebook's own list, in the order they are checked.
STATE_RULES: tuple[StateRule, ...] = (chi_death, orphaned_attachments, lost_last_province)


def demanded(game: GameState) -> list[Effect]:
    """What the rules demand of the board as it stands, or an empty list when it is already legal."""
    return [effect for rule in STATE_RULES for effect in rule(game)]


# The two victory conditions the CR states at a moment in the turn rather than as a condition that
# holds at all times, so neither belongs in STATE_RULES: a seat may pass through the Honor Victory
# threshold mid-turn and be back below it by the time its next turn starts, and that is not a win.
# The flow calls each at the boundary it names.
def honor_victory(game: GameState) -> list[Effect]:
    """Win the game for the seat starting its turn on the Honor Victory threshold or higher (CR,
    Honor Victory).

    Only the seat whose turn is starting can win this way, and only if it is still held to
    :attr:`~yasuki_core.engine.rules.victory.VictoryRule.HONOR_VICTORY` — a seat Kaede Sensei has
    excused starts the same turn on the same Honor and does not win.
    """
    if game.game_over:
        return []
    seat = game.active
    if VictoryRule.HONOR_VICTORY not in game.active_rules.get(seat, frozenset()):
        return []
    honor = game.table.seats[seat].honor
    if honor < ruleset.ACTIVE.honor_victory_at:
        return []
    return [WinGame(seat, f"Honor Victory on {honor} Family Honor")]


def dishonor_loss(game: GameState) -> list[Effect]:
    """Lose the game for the seat ending its turn at or below the Dishonor threshold (CR, Dishonor
    Loss/Victory), which wins the other seat a Dishonor Victory.

    Only the seat whose turn is ending is checked, so a seat driven below the threshold on its
    opponent's turn has its own turn to climb back out.
    """
    if game.game_over:
        return []
    seat = game.active
    if VictoryRule.DISHONOR_LOSS not in game.active_rules.get(seat, frozenset()):
        return []
    honor = game.table.seats[seat].honor
    if honor > ruleset.ACTIVE.dishonor_loss_at:
        return []
    return [LoseGame(seat, f"{honor} Family Honor", "Dishonor Victory")]
