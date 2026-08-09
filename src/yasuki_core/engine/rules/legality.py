from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.rules.actions import (
    Action,
    ActivateAbility,
    Cycle,
    DynastyDiscard,
    Legacy,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.economy import (
    GOLD_HANDLERS,
    effective_gold_production,
    effective_keywords,
    effective_recruit_discount,
)
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules import abilities
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding, DynastyPersonality
from yasuki_core.game_pieces.pregame import StrongholdCard
from yasuki_core.ruleset import SHATTERED_EMPIRE

# The boldface keyword marking a card the Legacy rulebook ability can search out.
LEGACY_KEYWORD = "Legacy"

# The active ruleset: legal Clan Alignments and the off-clan surcharge.
RULESET = SHATTERED_EMPIRE
OFF_CLAN_SURCHARGE = RULESET.off_clan_surcharge


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
        *_dynasty_discards(game, seat),
        *_legacy(game, seat),
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
        case ActivateAbility(card_id=card_id):
            return action in _abilities(game, seat, only=card_id)
        case Recruit(card_id=card_id):
            return action in _recruits(game, seat, only=card_id)
        case DynastyDiscard(card_id=card_id):
            return action in _dynasty_discards(game, seat, only=card_id)
        case _:
            raise ValueError(f"no legality rule for action {type(action).__name__}")


def _may_act(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` may take any action at all: the game is running, nothing is awaiting an
    answer, and it is that seat's turn."""
    return not (game.game_over or game.awaiting_decision) and seat is game.active


def _abilities(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """An ActivateAbility for each in-play card whose activated ability the seat can use in the
    current phase: controlled, cost payable, and with at least one legal target. ``only`` narrows to
    a single card."""
    return [
        ActivateAbility(card.id)
        for card in abilities.activatable(game, seat, game.phase)
        if only is None or card.id == only
    ]


def _cycle(game: GameState, seat: PlayerId) -> list[Action]:
    """The Cycle ability when the seat can take it: its first turn, not already used, and with a
    face-up Province card to put back. The rule is "one or more", so declining is not taking the
    action at all rather than taking it and choosing nothing."""
    if game.phase is not Phase.ACTION:
        return []
    if not is_first_turn(game, seat):
        return []
    if game.has_used(cycle_key(seat, game.turn)):
        return []
    return [Cycle()] if cycle_candidates(game, seat) else []


def _legacy(game: GameState, seat: PlayerId) -> list[Action]:
    """The Legacy ability when the seat can take it: once per turn, and only with a card in hand to
    pay the banish cost. Offered even when no Legacy card can be found — the rules make the whiff a
    loss rather than hiding the option (which would leak face-down province contents)."""
    if game.phase is not Phase.DYNASTY:
        return []
    if game.has_used(legacy_key(seat, game.turn)):
        return []
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    return [Legacy()] if hand.cards else []


def _dynasty_discards(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """A DynastyDiscard for each face-up card in the seat's provinces — the rule allows discarding
    any face-up province card, not only Holdings. ``only`` narrows to a single card."""
    if game.phase is not Phase.DYNASTY:
        return []
    discards: list[Action] = []
    for key, zone in game.table.zones.items():
        if key.owner is not seat or key.role is not ZoneRole.PROVINCE:
            continue
        discards.extend(
            DynastyDiscard(card.id)
            for card in zone.cards
            if card.face_up and (only is None or card.id == only)
        )
    return discards


def _recruits(game: GameState, seat: PlayerId, *, only: str | None = None) -> list[Action]:
    """The Recruit actions ``seat`` can afford: each face-up Holding or Personality in its provinces
    whose cost its pool plus its unbowed producers' gold could cover. A Personality is withheld while
    its Honor Requirement is above the seat's Family Honor (a dash ``None`` never withholds; the
    check is skipped entirely when the seat ignores Honor Requirements), and adds a Proclaim variant
    when it is own-clan and the seat has not Proclaimed this turn. A Holding adds an Invest variant
    when the seat could also cover the card's Invest cost. ``only`` narrows to a single card."""
    if game.phase is not Phase.DYNASTY:
        return []
    recruits: list[Action] = []
    seat_info = game.table.seats[seat]
    honor = seat_info.honor
    enforce_honor = not seat_info.ignores_honor_requirements
    fixed, variable = gold_reach(game, seat)
    for key, zone in game.table.zones.items():
        if key.owner is not seat or key.role is not ZoneRole.PROVINCE:
            continue
        for card in zone.cards:
            if only is not None and card.id != only:
                continue
            if not (isinstance(card, (DynastyHolding, DynastyPersonality)) and card.face_up):
                continue
            if (
                enforce_honor
                and isinstance(card, DynastyPersonality)
                and card.honor_requirement is not None
                and honor < card.honor_requirement
            ):
                continue
            affordable = fixed + sum(
                effective_gold_production(game, producer, targets=(card,)) for producer in variable
            )
            base = recruit_cost(game, card)
            if base <= affordable:
                recruits.append(Recruit(card.id))
                if can_proclaim(game, card):
                    recruits.append(Recruit(card.id, proclaim=True))
            invest = abilities.invest_for(card)
            if invest is not None and base + invest.minimum <= affordable:
                recruits.append(Recruit(card.id, invest=True))
    return recruits


def gold_producers(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The unbowed gold producers ``seat`` controls in play — its Stronghold and gold Holdings —
    each a source it may bow for gold (KD6, stat-derived)."""
    return [
        card
        for card in game.table.battlefield.cards
        if card.owner is seat and not card.bowed and effective_gold_production(game, card) > 0
    ]


def gold_reach(game: GameState, seat: PlayerId) -> tuple[int, tuple[L5RCard, ...]]:
    """What ``seat`` can raise before knowing what it is paying for, split from the producers that
    still need to know.

    Only a producer with a registered gold handler can read the cards being paid for; everything else
    yields its printed Gold Production plus its modifiers whatever the target.

    Returns
    -------
    fixed : int
        The seat's pool, every target-independent producer's yield, and every bow-time boost a
        producer could add if the seat opts in.
    variable : tuple of L5RCard
        The unbowed producers whose yield may still depend on what they pay for.
    """
    fixed = game.gold[seat]
    variable: list[L5RCard] = []
    for producer in gold_producers(game, seat):
        boost = abilities.production_boost_for(producer)
        if boost is not None:
            fixed += boost.amount
        if producer.printed_id in GOLD_HANDLERS:
            variable.append(producer)
        else:
            fixed += effective_gold_production(game, producer)
    return fixed, tuple(variable)


def reachable_gold(game: GameState, seat: PlayerId, card: L5RCard) -> int:
    """The gold ``seat`` could muster to recruit ``card``: its pool plus the yield of every unbowed
    producer — judged with ``card`` as the payment target since a producer's yield can depend on
    what it pays for — plus any bow-time boost a producer could add if the seat opts in."""
    fixed, variable = gold_reach(game, seat)
    return fixed + sum(
        effective_gold_production(game, producer, targets=(card,)) for producer in variable
    )


def recruit_cost(game: GameState, card: L5RCard) -> int:
    """The gold a seat pays to recruit ``card``: its printed gold cost, plus the off-clan surcharge
    when the card has a Clan Alignment the seat does not share, less the card's own conditional
    recruit discount. Floored at zero."""
    cost = card.gold_cost or 0
    seat_align = seat_alignment(game, card.owner)
    card_aligns = card_alignments(card)
    if seat_align is not None and card_aligns and seat_align not in card_aligns:
        cost += OFF_CLAN_SURCHARGE
    cost -= effective_recruit_discount(game, card)
    return max(0, cost)


def proclaim_key(seat: PlayerId, turn: int) -> str:
    """The once-per-turn usage key for a seat's Proclaim, scoped to the turn so it resets each turn
    without clearing ``GameState.once_per``."""
    return f"proclaim:{seat.name}:{turn}"


def can_proclaim(game: GameState, card: L5RCard) -> bool:
    """Whether recruiting ``card`` could be Proclaimed by its seat: a Personality carrying the seat's
    Clan Alignment that the seat has not yet Proclaimed against this turn."""
    if not isinstance(card, DynastyPersonality):
        return False
    seat = card.owner
    seat_align = seat_alignment(game, seat)
    if seat_align is None or seat_align not in card_alignments(card):
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
    return [
        card
        for key, zone in game.table.zones.items()
        if key.owner is seat and key.role is ZoneRole.PROVINCE
        for card in zone.cards
        if card.face_up
    ]


def legacy_key(seat: PlayerId, turn: int) -> str:
    """The once-per-turn usage key for a seat's Legacy ability, scoped to the turn so it resets each
    turn without clearing ``GameState.once_per``."""
    return f"legacy:{seat.name}:{turn}"


def is_legacy_card(game: GameState, card: L5RCard) -> bool:
    """Whether ``card`` carries the Legacy keyword, printed or granted by its own ability (Shrine of
    Courtesy grants itself Legacy for the second player), so the Legacy ability can search it out."""
    wanted = LEGACY_KEYWORD.lower()
    return any(keyword.lower() == wanted for keyword in effective_keywords(game, card))


def legacy_search_pool(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """Every card ``seat``'s Legacy search looks through: its whole dynasty deck plus the face-down
    (unrevealed) cards in its provinces. Face-up province cards are already recruitable and are not
    searched. This is the pool a search dialog shows."""
    pool = list(game.table.decks[DeckKey(seat, Side.DYNASTY)].cards)
    for key, zone in game.table.zones.items():
        if key.owner is seat and key.role is ZoneRole.PROVINCE:
            pool.extend(card for card in zone.cards if not card.face_up)
    return pool


def legacy_candidates(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Legacy cards ``seat`` could find right now — the Legacy cards within its search pool.
    Empty means a Legacy search would whiff and lose the game."""
    return [card for card in legacy_search_pool(game, seat) if is_legacy_card(game, card)]


def seat_clan(game: GameState, seat: PlayerId | None) -> str | None:
    """The clan printed on ``seat``'s Stronghold, or None when it has none in play."""
    for card in game.table.battlefield.cards:
        if card.owner is seat and isinstance(card, StrongholdCard):
            return card.clan
    return None


def seat_alignment(game: GameState, seat: PlayerId | None) -> str | None:
    """The seat's Clan Alignment slug, taken from its Stronghold, or None when the Stronghold carries
    no legal alignment (an unaligned seat)."""
    clan = seat_clan(game, seat)
    return RULESET.alignment(clan) if clan is not None else None


def card_alignments(card: L5RCard) -> set[str]:
    """The canonical Clan Alignment slugs ``card`` carries, dropping clan names that are not
    alignments in the active ruleset (minor clans, Shadowlands, "Unaligned", ...). Empty for an
    unaligned card."""
    return {slug for name in _clan_names(card) if (slug := RULESET.alignment(name)) is not None}


def _clan_names(card: L5RCard) -> tuple[str, ...]:
    """The card's printed clan names: its :attr:`clans` list, or the lone ``clan`` when that is
    empty."""
    if card.clans:
        return card.clans
    return (card.clan,) if card.clan else ()


def province_key_holding(game: GameState, seat: PlayerId, card_id: str) -> ZoneKey | None:
    """The Province of ``seat`` holding ``card_id``, or None when none does."""
    for key, zone in game.table.zones.items():
        if key.owner is seat and key.role is ZoneRole.PROVINCE:
            if any(card.id == card_id for card in zone.cards):
                return key
    return None


def province_key_of(game: GameState, seat: PlayerId, card_id: str) -> ZoneKey:
    """The Province of ``seat`` holding ``card_id``. Raise ValueError when none does — for callers
    that already know the card is there and would otherwise carry an impossible None."""
    key = province_key_holding(game, seat, card_id)
    if key is None:
        raise ValueError(f"no province of {seat.name} holds card {card_id}")
    return key
