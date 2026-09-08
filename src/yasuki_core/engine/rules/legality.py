from collections.abc import Iterator

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import favor_abilities
from yasuki_core.engine.rules.abilities.costs import can_pay
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import (
    abilities_for,
    ability_for,
    fixed_invest_amount,
    invest_amounts,
)
from yasuki_core.engine.rules.actions import (
    Action,
    ACTION_TIMINGS,
    ActionTiming,
    ActivateAbility,
    BattleDesignator,
    Cycle,
    DeclareAttack,
    DynastyDiscard,
    Equip,
    Inheritance,
    KharmicDraw,
    KharmicRefill,
    Legacy,
    Lobby,
    Pass,
    PlayStrategy,
    Recruit,
    UseFavorAbility,
)
from yasuki_core.engine.rules.board import queries
from yasuki_core.engine.rules.board.clans import card_alignments, seat_alignments
from yasuki_core.engine.rules.board.queries import has_keyword, owned_holdings, province_cards
from yasuki_core.engine.rules.board.seats import seat_stronghold
from yasuki_core.engine.rules.equip import equip_targets
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.gold.discounts import effective_recruit_discount
from yasuki_core.engine.rules.gold.producers import gold_reach, reachable_gold
from yasuki_core.engine.rules.gold.self_grants import maximum_gold_production
from yasuki_core.engine.rules.rulebook import lobby
from yasuki_core.engine.rules.rulebook.lobby import lobby_amount
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.card_values import effective_personal_honor
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.engine.rules.units import has_caster, has_presence, is_spell, location_permits
from yasuki_core.engine.table import DeckKey, location_of, ZoneKey, ZoneRole
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import (
    AttachmentPrint,
    HoldingPrint,
    PersonalityPrint,
    WindPrint,
)


# What the Kharmic rulebook abilities cost to use.
KHARMIC_COST = 2

# The Gold Production the Inheritance ability grants the Holding it targets (ShE).
INHERITANCE_PRODUCTION = 3


# The active ruleset: legal Clan Alignments and the off-clan surcharge.


def timings_of(game: GameState, action: Action) -> frozenset[ActionTiming]:
    """The designators ``action`` may be taken under, empty for a pass.

    A pass is the CR's alternative to taking an action rather than an action itself, so it carries
    no designator and every Action Round accepts it. An ``ActivateAbility`` reads its designators
    off the card, which is why this is a query rather than a table: the same action is Open on one
    Holding and Dynasty on another, and a card printing "Battle/Open" carries both.

    Raise ValueError for an action with no designator rule, and for an ``ActivateAbility`` naming a
    card that has no activated ability.
    """
    if isinstance(action, Pass):
        return frozenset()
    if isinstance(action, ActivateAbility):
        card = game.table.cards_by_id[action.card_id]
        ability = ability_for(card, action.ability_key)
        if ability is None:
            raise ValueError(f"card {action.card_id} has no activated ability to time")
        return frozenset(ability.timings)
    if isinstance(action, Lobby):
        return frozenset({ruleset.ACTIVE.lobby_timing})
    if isinstance(action, UseFavorAbility):
        granted = {ability.key: ability for ability in ruleset.ACTIVE.favor_abilities}
        if action.key not in granted:
            raise ValueError(f"this arc grants no Favor ability {action.key!r}")
        return frozenset({granted[action.key].timing})
    timing = ACTION_TIMINGS.get(type(action))
    if timing is None:
        raise ValueError(f"no designator for action {type(action).__name__}")
    return frozenset({timing})


def permitted_timings(game: GameState, seat: PlayerId) -> frozenset[ActionTiming]:
    """The designators the open Action Round permits ``seat``.

    None at all during a battle for a seat with no unit at the battlefield being fought: a player
    must control one or more units there to take an action at all (CR, Rule of Presence). A seat
    permitted nothing is skipped rather than asked, which :func:`~yasuki_core.engine.rules.flow
    .yield_priority` already does for a round that permits it nothing.
    """
    if (
        game.round.kind is RoundKind.BATTLE_SEGMENT
        and not has_presence(game, seat)
        and not has_absent_ability(game, seat)
    ):
        return frozenset()
    timings = game.round.timings
    return timings.active if seat is game.active else timings.others


def permits(game: GameState, seat: PlayerId, timing: ActionTiming) -> bool:
    """Whether the open Action Round permits ``seat`` to take an action designated ``timing``."""
    return timing in permitted_timings(game, seat)


def legal_actions(game: GameState, seat: PlayerId) -> list[Action]:
    """The free actions ``seat`` may take right now: always a pass, plus every rulebook action and
    card ability whose own conditions it meets in the current phase. Empty while a decision is
    pending and for any seat but the active one.

    Gold is not a free action: it is produced only while paying a cost (rules-skeleton §7), so it
    surfaces through the Recruit's ``ChoosePayment``, never here.
    """
    if not _may_act(game, seat):
        return []
    return [
        Pass(),
        *_abilities(game, seat),
        *_cycle(game, seat),
        *_recruits(game, seat),
        *_equips(game, seat),
        *_strategies(game, seat),
        *_dynasty_discards(game, seat),
        *_legacy(game, seat),
        *_kharmic(game, seat),
        *_inheritance(game, seat),
        *_lobby(game, seat),
        *_favor_abilities(game, seat),
        *_declare_attack(game, seat),
    ]


def is_legal(game: GameState, seat: PlayerId, action: Action) -> bool:
    """Whether ``seat`` may take exactly ``action`` right now — what membership in
    :func:`legal_actions` answers, scoped to one action.

    Raise ValueError for an action carrying no legality rule.
    """
    if not _may_act(game, seat):
        return False
    match action:
        case Pass():
            return True
        case Cycle():
            return bool(_cycle(game, seat))
        case Legacy():
            return bool(_legacy(game, seat))
        case Inheritance():
            return bool(_inheritance(game, seat))
        case ActivateAbility(card_id=card_id):
            return action in _abilities(game, seat, only=card_id)
        case Recruit(card_id=card_id):
            return action in _recruits(game, seat, only=card_id)
        case Equip(card_id=card_id):
            return action in _equips(game, seat, only=card_id)
        case PlayStrategy(card_id=card_id):
            return action in _strategies(game, seat, only=card_id)
        case DynastyDiscard(card_id=card_id):
            return action in _dynasty_discards(game, seat, only=card_id)
        case KharmicDraw(card_id=card_id) | KharmicRefill(card_id=card_id):
            return action in _kharmic(game, seat, only=card_id)
        case Lobby():
            return bool(_lobby(game, seat))
        case UseFavorAbility():
            return action in _favor_abilities(game, seat)
        case DeclareAttack():
            return bool(_declare_attack(game, seat))
        case _:
            raise ValueError(f"no legality rule for action {type(action).__name__}")


def _may_act(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` may take any action at all: the game is running, nothing is awaiting an
    answer, and ``seat`` holds the opportunity in the open round."""
    return not (game.game_over or game.awaiting_decision) and seat is game.round.priority


def _abilities(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """An ActivateAbility for each card whose activated ability the seat can use now: sitting
    somewhere that ability acts from, its designator permitted by the current round, controlled,
    cost payable, and with at least one legal target. ``only`` narrows to a single card."""
    return [
        ActivateAbility(card.id, ability.key)
        for card, ability in activatable(game, seat, permitted_timings(game, seat))
        if only is None or card.id == only
    ]


def _cycle(game: GameState, seat: PlayerId) -> list[Action]:
    """The Cycle ability when the seat can take it: its first turn, not already used, and with a
    face-up Province card to put back. The rule is "one or more", so declining is not taking the
    action at all rather than taking it and choosing nothing."""
    if not permits(game, seat, ACTION_TIMINGS[Cycle]):
        return []
    if not is_first_turn(game, seat):
        return []
    if game.has_used(cycle_key(seat, game.turn)):
        return []
    return [Cycle()] if cycle_candidates(game, seat) else []


def lobby_candidates(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Personalities ``seat`` could bow to Lobby: their own, unbowed, with 1 or more Personal
    Honor, and not one printed "may not Lobby". Zero Personal Honor is the boundary the datasheet
    draws, not merely a floor."""
    return [
        card
        for card in queries.owned_personalities(game, seat)
        if not card.bowed
        and effective_personal_honor(game, card) >= 1
        and card.printed_id not in lobby.MAY_NOT_LOBBY
    ]


def _lobby(game: GameState, seat: PlayerId) -> list[Action]:
    """The Lobby ability when the seat can take it.

    ShE datasheet: "If it is your turn and you have higher Family Honor than each other player, bow
    your target unbowed Personality with 1 or more Personal Honor to take the Imperial Favor."
    Which Personality bows is chosen when the action resolves, so this offers the ability once.

    Both sides of the comparison are read through :func:`lobby_amount`, since the datasheet adjusts
    an amount by the Bonuses and Penalties on the player it is about rather than on the player
    acting. Family Honor is what this Lobby checks; a Wind's own Lobby checks something else and
    reads it the same way.
    """
    if not permits(game, seat, ruleset.ACTIVE.lobby_timing):
        return []
    if seat is not game.active:
        return []
    if game.has_used(lobby_key(seat, game.turn)):
        return []
    if not lobby.may_lobby(game, seat):
        return []
    seats = game.table.seats
    honor = lobby_amount(game, seat, seats[seat].honor)
    if any(
        lobby_amount(game, other, info.honor) >= honor
        for other, info in seats.items()
        if other is not seat
    ):
        return []
    return [Lobby()] if lobby_candidates(game, seat) else []


def has_wind(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` has a Wind in play. A deck holds at most one, and it starts there."""
    return any(
        isinstance(card.printed, WindPrint)
        for card in game.table.battlefield.cards
        if card.owner is seat
    )


def _favor_abilities(game: GameState, seat: PlayerId) -> list[Action]:
    """The arc's Favor abilities the seat can take: designator permitted, no Wind in play, the
    rulebook's own restriction met, and a Favor cost somebody can pay.

    Good Faith: the whole cost has to be payable, which is the Favor and whatever else that arc's
    ability charges. Holding the Favor is not the test, since a seat may pay with an alternate.

    A Wind bars them outright — "While you have a Wind in play, you may not take rulebook Favor
    actions, an effect which cannot be overcome by card effects" (ShE datasheet, Winds) — so no card
    registry answers to it the way :func:`lobby.may_lobby` lets cards speak to Lobbying.
    """
    if has_wind(game, seat):
        return []
    actions: list[Action] = []
    for ability in favor_abilities.available_favor_abilities():
        if not permits(game, seat, ability.timing):
            continue
        if ability.active_seat_only and seat is not game.active:
            continue
        cost = favor_abilities.favor_ability_cost(game, seat, ability.key)
        if not all(effect.is_payable(game) for effect in cost):
            continue
        actions.append(UseFavorAbility(ability.key))
    return actions


def _kharmic(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """A Kharmic action for each card the seat could spend — from hand to draw, or from a Province
    to refill it face-up — when the round permits Open actions and the seat can reach the cost. Both
    are Repeatable, so neither claims a once-per-turn key. ``only`` narrows to a single card."""
    if reachable_gold(game, seat) < KHARMIC_COST:
        return []
    actions: list[Action] = []
    if permits(game, seat, ACTION_TIMINGS[KharmicDraw]):
        actions.extend(
            KharmicDraw(card.id)
            for card in kharmic_in_hand(game, seat)
            if only is None or card.id == only
        )
    if permits(game, seat, ACTION_TIMINGS[KharmicRefill]):
        actions.extend(
            KharmicRefill(card.id)
            for card in kharmic_in_provinces(game, seat)
            if only is None or card.id == only
        )
    return actions


def is_kharmic_card(game: GameState, card: L5RCard) -> bool:
    """Whether ``card`` carries the Kharmic keyword, so a Kharmic ability can spend it."""
    return has_keyword(game, card, keywords.KHARMIC)


def kharmic_in_hand(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Kharmic cards ``seat`` holds, which the Fate Kharmic ability discards to draw."""
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    return [card for card in hand.cards if is_kharmic_card(game, card)]


def kharmic_in_provinces(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Kharmic cards face-up in ``seat``'s Provinces, which the Dynasty Kharmic ability discards
    to refill face-up. A face-down Province card is unknown to its owner, so it cannot be named."""
    return [
        card for card in province_cards(game, seat) if card.face_up and is_kharmic_card(game, card)
    ]


def _legacy(game: GameState, seat: PlayerId) -> list[Action]:
    """The Legacy ability when the seat can take it: once per turn, and only with a card in hand to
    pay the banish cost. Offered even when no Legacy card can be found — the rules make the whiff a
    loss rather than hiding the option (which would leak face-down province contents)."""
    if not permits(game, seat, ACTION_TIMINGS[Legacy]):
        return []
    if game.has_used(legacy_key(seat, game.turn)):
        return []
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    return [Legacy()] if hand.cards else []


def inheritance_key(seat: PlayerId) -> str:
    """The once-per-*game* usage key for a seat's Inheritance ability. Unscoped by turn, unlike
    :func:`legacy_key` and :func:`cycle_key`, because the ability is spent for the whole game."""
    return f"inheritance:{seat.name}"


def _inheritance(game: GameState, seat: PlayerId) -> list[Action]:
    """The Inheritance ability when the seat can take it (ShE): only for the seat that did not go
    first, once per game, and only with a Stronghold to turn over and a Holding to raise."""
    if not permits(game, seat, ACTION_TIMINGS[Inheritance]):
        return []
    if seat is game.first_player or game.has_used(inheritance_key(seat)):
        return []
    stronghold = seat_stronghold(game, seat)
    # Turning the Stronghold over is what pays for the grant, and flip_face is a no-op without a
    # back face.
    if stronghold is None or stronghold.back_card_id is None:
        return []
    if not owned_holdings(game, seat):
        return []
    return [Inheritance()]


def _declare_attack(game: GameState, seat: PlayerId) -> list[Action]:
    """A DeclareAttack when the Attack Phase's round permits it and no attack stands yet.

    One declaration per phase: the CR gives the active player a single opportunity to create an
    attack.
    """
    if game.attack is not None or not permits(game, seat, ActionTiming.ATTACK):
        return []
    return [DeclareAttack()]


def _dynasty_discards(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """A DynastyDiscard for each face-up card in the seat's provinces — the rule allows discarding
    any face-up province card, not only Holdings. ``only`` narrows to a single card."""
    if not permits(game, seat, ACTION_TIMINGS[DynastyDiscard]):
        return []
    return [
        DynastyDiscard(card.id)
        for card in province_cards(game, seat)
        if card.face_up and (only is None or card.id == only)
    ]


def _recruits(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """The Recruit actions ``seat`` can afford: each face-up Holding or Personality in its provinces
    whose cost its pool plus its unbowed producers' gold could cover. A Personality is withheld
    while its Honor Requirement is above the seat's Family Honor (a dash ``None`` never withholds;
    the check is skipped entirely when the seat ignores Honor Requirements), and adds a Proclaim
    variant when it is own-clan and the seat has not Proclaimed this turn. A Holding adds an
    Invest variant when the seat could also cover the card's Invest cost. ``only`` narrows to a
    single card."""
    if not permits(game, seat, ACTION_TIMINGS[Recruit]):
        return []
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

    An attachment enters play only by attaching, so hand is a hard filter; the Personality is chosen
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
        affordable = fixed + sum(
            maximum_gold_production(game, producer, targets=(card,)) for producer in variable
        )
        base = effective_gold_cost(game, card)
        if base > affordable or not equip_targets(game, card):
            continue
        equips.append(Equip(card.id))
        invest = fixed_invest_amount(game, card)
        if invest is not None and base + invest <= affordable:
            equips.append(Equip(card.id, invest=True))
    return equips


def _strategies(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """The Strategies ``seat`` can play: each one in hand whose designator this round permits, whose
    Gold Cost it can reach, and which has a legal target.

    The card's own ability decides when it may be played, so this asks
    :func:`~yasuki_core.engine.rules.activatable` for the hand rather than reading a fixed
    timing off the action. ``only`` narrows to a single card.
    """
    playable = activatable(game, seat, permitted_timings(game, seat), at=(CardLocation.HAND,))
    return [
        PlayStrategy(card.id, ability.key)
        for card, ability in playable
        if (only is None or card.id == only)
        and effective_gold_cost(game, card) <= reachable_gold(game, seat, card)
    ]


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


def cycle_key(seat: PlayerId, turn: int) -> str:
    """The once-per-turn usage key for a seat's Cycle ability, scoped to the turn the way
    :func:`legacy_key` is."""
    return f"cycle:{seat.name}:{turn}"


def is_first_turn(game: GameState, seat: PlayerId) -> bool:
    """Whether the current turn is ``seat``'s first. The turn counter advances while the active seat
    alternates, so the second player's first turn is turn 2."""
    return game.turn == (1 if seat is game.first_player else 2)


def cycle_candidates(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The cards ``seat`` may put on the bottom of its deck with Cycle — the face-up ones in its
    Provinces. A face-down card is not eligible, so a Province nobody has revealed stays where it
    is."""
    return [card for card in province_cards(game, seat) if card.face_up]


def lobby_key(seat: PlayerId, turn: int) -> str:
    """The once-per-turn usage key for a seat's Lobby, scoped to the turn the way :func:`legacy_key`
    is.

    Named for the Lobby action rather than for the rulebook ability, because the ShE datasheet caps
    a player at one Lobby action per turn whatever granted it, not at one use of this ability.
    """
    return f"lobby:{seat.name}:{turn}"


def legacy_key(seat: PlayerId, turn: int) -> str:
    """The once-per-turn usage key for a seat's Legacy ability, scoped to the turn so it resets each
    turn without clearing ``GameState.once_per``."""
    return f"legacy:{seat.name}:{turn}"


def is_legacy_card(game: GameState, card: L5RCard) -> bool:
    """Whether ``card`` carries the Legacy keyword, so the Legacy ability can search it out. Shrine
    of Courtesy grants itself Legacy for the second player, which is why this is not a printed
    check."""
    return has_keyword(game, card, keywords.LEGACY)


def legacy_search_pool(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """Every card ``seat``'s Legacy search looks through: its whole dynasty deck plus the face-down
    (unrevealed) cards in its provinces. Face-up province cards are already recruitable and are not
    searched. This is the pool a search dialog shows."""
    pool = list(game.table.decks[DeckKey(seat, Side.DYNASTY)].cards)
    pool.extend(card for card in province_cards(game, seat) if not card.face_up)
    return pool


def legacy_candidates(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Legacy cards ``seat`` could find right now — the Legacy cards within its search pool.
    Empty means a Legacy search would whiff and lose the game."""
    return [card for card in legacy_search_pool(game, seat) if is_legacy_card(game, card)]


def _seat_cards(game: GameState, seat: PlayerId) -> Iterator[tuple[CardLocation, L5RCard]]:
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


# Where a card is when activating it is what its ability means. A card in hand is *played* rather
# than activated, and pays a Gold Cost to do it, so it answers to its own action and is left out of
# the default.
IN_PLAY: tuple[CardLocation, ...] = (CardLocation.BATTLEFIELD, CardLocation.PROVINCE)


def activatable(
    game: GameState,
    seat: PlayerId,
    permitted: frozenset[ActionTiming],
    *,
    at: tuple[CardLocation, ...] = IN_PLAY,
) -> list[tuple[L5RCard, Ability]]:
    """Each card ``seat`` may use an ability on right now, paired with the ability it may use:
    controlled, sitting somewhere the ability acts from, its designator among ``permitted``, its
    cost payable, and with at least one legal target.

    ``at`` narrows which of those places count, and defaults to the ones a card is *in play* in.
    Playing a card out of hand asks for :data:`CardLocation.HAND` explicitly, because it is a
    different action with a cost of its own.
    """
    ready: list[tuple[L5RCard, Ability]] = []
    # Presence is the seat's, not the card's, so it is settled once rather than per card offered.
    present = has_presence(game, seat)
    for location, card in _seat_cards(game, seat):
        if location not in at:
            continue
        # The attach rule cannot settle casting alone: a Personality can stop being a Shugenja
        # after the Spell landed on him.
        if is_spell(card) and not has_caster(game, card):
            continue
        for ability in abilities_for(card):
            if permitted.isdisjoint(ability.timings):
                continue
            if not _bow_permits(card, ability):
                continue
            # The Rule of Presence is about the player, not the card, so it gates an action taken
            # from anywhere — a Strategy out of hand as much as a Personality on the board.
            if not present and BattleDesignator.ABSENT not in ability.battle:
                continue
            if ActionTiming.RESPONSE in ability.timings and card.id in game.responded:
                continue
            if location not in ability.located_at:
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
            if not can_pay(game, card, ability.cost):
                continue
            if legal_targets(game, card, ability):
                ready.append((card, ability))
    return ready


def _bow_permits(card: L5RCard, ability: Ability) -> bool:
    """Whether ``card``'s bowed state leaves ``ability`` usable: abilities on a bowed card cannot be
    used, and Tireless is the keyword that escapes it (CR, Using Abilities; Tireless)."""
    return ability.tireless or not card.bowed


def _location_lifted(game: GameState, card: L5RCard, ability: Ability) -> bool:
    """Whether one of ``ability``'s designators excuses ``card`` from the Rules of Location (ShE
    datasheet).

    Remote reaches from home or from another battlefield; Home reaches from home alone, so a card
    standing at a battlefield that is not the current one is beyond it. Neither lifts the Rule of
    Presence.
    """
    if BattleDesignator.REMOTE in ability.battle:
        return True
    if BattleDesignator.HOME in ability.battle:
        return location_of(game.table, card).is_home
    return False


def has_absent_ability(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` holds any ability it could take with no presence at the current battlefield
    (ShE, Absent). What decides whether a seat with no units there is offered the opportunity at
    all, rather than skipped."""
    return any(
        BattleDesignator.ABSENT in ability.battle and _bow_permits(card, ability)
        for _, card in _seat_cards(game, seat)
        for ability in abilities_for(card)
    )


def legal_targets(game: GameState, card: L5RCard, ability: Ability) -> list[str]:
    """The ids ``ability`` may target from ``card`` right now.

    Filtered centrally rather than by each card's own ``targets``: during a battle, a card in a unit
    may only be targeted at the battlefield the battle is at (CR, Rules of Location), and a handler
    that forgot to say so would be a silent rules bug on every card that forgot. A card printing "at
    any location" says so on its ``Ability`` instead, where the filter can see it.
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
