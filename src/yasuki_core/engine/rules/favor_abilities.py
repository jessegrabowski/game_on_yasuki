from collections.abc import Callable

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import abilities
from yasuki_core.engine.rules.effects import Bow, Choose, Discard, DrawCard, Effect, Move
from yasuki_core.engine.rules.favor import is_rulebook_proxy
from yasuki_core.engine.rules.units import opposing_units_in_battle
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.table import Location, ZoneKey, ZoneRole
from yasuki_core.ruleset import FavorAbility

# No card charges a rulebook ability, so its cost is named for the rulebook itself.
RULEBOOK_SOURCE = "rulebook"
DISCARD_TO_DRAW = "favor_discard_to_draw"
SEND_HOME = "favor_send_home"
SEND_HOME_BOWED = "favor_send_home_bowed"


# What each arc's Favor abilities cost and do, keyed by ``FavorAbility.key``. An ability the ruleset
# names but nothing here implements is not offered, so an arc can be configured ahead of the engine
# features its abilities need.
#
# The whole cost goes in the cost builder, never half of it here and half in the effects: an
# ability is offered only when ``can_pay`` judges its cost payable, and a cost hidden among the
# effects is a cost nothing checks.
FAVOR_ABILITY_COSTS: dict[str, "FavorAbilityEffects"] = {}
FAVOR_ABILITY_EFFECTS: dict[str, "FavorAbilityEffects"] = {}


FavorAbilityEffects = Callable[[GameState, PlayerId], list[Effect]]


def favor_ability(
    key: str, *, cost: FavorAbilityEffects | None = None
) -> Callable[[FavorAbilityEffects], FavorAbilityEffects]:
    """Register the decorated builder as the effects of the Favor ability named ``key``.

    Parameters
    ----------
    key : str
        The ``FavorAbility.key`` this implements.
    cost : callable, optional
        What the ability charges beyond the Favor itself, which the Favor cost is added to. Default
        None, for an ability the Favor alone pays for.
    """

    def register(builder: FavorAbilityEffects) -> FavorAbilityEffects:
        FAVOR_ABILITY_EFFECTS[key] = builder
        if cost is not None:
            FAVOR_ABILITY_COSTS[key] = cost
        return builder

    return register


def favor_ability_cost(game: GameState, seat: PlayerId, key: str) -> list[Effect]:
    """Everything ``seat`` pays to take the Favor ability named ``key``: the Favor, plus whatever
    else that arc's ability charges."""
    extra = FAVOR_ABILITY_COSTS.get(key)
    return [
        *abilities.favor_cost_for_seat(game, seat, RULEBOOK_SOURCE),
        *(extra(game, seat) if extra is not None else []),
    ]


def available_favor_abilities() -> tuple[FavorAbility, ...]:
    """The arc's Favor abilities this engine can actually perform."""
    return tuple(
        ability
        for ability in ruleset.ACTIVE.favor_abilities
        if ability.key in FAVOR_ABILITY_EFFECTS
    )


def _discardable(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The Fate cards ``seat`` could discard. A rulebook proxy is not a card and cannot be spent."""
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    return tuple(card.id for card in hand.cards if not is_rulebook_proxy(card))


def _discard_a_fate_card(game: GameState, seat: PlayerId) -> list[Effect]:
    return [Choose(seat, _discardable(game, seat), 1, 1, DISCARD_TO_DRAW)]


@favor_ability("discard_to_draw", cost=_discard_a_fate_card)
def _discard_to_draw(game: GameState, seat: PlayerId) -> list[Effect]:
    """ShE datasheet: "Political Open, (Favor): If it is your turn, discard a Fate card to draw a
    card." The Favor and the discarded card are both cost; drawing is what it buys."""
    return [DrawCard(seat)]


@choice_resolver(DISCARD_TO_DRAW, prompt="Discard a Fate card to draw a card")
def _resolve_discard_to_draw(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Discard(chosen[0], seat)] if chosen else []


@favor_ability("draw")
def _draw(game: GameState, seat: PlayerId) -> list[Effect]:
    """Pre-Gold rulebook: "Limited: Draw a Fate card." The Favor is the whole cost; unlike the ShE
    ability it asks for no card alongside it."""
    return [DrawCard(seat)]


def _battle_candidates(game: GameState, seat: PlayerId, *, attackers_only: bool) -> tuple[str, ...]:
    """The Personalities at the battle now being fought that ``seat`` may send home.

    ``attackers_only`` narrows to the ability that names an *attacking* enemy, which only the
    Defender ever faces.
    """
    if attackers_only and (game.attack is None or seat is not game.attack.defender):
        return ()
    return opposing_units_in_battle(game, seat)


def _choose_attacker(game: GameState, seat: PlayerId) -> list[Effect]:
    return [Choose(seat, _battle_candidates(game, seat, attackers_only=True), 1, 1, SEND_HOME)]


@favor_ability("send_attacker_home", cost=_choose_attacker)
def _send_attacker_home(game: GameState, seat: PlayerId) -> list[Effect]:
    """ShE datasheet: "Political Battle, (Favor): Move a target attacking enemy Personality home."

    Attacking only, so the Attacker cannot use it to clear the Defender's army off its own Province.
    Naming the target is part of the cost, so the ability is withheld when there is nobody to name.
    """
    return []


def _choose_unit(game: GameState, seat: PlayerId) -> list[Effect]:
    return [
        Choose(seat, _battle_candidates(game, seat, attackers_only=False), 1, 1, SEND_HOME_BOWED)
    ]


@favor_ability("send_unit_home", cost=_choose_unit)
def _send_unit_home(game: GameState, seat: PlayerId) -> list[Effect]:
    """Pre-Gold rulebook: "Battle: Send a unit home from a battle, bowed." Either army's, and it
    arrives bowed, neither of which the ShE ability does."""
    return []


@choice_resolver(SEND_HOME, prompt="Move a target attacking enemy Personality home")
def _resolve_send_home(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    if not chosen:
        return []
    card = game.table.cards_by_id[chosen[0]]
    return [Move(chosen[0], Location.home(card.owner))]


@choice_resolver(SEND_HOME_BOWED, prompt="Send a unit home from the battle, bowed")
def _resolve_send_home_bowed(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The pre-Gold ability bows what it sends back, which the unit does not do by travelling."""
    if not chosen:
        return []
    card = game.table.cards_by_id[chosen[0]]
    return [Move(chosen[0], Location.home(card.owner)), Bow(chosen[0])]
