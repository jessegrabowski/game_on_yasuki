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
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH


def register_edict(
    printed_id: str, *, clan: str | None = None, ability_keywords: frozenset[str] = frozenset()
) -> None:
    """Register ``printed_id``'s Open ability to put itself into play as an Edict.

    Every Edict prints the same action (put this into play, discard your other Edicts), so it is
    registered rather than written out per card. Discarding the others is the rulebook's own limit
    of one Edict at a time restated on the card (ShE datasheet, Edicts).

    Parameters
    ----------
    printed_id : str
        The Edict's printed id.
    clan : str, optional
        A clan its controller must be playing, for the Edicts that name one. Default None, for an
        Edict anyone may put into play.
    ability_keywords : frozenset of str, optional
        The ability keywords the entry prints, as in "Political Open". Default empty.
    """

    def targets(game: GameState, source: L5RCard) -> list[str]:
        if clan is not None and not is_clan(game, source.owner, clan):
            return []
        return [source.id]

    def effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
        others = [
            card.id
            for card in game.table.battlefield.cards
            if card.owner is source.owner
            and card.id != source.id
            and keywords.EDICT in effective_keywords(game, card)
        ]
        return [
            PutIntoPlay(source.id),
            *(Discard(card_id, source.owner) for card_id in others),
        ]

    register_ability(
        printed_id,
        Ability(
            timings=(ActionTiming.OPEN,),
            label="Open: Put this Edict into play",
            cost=no_cost,
            targets=targets,
            effects=effects,
            hits_every_target=True,
            located_at=(CardLocation.HAND,),
            keywords=ability_keywords,
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
