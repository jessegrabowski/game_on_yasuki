from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BATTLEFIELD, UNPLACED_BOARD_POS, DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.pregame import StrongholdCard, SenseiCard, WindCard
from yasuki_core.game_pieces.dynasty import DynastyHolding, DynastyPersonality
from yasuki_core.engine.rules.actions import (
    ActivateAbility,
    Action,
    Cycle,
    DynastyDiscard,
    Legacy,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.state import GameState, Phase, TURN_PHASES
from yasuki_core.engine.rules.work import (
    ApplyEffects,
    ApplyAbilityEffects,
    FinishRecruit,
    ResolveRecruit,
    ResumeCascade,
    SelectAbilityTarget,
    WorkItem,
)
from yasuki_core.engine.rules.decisions import (
    BanishForLegacy,
    ChooseAbilityTarget,
    ChooseCards,
    ChooseInvestAmount,
    ChooseLegacyCard,
    ChoosePayment,
    DiscardToHandSize,
    DecisionResponse,
    PlaceLegacy,
)
from yasuki_core.engine.rules.economy import (
    effective_gold_production,
    effective_keywords,
    effective_recruit_discount,
)
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Choose,
    Discard,
    Effect,
    GrantModifier,
    MoveToDeck,
    PlaceInProvince,
    RefillProvince,
    RevealProvinces,
    ShuffleDeck,
    Then,
)
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules import abilities, triggers

# Imported for the registrations it performs; see rules/cards/__init__.py.
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.engine.rules.events import CardDiscarded, EnteredPlay, Revealed, TurnStarted
from yasuki_core.game_pieces.counters import SINCERITY
from yasuki_core.ruleset import SHATTERED_EMPIRE

# The boldface keyword marking a card the Legacy rulebook ability can search out.
LEGACY_KEYWORD = "Legacy"

# The keyword that refills a card's vacated Province face-up when it enters play (rather than the
# usual face-down), so the next card is recruitable the same turn.
RENEW_KEYWORD = "Renew"

# The default maximum hand size, enforced by the end-of-turn discard (rules-skeleton §1).
MAX_HAND_SIZE = 8

# The active ruleset: legal Clan Alignments and the off-clan surcharge.
RULESET = SHATTERED_EMPIRE
OFF_CLAN_SURCHARGE = RULESET.off_clan_surcharge


def next_phase(phase: Phase) -> Phase | None:
    """Return the phase that follows ``phase`` within a turn, or None after the last phase
    (Dynasty), where the turn ends with the fate draw."""
    index = TURN_PHASES.index(phase)
    return TURN_PHASES[index + 1] if index + 1 < len(TURN_PHASES) else None


# The pre-game permanents that get their enters-play effect fired as the game begins.
_PREGAME_PERMANENTS = (StrongholdCard, SenseiCard, WindCard)


def begin_game(game: GameState) -> None:
    """Run the game-start pass once after :meth:`GameState.start`, before the active player acts:
    fire each pre-game permanent's enters-play effect, then the first turn's housekeeping. Re-runs on
    every replay, so those effects must be idempotent."""
    _begin_pregame(game)
    _begin_turn(game)


def _begin_pregame(game: GameState) -> None:
    """Fire EnteredPlay for each pre-game permanent on the battlefield, so a Stronghold or Sensei with
    an ``@on(EnteredPlay, ...)`` trigger runs it as the game begins."""
    for card in list(game.table.battlefield.cards):
        if isinstance(card, _PREGAME_PERMANENTS):
            triggers.fire(game, EnteredPlay(card.id))


def advance(game: GameState) -> None:
    """Advance the active player's turn to the next phase; past the Dynasty phase, run the end of
    the turn and begin the next. The gold pool empties on every phase change.

    Pause instead of finishing the turn if the end-of-turn discard needs an answer: record the
    request on ``game.pending`` and return, leaving the caller to :func:`submit` a response before
    advancing again. Raise ``RuntimeError`` if called while a decision is already pending.
    """
    if game.awaiting_decision:
        raise RuntimeError("cannot advance while a decision is pending")
    game.clear_gold()
    following = next_phase(game.phase)
    if following is not None:
        game.phase = following
        return
    _end_turn(game)


def perform(game: GameState, action: Action) -> None:
    """Apply a chosen action, dispatching to its handler. The single action-apply dispatch,
    mirroring :func:`submit` for decisions. Raise ``ValueError`` for an action with no handler."""
    match action:
        case Pass():
            advance(game)
        case Recruit(card_id=card_id, invest=invest, proclaim=proclaim):
            recruit(game, card_id, invest, proclaim=proclaim)
        case DynastyDiscard(card_id=card_id):
            dynasty_discard(game, card_id)
        case Legacy():
            legacy(game)
        case Cycle():
            cycle(game)
        case ActivateAbility(card_id=card_id):
            activate(game, card_id)
        case _:
            raise ValueError(f"no handler for action {type(action).__name__}")
    # An action resolves fully before the next input; one that paused for a decision leaves its
    # remainder for the submit that answers it.
    run_stack(game)


def produce_gold(game: GameState, card_id: str, amount: int) -> None:
    """Bow the card and add ``amount`` gold to its owner's pool — the yield the payment offer quoted
    for it (KD6). Gold is only produced while paying a cost (rules-skeleton §7), so a payment drives
    this."""
    card = game.table.cards_by_id[card_id]
    card.bow()
    game.add_gold(card.owner, amount)


def gold_producers(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The unbowed gold producers ``seat`` controls in play — its Stronghold and gold Holdings —
    each a source it may bow for gold (KD6, stat-derived)."""
    return [
        card
        for card in game.table.battlefield.cards
        if card.owner is seat and not card.bowed and effective_gold_production(game, card) > 0
    ]


def reachable_gold(game: GameState, seat: PlayerId, card: L5RCard) -> int:
    """The gold ``seat`` could muster to recruit ``card``: its pool plus the yield of every unbowed
    producer — judged with ``card`` as the payment target since a producer's yield can depend on
    what it pays for — plus any bow-time boost a producer could add if the seat opts in."""
    total = game.gold[seat]
    for producer in gold_producers(game, seat):
        total += effective_gold_production(game, producer, targets=(card,))
        boost = abilities.production_boost_for(producer)
        if boost is not None:
            total += boost.amount
    return total


def _clan_names(card: L5RCard) -> tuple[str, ...]:
    """The card's printed clan names: its :attr:`clans` list, or the lone ``clan`` when that is
    empty."""
    if card.clans:
        return card.clans
    return (card.clan,) if card.clan else ()


def _card_alignments(card: L5RCard) -> set[str]:
    """The canonical Clan Alignment slugs ``card`` carries, dropping clan names that are not
    alignments in the active ruleset (minor clans, Shadowlands, "Unaligned", ...). Empty for an
    unaligned card."""
    return {slug for name in _clan_names(card) if (slug := RULESET.alignment(name)) is not None}


def _seat_alignment(game: GameState, seat: PlayerId | None) -> str | None:
    """The seat's Clan Alignment slug, taken from its Stronghold, or None when the Stronghold carries
    no legal alignment (an unaligned seat)."""
    clan = _seat_clan(game, seat)
    return RULESET.alignment(clan) if clan is not None else None


def recruit_cost(game: GameState, card: L5RCard) -> int:
    """The gold a seat pays to recruit ``card``: its printed gold cost, plus the off-clan surcharge
    when the card has a Clan Alignment the seat does not share, less the card's own conditional
    recruit discount. Floored at zero."""
    cost = card.gold_cost or 0
    seat_align = _seat_alignment(game, card.owner)
    card_aligns = _card_alignments(card)
    if seat_align is not None and card_aligns and seat_align not in card_aligns:
        cost += OFF_CLAN_SURCHARGE
    cost -= effective_recruit_discount(game, card)
    return max(0, cost)


def recruit(
    game: GameState,
    card_id: str,
    invest: bool = False,
    renew: bool = False,
    proclaim: bool = False,
) -> None:
    """Announce a Recruit: defer bringing the card into play, then pause for its cost payment. The
    payment bows gold producers to cover :func:`recruit_cost` plus any Invest cost; once answered,
    the stack resolves the move into play and the province refill.

    With ``invest`` set, also pay the card's Invest cost for its one-time enter-play effect. A fixed
    Invest folds straight into the payment; a variable one pauses first for
    :class:`ChooseInvestAmount` to pick how much to pay. With ``renew`` set, the vacated province
    refills face-up (a Renew granted by the recruiting effect). With ``proclaim`` set, claim the
    seat's once-per-turn Proclaim and add the Personality's Personal Honor to its Family Honor after
    it enters play (rules-skeleton §6); nothing is claimed until the payment resolves, so a
    cancelled Proclaim leaves it available. Raise ``ValueError`` if both ``invest`` and ``proclaim``
    are set — Invest belongs to Holdings and Proclaim to Personalities, so no card offers both."""
    if invest and proclaim:
        raise ValueError("a Recruit cannot both Invest and Proclaim")
    card = game.table.cards_by_id[card_id]
    seat = card.owner
    if not invest:
        game.pending = announce_recruit(
            game, card, seat, invest_amount=0, renew=renew, proclaim=proclaim
        )
        return
    ability = abilities.invest_for(card)
    if ability.minimum == ability.maximum:
        game.pending = announce_recruit(
            game, card, seat, invest_amount=ability.minimum, renew=renew
        )
        return
    affordable = reachable_gold(game, seat, card) - recruit_cost(game, card)
    top = min(ability.maximum, affordable)
    game.pending = ChooseInvestAmount(
        seat=seat,
        candidates=tuple(str(amount) for amount in range(ability.minimum, top + 1)),
        source_card_id=card_id,
    )


def announce_recruit(
    game: GameState,
    card: L5RCard,
    seat: PlayerId,
    invest_amount: int,
    renew: bool = False,
    proclaim: bool = False,
) -> ChoosePayment:
    """Queue the recruit and build the payment it must be paid with."""
    producers = gold_producers(game, seat)
    game.stack.append(ResolveRecruit(seat, card.id, invest_amount, renew, proclaim))
    return ChoosePayment(
        seat=seat,
        candidates=tuple(producer.id for producer in producers),
        amount=recruit_cost(game, card) + invest_amount,
        available=game.gold[seat],
        produced=tuple(
            (producer.id, effective_gold_production(game, producer, targets=(card,)))
            for producer in producers
        ),
        label=card.name,
        target_id=card.id,
        boostable=tuple(
            (producer.id, boost.amount)
            for producer in producers
            if (boost := abilities.production_boost_for(producer)) is not None
        ),
    )


def _apply_invest_amount(
    game: GameState, request: ChooseInvestAmount, response: DecisionResponse
) -> None:
    card = game.table.cards_by_id[request.source_card_id]
    game.pending = None
    game.pending = announce_recruit(game, card, card.owner, invest_amount=int(response.choices[0]))


def submit(game: GameState, response: DecisionResponse) -> None:
    """Answer the pending decision and resume the engine.

    Dispatch on the request type to its apply-handler, then continue: an end-of-turn discard begins
    the next turn, while a cost payment drains the stack to finish the action that paused for it.

    Raise ``RuntimeError`` if no decision is pending, or ``ValueError`` if the answer is malformed
    or illegal against the game state.
    """
    request = game.pending
    if request is None:
        raise RuntimeError("no decision is pending")
    if not request.accepts(response):
        raise ValueError("malformed answer to the pending decision")
    match request:
        case DiscardToHandSize():
            _apply_discard(game, request.seat, response.choices)
            game.pending = None
            _begin_next_turn(game)
        case ChoosePayment():
            _apply_payment(game, request, response)
            game.pending = None
            run_stack(game)
        case BanishForLegacy():
            _apply_legacy_banish(game, request, response)
        case ChooseLegacyCard():
            _apply_legacy_choice(game, request, response)
        case PlaceLegacy():
            _apply_legacy_placement(game, request, response)
        case ChooseAbilityTarget():
            _apply_ability_target(game, request, response)
        case ChooseCards():
            _apply_card_choice(game, request, response)
        case ChooseInvestAmount():
            _apply_invest_amount(game, request, response)
        case _:
            raise ValueError(f"no handler for decision {type(request).__name__}")
    # Symmetric with `perform`: an answered decision resolves fully before the next input.
    run_stack(game)


def cancel(game: GameState) -> None:
    """Back out of the pending decision, undoing the action that raised it.

    A Recruit's steps are cancellable, since nothing is committed until the payment is answered — no
    gold spent, no producer bowed, the card still in its province. Cancelling a payment drops its
    deferred :class:`ResolveRecruit`; cancelling an Invest amount drops the choice before the recruit
    is even announced.

    Raise ``RuntimeError`` if no decision is pending, or ``ValueError`` if the pending decision
    cannot be canceled.
    """
    request = game.pending
    if request is None:
        raise RuntimeError("no decision is pending")
    match request:
        case ChoosePayment():
            _cancel_recruit_payment(game)
        case ChooseInvestAmount():
            game.pending = None  # the recruit is not yet announced; nothing to undo
        case _:
            raise ValueError(f"{type(request).__name__} cannot be cancelled")


def _cancel_recruit_payment(game: GameState) -> None:
    if not game.stack or not isinstance(game.stack[-1], ResolveRecruit):
        raise ValueError("the pending payment has no recruit to undo")
    game.stack.pop()
    game.pending = None


def run_stack(game: GameState) -> None:
    """Drain deferred work, running each item until the stack empties or one pauses for a decision.
    A work item may itself emit a decision (setting ``pending``), so resolution stops there and
    resumes on the next :func:`submit`."""
    while game.stack and game.pending is None:
        _resolve(game, game.stack.pop())


def _resolve(game: GameState, item: WorkItem) -> None:
    match item:
        case ResolveRecruit(
            seat=seat, card_id=card_id, invest_amount=invest_amount, renew=renew, proclaim=proclaim
        ):
            _resolve_recruit(game, seat, card_id, invest_amount, renew=renew, proclaim=proclaim)
        case SelectAbilityTarget(card_id=card_id, candidates=candidates):
            owner = game.table.cards_by_id[card_id].owner
            game.pending = ChooseAbilityTarget(
                seat=owner, candidates=candidates, source_card_id=card_id
            )
        case ApplyAbilityEffects(card_id=card_id, target_ids=target_ids):
            source = game.table.cards_by_id[card_id]
            ability = abilities.ability_for(source)
            effects = [
                effect
                for target_id in target_ids
                for effect in ability.effects(source, game.table.cards_by_id[target_id])
            ]
            triggers.resolve_effects(game, effects)
        case FinishRecruit(card_id=card_id, invest_amount=invest_amount, proclaim=proclaim):
            _finish_recruit(game, card_id, invest_amount, proclaim=proclaim)
        case ResumeCascade():
            # An interrupting effect whose answer produces no effects of its own — a payment, say —
            # leaves its stash here for the generic drain. A Choose is popped by its own handler,
            # which splices the resolver's effects in.
            triggers.resume_cascade(game, item, [])
        case ApplyEffects(effects=effects):
            triggers.resolve_effects(game, list(effects))
        case _:
            raise ValueError(f"no resolver for work item {type(item).__name__}")


def _apply_payment(game: GameState, request: ChoosePayment, response: DecisionResponse) -> None:
    """Bow the chosen producers to cover the cost.

    Taking a boost is a stat change like any other: it grants the producer Gold Production for the
    turn, and the yield is then read off the card the same way an unboosted producer's is. What the
    boost costs is the card's own business, resolved once it has yielded.
    """
    target = game.table.cards_by_id.get(request.target_id)
    targets = (target,) if target is not None else ()
    boosted = set(response.boosted)
    for card_id in response.choices:
        card = game.table.cards_by_id[card_id]
        boost = abilities.production_boost_for(card) if card_id in boosted else None
        if boost is not None:
            triggers.resolve_effects(
                game,
                [
                    GrantModifier(
                        card_id,
                        card_id,
                        Stat.GOLD_PRODUCTION,
                        boost.amount,
                        Duration.UNTIL_END_OF_TURN,
                    )
                ],
            )
        produce_gold(game, card_id, effective_gold_production(game, card, targets=targets))
        if boost is not None:
            triggers.resolve_effects(game, boost.effects(card))
    game.spend_gold(request.seat, request.amount)


def _resolve_recruit(
    game: GameState,
    seat: PlayerId,
    card_id: str,
    invest_amount: int = 0,
    renew: bool = False,
    proclaim: bool = False,
) -> None:
    card = game.table.cards_by_id[card_id]
    # Read the Province before the move; afterwards no Province holds the card to look it up by.
    province_key = _province_key_holding(game, seat, card_id)
    # Enter unplaced so the client clusters the new card into the seat's home row by the stronghold,
    # rather than dropping it at the origin.
    ops.move_card(game.table, card, BATTLEFIELD, position=UNPLACED_BOARD_POS)
    if isinstance(card, DynastyHolding):
        card.bow()  # Holdings enter play bowed; Personalities enter unbowed (rules-skeleton §6)
    if province_key is not None:
        # Renew is read once the card has entered play, which is when the keyword speaks.
        renews = renew or RENEW_KEYWORD in effective_keywords(game, card)
        _defer_refill(game, province_key, face_up=renews)
    # Defer the post-entry steps so an enter-play trait that pauses for a choice resolves first.
    game.stack.append(FinishRecruit(card_id, invest_amount, proclaim))
    triggers.fire(game, EnteredPlay(card_id))


def _finish_recruit(
    game: GameState, card_id: str, invest_amount: int, proclaim: bool = False
) -> None:
    card = game.table.cards_by_id[card_id]
    _clear_sincerity(game, card)
    if proclaim:
        game.use_once(proclaim_key(card.owner, game.turn))
        ops.set_honor(game.table, card.owner, delta=card.personal_honor)
    if invest_amount:
        triggers.resolve_effects(game, abilities.invest_for(card).effect(card, invest_amount))


def _clear_sincerity(game: GameState, card: L5RCard) -> None:
    """Remove a card's Sincerity tokens once it has entered play — its trait has already read them
    during the ``EnteredPlay`` cascade (Sincerity keyword)."""
    held = card.counters.get(SINCERITY.key, 0)
    if held:
        card.adjust_counter(SINCERITY.key, -held)


def dynasty_discard(game: GameState, card_id: str) -> None:
    """Discard a face-up province card to its owner's dynasty discard and refill the province — the
    Dynasty Discard action. It has no cost, so it resolves at once with no payment."""
    card = game.table.cards_by_id[card_id]
    seat = card.owner
    province_key = _province_key_holding(game, seat, card_id)
    ops.move_card(game.table, card, ZoneKey(seat, ZoneRole.DYNASTY_DISCARD))
    if province_key is not None:
        _defer_refill(game, province_key)
    triggers.fire(game, CardDiscarded(card_id, card.side, seat))


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
    seat_align = _seat_alignment(game, seat)
    if seat_align is None or seat_align not in _card_alignments(card):
        return False
    return not game.has_used(proclaim_key(seat, game.turn))


def _defer_refill(game: GameState, zone: ZoneKey, *, face_up: bool = False) -> None:
    """Queue the refill of a Province a card has just left, behind the reactions to it leaving.

    The rules put it there: the effects triggered by the card leaving or entering play resolve
    first, and only then is the Province refilled — and only if it is still short.
    """
    game.stack.append(ApplyEffects((RefillProvince(zone, face_up=face_up),)))


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


def cycle(game: GameState) -> None:
    """Announce the Cycle ability: claim its once-per-turn use and pause for the seat to pick which
    face-up Province cards go back. The move, refill and reveal follow once the picks are in."""
    seat = game.active
    game.use_once(cycle_key(seat, game.turn))
    candidates = tuple(card.id for card in cycle_candidates(game, seat))
    triggers.resolve_effects(game, [Choose(seat, candidates, 1, len(candidates), "cycle")])


@triggers.choice_resolver(
    "cycle",
    prompt="Put face-up Province cards on the bottom of your deck — your last pick ends up lowest",
)
def _cycle_put_on_bottom(
    game: GameState, source_id: str | None, chosen: tuple[str, ...]
) -> list[Effect]:
    """Put each chosen card on the bottom in pick order, then refill the Provinces they left and
    reveal them all.

    Each card goes under the one before it, so the last pick ends up at the very bottom — the order
    the rule gives the player. The refill and the reveal are deferred together because the rule
    reveals *after* refilling, and both wait on the reactions to the cards leaving.
    """
    seat = game.table.cards_by_id[chosen[0]].owner
    # Read the Provinces before anything moves; afterwards none of them holds the card to find.
    vacated = [_province_key_holding(game, seat, card_id) for card_id in chosen]
    deck = DeckKey(seat, Side.DYNASTY)
    put_back = [MoveToDeck(card_id, deck, from_bottom=0) for card_id in chosen]
    refills = tuple(RefillProvince(key) for key in vacated if key is not None)
    return [*put_back, Then((*refills, RevealProvinces(seat)))]


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


def _reveal_search_pool(game: GameState, seat: PlayerId) -> None:
    """Let ``seat`` identify every card its Legacy search looked through. A face-down Province card
    is searched, so the seat has seen it by the time it chooses which Province to displace."""
    for card in legacy_search_pool(game, seat):
        card.add_peeker(seat)


def legacy_candidates(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Legacy cards ``seat`` could find right now — the Legacy cards within its search pool.
    Empty means a Legacy search would whiff and lose the game."""
    return [card for card in legacy_search_pool(game, seat) if is_legacy_card(game, card)]


def legacy(game: GameState) -> None:
    """Announce the Legacy ability: claim its once-per-turn use and pause for the banish cost. The
    search and placement follow once the banished card is chosen."""
    seat = game.active
    game.use_once(legacy_key(seat, game.turn))
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    game.pending = BanishForLegacy(seat=seat, candidates=tuple(card.id for card in hand.cards))


def _apply_legacy_banish(
    game: GameState, request: BanishForLegacy, response: DecisionResponse
) -> None:
    seat = request.seat
    banished = game.table.cards_by_id[response.choices[0]]
    ops.move_card(game.table, banished, ZoneKey(seat, ZoneRole.FATE_BANISH))
    game.pending = None
    _reveal_search_pool(game, seat)
    found = legacy_candidates(game, seat)
    if not found:
        game.loser = seat  # the whiff: failing to find a Legacy card loses the game
        return
    game.pending = ChooseLegacyCard(seat=seat, candidates=tuple(card.id for card in found))


def _apply_legacy_choice(
    game: GameState, request: ChooseLegacyCard, response: DecisionResponse
) -> None:
    seat = request.seat
    legacy_card = game.table.cards_by_id[response.choices[0]]
    game.pending = None
    provinces = _displaceable_provinces(game, seat, keep=legacy_card.id)
    if not provinces:
        # No province to sacrifice — only reachable at zero provinces (a military loss the engine
        # does not model yet). Reveal the found card where it sits rather than placing it.
        legacy_card.turn_face_up()
        return
    game.pending = PlaceLegacy(seat=seat, candidates=provinces, legacy_card_id=legacy_card.id)


def _apply_legacy_placement(
    game: GameState, request: PlaceLegacy, response: DecisionResponse
) -> None:
    seat = request.seat
    displaced = game.table.cards_by_id[response.choices[0]]
    legacy_card = game.table.cards_by_id[request.legacy_card_id]
    target_key = _province_key_of(game, seat, displaced.id)
    source_key = _province_key_holding(
        game, seat, legacy_card.id
    )  # None when it came from the deck
    game.pending = None
    if source_key is not None:
        _defer_refill(game, source_key)
    # One effect per occurrence, so each announces itself where it happens. Inline effects resolve
    # before the events queued behind them, so the placement still lands ahead of any reaction to
    # the discard.
    placing: list[Effect] = [
        Discard(displaced.id, seat),
        PlaceInProvince(legacy_card.id, target_key),
    ]
    if source_key is None:
        # The found card came out of the deck, so the deck the search read is no longer secret.
        placing.append(ShuffleDeck(DeckKey(seat, Side.DYNASTY)))
    triggers.resolve_effects(game, placing)


def _displaceable_provinces(game: GameState, seat: PlayerId, *, keep: str) -> tuple[str, ...]:
    """The province cards ``seat`` may discard to make room for a placed Legacy card — its face card
    in each province, skipping the province that already holds the found card (id ``keep``), which
    cannot be its own sacrifice."""
    displaceable: list[str] = []
    for key, zone in game.table.zones.items():
        if key.owner is not seat or key.role is not ZoneRole.PROVINCE or not zone.cards:
            continue
        if any(card.id == keep for card in zone.cards):
            continue
        displaceable.append(zone.cards[-1].id)
    return tuple(displaceable)


def activate(game: GameState, card_id: str) -> None:
    """Announce an activated ability: pay its cost, then resolve its target — a single chosen card,
    or every card it hits for an ``all_targets`` ability. The ability is guaranteed registered and to
    have a legal target — ``legal_actions`` only offers it then.

    Resolving the target is deferred behind the cost on the stack, so a cost whose own cascade pauses
    for a decision resolves fully first. Targets are fixed before paying (Good Faith): the candidates
    are the ones ``legal_actions`` validated, so the ability is never left with nothing to hit."""
    card = game.table.cards_by_id[card_id]
    ability = abilities.ability_for(card)
    targets = tuple(ability.targets(game, card))
    deferred = (
        ApplyAbilityEffects(card_id, targets)
        if ability.all_targets
        else SelectAbilityTarget(card_id, targets)
    )
    game.stack.append(deferred)
    triggers.resolve_effects(game, ability.cost(card))
    run_stack(game)  # resolve the target, unless the cost's cascade paused for a decision first


def _apply_ability_target(
    game: GameState, request: ChooseAbilityTarget, response: DecisionResponse
) -> None:
    source = game.table.cards_by_id[request.source_card_id]
    target = game.table.cards_by_id[response.choices[0]]
    ability = abilities.ability_for(source)
    game.pending = None
    triggers.resolve_effects(game, ability.effects(source, target))


def _apply_card_choice(game: GameState, request: ChooseCards, response: DecisionResponse) -> None:
    game.pending = None
    item = game.stack.pop()  # the ResumeCascade this choice paused, always stacked atop it
    if not isinstance(item, ResumeCascade):
        raise RuntimeError("a card choice resumed without its stashed cascade")
    resolver = triggers.CHOICE_RESOLVERS[request.resolver]
    triggers.resume_cascade(game, item, resolver(game, request.source_id, response.choices))
    run_stack(game)  # finish any work deferred behind the choice, unless it paused again


def _end_turn(game: GameState) -> None:
    seat = game.active
    _accrue_sincerity(game, seat)
    ops.draw_to_hand(game.table, seat)
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    excess = len(hand.cards) - MAX_HAND_SIZE
    if excess > 0:
        candidates = tuple(card.id for card in hand.cards)
        game.pending = DiscardToHandSize(seat, candidates, count=excess)
        return
    _begin_next_turn(game)


def _accrue_sincerity(game: GameState, seat: PlayerId) -> None:
    """Before ``seat``'s turn ends, give each face-up Sincerity card lingering in its Provinces a
    Sincerity token. A card that flushed (was recruited or discarded) or arrived face-down as a
    refill this turn is not face-up in a Province, so it does not accrue."""
    grants = [
        AdjustCounter(card.id, SINCERITY, 1)
        for key, zone in game.table.zones.items()
        if key.owner is seat and key.role is ZoneRole.PROVINCE
        for card in zone.cards
        if card.face_up and triggers.SINCERITY_KEYWORD in effective_keywords(game, card)
    ]
    triggers.resolve_effects(game, grants)


def _begin_next_turn(game: GameState) -> None:
    # Drop until-end-of-turn modifiers as the turn ends; the comprehension keeps creation order so
    # the list rebuilds identically under replay.
    game.modifiers = [m for m in game.modifiers if m.duration is not Duration.UNTIL_END_OF_TURN]
    game.turn += 1
    game.active = _other(game.active)
    game.phase = Phase.ACTION
    _begin_turn(game)


def _begin_turn(game: GameState) -> None:
    ops.straighten(game.table, game.active)
    for card_id in ops.reveal_provinces(game.table, game.active):
        triggers.fire(game, Revealed(card_id))
    triggers.fire(game, TurnStarted(game.active))


def _apply_discard(game: GameState, seat: PlayerId, card_ids: tuple[str, ...]) -> None:
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    by_id = {card.id: card for card in hand.cards}
    missing = [card_id for card_id in card_ids if card_id not in by_id]
    if missing:
        raise ValueError(f"discard names cards not in {seat.name}'s hand: {missing}")
    for card_id in card_ids:
        card = by_id[card_id]
        ops.move_card(game.table, card, ZoneKey(seat, ZoneRole.FATE_DISCARD))
        triggers.fire(game, CardDiscarded(card_id, card.side, seat))


def _seat_clan(game: GameState, seat: PlayerId) -> str | None:
    for card in game.table.battlefield.cards:
        if card.owner is seat and isinstance(card, StrongholdCard):
            return card.clan
    return None


def _province_key_holding(game: GameState, seat: PlayerId, card_id: str) -> ZoneKey | None:
    """The Province of ``seat`` holding ``card_id``, or None when none does."""
    for key, zone in game.table.zones.items():
        if key.owner is seat and key.role is ZoneRole.PROVINCE:
            if any(card.id == card_id for card in zone.cards):
                return key
    return None


def _province_key_of(game: GameState, seat: PlayerId, card_id: str) -> ZoneKey:
    """The Province of ``seat`` holding ``card_id``. Raise ValueError when none does — for callers
    that already know the card is there and would otherwise carry an impossible None."""
    key = _province_key_holding(game, seat, card_id)
    if key is None:
        raise ValueError(f"no province of {seat.name} holds card {card_id}")
    return key


def _other(seat: PlayerId) -> PlayerId:
    return PlayerId.P2 if seat is PlayerId.P1 else PlayerId.P1
