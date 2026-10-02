from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import bow_cost
from yasuki_core.engine.rules.abilities.idioms import (
    declarable_gold,
    declare_amount,
    register_event_entry,
)
from yasuki_core.engine.rules.abilities.model import (
    Ability,
    CardLocation,
    Interrupt,
    Interruption,
)
from yasuki_core.engine.rules.abilities.registry import register_ability, register_interrupt
from yasuki_core.engine.rules.board.queries import owned_personalities, personalities_in_play
from yasuki_core.engine.rules.stats.card_values import effective_chi
from yasuki_core.engine.rules.stats.keyword_grants import keyword_grant
from yasuki_core.engine.rules.gold.cost import unit_gold_cost
from yasuki_core.engine.rules.gold.discounts import recruit_discount
from yasuki_core.engine.rules.gold.production import gold_handler
from yasuki_core.engine.rules.board.seats import went_second
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    AskOption,
    Banish,
    Bow,
    CreateToken,
    DelayedEffect,
    Destroy,
    Effect,
    Move,
    MoveToDeck,
    Negated,
    ShuffleDeck,
    Unpayable,
)
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.rulebook.recruit import proclaim_gain
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import END_OF_TURN
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.engine.rules.board.queries import sincerity_seed_targets
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.table import DeckKey, Location, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import FIRE, SINCERITY, Counter, counter_from_key


# --- Decree of the Hantei ---

register_event_entry("decree_of_the_hantei", ability_keywords=frozenset({keywords.POLITICAL}))


# --- Ninube Aitso, "Doji Yeiko" (Experienced) ---

AITSO_PROCLAIM = 3


@proclaim_gain("ninube_aitso_doji_yeiko_experienced")
def _ninube_aitso_doji_yeiko_experienced_proclaim_gain(game: GameState, card: L5RCard) -> int:
    """When Proclaiming Aitso, you may gain 3 Honor instead of her Personal Honor."""
    return AITSO_PROCLAIM


def _ninube_aitso_doji_yeiko_experienced_applies(
    game: GameState, source: L5RCard, effect: Destroy
) -> bool:
    target = game.table.cards_by_id.get(effect.card_id)
    return target is not None and target in owned_personalities(game, source.owner)


def _ninube_aitso_doji_yeiko_experienced_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Reshuffle Aitso into her owner's Dynasty deck."""
    deck = DeckKey(source.owner, Side.DYNASTY)
    return [MoveToDeck(source.id, deck, from_top=0), ShuffleDeck(deck)]


def _ninube_aitso_doji_yeiko_experienced_interrupt(
    game: GameState, source: L5RCard, effect: Destroy
) -> Interruption:
    return Interruption(Negated(effect))


register_interrupt(
    "ninube_aitso_doji_yeiko_experienced",
    Interrupt(
        answers=Destroy,
        interrupt=_ninube_aitso_doji_yeiko_experienced_interrupt,
        applies=_ninube_aitso_doji_yeiko_experienced_applies,
        located_at=(CardLocation.BATTLEFIELD,),
        cost=_ninube_aitso_doji_yeiko_experienced_cost,
    ),
)


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
def _shrine_of_courtesy_recruit_discount(card: L5RCard, game: GameState, seat: PlayerId) -> int:
    """Courtesy grants -3 Gold Cost while you are the second player (you did not go first)."""
    return 3 if went_second(game, seat) else 0


@keyword_grant("shrine_of_courtesy")
def _shrine_of_courtesy_keywords(card: L5RCard, game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The same Courtesy clause grants Legacy, so a second player can search this Holding out."""
    return (keywords.LEGACY,) if went_second(game, seat) else ()


# --- Shrine of Sincerity ---


@gold_handler("shrine_of_sincerity")
def _shrine_of_sincerity_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
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
        cost=bow_cost,
        targets=_shrine_of_sincerity_targets,
        targeting_message="a Sincerity card in your Province",
        effects=_shrine_of_sincerity_effects,
    ),
)


# --- The Bad Death of Hida Daizu ---


def _the_bad_death_of_hida_daizu_amounts(game: GameState, source: L5RCard) -> tuple[int, ...]:
    """Every amount the seat could spend, from nothing up to what it can declare.

    The card reads "equal to or less than", so one amount reaches every unit at or under it and the
    same target is reachable at many amounts. Spending more than the target costs is legal and
    remains the seat's choice.

    A board with no Personality on it offers no amount at all: nothing there can be targeted, and a
    cost with no amount to choose is not payable (CR, Good Faith).
    """
    if not personalities_in_play(game):
        return ()
    return tuple(range(declarable_gold(game, source) + 1))


def _the_bad_death_of_hida_daizu_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """The amount is the cost block, settled before the target is chosen, since the legal targets
    are shaped by it (CR, Action Sequence steps B and C)."""
    return [
        declare_amount(
            source,
            _the_bad_death_of_hida_daizu_amounts(game, source),
            "How much Gold do you spend on The Bad Death of Hida Daizu?",
        )
    ]


def _the_bad_death_of_hida_daizu_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Personalities whose unit costs no more than the amount paid. An amount below every unit
    reaches none, and the card does nothing more (CR, Action Sequence step E)."""
    if game.amount_paid is None:
        return []
    return [
        card.id
        for card in personalities_in_play(game)
        if unit_gold_cost(game, card) <= game.amount_paid
    ]


def _the_bad_death_of_hida_daizu_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """The target stays in play until the turn ends, and the card banishes itself rather than
    reaching the discard through step F."""
    return [DelayedEffect(Banish(target.id), END_OF_TURN), Banish(source.id)]


register_ability(
    "the_bad_death_of_hida_daizu",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=_the_bad_death_of_hida_daizu_cost,
        targets=_the_bad_death_of_hida_daizu_targets,
        effects=_the_bad_death_of_hida_daizu_effects,
        located_at=(CardLocation.HAND,),
        targeting_message="a Personality to banish at the end of the turn",
        targets_after_cost=True,
    ),
)


# --- Togashi Noritada, Defender of the High House (Experienced) ---

NORITADA_MOVE_HOME = "Move Noritada home"


@on(EnteredPlay, "togashi_noritada_defender_of_the_high_house_experienced")
def _togashi_noritada_defender_of_the_high_house_experienced_entered_play(
    ctx: TriggerContext,
) -> list[Effect]:
    """Sincerity: Give Noritada a +1F Fire token for each token removed."""
    if ctx.event.card_id != ctx.card.id:
        return []
    sincerity = ctx.card.counters.get(SINCERITY.key, 0)
    if sincerity == 0:
        return []
    return [AdjustCounter(ctx.card.id, FIRE, sincerity)]


def _togashi_noritada_defender_of_the_high_house_experienced_destroy_options(
    noritada: L5RCard,
) -> dict[str, Counter]:
    """Each token Noritada holds, keyed by the option that destroys one of it."""
    held = (counter_from_key(key) for key, count in sorted(noritada.counters.items()) if count > 0)
    return {f"Destroy one of his {counter.name} tokens": counter for counter in held}


def _togashi_noritada_defender_of_the_high_house_experienced_cost(
    game: GameState, source: L5RCard
) -> list[Effect]:
    """Ask to move Noritada home or destroy one of his tokens, offering only what he can pay."""
    options = list(_togashi_noritada_defender_of_the_high_house_experienced_destroy_options(source))
    if not location_of(game.table, source).is_home:
        options.insert(0, NORITADA_MOVE_HOME)
    if not options:
        return [Unpayable("Noritada is home and holds no tokens")]
    question = "Move Noritada home, or destroy one of his tokens?"
    return [AskOption(source.owner, tuple(options), question, "togashi_noritada_cost", source.id)]


@choice_resolver("togashi_noritada_cost")
def _resolve_togashi_noritada_cost(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    noritada = game.table.cards_by_id[source_id]
    if chosen[0] == NORITADA_MOVE_HOME:
        return [Move(source_id, Location.home(noritada.owner))]
    options = _togashi_noritada_defender_of_the_high_house_experienced_destroy_options(noritada)
    return [AdjustCounter(source_id, options[chosen[0]], -1)]


def _togashi_noritada_defender_of_the_high_house_experienced_targets(
    game: GameState, source: L5RCard
) -> list[str]:
    """Enemy Personalities with lower Chi than Noritada."""
    chi = effective_chi(game, source)
    return [
        card.id
        for card in personalities_in_play(game)
        if card.owner is not source.owner and effective_chi(game, card) < chi
    ]


def _togashi_noritada_defender_of_the_high_house_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [Bow(target.id)]


register_ability(
    "togashi_noritada_defender_of_the_high_house_experienced",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=_togashi_noritada_defender_of_the_high_house_experienced_cost,
        targets=_togashi_noritada_defender_of_the_high_house_experienced_targets,
        targeting_message="an enemy Personality with lower Chi",
        effects=_togashi_noritada_defender_of_the_high_house_experienced_effects,
    ),
)
