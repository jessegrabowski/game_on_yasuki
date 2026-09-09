from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.board.clans import is_clan
from yasuki_core.engine.rules.keyword_grants import effective_keywords
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Discard,
    Effect,
    GrantModifier,
    PutIntoPlay,
)
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH


def register_edict(printed_id: str, *, clan: str | None = None) -> None:
    """Register ``printed_id``'s Open ability to put itself into play as an Edict.

    Every Edict prints the same action — put this into play, discard your other Edicts — so it is
    registered rather than written out per card. Discarding the others is the rulebook's own limit
    of one Edict at a time restated on the card (ShE datasheet, Edicts).

    Parameters
    ----------
    printed_id : str
        The Edict's printed id.
    clan : str, optional
        A clan its controller must be playing, for the Edicts that name one. Default None, for an
        Edict anyone may put into play.
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
        ),
    )


def register_event_entry(printed_id: str, *, timing: ActionTiming = ActionTiming.OPEN) -> None:
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
        ),
    )


def plus_one_gp_this_turn(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(source.id, target.id, Stat.GOLD_PRODUCTION, 1, Duration.UNTIL_END_OF_TURN)
    ]


def one_wealth(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 1)]
