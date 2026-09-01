from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    bow_cost,
    itself,
    personalities_in_play,
    register_ability,
)
from yasuki_core.engine.rules.economy import (
    PlayerState,
    gold_handler,
    keyword_grant,
    recruit_discount,
    unit_gold_cost,
)
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    AskAmount,
    Banish,
    Choose,
    CreateToken,
    DelayedEffect,
    Effect,
    PayGold,
)
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.state import END_OF_TURN, GameState
from yasuki_core.engine.rules.legality import reachable_gold
from yasuki_core.engine.rules.triggers import (
    TriggerContext,
    choice_resolver,
    on,
    sincerity_seed_targets,
)
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import SINCERITY


# --- Sasada, Pearl Champion (Experienced) ---


SASADAS_OROCHI = "orochi_follower_2f"


@on(EnteredPlay, "sasada_pearl_champion_experienced")
def _sasada_pearl_champion_experienced_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After Sasada enters play, create and attach a 2F Orochi Follower to her."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [CreateToken(SASADAS_OROCHI, ctx.card.owner, ctx.card.id, attach_to=ctx.card.id)]


# --- Shrine of Courtesy ---


@recruit_discount("shrine_of_courtesy")
def _shrine_of_courtesy_recruit_discount(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]
) -> int:
    """Courtesy grants -3 Gold Cost while you are the second player (you did not go first)."""
    return 3 if me.went_second else 0


@keyword_grant("shrine_of_courtesy")
def _shrine_of_courtesy_keywords(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]
) -> tuple[str, ...]:
    """The same Courtesy clause grants Legacy, so a second player can search this Holding out."""
    return (keywords.LEGACY,) if me.went_second else ()


# --- Shrine of Sincerity ---


@gold_handler("shrine_of_sincerity")
def _shrine_of_sincerity_gold(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
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
        label="Bow: seed a Sincerity token onto a Province Sincerity card",
        cost=bow_cost,
        targets=_shrine_of_sincerity_targets,
        effects=_shrine_of_sincerity_effects,
    ),
)


# --- The Bad Death of Hida Daizu ---


def _the_bad_death_of_hida_daizu_amounts(game: GameState, source: L5RCard) -> tuple[int, ...]:
    """Every amount the seat could spend, from nothing up to what it can raise.

    The card reads "equal to or less than", so one amount reaches every unit at or under it and the
    same target is reachable at many amounts. Spending more than the target costs is legal and
    remains the seat's choice.

    A board with no Personality on it offers no amount at all: nothing there can be targeted, and a
    cost with no amount to choose is not payable (CR, Good Faith).
    """
    if not personalities_in_play(game):
        return ()
    return tuple(range(reachable_gold(game, source.owner) + 1))


def _the_bad_death_of_hida_daizu_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Settle the amount before the target is chosen: the amount is the cost block, and the legal
    targets are shaped by it (CR, Action Sequence steps B and C)."""
    return [
        AskAmount(
            source.owner,
            _the_bad_death_of_hida_daizu_amounts(game, source),
            "How much Gold do you spend on The Bad Death of Hida Daizu?",
            "the_bad_death_of_hida_daizu",
            source.id,
        )
    ]


@choice_resolver("the_bad_death_of_hida_daizu")
def _resolve_the_bad_death_of_hida_daizu(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Pay the amount, then choose among the Personalities it reaches.

    An amount below every unit's Gold Cost reaches no target: the Gold is spent in the cost step and
    the effects after it do not happen, because an effect that requires a target and cannot find one
    stops the effects that follow it (CR, Action Sequence step E).
    """
    paid = int(chosen[0])
    targets = tuple(
        card.id for card in personalities_in_play(game) if unit_gold_cost(game, card) <= paid
    )
    payment = PayGold(seat, paid, "The Bad Death of Hida Daizu")
    if not targets:
        return [payment]
    return [payment, Choose(seat, targets, 1, 1, "the_bad_death_of_hida_daizu_target", source_id)]


@choice_resolver(
    "the_bad_death_of_hida_daizu_target",
    prompt="Choose a Personality to banish at the end of the turn",
)
def _resolve_the_bad_death_of_hida_daizu_target(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The target stays in play until the turn ends, and the card banishes itself rather than
    reaching the discard through step F."""
    return [DelayedEffect(Banish(chosen[0]), END_OF_TURN), Banish(source_id)]


register_ability(
    "the_bad_death_of_hida_daizu",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: Spend Gold to banish a target Personality at the end of the turn",
        cost=_the_bad_death_of_hida_daizu_cost,
        targets=itself,
        effects=lambda game, source, target: [],
        all_targets=True,
        located_at=(CardLocation.HAND,),
    ),
)
