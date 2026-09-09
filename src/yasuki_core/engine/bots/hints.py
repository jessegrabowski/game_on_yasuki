from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from yasuki_core.engine.bots.queries import (
    best_production,
    identifiable,
    in_play,
    newly_affordable,
    production,
    rank,
    readable_province_cards,
    spendable,
)
from yasuki_core.engine.rules.vocabulary.decisions import ChooseAbilityTarget, ChooseCards
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.rules.registrar import HandlerRegistry
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard


@dataclass(frozen=True)
class AbilityHint:
    """What a policy needs to play one card's activated ability.

    Attributes
    ----------
    worth_activating : callable
        Answers, from the view and the card, whether taking the ability now is worth what it costs.
    best_target : callable, optional
        Answers, from the view and the pending :class:`ChooseAbilityTarget`, which candidate to hit.
        Default None, which takes the first candidate as a generic agent would.
    optional_cost_answers : mapping of str to callable, optional
        Answers, per choice resolver, whether to pay an optional cost the resolution offers. Keyed
        by resolver rather than by card because the request carries the card the cost is paid *for*,
        not the card charging it. Default empty, offering no answer.
    """

    worth_activating: Callable[[GameView, L5RCard], bool]
    best_target: Callable[[GameView, ChooseAbilityTarget], str] | None = None
    optional_cost_answers: Mapping[str, Callable[[GameView, ChooseCards], bool]] = field(
        default_factory=dict
    )


# The activated abilities a policy has an economic model for, by printed id. An ability absent here
# is never activated: a policy cannot read what a card does, and guessing at an unmodelled one would
# spend a bow on an effect it has no way to value.
ABILITY_HINTS: HandlerRegistry[AbilityHint] = HandlerRegistry(
    "ability hints", "already has an ability hint"
)
_record_hint = ABILITY_HINTS.make_register()

# The optional-cost answers of every registered hint, by resolver. Indexed here rather than
# searched at decision time because a resolver names one card's cost: two hints claiming it is a
# typo in one of them, and the scan that finds the first would answer the other's cost silently.
_OPTIONAL_COST_ANSWERS: dict[str, Callable[[GameView, ChooseCards], bool]] = {}


def register_ability_hint(printed_id: str, hint: AbilityHint) -> None:
    """Record ``hint`` for ``printed_id``, and its optional-cost answers by resolver.

    Raise ValueError if the card already has a hint, or if another card already answers one of the
    resolvers this one claims. A refused registration records neither half.
    """
    for resolver in hint.optional_cost_answers:
        if resolver in _OPTIONAL_COST_ANSWERS:
            raise ValueError(f"{resolver} already has an optional cost answer")
    _record_hint(printed_id, hint)
    _OPTIONAL_COST_ANSWERS.update(hint.optional_cost_answers)


def optional_cost_answer(resolver: str) -> Callable[[GameView, ChooseCards], bool] | None:
    """The hint answering the optional cost ``resolver`` offers, or None when no card claims it."""
    return _OPTIONAL_COST_ANSWERS.get(resolver)


# How much more a non-Farm target must produce than the Modest Farm spent to reach it, before the
# chain is worth the face-down Province refill that recruiting a non-Farm costs.
CHAIN_PAYOFF_RATIO = 3


def _modest_farm_worth_activating(view: GameView, source: L5RCard) -> bool:
    """Whether Modest Farm should recruit out of sequence now.

    Nothing caps how many cards a seat recruits in its Dynasty Phase, so an out-of-sequence recruit
    is not an extra purchase on its own — the turn's production bounds the spending either way, and
    Modest Farm bows itself out of that production to grant it. Two things do pay for it, and one
    of them has to be true of some Holding the seat can still reach once that yield is gone.

    A Farm target is granted Renew, which refills the vacated Province face-up. Any other target
    refills it face-down, leaving the seat choosing from three live Provinces for the rest of the
    turn — a real cost, and one only a payoff elsewhere covers.

    That payoff is the chain. Destroying Modest Farm straightens the card it just recruited, so a
    big producer is spendable the moment it lands; when that Gold reaches a second producer the seat
    could not otherwise pay for, the recruit funds the recruit after it. Both halves are demanded of
    the chain — a target worth :data:`CHAIN_PAYOFF_RATIO` times the Farm being spent, and a producer
    on the other side of it. Firing on any purchase at all costs more in face-down refills than the
    chain returns.
    """
    reach = spendable(view) - production(view, source)
    cards = readable_province_cards(view)
    for card in cards.values():
        cost = view.stat(card, Stat.GOLD_COST)
        if not card.face_up or cost > reach:
            continue
        if keywords.FARM in card.keywords:
            return True
        if production(view, card) < CHAIN_PAYOFF_RATIO * max(production(view, source), 1):
            continue
        left = reach - cost
        if any(
            other.face_up
            and other.id != card.id
            and production(view, other) > 0
            and left < view.stat(other, Stat.GOLD_COST) <= left + production(view, card)
            for other in cards.values()
        ):
            return True
    return False


def _modest_farm_best_target(view: GameView, request: ChooseAbilityTarget) -> str:
    """A Farm ahead of anything else, because only a Farm target is granted the Renew that refills
    the vacated Province face-up. Among equals it ranks them as purchases."""
    cards = identifiable(view)
    return min(
        request.candidates,
        key=lambda card_id: (
            keywords.FARM not in cards[card_id].keywords,
            rank(view, cards[card_id]),
        ),
    )


def _modest_farm_worth_sacrificing(view: GameView, request: ChooseCards) -> bool:
    """Whether to destroy Modest Farm to straighten the card it just recruited.

    Modest Farm is an engine rather than a producer: it straightens every turn its owner's turn
    begins, and each straightening is another out-of-sequence recruit. Trading that for one turn of
    the target being straight is only worth it when that turn buys something — the recruit enters
    play bowed, so straightening it is worth exactly the Gold it could still raise this turn.

    Taken when that Gold puts a Province card in reach that is out of it, and declined otherwise,
    which keeps the engine.
    """
    target = identifiable(view).get(request.source_id or "")
    if target is None:
        return False
    before = spendable(view)
    return newly_affordable(view, before, before + production(view, target))


# The Gold Production Millet Farm grants a Farm for the turn.
MILLET_FARM_BOOST = 2


def _millet_farm_worth_activating(view: GameView, source: L5RCard) -> bool:
    """Whether Millet Farm should grant its Farm bonus now.

    The grant lasts until end of turn and Millet Farm bows itself to give it, so the seat nets
    :data:`MILLET_FARM_BOOST` less whatever Millet Farm would have yielded — and only on a Farm
    still straight enough to be bowed for it. Taken when that net puts a Province card in reach
    that is out of it, and declined otherwise: an unspent bonus expires at end of turn.
    """
    straight_farms = any(
        card.id != source.id and not card.bowed and keywords.FARM in card.keywords
        for card in in_play(view)
    )
    if not straight_farms:
        return False
    before = spendable(view)
    return newly_affordable(view, before, before - production(view, source) + MILLET_FARM_BOOST)


def _harvested_land_worth_activating(view: GameView, source: L5RCard) -> bool:
    """Whether Harvested Land should spend itself to raise the other Farms.

    It bows and destroys itself to give every other Farm +1 Gold Production for the turn, so the
    seat trades this Holding's whole yield for one Gold per Farm it can still bow. A bowed Farm has
    already been spent and collects nothing, which is what makes the count smaller than the board
    suggests. Taken when the net puts a Province card in reach that is out of it.
    """
    raised = sum(
        1
        for card in in_play(view)
        if card.id != source.id and not card.bowed and keywords.FARM in card.keywords
    )
    before = spendable(view)
    return newly_affordable(view, before, before + raised - production(view, source))


def _rural_market_worth_activating(view: GameView, source: L5RCard) -> bool:
    """Whether Rural Market should spend a Wealth token to straighten a Farm.

    A straightened Farm can be bowed for its yield again this turn, and the token that buys it is
    one Gold off Rural Market's own production — but only while Rural Market is still straight
    enough to be bowed for that Gold. It is Tireless, so paying costs it no bow of its own.
    """
    bowed_farms = [card for card in in_play(view) if card.bowed and keywords.FARM in card.keywords]
    if not bowed_farms:
        return False
    before = spendable(view)
    token = 0 if source.bowed else 1
    return newly_affordable(view, before, before + best_production(view, bowed_farms) - token)


def _largest_producer(view: GameView, request: ChooseAbilityTarget) -> str:
    """The candidate whose straightening raises the most Gold: the largest producer, then the id."""
    cards = identifiable(view)
    return min(
        request.candidates,
        key=lambda card_id: (-production(view, cards[card_id]), card_id),
    )


def _ichiba_district_worth_activating(view: GameView, source: L5RCard) -> bool:
    """Whether Ichiba District should banish a card to raise a Port.

    The cost is the top card of the Fate deck rather than any Gold, and these policies price a card
    at nothing, so the only question is whether the Gold arrives somewhere it can be spent from. A
    bowed Port has already produced and cannot be bowed again, so the grant has to land on a
    straight one to be worth anything this turn.
    """
    if not any(not card.bowed and keywords.PORT in card.keywords for card in in_play(view)):
        return False
    before = spendable(view)
    return newly_affordable(view, before, before + 1)


def _largest_straight_producer(view: GameView, request: ChooseAbilityTarget) -> str:
    """The candidate that can still be bowed for the Gold, largest first.

    A grant is only collected by bowing the card that receives it, so a bowed one is spent for
    nothing. The grant is flat and the yield beside it is not, which is what breaks the tie.
    """
    cards = identifiable(view)
    return min(
        request.candidates,
        key=lambda card_id: (
            cards[card_id].bowed,
            -production(view, cards[card_id]),
            card_id,
        ),
    )


def _verdant_wilds_worth_activating(view: GameView, source: L5RCard) -> bool:
    """Whether Verdant Wilds should bow itself to straighten a card.

    It produces five Gold and bows to pay, so the straightened card has to be worth more than that
    before the seat is ahead. Almost nothing is, which is the answer: the trade is offered every
    turn and is worth taking only when a bigger producer is sitting bowed.
    """
    bowed = [card for card in in_play(view) if card.bowed]
    if not bowed:
        return False
    before = spendable(view)
    after = before + best_production(view, bowed) - production(view, source)
    return newly_affordable(view, before, after)


register_ability_hint(
    "modest_farm",
    AbilityHint(
        worth_activating=_modest_farm_worth_activating,
        best_target=_modest_farm_best_target,
        optional_cost_answers={"modest_farm_straighten": _modest_farm_worth_sacrificing},
    ),
)
register_ability_hint(
    "millet_farm",
    AbilityHint(
        worth_activating=_millet_farm_worth_activating,
        best_target=_largest_straight_producer,
    ),
)
register_ability_hint(
    "harvested_land",
    AbilityHint(worth_activating=_harvested_land_worth_activating),
)
register_ability_hint(
    "rural_market",
    AbilityHint(
        worth_activating=_rural_market_worth_activating,
        best_target=_largest_producer,
    ),
)
register_ability_hint(
    "ichiba_district",
    AbilityHint(
        worth_activating=_ichiba_district_worth_activating,
        best_target=_largest_straight_producer,
    ),
)
register_ability_hint(
    "verdant_wilds",
    AbilityHint(
        worth_activating=_verdant_wilds_worth_activating,
        best_target=_largest_producer,
    ),
)
