from collections.abc import Iterator

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import gold_charged, payable
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, TargetGroup, use_tags
from yasuki_core.engine.rules.vocabulary.decisions import (
    PickedTargets,
    answerable,
    within_reach,
)
from yasuki_core.engine.rules.effects import AskAmount
from yasuki_core.engine.rules.abilities.registry import (
    abilities_for,
    ability_for,
    acts_from_discard,
    holds_seat_grant,
    fixed_invest_amount,
    granted_tireless,
)
from yasuki_core.engine.rules.vocabulary.actions import (
    Action,
    ACTION_TIMINGS,
    ActionTiming,
    ActivateAbility,
    BattleDesignator,
    DeclareAttack,
    Equip,
    Pass,
    PlayInterrupt,
    PlayStrategy,
)
from yasuki_core.engine.rules.board.clans import (
    card_alignments,
    seat_alignments,
    shares_seat_alignment,
)
from yasuki_core.engine.rules.units.composition import in_a_unit
from yasuki_core.engine.rules.board.queries import (
    has_keyword,
    province_cards,
    units_at,
)
from yasuki_core.engine.rules.rulebook.equip import (
    equip_discount_onto,
    equip_gold,
    equip_targets,
    equippable,
)
from yasuki_core.engine.rules.rulebook.joining import may_join
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.rulebook.discipline import (
    Reach,
    discipline_granters,
    may_have_discipline,
    reach,
    under_discipline,
)
from yasuki_core.engine.rules.gold.discounts import (
    discounted_gold_cost,
    effective_recruit_discount,
)
from yasuki_core.engine.rules.gold.producers import gold_reach
from yasuki_core.engine.rules.state import GameState, seat_once_key, used_this_turn
from yasuki_core.engine.rules.turn.structure import ActionRound
from yasuki_core.engine.rules.rulebook.equip import has_caster, is_spell
from yasuki_core.engine.table import DeckKey, location_of, ZoneRole
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import (
    AttachmentPrint,
    PersonalityPrint,
    WindPrint,
)


# The active ruleset: legal Clan Alignments and the off-clan surcharge.


def timings_of(game: GameState, action: Action) -> frozenset[ActionTiming]:
    """The designators ``action`` may be taken under, empty for a pass.

    A pass is the CR's alternative to taking an action, not an action itself, so it carries no
    designator and every Action Round accepts it. An ``ActivateAbility`` reads its designators off
    the card: the same action is Open on one Holding and Dynasty
    on another, and a card printing "Battle/Open" carries both.

    Raise ValueError for an action with no designator rule, and for an ``ActivateAbility`` naming a
    card that has no activated ability.
    """
    if isinstance(action, Pass):
        return frozenset()
    if isinstance(action, ActivateAbility):
        card = game.table.cards_by_id[action.card_id]
        ability = ability_for(game, card, action.ability_key)
        if ability is None:
            raise ValueError(f"card {action.card_id} has no activated ability to time")
        return frozenset(ability.timings)
    timing = ACTION_TIMINGS.get(type(action))
    if timing is None:
        raise ValueError(f"no designator for action {type(action).__name__}")
    return frozenset({timing})


def permitted_timings(game: GameState, seat: PlayerId) -> frozenset[ActionTiming]:
    """The designators the open Action Round permits ``seat``.

    None at all during a battle for a seat with no unit at the battlefield being fought: a player
    must control one or more units there to take an action at all (CR, Rule of Presence). A seat
    permitted nothing is skipped rather than asked, which
    :func:`~yasuki_core.engine.rules.turn.sequence.yield_priority` already does for a round that
    permits it nothing.
    """
    return permitted_timings_in(game, game.round, seat)


def permitted_timings_in(
    game: GameState, round: ActionRound, seat: PlayerId
) -> frozenset[ActionTiming]:
    """The designators ``round`` permits ``seat``, for a round other than the open one: what an
    Interrupt asks of the round its action was taken in.

    None at all for a seat with no unit at the battlefield being fought, whatever round is asking
    (CR, Actions in Battle: the Rule of Presence applies to every action type). Whether a battle is
    being fought is read off the attack rather than off the round, because an Interrupt, a Response
    and a duel window all sit over a battle segment without being one.
    """
    attack = game.attack
    in_battle = attack is not None and attack.current is not None
    if in_battle and not has_presence(game, seat) and not has_absent_ability(game, seat):
        return frozenset()
    timings = round.timings
    return timings.active if seat is game.active else timings.others


def permits(game: GameState, seat: PlayerId, timing: ActionTiming) -> bool:
    """Whether the open Action Round permits ``seat`` to take an action designated ``timing``."""
    return timing in permitted_timings(game, seat)


def legal_actions(game: GameState, seat: PlayerId) -> list[Action]:
    """The free actions ``seat`` may take right now: always a pass, plus every rulebook action and
    card ability whose own conditions it meets in the current phase. Empty while a decision is
    pending and for any seat but the active one.

    Gold is not a free action: it is produced only while paying a cost (rules-skeleton section 7),
    so it surfaces through a cost's ``ChoosePayment``, never here. An additional action limited to
    some follow-ups offers only those.
    """
    if not _may_act(game, seat):
        return []
    available = [
        *_abilities(game, seat),
        *_equips(game, seat),
        *_strategies(game, seat),
        *_declare_attack(game, seat),
        *_interrupts(game, seat),
    ]
    return [Pass(), *(action for action in available if _follows_up(game, action))]


def is_legal(game: GameState, seat: PlayerId, action: Action) -> bool:
    """Whether ``seat`` may take exactly ``action`` right now: what membership in
    :func:`~.legal_actions` answers, scoped to one action.

    Raise ValueError for an action carrying no legality rule.
    """
    if not _may_act(game, seat):
        return False
    match action:
        case Pass():
            return True
        case _ if not _follows_up(game, action):
            return False
        case ActivateAbility(card_id=card_id):
            return action in _abilities(game, seat, only=card_id)
        case Equip(card_id=card_id):
            return action in _equips(game, seat, only=card_id)
        case PlayStrategy(card_id=card_id):
            return action in _strategies(game, seat, only=card_id)
        case DeclareAttack():
            return bool(_declare_attack(game, seat))
        case PlayInterrupt():
            return action in _interrupts(game, seat)
        case _:
            raise ValueError(f"no legality rule for action {type(action).__name__}")


def _interrupts(game: GameState, seat: PlayerId) -> list[Action]:
    """The Interrupts ``seat`` may take in an open Interrupt step, against the action held there.
    Imported where it is used: the Interrupt module reads legality for targets and presence."""
    from yasuki_core.engine.rules.interrupts import interrupt_actions

    if not permits(game, seat, ActionTiming.INTERRUPT):
        return []
    return interrupt_actions(game, seat)


def _follows_up(game: GameState, action: Action) -> bool:
    """Whether ``action`` is one the open opportunity may be spent on: any, unless it is an
    additional action limited to some follow-ups (CR, Additional Action)."""
    follow_ups = game.round.follow_ups
    return follow_ups is None or action in follow_ups


def _may_act(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` may take any action at all: the game is running, nothing is awaiting an
    answer, and ``seat`` holds the opportunity in the open round."""
    return not (game.game_over or game.awaiting_decision) and seat is game.round.priority


def _abilities(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """An ActivateAbility for each ability the seat can use now on a card it controls: sitting
    somewhere the ability acts from, its designator permitted by the current round, cost payable,
    and with at least one legal target. ``only`` narrows to a single card."""
    return [
        ActivateAbility(card.id, ability.key)
        for card, ability in activatable(game, seat, permitted_timings(game, seat))
        if only is None or card.id == only
    ]


def has_wind(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` has a Wind in play. A deck holds at most one, and it starts there."""
    return any(
        isinstance(card.printed, WindPrint)
        for card in game.table.battlefield.cards
        if card.owner is seat
    )


def _declare_attack(game: GameState, seat: PlayerId) -> list[Action]:
    """A DeclareAttack when the Attack Phase's round permits it and no attack stands yet.

    One declaration per phase: the CR gives the active player a single opportunity to create an
    attack.
    """
    if game.attack is not None or not permits(game, seat, ActionTiming.ATTACK):
        return []
    return [DeclareAttack()]


def _equips(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """The Equip actions ``seat`` can take: each attachment Equip may reach, in hand or in a discard
    pile its own text opens, that it can afford and some Personality it controls would accept.

    The Personality is chosen through the decision the action raises, and the action is withheld
    unless at least one would take the card. ``only`` narrows to a single card."""
    if not permits(game, seat, ACTION_TIMINGS[Equip]):
        return []
    reach = gold_reach(game, seat)
    equips: list[Action] = []
    for card in equippable(game, seat):
        if only is not None and card.id != only:
            continue
        if not isinstance(card.printed, AttachmentPrint):
            continue
        if not may_join(game, seat, card):
            continue
        targets = equip_targets(game, card)
        if not targets:
            continue
        affordable = reach.for_card(game, card)
        discounts = {0, *(equip_discount_onto(game, target, card) for target in targets)}
        investing = (False, True) if fixed_invest_amount(game, card) is not None else (False,)
        equips.extend(
            Equip(card.id, invest=invest, discount=discount)
            for discount in sorted(discounts)
            for invest in investing
            if equip_gold(game, card, invest=invest, discount=discount) <= affordable
        )
    return equips


def _strategies(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """The Strategies ``seat`` can play: each one in hand, or in its Fate discard pile under
    Discipline, whose designator this round permits, whose Gold Cost it can reach, and which has a
    legal target.

    Asks :func:`playable` and :func:`playable_under_discipline`, since the card's own ability
    decides when it may be played. ``only`` narrows to a single card.
    """
    gold = gold_reach(game, seat)
    permitted = permitted_timings(game, seat)
    offers = [
        *((card, ability, False) for card, ability in playable(game, seat, permitted)),
        *(
            (card, ability, True)
            for card, ability in playable_under_discipline(game, seat, permitted)
        ),
    ]
    return [
        PlayStrategy(card.id, ability.key, disciplined=disciplined)
        for card, ability, disciplined in offers
        if (only is None or card.id == only)
        and strategy_gold(game, card, ability, disciplined=disciplined) <= gold.for_card(game, card)
    ]


def action_gold(game: GameState, action: ActivateAbility | Equip | PlayStrategy) -> tuple[int, ...]:
    """The Gold ``action`` charges in all, discounts included, least first: one amount, or one for
    each amount a variable cost lets the payer pick. A Strategy whose ability charges Gold as well
    pays its Gold Cost and that Gold as two payments, and the amount is their sum.

    Raise ``ValueError`` for an ability the card does not have.
    """
    card = game.table.cards_by_id[action.card_id]
    match action:
        case Equip(invest=invest, discount=discount):
            return (equip_gold(game, card, invest=invest, discount=discount),)
        case ActivateAbility(ability_key=key):
            return _ability_gold(game, card, _ability_named(game, card, key))
        case PlayStrategy(ability_key=key, disciplined=disciplined):
            ability = _ability_named(game, card, key)
            return (strategy_gold(game, card, ability, disciplined=disciplined),)


def _ability_named(game: GameState, card: L5RCard, key: str | None) -> Ability:
    ability = ability_for(game, card, key)
    if ability is None:
        raise ValueError(f"{card.id} has no ability keyed {key!r}")
    return ability


def _ability_gold(game: GameState, card: L5RCard, ability: Ability) -> tuple[int, ...]:
    costs = ability.discounted_cost(game, card, plays_card=False)
    fixed = gold_charged(costs)
    asked = next((cost for cost in costs if isinstance(cost, AskAmount)), None)
    if asked is None:
        return (fixed,)
    return tuple(fixed + gold_charged(asked.answered(game, amount)) for amount in asked.amounts)


def strategy_gold(
    game: GameState, card: L5RCard, ability: Ability, *, disciplined: bool = False
) -> int:
    """The Gold playing ``card`` for ``ability`` charges in all: its Gold Cost, with its Discipline
    added when ``disciplined``, and the Gold its ability's cost adds, with the action's one
    discount spent across both."""
    purchase = ability.purchase(game, card, plays_card=True)
    if disciplined:
        purchase = under_discipline(game, purchase)
    added = ability.discounted_cost(game, card, plays_card=True)
    return discounted_gold_cost(game, purchase) + gold_charged(added)


def recruit_cost(game: GameState, card: L5RCard, *, raised_by: int = 0) -> int:
    """The gold a seat pays to recruit ``card``: its gold cost with modifiers, plus the off-clan
    surcharge when the card has a Clan Alignment the seat does not share, less the card's own
    conditional recruit discount. Floored at zero.

    Parameters
    ----------
    raised_by : int, optional
        Gold the card's Gold Cost is about to be raised by, an Invest not yet laid, so the cost is
        read as it will stand when it is paid. Default 0.
    """
    cost = effective_gold_cost(game, card) + raised_by
    seat_aligns = seat_alignments(game, card.owner)
    card_aligns = card_alignments(card)
    if seat_aligns and card_aligns and seat_aligns.isdisjoint(card_aligns):
        cost += ruleset.ACTIVE.off_clan_surcharge
    cost -= effective_recruit_discount(game, card)
    return max(0, cost)


PROCLAIM = "proclaim"


def can_proclaim(game: GameState, card: L5RCard) -> bool:
    """Whether recruiting ``card`` could be Proclaimed by its seat: a Personality carrying the
    seat's Clan Alignment that the seat has not yet Proclaimed against this turn."""
    if not isinstance(card.printed, PersonalityPrint):
        return False
    seat = card.owner
    if seat is None:
        return False
    if not shares_seat_alignment(game, card):
        return False
    return not game.has_used(seat_once_key(seat, PROCLAIM, game.turn))


def is_legacy_card(game: GameState, card: L5RCard) -> bool:
    """Whether ``card`` carries the Legacy keyword, so the Legacy ability can search it out. Shrine
    of Courtesy grants itself Legacy for the second player, which is why this is not a printed
    check."""
    return has_keyword(game, card, keywords.LEGACY)


def legacy_search_pool(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """Every card ``seat``'s Legacy search looks through: its whole dynasty deck plus the
    face-down (unrevealed) cards in its provinces, the pool a search dialog shows. Face-up
    province cards are already recruitable and are not searched."""
    pool = list(game.table.decks[DeckKey(seat, Side.DYNASTY)].cards)
    pool.extend(card for card in province_cards(game, seat) if not card.face_up)
    return pool


def legacy_candidates(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Legacy cards ``seat`` could find right now: the Legacy cards within its search pool.
    Empty means a Legacy search would whiff and lose the game."""
    return [card for card in legacy_search_pool(game, seat) if is_legacy_card(game, card)]


def seat_cards(game: GameState, seat: PlayerId) -> Iterator[tuple[CardLocation, L5RCard]]:
    """Every card ``seat`` could activate something on, with where it is sitting.

    A card in hand is yielded like any other. Only an ability whose ``located_at`` names the hand is
    offered from there, and every ability defaults to the battlefield, so a card waiting to be
    played stays silent until one says otherwise. A card announced out of the hand is in a
    resolution area until it lands (CR, Resolution Area), so it offers nothing from the hand.
    """
    for card in game.table.battlefield.cards:
        if card.owner is seat:
            yield CardLocation.BATTLEFIELD, card
    for key, zone in game.table.zones.items():
        if key.owner is not seat:
            continue
        if key.role is ZoneRole.PROVINCE:
            for card in zone.cards:
                if card.face_up:  # face-down, what the card is has not been revealed
                    yield CardLocation.PROVINCE, card
        elif key.role is ZoneRole.HAND:
            yield from (
                (CardLocation.HAND, card)
                for card in zone.cards
                if card.id not in game.announced_cards
            )
        elif key.role is ZoneRole.RULEBOOK:
            yield from ((CardLocation.RULEBOOK, card) for card in zone.cards)
        elif key.role in (ZoneRole.FATE_DISCARD, ZoneRole.DYNASTY_DISCARD):
            # A pile runs long and almost nothing acts from it, so it is read only for a card that
            # prints such an ability or could have Discipline, or while a grant could give one.
            granted = holds_seat_grant(game, seat)
            disciplined = key.role is ZoneRole.FATE_DISCARD and bool(
                discipline_granters(game, seat)
            )
            yield from (
                (CardLocation.DISCARD, card)
                for card in zone.cards
                if card.id not in game.announced_cards
                and (
                    granted
                    or acts_from_discard(card)
                    or may_have_discipline(card, granted=disciplined)
                )
            )


# Every place ``seat_cards`` yields a card from. A card's own ability in hand is *played* rather
# than activated, and pays a Gold Cost to do it, so :func:`~.reach` tells the two actions apart
# below rather than the location alone.
ACTIVATED_FROM: tuple[CardLocation, ...] = (
    CardLocation.BATTLEFIELD,
    CardLocation.PROVINCE,
    CardLocation.RULEBOOK,
    CardLocation.HAND,
    CardLocation.DISCARD,
)


def activatable(
    game: GameState, seat: PlayerId, permitted: frozenset[ActionTiming]
) -> list[tuple[L5RCard, Ability]]:
    """Each card ``seat`` may activate an ability on right now, paired with the ability: controlled,
    sitting somewhere the ability acts from, its designator among ``permitted``, its cost payable,
    and with at least one legal target.

    A card's own ability acts from where the card is in play, or from the seat's rulebook zone.
    One a keyword confers acts from the hand as well. Playing a card's own ability out of hand is
    a different action with a cost of its own, which :func:`playable` lists.
    """
    return _usable(game, seat, permitted, at=ACTIVATED_FROM, reached=Reach.ACTIVATED)


def playable(
    game: GameState, seat: PlayerId, permitted: frozenset[ActionTiming]
) -> list[tuple[L5RCard, Ability]]:
    """Each card in hand ``seat`` may play right now, paired with the ability it plays as, under
    the tests :func:`activatable` applies."""
    return _usable(game, seat, permitted, at=(CardLocation.HAND,), reached=Reach.PLAYED)


def playable_under_discipline(
    game: GameState, seat: PlayerId, permitted: frozenset[ActionTiming]
) -> list[tuple[L5RCard, Ability]]:
    """Each card in ``seat``'s Fate discard pile it may play right now under Discipline, paired
    with the ability it plays as, under the tests :func:`activatable` applies (CR, Discipline)."""
    at = (CardLocation.DISCARD,)
    return _usable(game, seat, permitted, at=at, reached=Reach.PLAYED_UNDER_DISCIPLINE)


def _usable(
    game: GameState,
    seat: PlayerId,
    permitted: frozenset[ActionTiming],
    *,
    at: tuple[CardLocation, ...],
    reached: Reach,
) -> list[tuple[L5RCard, Ability]]:
    ready: list[tuple[L5RCard, Ability]] = []
    # Presence is the seat's, not the card's, so it is settled once rather than per card offered.
    present = has_presence(game, seat)
    for location, card in seat_cards(game, seat):
        if location not in at:
            continue
        # The attach rule cannot settle casting alone: a Personality can stop being a Shugenja
        # after the Spell landed on him. A Spell not yet in play is cast by nobody and asks no
        # caster of a keyword ability used from the hand.
        if location is CardLocation.BATTLEFIELD and is_spell(card) and not has_caster(game, card):
            continue
        for ability in abilities_for(game, card):
            how = reach(
                game, location, card, ability.located_at, from_rulebook=ability.from_rulebook
            )
            if how is not reached:
                continue
            if permitted.isdisjoint(ability.timings):
                continue
            if not _bow_permits(game, card, ability):
                continue
            # The Rule of Presence is about the player, not the card, so it gates an action taken
            # from anywhere, a Strategy out of hand as much as a Personality on the board.
            if not present and BattleDesignator.ABSENT not in ability.battle_designators:
                continue
            if ActionTiming.RESPONSE in ability.timings and card.id in game.responded:
                continue
            # An activated ability is once per turn unless it prints Repeatable (CR, Using
            # Abilities 0.3), where the arc says so. A card played from hand is spent, so nothing
            # rations it.
            if (
                ruleset.ACTIVE.abilities_once_per_turn
                and reached is Reach.ACTIVATED
                and not ability.repeatable
                and all(used_this_turn(game, card, tag) for tag in use_tags(game, card, ability))
            ):
                continue
            # A card in a unit may only be acted from at the battlefield the battle is at (CR,
            # Rules of Location). A card in hand or in a Province is in no unit, and neither is a
            # Holding.
            if (
                location is CardLocation.BATTLEFIELD
                and not _location_lifted(game, card, ability)
                and not location_permits(game, card)
            ):
                continue
            plays_card = reached is not Reach.ACTIVATED
            costs = ability.discounted_cost(game, card, plays_card=plays_card)
            if not payable(game, costs):
                continue
            if ability.targets_after_cost or phrases_reachable(game, card, ability):
                ready.append((card, ability))
    return ready


def _bow_permits(game: GameState, card: L5RCard, ability: Ability) -> bool:
    """Whether ``card``'s bowed state leaves ``ability`` usable: abilities on a bowed card cannot be
    used, and Tireless is the keyword that escapes it, printed on the ability or granted to the
    card by another in play (CR, Using Abilities, Tireless)."""
    return not card.bowed or ability.tireless or granted_tireless(game, card)


def _location_lifted(game: GameState, card: L5RCard, ability: Ability) -> bool:
    """Whether one of ``ability``'s designators excuses ``card`` from the Rules of Location (ShE
    datasheet).

    Remote reaches from home or from another battlefield. Home reaches from home alone, so a card
    standing at a battlefield that is not the current one is beyond it. Neither lifts the Rule of
    Presence.
    """
    if BattleDesignator.REMOTE in ability.battle_designators:
        return True
    if BattleDesignator.HOME in ability.battle_designators:
        return location_of(game.table, card).is_home
    return False


def has_absent_ability(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` holds any ability it could take with no presence at the current battlefield
    (ShE, Absent). What decides whether a seat with no units there is offered the opportunity at
    all, rather than skipped."""
    return any(
        BattleDesignator.ABSENT in ability.battle_designators and _bow_permits(game, card, ability)
        for _, card in seat_cards(game, seat)
        for ability in abilities_for(game, card)
    )


def group_targets(
    game: GameState,
    card: L5RCard,
    ability: Ability,
    group: TargetGroup,
    picked: PickedTargets = (),
) -> list[str]:
    """The ids ``group``, one "target" phrase of ``ability``, may be pointed at from ``card`` right
    now, given the phrases already settled in ``picked``.

    Filtered centrally: during a battle, a card in a unit may only be targeted at the
    battlefield the battle is at (CR, Rules of Location), unless the ``Ability`` sets
    ``targets_any_location``.
    """
    # Filtered against the limits here so the offering, the question and a substitution all agree
    # on what is targetable, and a phrase whose limits leave nothing withholds the action.
    offered = within_reach(
        group.candidates(game, card, picked), group.conditions(game, card, picked)
    )
    attack = game.attack
    if attack is None or attack.current is None or ability.targets_any_location:
        return list(offered)
    by_id = game.table.cards_by_id
    return [
        target_id
        for target_id in offered
        if target_id not in by_id or location_permits(game, by_id[target_id])
    ]


def phrases_reachable(
    game: GameState, card: L5RCard, ability: Ability, picked: PickedTargets = ()
) -> bool:
    """Whether ``ability``'s "target" phrases after ``picked`` can all still be met, which a seat
    must be able to do to announce the action or make a choice in it (CR, Good Faith Rule; CR,
    Choice Paradoxes). "Target two or more of your unbowed Merchant or Ninja Personalities" is no
    action for a seat with one, and a Fear's target is part of the action's targeting.

    A phrase taking no card is met by taking none. One taking a single card is met when a card it
    offers leaves the phrases after it reachable. One taking several, or limiting the set it takes,
    is met when it can be answered at all, since the phrases after it depend on the whole set.
    """
    if len(picked) == len(ability.phrases):
        return True
    group = ability.phrases[len(picked)]
    offered = tuple(group_targets(game, card, ability, group, picked))
    minimum, _ = group.wanted(game, card, picked, offered)
    if minimum == 0 and phrases_reachable(game, card, ability, (*picked, ())):
        return True
    limits = group.conditions(game, card, picked)
    if not answerable(offered, max(minimum, 1), limits):
        return False
    if minimum > 1 or limits:
        return True
    return any(phrases_reachable(game, card, ability, (*picked, (target,))) for target in offered)


def choosable_targets(
    game: GameState, card: L5RCard, ability: Ability, picked: PickedTargets = ()
) -> list[str]:
    """The cards ``ability``'s next "target" phrase after ``picked`` offers that leave its later
    phrases reachable (CR, Choice Paradoxes). A phrase taking several cards offers every legal one,
    as :func:`phrases_reachable` reads it."""
    group = ability.phrases[len(picked)]
    offered = group_targets(game, card, ability, group, picked)
    if len(picked) + 1 == len(ability.phrases):
        return offered
    minimum, _ = group.wanted(game, card, picked, tuple(offered))
    if minimum > 1 or group.conditions(game, card, picked):
        return offered
    return [
        target for target in offered if phrases_reachable(game, card, ability, (*picked, (target,)))
    ]


def legal_targets(game: GameState, card: L5RCard, ability: Ability) -> list[str]:
    """The ids ``ability``'s first "target" phrase may be pointed at from ``card`` right now, which
    is what an Interrupt may substitute for a chosen target."""
    return group_targets(game, card, ability, ability.phrases[0])


def has_presence(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` controls a unit at the battle now being fought (CR, Rule of Presence).

    True outside a battle, where presence is not a question anyone asks.
    """
    attack = game.attack
    if attack is None or attack.current is None:
        return True
    return bool(units_at(game, attack.current, seat))


def location_permits(game: GameState, card: L5RCard) -> bool:
    """Whether the Rules of Location leave ``card`` free to be acted from and targeted.

    A card in a unit must stand at the battle now being fought. A card in no unit (a Holding, a
    Region, a Stronghold) stands nowhere those rules speak of, so they never exclude it, and
    neither rule applies outside a battle at all. A card in a unit stands where its Personality
    stands, so its own recorded location answers for it.
    """
    attack = game.attack
    if attack is None or attack.current is None:
        return True
    if not in_a_unit(game, card):
        return True
    return location_of(game.table, card).battlefield == attack.current
