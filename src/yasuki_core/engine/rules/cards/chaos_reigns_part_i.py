from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.rulebook.favor_payment import DISCARD_THE_FAVOR, favor_payer
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.idioms import register_entry
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability, tireless_grant
from yasuki_core.engine.rules.action_record import action_keywords
from yasuki_core.engine.rules.board.queries import owned_personalities
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    AskOption,
    Bow,
    Choose,
    DiscardFavor,
    DrawCard,
    Effect,
    GainHonor,
    Move,
)
from yasuki_core.engine.rules.vocabulary.game_events import CardDiscarded
from yasuki_core.engine.rules.legality import has_wind
from yasuki_core.engine.rules.rulebook.equip import attach_restriction
from yasuki_core.engine.rules.units.membership import attached_to, attachments_of
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import action_did, at_cap, choice_resolver
from yasuki_core.engine.rules.board.queries import opposing_units_in_battle
from yasuki_core.engine.rules.board.seats import seat_stronghold
from yasuki_core.engine.table import Location
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH


# --- Act With Authority ---

# "Open: Put this Edict into play." Its granted Favor ability has no handler yet.
register_entry("act_with_authority", clears=keywords.EDICT)


# --- Asceticism ---

# "Open: Put this Edict into play." Its Equip surcharge has no handler yet.
register_entry("asceticism", clears=keywords.EDICT)


# --- Caravansary ---

WEALTH_CAP = 3


def _caravansary_targets(game: GameState, source: L5RCard) -> list[str]:
    """Itself, once the action just resolved was its controller's and discarded a Fate card.

    Reads the action rather than the board: nothing on the board says whose action discarded
    the card.
    """
    if at_cap(source, WEALTH, WEALTH_CAP):
        return []
    mine = any(
        event.side is Side.FATE and event.cause is source.owner
        for event in action_did(game, CardDiscarded)
    )
    return [source.id] if mine else []


def _caravansary_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 1)]


register_ability(
    "caravansary",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        label="Response: take a +1GP Wealth token for the Fate card your action discarded",
        cost=no_cost,
        targets=_caravansary_targets,
        effects=_caravansary_effects,
        hits_every_target=True,
    ),
)


# --- Honor Your Oaths ---

OATHS_HONOR = 1
BOW_A_YOJIMBO = "Bow your target Yojimbo"
DECLINE_SECOND_CLAUSE = "Take neither"


def _honor_your_oaths_targets(game: GameState, source: L5RCard) -> list[str]:
    """The enemy Personalities at the battle, offered only while you control the Favor.

    Controlling it is a condition rather than a cost: nothing here spends it, and the clause below
    is the only part of the card that can.
    """
    if game.favor_holder is not source.owner:
        return []
    return list(opposing_units_in_battle(game, source.owner))


def _honor_your_oaths_bowable_yojimbo(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    return tuple(
        card.id
        for card in owned_personalities(game, seat)
        if not card.bowed and keywords.YOJIMBO in effective_keywords(game, card)
    )


def _honor_your_oaths_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Move the target home, then offer the clause that buys an honor and a card.

    The two ways to buy it are offered together and only when each can actually be met, so a seat
    with no Yojimbo and no Favor is never asked a question it cannot answer. The discard is an
    effect rather than a cost, so nothing may pay it in the Favor's place: "discarding the Favor
    can happen only if you control it" (CR, Imperial Favor).
    """
    seat = source.owner
    options: list[str] = []
    if _honor_your_oaths_bowable_yojimbo(game, seat):
        options.append(BOW_A_YOJIMBO)
    if game.favor_holder is seat:
        options.append(DISCARD_THE_FAVOR)
    moved = [Move(target.id, Location.home(target.owner))]
    if not options:
        return moved
    question = "Gain 1 Honor and draw a card by paying which?"
    offer = AskOption(
        seat,
        (*options, DECLINE_SECOND_CLAUSE),
        question,
        "honor_your_oaths_second_clause",
        source.id,
    )
    return [*moved, offer]


def _honor_your_oaths_reward(seat: PlayerId) -> list[Effect]:
    return [GainHonor(seat, OATHS_HONOR), DrawCard(seat)]


@choice_resolver("honor_your_oaths_second_clause")
def _resolve_honor_your_oaths_second_clause(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Resolve whichever half the seat named. Neither makes this a Favor action: the Favor icon is
    a cost only in an action's cost block, and here it is in the effect text (ShE datasheet, The
    Favor Icon)."""
    if not chosen or chosen[0] == DECLINE_SECOND_CLAUSE:
        return []
    if chosen[0] == DISCARD_THE_FAVOR:
        return [DiscardFavor(seat), *_honor_your_oaths_reward(seat)]
    return [
        Choose(
            seat,
            _honor_your_oaths_bowable_yojimbo(game, seat),
            1,
            1,
            "honor_your_oaths_yojimbo",
            source_id,
        )
    ]


@choice_resolver(
    "honor_your_oaths_yojimbo", prompt="Bow your Yojimbo to gain 1 Honor and draw a card"
)
def _resolve_honor_your_oaths_yojimbo(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Bow(chosen[0]), *_honor_your_oaths_reward(seat)] if chosen else []


register_ability(
    "honor_your_oaths",
    Ability(
        timings=(ActionTiming.BATTLE,),
        keywords=frozenset({keywords.POLITICAL}),
        label="Battle: Move a target enemy Personality home",
        cost=no_cost,
        targets=_honor_your_oaths_targets,
        targeting_message="an enemy Personality",
        effects=_honor_your_oaths_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Latest Fashions ---

FASHIONS_HONOR = 1


@attach_restriction("latest_fashions")
def _latest_fashions_attach_restriction(
    game: GameState, personality: L5RCard, card: L5RCard
) -> bool:
    """A Personality may only attach one Kimono."""
    return not any(
        keywords.KIMONO in effective_keywords(game, attached)
        for attached in attachments_of(game, personality)
    )


def _latest_fashions_targets(game: GameState, source: L5RCard) -> list[str]:
    """Itself, once the action just resolved was Political and targeted or was from the Personality
    wearing it."""
    if keywords.POLITICAL not in action_keywords(game):
        return []
    wearer = attached_to(game, source)
    if wearer is None:
        return []
    from_wearer = isinstance(game.action, ActivateAbility) and game.action.card_id == wearer.id
    return [source.id] if from_wearer or wearer.id in game.action_targets else []


def _latest_fashions_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [GainHonor(source.owner, FASHIONS_HONOR)]


register_ability(
    "latest_fashions",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        label="Response: after a Political action targeting or from this Personality, gain 1 Honor",
        cost=no_cost,
        targets=_latest_fashions_targets,
        effects=_latest_fashions_effects,
        hits_every_target=True,
    ),
)


# --- Manjodh ---


@favor_payer("manjodh")
def _manjodh_favor_payer(game: GameState, card: L5RCard) -> list[Effect] | None:
    """ "Political Interrupt, :bow:: If you have no Wind, pay the action's :favor: cost."

    Implemented as a payer priced at bowing rather than as the printed Interrupt, offered wherever
    every other payer is offered. The printed timing cannot be honored: costs are paid at step B of
    the Action Sequence and Interrupts are played at D, so the window opens two steps after the cost
    it names.
    """
    if card.bowed or has_wind(game, card.owner):
        return None
    return [Bow(card.id)]


# --- Rumormongering ---

# "Political Open: Put this Edict into play." Its Favor-discard reaction has no handler yet.
register_entry(
    "rumormongering", clears=keywords.EDICT, ability_keywords=frozenset({keywords.POLITICAL})
)


# --- Shrine to Inari ---


@tireless_grant("shrine_to_inari")
def _shrine_to_inari_tireless_grant(game: GameState, source: L5RCard, card: L5RCard) -> bool:
    """Your Stronghold's printed abilities have Tireless while this Holding is unbowed."""
    return not source.bowed and card is seat_stronghold(game, source.owner)
