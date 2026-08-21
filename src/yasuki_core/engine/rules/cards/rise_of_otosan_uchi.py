from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    owned_personalities,
    CardLocation,
    InvestAbility,
    bow_cost,
    itself,
    may_remain_bowed,
    no_cost,
    owned_holdings,
    register_ability,
    register_invest,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
    AskAmount,
    Banish,
    Bow,
    Choose,
    CreateToken,
    Destroy,
    Discard,
    DrawCard,
    Effect,
    GainHonor,
    MoveToDeck,
    PayGold,
    ShuffleDeck,
    Then,
)
from yasuki_core.engine.rules.economy import effective_chi, effective_gold_cost
from yasuki_core.engine.rules.equip import creation_targets
from yasuki_core.engine.rules.legality import reachable_gold, seat_alignment_name
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.events import EnteredPlay, Straightened
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH


# --- Blessings of the Red Panda Spirit ---


@choice_resolver("red_panda_spirit_keep")
def _resolve_red_panda_spirit_keep(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Reshuffle the Event into its owner's Dynasty deck, or discard it. Declining is not doing
    nothing — the Event leaves its Province either way, and only where it goes is the seat's."""
    if not chosen:
        return [Discard(source_id, seat)]
    deck = DeckKey(seat, Side.DYNASTY)
    return [MoveToDeck(source_id, deck, from_top=0), ShuffleDeck(deck)]


def _blessings_of_the_red_panda_spirit_targets(game: GameState, card: L5RCard) -> list[str]:
    """The Event itself. The ability names no card at all, but an ability whose candidates are empty
    is never offered, so it stands as its own — paired with ``all_targets`` so the seat is not asked
    to pick the only thing there is."""
    return [card.id]


def _blessings_of_the_red_panda_spirit_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """A gift to the table, then a question. Every seat gains and draws in seat order; the reshuffle
    is deferred so it follows the draws, which is the order the card states."""
    gifts: list[Effect] = []
    for seat in game.table.seats:
        gifts.append(GainHonor(seat, 1))
        gifts.append(DrawCard(seat))
    question = f"Shuffle {source.name} into your Dynasty deck instead of discarding it?"
    return [
        *gifts,
        Then(
            (
                Ask(
                    source.owner,
                    question,
                    "red_panda_spirit_keep",
                    subjects=(source.id,),
                    source_id=source.id,
                ),
            )
        ),
    ]


register_ability(
    "blessings_of_the_red_panda_spirit",
    Ability(
        timing=ActionTiming.OPEN,
        label="Each player gains 1 Honor and draws a card",
        cost=no_cost,
        targets=_blessings_of_the_red_panda_spirit_targets,
        effects=_blessings_of_the_red_panda_spirit_effects,
        all_targets=True,
        located_at=(CardLocation.PROVINCE,),
    ),
)


# --- Bound in Blood ---

HORROR = "horror_shadowlands_personality"
GOLD_PER_SACRIFICE = 2
MOST_SACRIFICES = 4


def _bound_in_blood_amounts(game: GameState, source: L5RCard) -> tuple[int, ...]:
    """The sums worth spending: two Gold buys one Personality and every two more buys another, up to
    four or however many the seat has, and never more than it can raise.

    Nothing smaller is offered. An action whose targeting is priced by a variable Gold cost may only
    be announced for an amount that buys a legal target (CR, Good Faith).
    """
    seat = source.owner
    bodies = min(MOST_SACRIFICES, len(owned_personalities(game, seat)))
    affordable = reachable_gold(game, seat) // GOLD_PER_SACRIFICE
    return tuple(count * GOLD_PER_SACRIFICE for count in range(1, min(bodies, affordable) + 1))


def _bound_in_blood_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow the Spell, then settle the :X: — both are printed in the cost block, so both are paid
    before the Personalities are chosen (CR, Action Sequence)."""
    return [
        Bow(source.id),
        AskAmount(
            source.owner,
            _bound_in_blood_amounts(game, source),
            "How much Gold do you spend binding blood?",
            "bound_in_blood",
            source.id,
        ),
    ]


@choice_resolver("bound_in_blood")
def _resolve_bound_in_blood(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Pay what was named, then take the bodies it bought."""
    spent = int(chosen[0])
    bodies = min(MOST_SACRIFICES, spent // GOLD_PER_SACRIFICE)
    offered = tuple(card.id for card in owned_personalities(game, seat))
    return [
        PayGold(seat, spent, "Bound in Blood"),
        Choose(seat, offered, bodies, bodies, "bound_in_blood_sacrifice", source_id),
    ]


@choice_resolver("bound_in_blood_sacrifice", prompt="Choose the Personalities to bind")
def _resolve_bound_in_blood_sacrifice(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The Horror is measured against the bound before they are banished, since it is made of what
    they were."""
    bound = [game.table.cards_by_id[card_id] for card_id in chosen]
    horror = CreateToken(
        HORROR,
        seat,
        source_id,
        stats=(
            (Stat.GOLD_COST, sum(effective_gold_cost(game, card) for card in bound)),
            (Stat.FORCE, sum(effective_chi(game, card) for card in bound)),
            (Stat.CHI, len(bound)),
        ),
    )
    return [horror, *(Banish(card.id) for card in bound), Destroy(source_id, seat)]


register_ability(
    "bound_in_blood",
    Ability(
        timing=ActionTiming.OPEN,
        label="Open: Bow and spend Gold to bind your Personalities into a Horror",
        cost=_bound_in_blood_cost,
        targets=itself,
        effects=lambda game, source, target: [],
        all_targets=True,
    ),
)


# --- Courts of Otosan Uchi ---

COURTIER = "courtier_personality_0_2_2"


def _courts_of_otosan_uchi_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """A Wealth token and a Courtier who joins the Clan the Holding's controller plays."""
    return [
        AdjustCounter(source.id, WEALTH, 1),
        CreateToken(
            COURTIER, source.owner, source.id, clan=seat_alignment_name(game, source.owner)
        ),
    ]


register_invest(
    "courts_of_otosan_uchi",
    InvestAbility(minimum=2, maximum=2, effect=_courts_of_otosan_uchi_invest),
)


# --- Culling Grounds ---

EXPENDABLE_SERVANT = "expendable_personality_0_2_1"


may_remain_bowed("culling_grounds")


@on(Straightened, "culling_grounds")
def _culling_grounds_straightened(ctx: TriggerContext) -> list[Effect]:
    """Until the game ends, if this Holding is ever unbowed, banish the Personality.

    Which is why the Holding may remain bowed: standing it up again to produce Gold is what costs
    the servant. Nothing it created earlier and lost is chased, so a second servant is only ever at
    risk of the same bargain.
    """
    if ctx.event.card_id != ctx.card.id:
        return []
    return [Banish(created) for created in ctx.game.creations_of(ctx.card.id)]


def _culling_grounds_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Create and Recruit the servant, ignoring Gold Cost — nothing is paid for it, so there is no
    payment to raise; the Honor is the price."""
    return [
        CreateToken(EXPENDABLE_SERVANT, source.owner, source.id),
        GainHonor(source.owner, -1),
    ]


register_ability(
    "culling_grounds",
    Ability(
        timing=ActionTiming.OPEN,
        label="Open: Bow and lose 1 Honor to recruit a 0F/2C Expendable Personality",
        cost=bow_cost,
        targets=itself,
        effects=_culling_grounds_effects,
        all_targets=True,
    ),
)


# --- Kitsu Watanabe (Experienced) ---

LION_ANCESTOR = "lion_ancestor"


def _kitsu_watanabe_experienced_targets(game: GameState, source: L5RCard) -> list[str]:
    return [holding.id for holding in owned_holdings(game, source.owner)]


def _kitsu_watanabe_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """The Holding is spent on the summons, so it goes before the Ancestor answers."""
    return [
        Destroy(target.id, source.owner),
        CreateToken(LION_ANCESTOR, source.owner, source.id),
    ]


register_ability(
    "kitsu_watanabe_experienced",
    Ability(
        timing=ActionTiming.OPEN,
        label="Open: Destroy your Holding to call up a 2F/2C/3PH Lion Ancestor",
        cost=no_cost,
        targets=_kitsu_watanabe_experienced_targets,
        effects=_kitsu_watanabe_experienced_effects,
    ),
)


# --- Rebuilt Harbor ---


def _rebuilt_harbor_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """One +1GP Wealth token per gold invested — Rebuilt Harbor's variable payoff."""
    return [AdjustCounter(source.id, WEALTH, amount)]


register_invest(
    "rebuilt_harbor", InvestAbility(minimum=1, maximum=3, effect=_rebuilt_harbor_invest)
)


# --- Shinjo Saeki, Clan Champion (Experienced 2) ---

CAVALRY_FOLLOWER = "cavalry"


@on(EnteredPlay, "shinjo_saeki_clan_champion_experienced_2")
def _shinjo_saeki_clan_champion_experienced_2_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After Saeki enters play, create and Equip a 1F Cavalry Follower to each of your Cavalry
    Personalities — himself among them, since he carries the keyword."""
    if ctx.event.card_id != ctx.card.id:
        return []
    cavalry = ctx.game.table.creatable_tokens[CAVALRY_FOLLOWER]
    return [
        CreateToken(CAVALRY_FOLLOWER, ctx.card.owner, ctx.card.id, attach_to=rider.id)
        for rider in creation_targets(ctx.game, ctx.card.owner, cavalry, keyword=keywords.CAVALRY)
    ]
