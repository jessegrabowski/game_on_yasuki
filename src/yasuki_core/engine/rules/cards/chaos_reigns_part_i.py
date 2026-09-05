from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    DISCARD_THE_FAVOR,
    favor_cost_for_seat,
    favor_payer,
    favor_payers,
    no_cost,
    owned_personalities,
    register_edict,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.economy import effective_keywords
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    AskOption,
    Bow,
    Choose,
    DrawCard,
    Effect,
    GainHonor,
    Move,
)
from yasuki_core.engine.rules.events import CardDiscarded
from yasuki_core.engine.rules.legality import has_wind
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import action_did, at_cap, choice_resolver
from yasuki_core.engine.rules.units import opposing_units_in_battle
from yasuki_core.engine.table import Location
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH


# --- Act With Authority ---

# "Open: Put this Edict into play." Its granted Favor ability has no handler yet.
register_edict("act_with_authority")


# --- Asceticism ---

# "Open: Put this Edict into play." Its Equip surcharge has no handler yet.
register_edict("asceticism")


# --- Caravansary ---

WEALTH_CAP = 3


def _caravansary_targets(game: GameState, source: L5RCard) -> list[str]:
    """Itself, once the action just resolved was its controller's and discarded a Fate card.

    A Response reads the action rather than the board: the discarded card is already in a pile by
    the time the Step opens, and nothing on the board says whose action put it there.
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
        all_targets=True,
    ),
)


# --- Honor Your Oaths ---

OATHS_HONOR = 1
BOW_A_YOJIMBO = "Bow your target Yojimbo"
DECLINE_SECOND_CLAUSE = "Take neither"


def _honor_your_oaths_targets(game: GameState, source: L5RCard) -> list[str]:
    """The enemy Personalities at the battle, offered only while you control the Favor.

    Controlling it is a condition rather than a cost — nothing here spends it, and the clause below
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
    with no Yojimbo and no way to pay the Favor is never asked a question it cannot answer.
    """
    seat = source.owner
    options: list[str] = []
    if _honor_your_oaths_bowable_yojimbo(game, seat):
        options.append(BOW_A_YOJIMBO)
    if favor_payers(game, seat):
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
    """Charge whichever half the seat named. Paying the Favor here is what makes this a Favor
    action; bowing the Yojimbo leaves it an ordinary one (ShE datasheet, The Favor Icon)."""
    if not chosen or chosen[0] == DECLINE_SECOND_CLAUSE:
        return []
    if chosen[0] == DISCARD_THE_FAVOR:
        return [*favor_cost_for_seat(game, seat, source_id), *_honor_your_oaths_reward(seat)]
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
        label="Battle: Move a target enemy Personality home",
        cost=no_cost,
        targets=_honor_your_oaths_targets,
        effects=_honor_your_oaths_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Manjodh ---


@favor_payer("manjodh")
def _manjodh_favor_payer(game: GameState, card: L5RCard) -> list[Effect] | None:
    """ "Political Interrupt, :bow:: If you have no Wind, pay the action's :favor: cost."

    Implemented as a payer priced at bowing rather than as the Interrupt it prints. Costs are paid
    at step B of the Action Sequence and Interrupts are played at D, so the printed window opens
    two steps after the cost it names — a contradiction in the card that no correct Interrupt round
    would resolve. Offering him where every other payer is offered delivers what the card is for.
    """
    if card.bowed or has_wind(game, card.owner):
        return None
    return [Bow(card.id)]


# --- Rumormongering ---

# "Political Open: Put this Edict into play." Its Favor-discard reaction has no handler yet.
register_edict("rumormongering")
