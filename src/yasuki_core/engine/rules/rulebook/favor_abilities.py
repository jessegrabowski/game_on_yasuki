from collections.abc import Callable
from typing import TypeGuard

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import (
    opposing_units_in_battle,
    personalities_in_play,
    rulebook_proxy_id,
)
from yasuki_core.engine.rules.board.seats import cards_in_hand
from yasuki_core.engine.rules.effects import (
    Bow,
    Choose,
    Discard,
    DrawCard,
    Effect,
    Move,
    Rehonor,
    Unpayable,
)
from yasuki_core.engine.rules.legality import has_wind
from yasuki_core.engine.rules.rulebook.favor_payment import favor_cost
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import Action, ActionTiming, ActivateAbility
from yasuki_core.engine.table import Location
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import (
    ONYX_FAVOR_PROXY_ID,
    PRE_GOLD_FAVOR_PROXY_ID,
    Side,
)
from yasuki_core.game_pieces.prints import RulebookPrint

DISCARD_TO_DRAW = "discard_to_draw"
SEND_ATTACKER_HOME = "send_attacker_home"
DRAW = "draw"
RESTORE_HONOR = "restore_honor"
SEND_UNIT_HOME = "send_unit_home"

FAVOR_ABILITY_KEYS = frozenset(
    {DISCARD_TO_DRAW, SEND_ATTACKER_HOME, DRAW, RESTORE_HONOR, SEND_UNIT_HOME}
)

# The resolvers of the choices the abilities' costs raise.
_DISCARD_RESOLVER = "favor_discard_to_draw"
_SEND_HOME_RESOLVER = "favor_send_home"
_SEND_HOME_BOWED_RESOLVER = "favor_send_home_bowed"
_RESTORE_HONOR_RESOLVER = "favor_restore_honor"

# The print each seat's Favor ability proxy presents, one per arc family. ``rulebook/proxies.py``
# deals whichever the active ruleset names.
ONYX_FAVOR_PROXY = RulebookPrint(
    name="Imperial Favor", side=Side.FATE, printed_id=ONYX_FAVOR_PROXY_ID, card_type="Other"
)
PRE_GOLD_FAVOR_PROXY = RulebookPrint(
    name="Imperial Favor", side=Side.FATE, printed_id=PRE_GOLD_FAVOR_PROXY_ID, card_type="Other"
)

_FAVOR_PROXY_CARD_IDS = frozenset(
    rulebook_proxy_id(seat, printed_id)
    for seat in PlayerId
    for printed_id in (ONYX_FAVOR_PROXY_ID, PRE_GOLD_FAVOR_PROXY_ID)
)


def is_favor_ability(action: Action) -> TypeGuard[ActivateAbility]:
    """Whether ``action`` takes a rulebook Favor ability on a seat's Favor proxy. The card is
    checked as well as the key, because a card may print an ability under the same key."""
    return (
        isinstance(action, ActivateAbility)
        and action.ability_key in FAVOR_ABILITY_KEYS
        and action.card_id in _FAVOR_PROXY_CARD_IDS
    )


SeatCost = Callable[[GameState, PlayerId], list[Effect]]


def _favor_cost(extra: SeatCost | None) -> Callable[[GameState, L5RCard], list[Effect]]:
    """The cost of a rulebook Favor ability: the Favor, plus ``extra`` when the ability charges
    more.

    The whole cost goes here, never half of it in the effects: an ability is offered only when its
    cost is payable, and a cost hidden among the effects is a cost nothing checks. A Wind makes it
    unpayable: "While you have a Wind in play, you may not take rulebook Favor actions, an effect
    which cannot be overcome by card effects" (ShE datasheet, Winds), so no payer can answer it.
    """

    def cost(game: GameState, source: L5RCard) -> list[Effect]:
        seat = source.owner
        if has_wind(game, seat):
            return [Unpayable(reason=f"{seat.name} has a Wind in play")]
        return [*favor_cost(game, source), *(extra(game, seat) if extra is not None else [])]

    return cost


def _on_your_turn(game: GameState, source: L5RCard) -> list[str]:
    """The proxy itself while its seat is the active one. An ability reading "If it is your turn"
    needs this, since an Open designator does not restrict it to the active seat on its own."""
    return itself(game, source) if source.owner is game.active else []


def _draw(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DrawCard(seat=source.owner)]


def _nothing(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The effects of an ability whose cost names its target: the choice in the cost does the
    work."""
    return []


def _favor_ability(
    *,
    key: str,
    timing: ActionTiming,
    label: str,
    effects: Callable[[GameState, L5RCard, L5RCard], list[Effect]],
    extra_cost: SeatCost | None = None,
    targets: Callable[[GameState, L5RCard], list[str]] = itself,
    ability_keywords: frozenset[str] = frozenset(),
) -> Ability:
    return Ability(
        timings=(timing,),
        label=label,
        cost=_favor_cost(extra_cost),
        targets=targets,
        effects=effects,
        hits_every_target=True,
        key=key,
        keywords=ability_keywords,
        located_at=(CardLocation.RULEBOOK,),
        from_rulebook=True,
    )


def _discard_a_fate_card(game: GameState, seat: PlayerId) -> list[Effect]:
    candidates = tuple(card.id for card in cards_in_hand(game, seat))
    return [
        Choose(seat=seat, candidates=candidates, minimum=1, maximum=1, resolver=_DISCARD_RESOLVER)
    ]


@choice_resolver(_DISCARD_RESOLVER, prompt="Discard a Fate card to draw a card")
def _resolve_discard_to_draw(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Discard(card_id=chosen[0], cause=seat)] if chosen else []


def _battle_candidates(game: GameState, seat: PlayerId, *, attackers_only: bool) -> tuple[str, ...]:
    """The Personalities at the battle now being fought that ``seat`` may send home.

    ``attackers_only`` narrows to the ability that names an *attacking* enemy, which only the
    Defender ever faces.
    """
    if attackers_only and (game.attack is None or seat is not game.attack.defender):
        return ()
    return opposing_units_in_battle(game, seat)


def _choose_attacker(game: GameState, seat: PlayerId) -> list[Effect]:
    candidates = _battle_candidates(game, seat, attackers_only=True)
    return [
        Choose(seat=seat, candidates=candidates, minimum=1, maximum=1, resolver=_SEND_HOME_RESOLVER)
    ]


@choice_resolver(_SEND_HOME_RESOLVER, prompt="Move a target attacking enemy Personality home")
def _resolve_send_home(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    if not chosen:
        return []
    card = game.table.cards_by_id[chosen[0]]
    return [Move(card_id=chosen[0], to=Location.home(card.owner))]


def _choose_unit(game: GameState, seat: PlayerId) -> list[Effect]:
    candidates = _battle_candidates(game, seat, attackers_only=False)
    return [
        Choose(
            seat=seat,
            candidates=candidates,
            minimum=1,
            maximum=1,
            resolver=_SEND_HOME_BOWED_RESOLVER,
        )
    ]


@choice_resolver(_SEND_HOME_BOWED_RESOLVER, prompt="Send a unit home from the battle, bowed")
def _resolve_send_home_bowed(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The pre-Gold ability bows what it sends back, which the unit does not do by traveling."""
    if not chosen:
        return []
    card = game.table.cards_by_id[chosen[0]]
    return [Move(card_id=chosen[0], to=Location.home(card.owner)), Bow(card_id=chosen[0])]


def _choose_dishonorable(game: GameState, seat: PlayerId) -> list[Effect]:
    candidates = tuple(
        card.id for card in personalities_in_play(game) if card.owner is seat and card.dishonorable
    )
    return [
        Choose(
            seat=seat, candidates=candidates, minimum=1, maximum=1, resolver=_RESTORE_HONOR_RESOLVER
        )
    ]


@choice_resolver(_RESTORE_HONOR_RESOLVER, prompt="Restore a Dishonored Personality to Honorable")
def _resolve_restore_honor(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Rehonor(card_id=chosen[0])] if chosen else []


# The Onyx/ShE datasheet's two. The Favor and the discarded card are both cost of the draw, and
# naming the attacker is cost of the Battle ability, so each is withheld with nothing to name. The
# Battle ability names an *attacking* enemy, so the Attacker cannot use it to clear the Defender's
# army off its own Province.
register_ability(
    ONYX_FAVOR_PROXY_ID,
    _favor_ability(
        key=DISCARD_TO_DRAW,
        timing=ActionTiming.OPEN,
        label="Political Open, :favor:: If it is your turn, discard a Fate card to draw a card.",
        effects=_draw,
        extra_cost=_discard_a_fate_card,
        targets=_on_your_turn,
        ability_keywords=frozenset({keywords.POLITICAL}),
    ),
)
register_ability(
    ONYX_FAVOR_PROXY_ID,
    _favor_ability(
        key=SEND_ATTACKER_HOME,
        timing=ActionTiming.BATTLE,
        label="Political Battle, :favor:: Move a target attacking enemy Personality home.",
        effects=_nothing,
        extra_cost=_choose_attacker,
        ability_keywords=frozenset({keywords.POLITICAL}),
    ),
)

# The pre-Gold rulebook's (Soul of the Empire). The draw asks for nothing alongside the Favor.
# Naming the Personality is cost of the other two, which are withheld with nobody to name. Sending
# home bows the unit, which the datasheet ability does not do. The fourth, "Reaction: Prevent a
# Family Honor loss.", needs honor-loss prevention, which the engine does not model, so it is not
# registered.
register_ability(
    PRE_GOLD_FAVOR_PROXY_ID,
    _favor_ability(
        key=DRAW,
        timing=ActionTiming.LIMITED,
        label="Limited: Draw a Fate card.",
        effects=_draw,
    ),
)
register_ability(
    PRE_GOLD_FAVOR_PROXY_ID,
    _favor_ability(
        key=RESTORE_HONOR,
        timing=ActionTiming.OPEN,
        label="Open: Restore a Dishonored Personality to Honorable status.",
        effects=_nothing,
        extra_cost=_choose_dishonorable,
    ),
)
register_ability(
    PRE_GOLD_FAVOR_PROXY_ID,
    _favor_ability(
        key=SEND_UNIT_HOME,
        timing=ActionTiming.BATTLE,
        label="Battle: Send a unit home from a battle, bowed.",
        effects=_nothing,
        extra_cost=_choose_unit,
    ),
)
