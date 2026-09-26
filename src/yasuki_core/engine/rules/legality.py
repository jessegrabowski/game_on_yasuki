from collections.abc import Callable, Iterator

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import payable
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, once_tag
from yasuki_core.engine.rules.effects import PayGold
from yasuki_core.engine.rules.abilities.registry import (
    abilities_for,
    ability_for,
    fixed_invest_amount,
    granted_tireless,
    invest_amounts,
    recruit_timing_of,
)
from yasuki_core.engine.rules.vocabulary.actions import (
    Action,
    ACTION_TIMINGS,
    ActionTiming,
    ActivateAbility,
    BattleDesignator,
    DeclareAttack,
    DiscardToInterrupt,
    Equip,
    Pass,
    PlayInterrupt,
    PlayStrategy,
    Recruit,
)
from yasuki_core.engine.rules.board.clans import card_alignments, seat_alignments
from yasuki_core.engine.rules.units.composition import in_a_unit
from yasuki_core.engine.rules.board.queries import (
    has_keyword,
    province_cards,
    units_at,
)
from yasuki_core.engine.rules.rulebook.equip import equip_targets
from yasuki_core.engine.rules.rulebook.copies import copy_may_enter
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.gold.discounts import (
    discounted_gold,
    equip_purchase,
    discounted_gold_cost,
    effective_recruit_discount,
)
from yasuki_core.engine.rules.gold.producers import gold_reach, reachable_gold
from yasuki_core.engine.rules.gold.self_grants import maximum_gold_production
from yasuki_core.engine.rules.state import GameState, used_this_turn
from yasuki_core.engine.rules.turn.structure import ActionRound, RoundKind
from yasuki_core.engine.rules.rulebook.equip import has_caster, is_spell
from yasuki_core.engine.table import DeckKey, location_of, ZoneKey, ZoneRole
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import (
    AttachmentPrint,
    HoldingPrint,
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
    if isinstance(action, Recruit):
        return recruit_timings(game, action.card_id)
    timing = ACTION_TIMINGS.get(type(action))
    if timing is None:
        raise ValueError(f"no designator for action {type(action).__name__}")
    return frozenset({timing})


def recruit_timings(game: GameState, card_id: str) -> frozenset[ActionTiming]:
    """The designators ``card_id`` may be Recruited under: the rulebook's Dynasty, plus any its own
    text adds ("You may Recruit this Holding as a Political Open action")."""
    added = recruit_timing_of(game, card_id)
    if added is None:
        return frozenset({ACTION_TIMINGS[Recruit]})
    return frozenset({ACTION_TIMINGS[Recruit], added.timing})


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

    None at all during a battle for a seat with no unit at the battlefield being fought, in a
    battle segment and in the Interrupt step over one alike (CR, Actions in Battle: the Rule of
    Presence applies to every action type, Interrupts included).
    """
    in_battle = round.kind is RoundKind.BATTLE_SEGMENT or (
        round.kind is RoundKind.INTERRUPT
        and game.attack is not None
        and game.attack.current is not None
    )
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
    so it surfaces through the Recruit's ``ChoosePayment``, never here.
    """
    if not _may_act(game, seat):
        return []
    return [
        Pass(),
        *_abilities(game, seat),
        *_recruits(game, seat),
        *_equips(game, seat),
        *_strategies(game, seat),
        *_declare_attack(game, seat),
        *_interrupts(game, seat),
    ]


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
        case ActivateAbility(card_id=card_id):
            return action in _abilities(game, seat, only=card_id)
        case Recruit(card_id=card_id):
            return action in _recruits(game, seat, only=card_id)
        case Equip(card_id=card_id):
            return action in _equips(game, seat, only=card_id)
        case PlayStrategy(card_id=card_id):
            return action in _strategies(game, seat, only=card_id)
        case DeclareAttack():
            return bool(_declare_attack(game, seat))
        case PlayInterrupt() | DiscardToInterrupt():
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


def _recruits(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """The Recruit actions ``seat`` can afford: each face-up Holding or Personality in its provinces
    whose cost its pool plus its unbowed producers' gold could cover. A Personality is withheld
    while its Honor Requirement is above the seat's Family Honor (a dash ``None`` never withholds,
    and the check is skipped entirely when the seat ignores Honor Requirements), and adds a Proclaim
    variant when it is own-clan and the seat has not Proclaimed this turn. A Holding adds an Invest
    variant when the seat could also cover the card's Invest cost. ``only`` narrows to a
    single card."""
    permitted = permitted_timings(game, seat)
    recruits: list[Action] = []
    seat_info = game.table.seats[seat]
    honor = seat_info.honor
    enforce_honor = not seat_info.ignores_honor_requirements
    fixed, variable = gold_reach(game, seat)
    for card in province_cards(game, seat):
        if only is not None and card.id != only:
            continue
        if not (isinstance(card.printed, (HoldingPrint, PersonalityPrint)) and card.face_up):
            continue
        if permitted.isdisjoint(recruit_timings(game, card.id)):
            continue
        if not copy_may_enter(game, seat, card):
            continue
        if (
            enforce_honor
            and isinstance(card.printed, PersonalityPrint)
            and card.honor_requirement is not None
            and honor < card.honor_requirement
        ):
            continue
        affordable = fixed + sum(
            maximum_gold_production(game, producer, targets=(card,)) for producer in variable
        )
        base = recruit_cost(game, card)
        if base <= affordable:
            recruits.append(Recruit(card.id))
            if can_proclaim(game, card):
                recruits.append(Recruit(card.id, proclaim=True))
        invest = invest_amounts(game, card)
        if invest is not None and base + min(invest) <= affordable:
            recruits.append(Recruit(card.id, invest=True))
    return recruits


def _equips(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """The Equip actions ``seat`` can take: each attachment in hand it can afford that some
    Personality it controls would accept.

    An attachment enters play only by attaching, so hand is a hard filter. The Personality is chosen
    through the decision the action raises, and the action is withheld unless at least one would
    take the card. ``only`` narrows to a single card."""
    if not permits(game, seat, ACTION_TIMINGS[Equip]):
        return []
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards
    fixed, variable = gold_reach(game, seat)
    equips: list[Action] = []
    for card in hand:
        if only is not None and card.id != only:
            continue
        if not isinstance(card.printed, AttachmentPrint):
            continue
        if not copy_may_enter(game, seat, card):
            continue
        affordable = fixed + sum(
            maximum_gold_production(game, producer, targets=(card,)) for producer in variable
        )
        base = effective_gold_cost(game, card)
        purchase = equip_purchase(card)
        if discounted_gold(game, purchase, base) > affordable or not equip_targets(game, card):
            continue
        equips.append(Equip(card.id))
        invest = fixed_invest_amount(game, card)
        if invest is not None and discounted_gold(game, purchase, base + invest) <= affordable:
            equips.append(Equip(card.id, invest=True))
    return equips


def _strategies(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """The Strategies ``seat`` can play: each one in hand whose designator this round permits, whose
    Gold Cost it can reach, and which has a legal target.

    Asks :func:`~yasuki_core.engine.rules.playable` for the hand, since the card's own ability
    decides when it may be played. ``only`` narrows to a single card.
    """
    return [
        PlayStrategy(card.id, ability.key)
        for card, ability in playable(game, seat, permitted_timings(game, seat))
        if (only is None or card.id == only)
        and strategy_gold(game, card, ability) <= reachable_gold(game, seat, card)
    ]


def strategy_gold(game: GameState, card: L5RCard, ability: Ability) -> int:
    """The Gold playing ``card`` for ``ability`` charges in all: its Gold Cost and the Gold its
    ability's cost adds, with the action's one discount spent across both."""
    gold_cost = discounted_gold_cost(game, ability.purchase(game, card, plays_card=True))
    added = ability.discounted_cost(game, card, plays_card=True)
    return gold_cost + sum(effect.amount for effect in added if isinstance(effect, PayGold))


def recruit_cost(game: GameState, card: L5RCard) -> int:
    """The gold a seat pays to recruit ``card``: its gold cost with modifiers, plus the off-clan
    surcharge when the card has a Clan Alignment the seat does not share, less the card's own
    conditional recruit discount. Floored at zero."""
    cost = effective_gold_cost(game, card)
    seat_aligns = seat_alignments(game, card.owner)
    card_aligns = card_alignments(card)
    if seat_aligns and card_aligns and seat_aligns.isdisjoint(card_aligns):
        cost += ruleset.ACTIVE.off_clan_surcharge
    cost -= effective_recruit_discount(game, card)
    return max(0, cost)


def proclaim_key(seat: PlayerId, turn: int) -> str:
    """The once-per-turn usage key for a seat's Proclaim, scoped to the turn so it resets each turn
    without clearing ``GameState.once_per``."""
    return f"proclaim:{seat.name}:{turn}"


def can_proclaim(game: GameState, card: L5RCard) -> bool:
    """Whether recruiting ``card`` could be Proclaimed by its seat: a Personality carrying the
    seat's Clan Alignment that the seat has not yet Proclaimed against this turn."""
    if not isinstance(card.printed, PersonalityPrint):
        return False
    seat = card.owner
    if seat is None:
        return False
    if seat_alignments(game, seat).isdisjoint(card_alignments(card)):
        return False
    return not game.has_used(proclaim_key(seat, game.turn))


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
    played stays silent until one says otherwise.
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
            yield from ((CardLocation.HAND, card) for card in zone.cards)
        elif key.role is ZoneRole.RULEBOOK:
            yield from ((CardLocation.RULEBOOK, card) for card in zone.cards)


# Every place ``seat_cards`` yields a card from. A card's own ability in hand is *played* rather
# than activated, and pays a Gold Cost to do it, so ``_played`` and ``_activated`` tell the two
# actions apart below rather than the location alone.
ACTIVATED_FROM: tuple[CardLocation, ...] = (
    CardLocation.BATTLEFIELD,
    CardLocation.PROVINCE,
    CardLocation.RULEBOOK,
    CardLocation.HAND,
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
    return _usable(game, seat, permitted, at=ACTIVATED_FROM, offered=_activated)


def playable(
    game: GameState, seat: PlayerId, permitted: frozenset[ActionTiming]
) -> list[tuple[L5RCard, Ability]]:
    """Each card in hand ``seat`` may play right now, paired with the ability it plays as, under
    the tests :func:`activatable` applies."""
    return _usable(game, seat, permitted, at=(CardLocation.HAND,), offered=_played)


def _activated(location: CardLocation, ability: Ability) -> bool:
    return location is not CardLocation.HAND or ability.from_rulebook


def _played(location: CardLocation, ability: Ability) -> bool:
    return not _activated(location, ability)


def _usable(
    game: GameState,
    seat: PlayerId,
    permitted: frozenset[ActionTiming],
    *,
    at: tuple[CardLocation, ...],
    offered: Callable[[CardLocation, Ability], bool],
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
            if location not in ability.located_at or not offered(location, ability):
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
                and _activated(location, ability)
                and not ability.repeatable
                and used_this_turn(game, card, once_tag(ability))
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
            costs = ability.discounted_cost(game, card, plays_card=_played(location, ability))
            if not payable(game, costs):
                continue
            if legal_targets(game, card, ability):
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


def legal_targets(game: GameState, card: L5RCard, ability: Ability) -> list[str]:
    """The ids ``ability`` may target from ``card`` right now.

    Filtered centrally: during a battle, a card in a unit may only be targeted at the
    battlefield the battle is at (CR, Rules of Location), unless the ``Ability`` sets
    ``targets_any_location``.
    """
    offered = ability.targets(game, card)
    attack = game.attack
    if attack is None or attack.current is None or ability.targets_any_location:
        return offered
    by_id = game.table.cards_by_id
    return [
        target_id
        for target_id in offered
        if target_id not in by_id or location_permits(game, by_id[target_id])
    ]


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
