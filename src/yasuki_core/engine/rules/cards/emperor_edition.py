from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.duel.procedure import duel_decided_by
from yasuki_core.engine.rules.effects import (
    AskOption,
    Choose,
    DelayedEffect,
    Destroy,
    Dishonor,
    DrawCard,
    Effect,
    Evaluate,
    GainHonor,
    StartDuel,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.conditions import condition_holds
from yasuki_core.engine.rules.stats.stat_grants import stat_grant
from yasuki_core.engine.rules.triggers import action_recruited, choice_resolver
from yasuki_core.engine.rules.turn.structure import DUEL_CONSEQUENCES
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Condition, Stat
from yasuki_core.game_pieces.cards import L5RCard


# --- Sanctioned Duel ---

SANCTIONED_DUEL_REFUSAL_HONOR = 2

# The refusal resolver's key, named so the bot policy and the card cannot drift apart. The
# decorator below spells it out, because the card-layout hook reads that argument statically.
SANCTIONED_DUEL_RESOLVER = "sanctioned_duel_refusal"

SANCTIONED_DUEL_REFUSE = "Refuse the challenge"
SANCTIONED_DUEL_ACCEPT = "Accept the challenge"


def _sanctioned_duel_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your unbowed Personalities, which the card targets as the challenger.

    None at all where no other seat has a Personality to be challenged. Both targets have to exist
    for the challenge to happen, and the second is picked after this one, so an ability offered on
    the challenger alone would resolve into a pick with nothing to pick.
    """
    personalities = personalities_in_play(game)
    if not any(card.owner is not source.owner for card in personalities):
        return []
    return [card.id for card in personalities if card.owner is source.owner and not card.bowed]


def _sanctioned_duel_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Having targeted the challenger, pick whom it challenges. One ability takes one target, so
    the challenged Personality is a pick of its own.

    Nothing at all where the last opposing Personality left between the announcement and here: the
    challenge does not happen, and a ``Choose`` of one from none would pend unanswerably.
    """
    challenged = tuple(
        card.id for card in personalities_in_play(game) if card.owner is not source.owner
    )
    if not challenged:
        return []
    return [
        Choose(
            seat=source.owner,
            candidates=challenged,
            minimum=1,
            maximum=1,
            resolver="sanctioned_duel_challenge",
            source_id=target.id,
            resolver_context=(source.id,),
        )
    ]


@choice_resolver("sanctioned_duel_challenge", prompt="Choose the Personality to challenge")
def _resolve_sanctioned_duel_challenge(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...] = (),
) -> list[Effect]:
    """Put the challenge to the challenged Personality's controller, who may refuse it (CR,
    Challenge). ``source_id`` is the challenger, picked as the card's target, and
    ``resolver_context`` carries the Strategy that is asking."""
    challenged = game.table.cards_by_id[chosen[0]]
    (strategy,) = resolver_context
    return [
        AskOption(
            seat=challenged.owner,
            options=(SANCTIONED_DUEL_REFUSE, SANCTIONED_DUEL_ACCEPT),
            question=f"{challenged.name} is challenged to a duel",
            resolver=SANCTIONED_DUEL_RESOLVER,
            source_id=strategy,
            resolver_context=(source_id, challenged.id),
        )
    ]


@choice_resolver("sanctioned_duel_refusal")
def _resolve_sanctioned_duel_refusal(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...] = (),
) -> list[Effect]:
    """A refused challenge creates no duel at all (CR, Challenge), so the refusal branch resolves
    as ordinary effects, with no duel for a consequence to wait on."""
    challenger, challenged = resolver_context
    # The answering seat is the challenged one, so every branch reads the acting seat off the
    # challenger instead: the Strategy is its controller's, and so is what the branch does.
    challenging_seat = game.table.cards_by_id[challenger].owner
    if chosen[0] == SANCTIONED_DUEL_REFUSE:
        return [
            Dishonor(challenged, challenging_seat),
            GainHonor(challenging_seat, SANCTIONED_DUEL_REFUSAL_HONOR),
        ]
    return [
        StartDuel(challenger, challenged, source_id),
        DelayedEffect(
            Evaluate("sanctioned_duel_loser", source_id, challenging_seat), DUEL_CONSEQUENCES
        ),
    ]


@choice_resolver("sanctioned_duel_loser")
def _resolve_sanctioned_duel_loser(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The loser is only known once the duel is decided, so the destruction is delayed to the
    duel's end and reads the outcome there. A duel both Personalities lost destroys both, and a
    challenge that did not happen destroys nobody rather than reading off the next duel to end."""
    duel = duel_decided_by(game, source_id)
    if duel is None:
        return []
    return [Destroy(duel.duelist_of(loser), seat) for loser in duel.outcome.losers]


register_ability(
    "sanctioned_duel",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_sanctioned_duel_targets,
        targeting_message="your unbowed Personality",
        effects=_sanctioned_duel_effects,
        located_at=(CardLocation.HAND,),
        keywords=frozenset({keywords.IAIJUTSU}),
    ),
)


# --- Togashi Korimi ---

TOGASHI_KORIMI_DEFENDING_FORCE = 2


# The Shattered Empire printing, "Response, :bow:: After you Recruit Korimi, draw a card." Its
# Emperor printing made the draw an optional trait on entry, and its Ivory printing an Interrupt.
@stat_grant("togashi_korimi")
def _togashi_korimi_stat_grant(game: GameState, source: L5RCard, card: L5RCard, stat: Stat) -> int:
    """Korimi has +2F while defending."""
    if stat is not Stat.FORCE or card is not source:
        return 0
    if not condition_holds(game, card, Condition.DEFENDING):
        return 0
    return TOGASHI_KORIMI_DEFENDING_FORCE


def _togashi_korimi_targets(game: GameState, source: L5RCard) -> list[str]:
    """Herself, once the action just resolved was her controller's and Recruited her."""
    if game.action_seat is not source.owner or not action_recruited(game, source.id):
        return []
    return [source.id]


def _togashi_korimi_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DrawCard(source.owner)]


register_ability(
    "togashi_korimi",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        cost=bow_cost,
        targets=_togashi_korimi_targets,
        effects=_togashi_korimi_effects,
        hits_every_target=True,
    ),
)
