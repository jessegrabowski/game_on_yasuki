from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import bow_cost, bow_parent_cost, no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import (
    ATTACK_TARGET,
    attack_targets,
    personalities_in_play,
)
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.units.membership import attached_to
from yasuki_core.engine.rules.stats.card_values import effective_chi
from yasuki_core.engine.rules.gold.discounts import recruit_discount
from yasuki_core.engine.rules.board.clans import is_clan
from yasuki_core.engine.rules.effects import (
    Choose,
    DelayedEffect,
    Destroy,
    Discard,
    Effect,
    Fear,
    GainHonor,
    GrantModifier,
    GrantPriority,
    MoveToHand,
    Show,
    ShuffleDeck,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.game_events import (
    CardFocused,
    DuelDeclared,
    DuelEnded,
    DuelResolved,
    FocusedCardsRevealed,
    FocusEffectsResolved,
    StrikeDeclared,
)
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.turn.structure import BEGINNING_OF_COMBAT
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import AttachmentPrint


# --- Fantastic Gardens ---

GARDENS_HONOR = 2


@recruit_discount("fantastic_gardens")
def _fantastic_gardens_recruit_discount(card: L5RCard, game: GameState, seat: PlayerId) -> int:
    """Enters play for 2 less Gold if you are a Crane Clan player."""
    return 2 if is_clan(game, seat, ruleset.CRANE) else 0


def _fantastic_gardens_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Gain 2 Honor."""
    return [GainHonor(source.owner, GARDENS_HONOR)]


register_ability(
    "fantastic_gardens",
    Ability(
        timings=(ActionTiming.LIMITED,),
        repeatable=True,
        cost=bow_cost,
        targets=itself,
        effects=_fantastic_gardens_effects,
        hits_every_target=True,
    ),
)


# --- Imperial Gift ---


def _imperial_gift_fate_deck_items(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The Items in ``seat``'s Fate deck. What the search may turn up."""
    return tuple(
        card.id
        for card in game.table.decks[DeckKey(seat, Side.FATE)].cards
        if isinstance(card.printed, AttachmentPrint)
        and card.printed.attachment_type is AttachmentType.ITEM
    )


@choice_resolver("imperial_gift_item", prompt="Search your Fate deck for an Item")
def _resolve_imperial_gift_item(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Show the Item to the table, put it in hand, then shuffle the deck the search read. The
    disclosure outlives the move: once the opponent has seen which Item was taken, hiding the card
    again does not unsay it."""
    return [
        Show(chosen[0]),
        MoveToHand(chosen[0], seat),
        ShuffleDeck(DeckKey(seat, Side.FATE)),
    ]


def _imperial_gift_targets(game: GameState, card: L5RCard) -> list[str]:
    """The Event itself. The honor is unconditional, so the ability is offered whether or not the
    Fate deck holds an Item. The search is a choice raised after it, not the ability's target."""
    return [card.id]


def _imperial_gift_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Gain 2 Honor, spend the Event, then search. The card offers no choice about taking what it
    finds, so the search is skipped only when the deck holds no Item at all."""
    seat = source.owner
    spent: list[Effect] = [GainHonor(seat, 2), Discard(source.id, seat)]
    items = _imperial_gift_fate_deck_items(game, seat)
    if not items:
        return spent
    return [*spent, Choose(seat, items, 1, 1, "imperial_gift_item", source.id)]


register_ability(
    "imperial_gift",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_imperial_gift_targets,
        effects=_imperial_gift_effects,
        hits_every_target=True,
        located_at=(CardLocation.PROVINCE,),
    ),
)


# --- Poisoned Weapon ---

POISONED_WEAPON_CHI = -3
POISONED_WEAPON_HONOR = -4


def _poisoned_weapon_after_focus_effects(game: GameState) -> bool:
    """Whether the duel has announced its Focus Effects resolved and has not yet been decided.

    The duel's steps announce themselves in order, so the latest one still standing in the turn's
    history is which step the duel is on. A window carries no identity of its own.
    """
    steps = (
        DuelDeclared,
        CardFocused,
        StrikeDeclared,
        FocusedCardsRevealed,
        FocusEffectsResolved,
        DuelResolved,
        DuelEnded,
    )
    latest = next((event for event in reversed(game.turn_events) if isinstance(event, steps)), None)
    return isinstance(latest, FocusEffectsResolved)


def _poisoned_weapon_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Personality facing yours in the duel, which the card names as "the other Personality"."""
    duel = game.duel_being_fought
    if duel is None or not _poisoned_weapon_after_focus_effects(game):
        return []
    mine = next((seat for seat in (duel.challenger, duel.challenged) if seat is source.owner), None)
    return [] if mine is None else [duel.duelist_of(duel.opponent_of(mine))]


def _poisoned_weapon_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The text gives the Chi loss no duration, so it lasts until the end of the turn (CR, Ongoing).

    Nothing here ends the duel. A Personality the Chi loss destroys leaves play, and the duel ends
    without resolution because a duelist left it, which is the rule the card's reminder restates.
    """
    return [
        GrantModifier(
            source_id=source.id,
            target_id=target.id,
            stat=Stat.CHI,
            amount=POISONED_WEAPON_CHI,
            duration=Duration.UNTIL_END_OF_TURN,
        ),
        GainHonor(source.owner, POISONED_WEAPON_HONOR),
    ]


register_ability(
    "poisoned_weapon",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        cost=no_cost,
        targets=_poisoned_weapon_targets,
        effects=_poisoned_weapon_effects,
        located_at=(CardLocation.HAND,),
        # "The other Personality in the duel" is not a target the player picks: the duel decides
        # which Personality it is, so the card hits it without asking.
        hits_every_target=True,
    ),
)


# --- Skeletal Troops ---

SKELETAL_TROOPS_HONOR_LOSS = 2
SKELETAL_TROOPS_FEAR = 3


@on(EnteredPlay, "skeletal_troops")
def _skeletal_troops_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Follower enters play, lose 2 Honor."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -SKELETAL_TROOPS_HONOR_LOSS, source_id=ctx.card.id)]


def _skeletal_troops_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Fear(SKELETAL_TROOPS_FEAR, target.id, source.owner)]


register_ability(
    "skeletal_troops",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_skeletal_troops_effects,
    ),
)


# --- Sneak Attack ---


def _sneak_attack_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Hand the Attacker the opportunity the Combat Segment would otherwise open on the Defender.

    An Engage action reaches a segment that has not started, so the grant is held until it does. It
    resolves at the next Combat Segment to open, which is this battle's. A held effect is spent
    when it fires, so it cannot reach the battle after.
    """
    return [DelayedEffect(GrantPriority(game.attack.attacker), BEGINNING_OF_COMBAT)]


register_ability(
    "sneak_attack",
    Ability(
        timings=(ActionTiming.ENGAGE,),
        cost=no_cost,
        targets=itself,
        effects=_sneak_attack_effects,
        hits_every_target=True,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Touch of Death ---


def _touch_of_death_targets(game: GameState, source: L5RCard) -> list[str]:
    """Bowed Personalities whose Chi does not exceed the Shugenja carrying this Spell.

    "Equal or lower" names no referent. The comparison is against the caster. The caster is never
    among these, since he has to be unbowed to pay the cost that bows him.
    """
    caster = attached_to(game, source)
    if caster is None:
        return []
    ceiling = effective_chi(game, caster)
    return [
        card.id
        for card in personalities_in_play(game)
        if card.bowed and effective_chi(game, card) <= ceiling
    ]


def _touch_of_death_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Destroy(target.id, source.owner), Destroy(source.id, source.owner)]


register_ability(
    "touch_of_death",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_parent_cost,
        targets=_touch_of_death_targets,
        targeting_message="a bowed Personality with equal or lower Chi",
        effects=_touch_of_death_effects,
    ),
)
