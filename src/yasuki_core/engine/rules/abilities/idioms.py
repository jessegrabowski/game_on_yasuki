from collections.abc import Callable
from dataclasses import replace

from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.board.clans import is_clan
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    AskOption,
    Discard,
    Effect,
    GainHonor,
    GrantModifier,
    PutIntoPlay,
)
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH

# The key of the ability a Ring is discarded from hand to use.
PITCH = "pitch"


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
        What a client shows for the entry. Default names the designators and ``clears``.
    ability_keywords : frozenset of str, optional
        The ability keywords the entry prints, as in "Political Open". Default empty.
    """
    timings = timing if isinstance(timing, tuple) else (timing,)

    def targets(game: GameState, source: L5RCard) -> list[str]:
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

    if label is None:
        designators = "/".join(held.name.capitalize() for held in timings)
        label = f"{designators}: Put this {clears or 'card'} into play"
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
        ),
    )


def register_ring(
    printed_id: str, *, ability: Ability, pitch: bool, ruleset: str | None = None
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
    pitch : bool
        Whether the Ring may be discarded from hand to use ``ability``.
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
                label=f"Discard from hand: {ability.label}",
                cost=no_cost,
                located_at=(CardLocation.HAND,),
                ruleset=ruleset,
            ),
        )


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

    def effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
        return [PutIntoPlay(source.id)]

    register_ability(
        printed_id,
        Ability(
            timings=(timing,),
            label=f"{timing.name.capitalize()}: Put this Event into play",
            cost=no_cost,
            targets=itself,
            effects=effects,
            hits_every_target=True,
            located_at=(CardLocation.PROVINCE,),
            keywords=ability_keywords,
        ),
    )


def plus_one_gp_this_turn(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(source.id, target.id, Stat.GOLD_PRODUCTION, 1, Duration.UNTIL_END_OF_TURN)
    ]


def one_wealth(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 1)]


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
    return [GainHonor(named, -int(resolver_context[0]))]


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
    return [GainHonor(moved, delta)]
