from collections.abc import Callable
from dataclasses import replace

from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import ability_for, register_ability
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.board.clans import is_clan
from yasuki_core.engine.rules.board.queries import favor_actions_this_turn, terrains_at
from yasuki_core.engine.rules.rulebook.copies import copy_may_enter
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
    AskOption,
    Choose,
    Destroy,
    Discard,
    Effect,
    GainHonor,
    GrantModifier,
    PutIntoPlay,
)
from yasuki_core.engine.rules.gold.discounts import unspent_action_discount
from yasuki_core.engine.rules.gold.producers import reachable_gold
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.engine.rules.vocabulary.game_events import ActionResolved, BattleResolved
from yasuki_core.ruleset import RingEntry, ring_entry
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH

# The key of the ability a Ring is discarded from hand to use.
PITCH = "pitch"
# The trait every Ring prints for its cast from hand, which is what a client shows for it.
RING_PITCH = "You may discard this Ring from your hand to use its ability without cost."


def plays_clan(clan: str) -> Callable[[GameState, L5RCard], bool]:
    """The entry condition "if you are a <clan> player", read from the owner's Stronghold."""

    def condition(game: GameState, source: L5RCard) -> bool:
        return is_clan(game, source.owner, clan)

    return condition


def register_entry(
    printed_id: str,
    *,
    timing: ActionTiming | tuple[ActionTiming, ...] = ActionTiming.OPEN,
    condition: Callable[[GameState, L5RCard], bool] | None = None,
    clears: str | None = None,
    extra_effects: Callable[[GameState, L5RCard], list[Effect]] | None = None,
    key: str | None = None,
    label: str | None = None,
    ability_keywords: frozenset[str] = frozenset(),
    ruleset: str | None = None,
) -> None:
    """Register ``printed_id``'s ability to put itself into play from hand.

    The shape every Edict, Kata and action-entry Ring prints: an ability taken from hand whose
    effect is the card entering play, with nothing to pay. Step F does not discard the card
    afterward because it is now in play (CR, Action Sequence).

    Parameters
    ----------
    printed_id : str
        The card's printed id.
    timing : ActionTiming or tuple of ActionTiming, optional
        The designators the entry is taken under, as in "Open/Dynasty". Default ``OPEN``.
    condition : callable, optional
        Maps ``(game, source_card)`` to whether the entry may be taken right now, for a card whose
        text opens with "If X". Default None, for a card anyone may put into play at any time.
    clears : str, optional
        A keyword whose other holders the owner controls are discarded as the card enters, as an
        Edict discards the owner's other Edicts (ShE datasheet, Edicts). Default None.
    extra_effects : callable, optional
        Maps ``(game, source_card)`` to effects resolved after the card enters, for a card whose
        entry prints a further clause. Default None.
    key : str, optional
        The ability's key, needed when the card prints another ability. Default None.
    label : str, optional
        What a client shows for the entry, when the card prints its entry as a trait rather than
        an ability. Default None, which shows the printed ability.
    ability_keywords : frozenset of str, optional
        The ability keywords the entry prints, as in "Political Open". Default empty.
    ruleset : str, optional
        The name of the one ruleset the entry is in force under, for a card whose text differs
        between arcs. Default None, for a text every arc reads.
    """
    timings = timing if isinstance(timing, tuple) else (timing,)

    def targets(game: GameState, source: L5RCard) -> list[str]:
        if not copy_may_enter(game, source.owner, source):
            return []
        if condition is not None and not condition(game, source):
            return []
        return [source.id]

    def cleared(game: GameState, source: L5RCard) -> list[str]:
        if clears is None:
            return []
        return [
            card.id
            for card in game.table.battlefield.cards
            if card.owner is source.owner
            and card.id != source.id
            and clears in effective_keywords(game, card)
        ]

    def effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
        return [
            PutIntoPlay(source.id),
            *(Discard(card_id, source.owner) for card_id in cleared(game, source)),
            *(extra_effects(game, source) if extra_effects is not None else ()),
        ]

    register_ability(
        printed_id,
        Ability(
            timings=timings,
            label=label,
            cost=no_cost,
            targets=targets,
            effects=effects,
            hits_every_target=True,
            located_at=(CardLocation.HAND,),
            key=key,
            keywords=ability_keywords,
            ruleset=ruleset,
        ),
    )


def register_ring(
    printed_id: str, *, ability: Ability, pitch: str | None, ruleset: str | None = None
) -> None:
    """Register a Ring's printed ability, and the cast that discards the Ring from hand to use it.

    A Ring's text may let its holder discard it from hand for an effect, normally to use the Ring's
    ability without cost (CR, Ring). That cast is the same ability again, taken from hand with
    nothing to pay, and step F discards the card because it is still in hand.

    Parameters
    ----------
    printed_id : str
        The Ring's printed id.
    ability : :class:`~yasuki_core.engine.rules.abilities.model.Ability`
        The ability as printed on the Ring in play. It needs a ``key`` when ``pitch`` is set,
        since the cast is a second ability on the card.
    pitch : str or None
        The trait letting the Ring be discarded from hand to use ``ability``, as the card prints
        it, which is what a client shows for the cast. None for a Ring that prints no such trait.
    ruleset : str, optional
        The name of the one ruleset both registrations are in force under, for a Ring whose text
        differs between arcs. Default None, for a text every arc reads.
    """
    register_ability(printed_id, replace(ability, ruleset=ruleset))
    if pitch:
        register_ability(
            printed_id,
            replace(
                ability,
                key=PITCH,
                label=pitch,
                cost=no_cost,
                located_at=(CardLocation.HAND,),
                ruleset=ruleset,
            ),
        )


# The key of the answer that puts a "Play after X" Ring into play.
TRAIT_ENTRY = "trait_entry"


@choice_resolver(TRAIT_ENTRY)
def _resolve_trait_entry(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [PutIntoPlay(card_id) for card_id in chosen]


def register_trait_entry(
    printed_id: str,
    event_type: type,
    guard: Callable[[TriggerContext], bool],
    *,
    ruleset: str | None = None,
) -> None:
    """Register ``printed_id``'s "Play after X" trait: from hand, when ``event_type`` fires and
    ``guard`` holds, its owner is asked whether to put it into play.

    The CR's Ring rule: the card may enter immediately after its condition is fulfilled, this may
    not be delayed, and the condition may be fulfilled more than once. So the question is asked
    each time the event fires with the guard holding, and declining leaves the card in hand for
    the next time.

    Parameters
    ----------
    printed_id : str
        The card's printed id.
    event_type : type
        The event whose resolution the text names.
    guard : callable
        Maps the trigger context to whether this firing fulfills the condition.
    ruleset : str, optional
        The name of the one ruleset the trait is in force under, for a card whose text differs
        between arcs. Default None, for a text every arc reads.
    """

    def entry(ctx: TriggerContext) -> list[Effect]:
        if ring_entry() is not RingEntry.IMMEDIATE:
            raise NotImplementedError(f"{ring_entry().name} Ring entry is not implemented")
        card = ctx.card
        if not guard(ctx) or not copy_may_enter(ctx.game, card.owner, card):
            return []
        question = f"Put {card.name} into play?"
        return [Ask(card.owner, question, TRAIT_ENTRY, subjects=(card.id,), source_id=card.id)]

    on(event_type, printed_id, where=(CardLocation.HAND,), ruleset=ruleset)(entry)


def resolved_favor_actions(at_least: int) -> Callable[[TriggerContext], bool]:
    """The guard for "Play after you resolve ``at_least`` or more Favor actions in one turn": the
    :class:`~.ActionResolved` firing is the owner's Favor action, and it brings the owner's count
    this turn to ``at_least``."""

    def guard(ctx: TriggerContext) -> bool:
        event = ctx.event
        if not isinstance(event, ActionResolved) or not event.favor:
            return False
        owner = ctx.card.owner
        return event.seat is owner and favor_actions_this_turn(ctx.game, owner) >= at_least

    return guard


def enemy_units_ever_present(event: BattleResolved, seat: PlayerId) -> bool:
    """Whether "any enemy units were ever at its battlefield" holds for ``seat``: a Personality
    of another seat's is on the battle's presence record."""
    return any(owner is not seat for owner, _ in event.ever_present)


def register_event_entry(
    printed_id: str,
    *,
    timing: ActionTiming = ActionTiming.OPEN,
    ability_keywords: frozenset[str] = frozenset(),
) -> None:
    """Register ``printed_id``'s "put this Event into play" action, taken from the Province it
    sits face-up in.

    Step F does not discard the card afterward because it is no longer where it was played from
    (CR, Action Sequence). The Province it vacates refills when the board settles, like any other.

    Parameters
    ----------
    printed_id : str
        The Event's printed id.
    timing : ActionTiming, optional
        The designator the entry is taken under. Default ``OPEN``, which most Events print.
    ability_keywords : frozenset of str, optional
        The ability keywords the entry prints, as in "Political Open". Default empty.
    """

    def targets(game: GameState, source: L5RCard) -> list[str]:
        return [source.id] if copy_may_enter(game, source.owner, source) else []

    def effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
        return [PutIntoPlay(source.id)]

    register_ability(
        printed_id,
        Ability(
            timings=(timing,),
            label=f"{timing.name.capitalize()}: Put this Event into play",
            cost=no_cost,
            targets=targets,
            effects=effects,
            hits_every_target=True,
            located_at=(CardLocation.PROVINCE,),
            keywords=ability_keywords,
        ),
    )


# The choice of which Terrain a Terrain entering play destroys, when more than one is there.
TERRAIN_ENTRY = "terrain_entry"


def _terrain_enters(game: GameState, source_id: str, destroyed: tuple[str, ...]) -> list[Effect]:
    """Destroy ``destroyed``, then put ``source_id`` into play at the battlefield being fought."""
    attack = game.attack
    assert attack is not None and attack.current is not None
    owner = game.table.cards_by_id[source_id].owner
    return [
        *(Destroy(card_id, cause=owner) for card_id in destroyed),
        PutIntoPlay(source_id, battlefield=attack.current),
    ]


@choice_resolver(TERRAIN_ENTRY, prompt="Choose a Terrain to destroy")
def _resolve_terrain_entry(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return _terrain_enters(game, source_id, destroyed=chosen)


def register_terrain(
    printed_id: str,
    *,
    timings: tuple[ActionTiming, ...] = (ActionTiming.BATTLE,),
    ability_keywords: frozenset[str] = frozenset(),
) -> None:
    """Register ``printed_id``'s "Battle: Destroy a Terrain (if able). Put this Terrain into play."

    Taken from hand during a battle. Its Terrain enters play at the current battlefield, standing
    in no unit there (CR, Terrain). The Terrain it destroys is its owner's pick when there is more
    than one to pick from, and none is no obstacle, since the destruction is only "if able".
    "A Terrain" is read as one at the current battlefield. Every Terrain is discarded when its own
    battle ends, so no other battlefield holds one.

    Parameters
    ----------
    printed_id : str
        The Terrain's printed id.
    timings : tuple of ActionTiming, optional
        The designators the entry is taken under, as in "Battle/Engage". Default ``BATTLE``.
    ability_keywords : frozenset of str, optional
        The ability keywords the entry prints, as in "Political Terrain Battle". Default empty.
    """

    def targets(game: GameState, source: L5RCard) -> list[str]:
        attack = game.attack
        if attack is None or attack.current is None:
            return []
        return [source.id] if copy_may_enter(game, source.owner, source) else []

    def effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
        attack = game.attack
        assert attack is not None and attack.current is not None
        standing = tuple(card.id for card in terrains_at(game, attack.current))
        if len(standing) > 1:
            return [
                Choose(
                    seat=source.owner,
                    candidates=standing,
                    minimum=1,
                    maximum=1,
                    resolver=TERRAIN_ENTRY,
                    source_id=source.id,
                )
            ]
        return _terrain_enters(game, source.id, destroyed=standing)

    register_ability(
        printed_id,
        Ability(
            timings=timings,
            cost=no_cost,
            targets=targets,
            effects=effects,
            hits_every_target=True,
            located_at=(CardLocation.HAND,),
            keywords=ability_keywords,
        ),
    )


def plus_one_gp_this_turn(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(source.id, target.id, Stat.GOLD_PRODUCTION, 1, Duration.UNTIL_END_OF_TURN)
    ]


def one_wealth(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 1)]


def declarable_gold(game: GameState, source: L5RCard, ability_key: str | None = None) -> int:
    """The largest amount ``source``'s controller can declare for the variable Gold cost of the
    ability ``ability_key`` names: what they can raise plus what their discount on it takes off.

    The declared amount is what the action reads, and a discount lowers only what is paid for it.
    The CR's own variable costs read the same way: Recruit matches the Gold Cost against the amount
    declared and charges the off-clan 2 Gold on top of it (CR, Recruit).
    """
    return reachable_gold(game, source.owner) + _unspent_discount(game, source, ability_key)


def _unspent_discount(game: GameState, source: L5RCard, ability_key: str | None) -> int:
    """The most the ability's discount could take off its variable amount: all of it, as though
    nothing else in the action had spent any. The cost's pricing trims what the seat cannot pay."""
    ability = ability_for(game, source, ability_key)
    if ability is None:
        return 0
    return unspent_action_discount(game, ability.purchase(game, source, plays_card=False))


def ask_who_loses_honor(game: GameState, seat: PlayerId, amount: int, source_id: str) -> AskOption:
    """The question "a target player loses N Honor" prints: name the player, the acting seat's
    call.

    Parameters
    ----------
    game : GameState
        The game, for the seats it may name.
    seat : PlayerId
        The seat naming the player.
    amount : int
        The N the card prints.
    source_id : str
        The card asking, carried to the resolver.
    """
    return AskOption(
        seat,
        tuple(info.name for info in game.table.seats.values()),
        f"Who loses {amount} Honor?",
        "honor_loss_player",
        source_id,
        resolver_context=(str(amount),),
    )


@choice_resolver("honor_loss_player")
def _resolve_honor_loss_player(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...] = (),
) -> list[Effect]:
    named = next(player for player, info in game.table.seats.items() if info.name == chosen[0])
    return [GainHonor(named, -int(resolver_context[0]), source_id=source_id)]


def ask_whose_honor_moves(
    game: GameState, seat: PlayerId, amount: int, source_id: str
) -> AskOption:
    """The question "a target player gains or loses N Honor" prints: name the player, then the
    direction, both the acting seat's call.

    Parameters
    ----------
    game : GameState
        The game, for the seats it may name.
    seat : PlayerId
        The seat answering both questions.
    amount : int
        The N the card prints.
    source_id : str
        The card asking, carried to the resolvers.
    """
    return AskOption(
        seat,
        tuple(info.name for info in game.table.seats.values()),
        "Whose Honor moves?",
        "honor_swing_player",
        source_id,
        resolver_context=(str(amount),),
    )


@choice_resolver("honor_swing_player")
def _resolve_honor_swing_player(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...] = (),
) -> list[Effect]:
    named = chosen[0]
    picked = next(player for player, info in game.table.seats.items() if info.name == named)
    amount = int(resolver_context[0])
    return [
        AskOption(
            seat,
            (f"Gain {amount} Honor", f"Lose {amount} Honor"),
            f"Does {named} gain or lose {amount} Honor?",
            "honor_swing",
            source_id,
            resolver_context=(picked.name, str(amount)),
        )
    ]


@choice_resolver("honor_swing")
def _resolve_honor_swing(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...] = (),
) -> list[Effect]:
    moved = PlayerId[resolver_context[0]]
    amount = int(resolver_context[1])
    delta = amount if chosen[0].startswith("Gain") else -amount
    return [GainHonor(moved, delta, source_id=source_id)]
