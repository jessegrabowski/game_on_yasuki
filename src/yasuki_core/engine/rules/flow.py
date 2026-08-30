from dataclasses import replace

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.table import BATTLEFIELD, UNPLACED_BOARD_POS, DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.engine.rules.actions import (
    ActivateAbility,
    Action,
    ActionTiming,
    Cycle,
    DeclareAttack,
    DynastyDiscard,
    Equip,
    Inheritance,
    KharmicDraw,
    KharmicRefill,
    Legacy,
    Pass,
    PlayStrategy,
    Recruit,
)
from yasuki_core.engine.rules.state import (
    ActionRound,
    END_OF_TURN,
    GameState,
    Moment,
    PHASE_TIMINGS,
    Phase,
    RESPONSE_TIMINGS,
    TURN_PHASES,
)
from yasuki_core.engine.rules.work import (
    ApplyEffects,
    DiscardPlayed,
    FightNextBattle,
    ResolveStrategy,
    CompleteProduction,
    ContinuePayment,
    ApplyAbilityEffects,
    FinishRecruit,
    ResolveEquip,
    ResolveRecruit,
    ResumeCascade,
    SelectAbilityTarget,
    WorkItem,
)
from yasuki_core.engine.rules.decisions import (
    AssignUnits,
    ChooseAmount,
    ChooseBattlefield,
    ChooseOption,
    LeaveBowed,
    BanishForLegacy,
    ChooseAbilityTarget,
    ChooseCards,
    ChooseDistribution,
    ChooseEquipTarget,
    ChooseFortificationProvince,
    ChooseInheritanceTarget,
    Confirm,
    ChooseInvestAmount,
    ChooseLegacyCard,
    ChoosePayment,
    DiscardToHandSize,
    DecisionResponse,
    PlaceLegacy,
)
from yasuki_core.engine.rules.equip import equip_targets
from yasuki_core.engine.rules.economy import (
    effective_gold_cost,
    effective_gold_production,
    effective_keywords,
    effective_personal_honor,
)
from yasuki_core.engine.rules.legality import (
    INHERITANCE_PRODUCTION,
    KHARMIC_COST,
    cycle_candidates,
    cycle_key,
    legacy_candidates,
    legacy_key,
    legacy_search_pool,
    permitted_timings,
    inheritance_key,
    proclaim_key,
    province_key_holding,
    province_zones,
    province_key_of,
    reachable_gold,
    recruit_cost,
    seat_holdings,
    seat_stronghold,
)
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Choose,
    Discard,
    DrawCard,
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
from yasuki_core.engine.rules.payments import payment_request
from yasuki_core.engine.rules import abilities, battle, triggers

# Imported for the registrations it performs; see rules/cards/__init__.py.
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.engine.rules.events import (
    CardDiscarded,
    EnteredPlay,
    ProducedGold,
    ProducingGold,
    Revealed,
    Straightened,
    TurnStarted,
)
from yasuki_core.game_pieces.counters import SINCERITY
from yasuki_core.game_pieces.prints import SenseiPrint, StrongholdPrint, WindPrint

# The default maximum hand size, enforced by the end-of-turn discard (rules-skeleton §1).
MAX_HAND_SIZE = 8


def next_phase(phase: Phase) -> Phase | None:
    """Return the phase that follows ``phase`` within a turn, or None after the last phase
    (Dynasty), where the turn ends with the fate draw."""
    index = TURN_PHASES.index(phase)
    return TURN_PHASES[index + 1] if index + 1 < len(TURN_PHASES) else None


# The pre-game permanents that get their enters-play effect fired as the game begins.
_PREGAME_PERMANENTS = (StrongholdPrint, SenseiPrint, WindPrint)


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
        if isinstance(card.printed, _PREGAME_PERMANENTS):
            triggers.fire(game, EnteredPlay(card.id))


def advance(game: GameState) -> None:
    """Advance the active player's turn to the next phase; past the Dynasty phase, run the end of
    the turn and begin the next. The gold pool empties on every phase change.

    Pause instead of finishing the turn if the end-of-turn discard needs an answer: record the
    request on ``game.pending`` and return, leaving the caller to :func:`submit` a response before
    advancing again. That discard is the only question the end of a turn may ask — raise
    ``RuntimeError`` if a delayed effect asks one of its own, and if called while a decision is
    already pending.
    """
    if game.awaiting_decision:
        raise RuntimeError("cannot advance while a decision is pending")
    game.clear_gold()
    if game.phase is Phase.ACTION:
        _lift_straighten_delays(game)
    elif game.phase is Phase.BATTLE:
        battle.end_attack_phase(game)
    following = next_phase(game.phase)
    if following is not None:
        game.phase = following
        open_round(game)
        return
    _end_turn(game)


def _lift_straighten_delays(game: GameState) -> None:
    """Free the active seat's cards that were forbidden to straighten, now its Action Phase is over.

    Only a *later* Action Phase than the one the delay began on counts: a card bowed to pay for an
    Action is forbidden until the seat's next Action Phase, not the rest of this one. A card that has
    left the table takes its delay with it — nothing it could be forbidden from is left.
    """
    by_id = game.table.cards_by_id
    game.straighten_delayed = {
        card_id: imposed
        for card_id, imposed in game.straighten_delayed.items()
        if (card := by_id.get(card_id)) is not None
        and not (card.owner is game.active and game.turn > imposed)
    }


def forget_action(game: GameState) -> None:
    """Drop the record of the action last resolved, so nothing outside one is read back as one.

    A Response asks what the action it follows did. Anything still recorded across a turn or phase
    boundary is not that, and would let a Step open on an action two turns gone.
    """
    game.action_events.clear()
    game.action_taken = ""


def open_round(game: GameState) -> None:
    """Open the Action Round for the current phase, giving the active seat the first opportunity."""
    game.round_stack.clear()
    forget_action(game)
    game.round = ActionRound(timings=PHASE_TIMINGS[game.phase], priority=game.active)


def yield_priority(game: GameState, *, passed: bool) -> None:
    """Hand the opportunity to act to the next seat in turn order, closing the round once every seat
    has passed consecutively.

    A pass counts toward closing; taking an action resets the count. A seat the round permits nothing
    never receives the opportunity, and counts as having passed.
    """
    seats = list(game.table.seats)
    passes = game.round.passes + 1 if passed else 0
    after = seats.index(game.round.priority) + 1
    for seat in seats[after:] + seats[:after]:
        if passes >= len(seats):
            break
        # Permitted-but-idle still gets asked: whether to decline a window is the seat's own call,
        # and auto-passing on its behalf is a strategy its policy owns, not a rule of the round.
        if permitted_timings(game, seat):
            game.round = replace(game.round, priority=seat, passes=passes)
            return
        passes += 1
    if game.round_stack:
        close_response_window(game)
        return
    advance(game)


# How each action reads when a Response Step names the thing it answers. A Response is taken against
# an action, so the wording is the action's rather than any one effect it had.
_ACTION_WORDING: dict[type, str] = {
    Recruit: "the Recruit of",
    Equip: "the Equip of",
    ActivateAbility: "the ability on",
    DynastyDiscard: "the discard of",
    KharmicDraw: "the Kharmic draw on",
    KharmicRefill: "the Kharmic refill on",
    Legacy: "Legacy",
    Cycle: "Cycle",
    DeclareAttack: "the attack",
}


def describe_action(game: GameState, action: Action) -> str:
    """``action`` worded for a player — "the Recruit of Courts of Otosan Uchi"."""
    wording = _ACTION_WORDING.get(type(action), type(action).__name__)
    card = game.table.cards_by_id.get(getattr(action, "card_id", ""))
    return f"{wording} {card.name}" if card is not None else wording


def perform(game: GameState, action: Action) -> None:
    """Apply a chosen action, dispatching to its handler. The single action-apply dispatch,
    mirroring :func:`submit` for decisions. Raise ``ValueError`` for an action with no handler."""
    if not isinstance(action, Pass) and not game.round_stack:
        game.action_events.clear()
        game.action_taken = describe_action(game, action)
    match action:
        case Pass():
            yield_priority(game, passed=True)
        case Recruit(card_id=card_id, invest=invest, proclaim=proclaim):
            recruit(game, card_id, invest, proclaim=proclaim)
        case Equip(card_id=card_id, invest=invest):
            equip(game, card_id, invest=invest)
        case DynastyDiscard(card_id=card_id):
            dynasty_discard(game, card_id)
        case Legacy():
            legacy(game)
        case Inheritance():
            inheritance(game)
        case Cycle():
            cycle(game)
        case KharmicDraw(card_id=card_id):
            kharmic_draw(game, card_id)
        case KharmicRefill(card_id=card_id):
            kharmic_refill(game, card_id)
        case ActivateAbility(card_id=card_id):
            activate(game, card_id)
        case PlayStrategy(card_id=card_id):
            play_strategy(game, card_id)
        case DeclareAttack():
            battle.declare_attack(game)
            battle.open_maneuvers(game)
        case _:
            raise ValueError(f"no handler for action {type(action).__name__}")
    # An action resolves fully before the next input; one that paused for a decision leaves its
    # remainder for the submit that answers it.
    run_stack(game)
    if not isinstance(action, Pass):
        _yield_after_action(game)


def play_strategy(game: GameState, card_id: str) -> None:
    """Announce a Strategy: defer its resolution, then pause for its Gold Cost.

    The card stays in hand until the payment is answered, so backing out of the payment leaves it
    there — the unwind truncates the tape to before the announcement and replays, and a card that
    never moved needs nothing put back.
    """
    card = game.table.cards_by_id[card_id]
    seat = card.owner
    game.stack.append(ResolveStrategy(card_id))
    game.pending = payment_request(
        game, seat, effective_gold_cost(game, card), card.name, target=card
    )


def _resolve_strategy(game: GameState, card_id: str) -> None:
    """Resolve a paid-for Strategy: its ability against its target, and then its discard.

    The discard is stacked *under* the ability's own work so it runs after it, whether the ability
    hits every target at once or pauses to be pointed at one.
    """
    card = game.table.cards_by_id[card_id]
    ability = abilities.ability_for(card)
    if ability is None:
        raise ValueError(f"{card_id} has no ability to resolve")
    game.stack.append(DiscardPlayed(card_id))
    _defer_ability(game, card, ability)


def _discard_played(game: GameState, card_id: str) -> None:
    """Discard a card whose play has finished, unless it has already left the hand.

    Step F discards the played card "unless it is now in play" (CR, Action Sequence) — a Terrain, a
    Kata or an Edict reaches the board as the thing its own text does. A card that banished itself has
    left by another road, and discarding it would drag it back out of the pile it chose, so the
    test is whether it is still in hand rather than whether it reached the board.
    """
    card = game.table.cards_by_id[card_id]
    if card not in game.table.zones[ZoneKey(card.owner, ZoneRole.HAND)].cards:
        return
    triggers.resolve_effects(game, [Discard(card_id, card.owner)])


def produce_gold(game: GameState, card_id: str, target_ids: tuple[str, ...] = ()) -> None:
    """Open the producer's window, then bow it and add its yield to its owner's pool (KD6).

    Gold is only produced while paying a cost (rules-skeleton §7), so a payment drives this. The
    yield is read after the window rather than quoted up front, because a trait firing there can
    raise it, and announced through ``ProducedGold`` afterwards, because a price payable once the
    card has bowed cannot resolve while the yield is still unread.

    The read is deferred onto the stack rather than run inline so that a window trait may pause for
    a decision: the yield is then taken on the far side of whatever the seat answers.
    """
    card = game.table.cards_by_id[card_id]
    game.stack.append(CompleteProduction(card_id, target_ids))
    triggers.fire(game, ProducingGold(card_id, card.owner))


def _complete_production(game: GameState, card_id: str, target_ids: tuple[str, ...]) -> None:
    """Bow the producer for whatever it is worth now, and announce what it made."""
    card = game.table.cards_by_id[card_id]
    targets = tuple(game.table.cards_by_id[tid] for tid in target_ids)
    amount = effective_gold_production(game, card, targets=targets)
    card.bow()
    game.add_gold(card.owner, amount)
    triggers.fire(game, ProducedGold(card_id, card.owner, amount))


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
            game, card, seat, invest_amount=None, renew=renew, proclaim=proclaim
        )
        return
    amounts = abilities.invest_amounts(game, card)
    affordable = reachable_gold(game, seat, card) - recruit_cost(game, card)
    payable = tuple(amount for amount in amounts if amount <= affordable)
    if len(payable) == 1:
        game.pending = announce_recruit(game, card, seat, invest_amount=payable[0], renew=renew)
        return
    game.pending = ChooseInvestAmount(
        seat=seat,
        candidates=tuple(str(amount) for amount in payable),
        source_card_id=card_id,
    )


def announce_recruit(
    game: GameState,
    card: L5RCard | L5RCard,
    seat: PlayerId,
    invest_amount: int | None,
    renew: bool = False,
    proclaim: bool = False,
) -> ChoosePayment:
    """Queue the recruit and build the payment it must be paid with."""
    game.stack.append(ResolveRecruit(seat, card.id, invest_amount, renew, proclaim))
    amount = recruit_cost(game, card) + (invest_amount or 0)
    return payment_request(game, seat, amount, card.name, target=card)


def equip(game: GameState, card_id: str, *, invest: bool = False) -> None:
    """Announce an Equip by asking which Personality the card joins. Answering that raises the cost.

    Equip is the rulebook action, with a cost and a target. An effect that merely *attaches* a card
    reaches the same board without paying (CR, Equip), so the two do not share a path.

    Raise ``ValueError`` if ``invest`` names an Invest whose amount the player chooses. Every
    attachment printing one prints a fixed cost, so the amount is settled here rather than through a
    decision, and a variable one would need a step this path does not have.
    """
    card = game.table.cards_by_id[card_id]
    game.pending = ChooseEquipTarget(
        seat=card.owner,
        candidates=tuple(target.id for target in equip_targets(game, card)),
        source_card_id=card_id,
        invest_amount=_equip_invest_amount(game, card) if invest else None,
    )


def _finish_invest(game: GameState, card: L5RCard, invest_amount: int | None) -> None:
    """Charge ``card``'s Invest against itself and run what it bought. None is a card recruited
    without the option, which a free Invest is not — a card whose own text drops its Invest to zero
    still buys what the Invest buys.

    Invest belongs to a card entering play rather than to the action that brought it (CR, Invest),
    so Recruit and Equip reach this by the same road.
    """
    if invest_amount is None:
        return
    triggers.resolve_effects(
        game,
        [
            GrantModifier(card.id, card.id, Stat.GOLD_COST, invest_amount, Duration.PERMANENT),
            *abilities.invest_for(card).effect(game, card, invest_amount),
        ],
    )


def _equip_invest_amount(game: GameState, card: L5RCard) -> int:
    """The Invest cost ``card`` charges to Equip with."""
    amount = abilities.fixed_invest_amount(game, card)
    if amount is None:
        raise ValueError(f"{card.id} prints no fixed Invest for Equip to charge")
    return amount


def inheritance(game: GameState) -> None:
    """Announce the Inheritance ability by asking which Holding it raises. ``legal_actions`` has
    already checked the seat did not go first, has not spent the ability, and has both a Stronghold
    to turn over and a Holding to raise."""
    seat = game.active
    game.pending = ChooseInheritanceTarget(
        seat=seat,
        candidates=tuple(card.id for card in seat_holdings(game, seat)),
    )


def _apply_inheritance_target(
    game: GameState, request: ChooseInheritanceTarget, response: DecisionResponse
) -> None:
    """Spend the once-per-game use, turn the Stronghold over, and raise the chosen Holding.

    The Stronghold turns over rather than to a named face: a seat whose Stronghold a card has
    already flipped turns it back (ShE, The Inheritance Rule).
    """
    seat = request.seat
    game.pending = None
    game.use_once(inheritance_key(seat))
    stronghold = seat_stronghold(game, seat)
    stronghold.flip_face()
    triggers.resolve_effects(
        game,
        [
            GrantModifier(
                source_id=stronghold.id,
                target_id=response.choices[0],
                stat=Stat.GOLD_PRODUCTION,
                amount=INHERITANCE_PRODUCTION,
                duration=Duration.UNTIL_END_OF_TURN,
            )
        ],
    )


def _apply_equip_target(
    game: GameState, request: ChooseEquipTarget, response: DecisionResponse
) -> None:
    """Take the chosen Personality and put the Equip's cost to the seat."""
    card = game.table.cards_by_id[request.source_card_id]
    game.pending = announce_equip(
        game, card, card.owner, response.choices[0], invest_amount=request.invest_amount
    )


def announce_equip(
    game: GameState, card: L5RCard, seat: PlayerId, target_id: str, invest_amount: int | None = None
) -> ChoosePayment:
    """Queue the attach and build the payment it must be paid with."""
    game.stack.append(ResolveEquip(card.id, target_id, invest_amount))
    amount = effective_gold_cost(game, card) + (invest_amount or 0)
    return payment_request(game, seat, amount, card.name, target=card)


def _resolve_equip(
    game: GameState, card_id: str, target_id: str, invest_amount: int | None = None
) -> None:
    """Bring the paid-for attachment out of hand and onto its Personality."""
    card = game.table.cards_by_id[card_id]
    ops.move_card(game.table, card, BATTLEFIELD, position=UNPLACED_BOARD_POS)
    ops.attach_to_personality(game.table, card, game.table.cards_by_id[target_id])
    # Legal before anything is told it arrived, for the reason _put_into_play gives.
    triggers.enforce_state_rules(game)
    triggers.fire(game, EnteredPlay(card_id, from_hand=True))
    _finish_invest(game, card, invest_amount)


def announce_rulebook_cost(
    game: GameState, seat: PlayerId, amount: int, label: str, effects: tuple[Effect, ...]
) -> ChoosePayment:
    """Queue ``effects`` behind a gold cost that no card stands behind, and build the payment.

    A rulebook ability charges the player rather than pricing a card, so the payment carries no
    target and every producer is quoted at what it makes for nobody in particular.
    """
    game.stack.append(ApplyEffects(effects))
    return payment_request(game, seat, amount, label)


def _apply_invest_amount(
    game: GameState, request: ChooseInvestAmount, response: DecisionResponse
) -> None:
    card = game.table.cards_by_id[request.source_card_id]
    game.pending = None
    game.pending = announce_recruit(game, card, card.owner, invest_amount=int(response.choices[0]))


# The decisions that are steps of the turn rather than actions taken in a round: the end-of-turn
# discard, and the turn-start choice of what to leave bowed. Every new DecisionRequest owes an
# answer to which of the two it is.
_TURN_STRUCTURE = (DiscardToHandSize, LeaveBowed)


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
        case LeaveBowed():
            game.pending = None
            _open_turn(game, frozenset(response.choices))
        case ChoosePayment():
            # Cleared first: paying resolves the boost prices, and one that asks a question leaves
            # its decision on `pending` for the seat to answer next.
            game.pending = None
            _apply_payment(game, request, response)
            run_stack(game)
        case BanishForLegacy():
            _apply_legacy_banish(game, request, response)
        case ChooseLegacyCard():
            _apply_legacy_choice(game, request, response)
        case PlaceLegacy():
            _apply_legacy_placement(game, request, response)
        case ChooseAbilityTarget():
            _apply_ability_target(game, request, response)
        case ChooseEquipTarget():
            _apply_equip_target(game, request, response)
        case ChooseInheritanceTarget():
            _apply_inheritance_target(game, request, response)
        case ChooseFortificationProvince():
            _apply_fortification_province(game, request, response)
        case ChooseCards():
            _apply_card_choice(game, request, response)
        case ChooseAmount():
            _apply_card_choice(game, request, response)
        case ChooseOption():
            _apply_card_choice(game, request, response)
        case ChooseDistribution():
            _apply_card_choice(game, request, response)
        # One case per union member, so the exhaustiveness guard can read them off the AST.
        case Confirm():
            _apply_card_choice(game, request, response)
        case ChooseInvestAmount():
            _apply_invest_amount(game, request, response)
        case AssignUnits():
            battle.apply_assignment(game, request, response)
        case ChooseBattlefield():
            game.pending = None
            battle.fight_battle(game, int(response.choices[0]))
        case _:
            raise ValueError(f"no handler for decision {type(request).__name__}")
    # Symmetric with `perform`: an answered decision resolves fully before the next input.
    run_stack(game)
    # Turn structure is not an action: the round these resolve into is not one an action would
    # yield in, because the turn they belong to is either already over or has not opened yet.
    if not isinstance(request, _TURN_STRUCTURE):
        _yield_after_action(game)


def cancel(game: GameState) -> None:
    """Replay a recorded ``Cancel``, dropping the work the decision was queued in front of.

    Live play does not reach this: :meth:`EngineSession.abort` unwinds by truncating the tape, so no
    new ``Cancel`` is ever written. It stays to replay tapes that already hold one.

    Raise ``RuntimeError`` if no decision is pending, or ``ValueError`` if the pending decision
    cannot be canceled.
    """
    request = game.pending
    if request is None:
        raise RuntimeError("no decision is pending")
    match request:
        case ChoosePayment():
            _cancel_payment(game)
        case ChooseInvestAmount():
            game.pending = None  # the recruit is not yet announced; nothing to undo
        case _:
            raise ValueError(f"{type(request).__name__} cannot be cancelled")


def _cancel_payment(game: GameState) -> None:
    """Drop the work the cancelled payment stands in front of, whatever queued it — a Recruit's
    :class:`ResolveRecruit` or a rulebook cost's :class:`ApplyEffects`.

    The item is always the top of the stack: announcing a cost pushes exactly one, and the engine is
    paused on the payment from that moment until it is answered or cancelled, so nothing can have
    pushed since.
    """
    if not game.stack:
        raise ValueError("the pending payment has no queued work to undo")
    game.stack.pop()
    game.pending = None


def run_stack(game: GameState) -> None:
    """Drain deferred work, running each item until the stack empties or one pauses for a decision.
    A work item may itself emit a decision (setting ``pending``), so resolution stops there and
    resumes on the next :func:`submit`. Once the board settles, every Province standing short
    refills.
    """
    while game.stack and game.pending is None:
        _resolve(game, game.stack.pop())
    if game.pending is None:
        _refill_short_provinces(game)


def _refill_short_provinces(game: GameState) -> None:
    """Refill every Province standing short, face-down, as far as the Dynasty decks reach.

    A Province refills because it is empty, whatever emptied it. The refills the rules time
    explicitly — a Renew's face-up arrival, Kharmic's — resolve inside the cascade and land first,
    leaving nothing short here.
    """
    for key, zone in game.table.zones.items():
        if key.role is ZoneRole.PROVINCE and zone.has_capacity():
            ops.fill_province(game.table, key.owner, zone)


def _resolve(game: GameState, item: WorkItem) -> None:
    match item:
        case ResolveRecruit(
            seat=seat, card_id=card_id, invest_amount=invest_amount, renew=renew, proclaim=proclaim
        ):
            _resolve_recruit(game, seat, card_id, invest_amount, renew=renew, proclaim=proclaim)
        case ResolveEquip(card_id=card_id, target_id=target_id, invest_amount=invest_amount):
            _resolve_equip(game, card_id, target_id, invest_amount)
        case ResolveStrategy(card_id=card_id):
            _resolve_strategy(game, card_id)
        case DiscardPlayed(card_id=card_id):
            _discard_played(game, card_id)
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
                for effect in ability.effects(game, source, game.table.cards_by_id[target_id])
            ]
            triggers.resolve_effects(game, effects)
        case FinishRecruit(card_id=card_id, invest_amount=invest_amount, proclaim=proclaim):
            _finish_recruit(game, card_id, invest_amount, proclaim=proclaim)
        case CompleteProduction(card_id=card_id, target_ids=target_ids):
            _complete_production(game, card_id, target_ids)
        case ContinuePayment(seat=seat, amount=amount, label=label, target_id=target_id):
            _continue_payment(game, seat, amount, label, target_id)
        case ResumeCascade():
            # An interrupting effect whose answer produces no effects of its own — a payment, say —
            # leaves its stash here for the generic drain. A Choose is popped by its own handler,
            # which splices the resolver's effects in.
            triggers.resume_cascade(game, item, [])
        case ApplyEffects(effects=effects):
            triggers.resolve_effects(game, list(effects))
        case FightNextBattle():
            battle.fight_next_battle(game)
        case _:
            raise ValueError(f"no resolver for work item {type(item).__name__}")


def _apply_payment(game: GameState, request: ChoosePayment, response: DecisionResponse) -> None:
    """Bow the producer the answer names, adding what it makes to the seat's pool.

    An answer names at most one — none when the pool already covers the cost — and the payment comes
    back round for whatever is still owed.

    Nothing here knows what a producer is worth. A card that can raise its own yield is asked in the
    window :func:`produce_gold` opens, and what it owes for saying yes is settled on the far side of
    the bow — both the card's own business, neither the payment's.
    """
    target_ids = (request.target_id,) if request.target_id in game.table.cards_by_id else ()
    for card_id in response.choices:
        produce_gold(game, card_id, target_ids)


def _continue_payment(
    game: GameState, seat: PlayerId, amount: int, label: str, target_id: str
) -> None:
    """Spend once ``seat``'s pool covers ``amount``, or ask it to bow more producers.

    Raise ``RuntimeError`` if what is left unbowed can no longer reach the cost. Affordability
    decided the action was payable before it was announced, so arriving here means that projection
    was wrong — the alternative is a seat stranded on a question with no legal answer, or handed
    what it was paying for at no charge.
    """
    if game.gold[seat] >= amount:
        game.spend_gold(seat, amount)
        return
    # The authoritative reachability check. `ChoosePayment.accepts` asks the same question of its
    # own snapshot, which is what greys out an answer before it is sent; this one asks the live
    # board, and the two can differ when an answer changes what another producer is worth.
    target = game.table.cards_by_id.get(target_id)
    if reachable_gold(game, seat, target) < amount:
        raise RuntimeError(
            f"{seat.name} cannot cover {amount} for {label}: the pool holds {game.gold[seat]} "
            f"and everything still unbowed cannot make up the difference"
        )
    game.pending = payment_request(game, seat, amount, label, target=target)


def _resolve_recruit(
    game: GameState,
    seat: PlayerId,
    card_id: str,
    invest_amount: int | None = None,
    renew: bool = False,
    proclaim: bool = False,
) -> None:
    card = game.table.cards_by_id[card_id]
    # Read the Province before the move; afterwards no Province holds the card to look it up by.
    province_key = province_key_holding(game, seat, card_id)
    # Enter unplaced so the client clusters the new card into the seat's home row by the stronghold,
    # rather than dropping it at the origin.
    ops.move_card(game.table, card, BATTLEFIELD, position=UNPLACED_BOARD_POS)
    if abilities.enters_play_bowed(card):
        card.bow()  # Holdings enter play bowed; Personalities enter unbowed (rules-skeleton §6)
    fortification = keywords.FORTIFICATION in effective_keywords(game, card)
    if province_key is not None:
        if fortification:
            ops.attach_to_province(game.table, card, province_key)
        # Renew is read once the card has entered play, which is when the keyword speaks.
        renews = renew or keywords.RENEW in effective_keywords(game, card)
        _defer_refill(game, province_key, face_up=renews)
    elif fortification:
        # Brought in from somewhere other than a Province, so its controller picks one (CR,
        # Fortification). Nothing is told it arrived until it has a Province to have arrived at.
        game.pending = ChooseFortificationProvince(
            seat=seat,
            candidates=_province_slots(game, seat),
            source_card_id=card_id,
            invest_amount=invest_amount,
            proclaim=proclaim,
        )
        return
    _announce_entering_play(game, card_id, invest_amount, proclaim)


def _province_slots(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """Every one of ``seat``'s Provinces, named by slot. A Province is a slot rather than the card
    standing in it, so an empty one is as attachable as any other (CR, Fortification)."""
    return tuple(key.token for key, _ in province_zones(game, seat))


def _apply_fortification_province(
    game: GameState, request: ChooseFortificationProvince, response: DecisionResponse
) -> None:
    """Attach the waiting Fortification to the Province the seat named, then let it arrive."""
    card = game.table.cards_by_id[request.source_card_id]
    province = ZoneKey.from_token(response.choices[0])
    game.pending = None
    ops.attach_to_province(game.table, card, province)
    _announce_entering_play(game, card.id, request.invest_amount, request.proclaim)


def _announce_entering_play(
    game: GameState, card_id: str, invest_amount: int, proclaim: bool
) -> None:
    """The tail every recruited card shares: make the board legal, queue the post-entry steps, and
    announce the arrival."""
    # A card reaching the battlefield can make the board illegal, and the board is made legal
    # before anything is told the card arrived — a trigger that reads a state the rules say cannot
    # exist is deciding on a board that never legally existed.
    triggers.enforce_state_rules(game)
    # Defer the post-entry steps so an enter-play trait that pauses for a choice resolves first.
    game.stack.append(FinishRecruit(card_id, invest_amount, proclaim))
    triggers.fire(game, EnteredPlay(card_id))


def _finish_recruit(
    game: GameState, card_id: str, invest_amount: int | None, proclaim: bool = False
) -> None:
    card = game.table.cards_by_id[card_id]
    _clear_sincerity(game, card)
    if proclaim:
        game.use_once(proclaim_key(card.owner, game.turn))
        ops.set_honor(game.table, card.owner, delta=effective_personal_honor(game, card))
    _finish_invest(game, card, invest_amount)


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
    province_key = province_key_holding(game, seat, card_id)
    ops.move_card(game.table, card, ZoneKey(seat, ZoneRole.DYNASTY_DISCARD))
    if province_key is not None:
        _defer_refill(game, province_key)
    triggers.fire(game, CardDiscarded(card_id, card.side, seat))


def _defer_refill(game: GameState, zone: ZoneKey, *, face_up: bool = False) -> None:
    """Queue the refill of a Province a card has just left, behind the reactions to it leaving.

    The rules put it there: the effects triggered by the card leaving or entering play resolve
    first, and only then is the Province refilled — and only if it is still short.
    """
    game.stack.append(ApplyEffects((RefillProvince(zone, face_up=face_up),)))


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
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Put each chosen card on the bottom in pick order, then refill the Provinces they left and
    reveal them all.

    Each card goes under the one before it, so the last pick ends up at the very bottom — the order
    the rule gives the player. The refill and the reveal are deferred together because the rule
    reveals *after* refilling, and both wait on the reactions to the cards leaving.
    """
    seat = game.table.cards_by_id[chosen[0]].owner
    # Read the Provinces before anything moves; afterwards none of them holds the card to find.
    vacated = [province_key_holding(game, seat, card_id) for card_id in chosen]
    deck = DeckKey(seat, Side.DYNASTY)
    put_back = [MoveToDeck(card_id, deck, from_bottom=0) for card_id in chosen]
    refills = tuple(RefillProvince(key) for key in vacated if key is not None)
    return [*put_back, Then((*refills, RevealProvinces(seat)))]


def kharmic_draw(game: GameState, card_id: str) -> None:
    """Announce the Fate Kharmic ability: discard ``card_id`` from hand to draw a card."""
    seat = game.round.priority
    _announce_kharmic(game, seat, (Discard(card_id, seat), Then((DrawCard(seat),))))


def kharmic_refill(game: GameState, card_id: str) -> None:
    """Announce the Dynasty Kharmic ability: discard ``card_id`` from its Province and refill that
    Province face-up."""
    seat = game.round.priority
    vacated = province_key_of(game, seat, card_id)
    _announce_kharmic(
        game, seat, (Discard(card_id, seat), Then((RefillProvince(vacated, face_up=True),)))
    )


def _announce_kharmic(game: GameState, seat: PlayerId, effects: tuple[Effect, ...]) -> None:
    """Pause for the gold cost both Kharmic forms share, queueing ``effects`` behind it. Repeatable,
    so no once-per-turn key is claimed."""
    game.pending = announce_rulebook_cost(game, seat, KHARMIC_COST, keywords.KHARMIC, effects)


def _reveal_search_pool(game: GameState, seat: PlayerId) -> None:
    """Let ``seat`` identify every card its Legacy search looked through. A face-down Province card
    is searched, so the seat has seen it by the time it chooses which Province to displace."""
    for card in legacy_search_pool(game, seat):
        card.add_peeker(seat)


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
        # The whiff: failing to find a Legacy card loses the game.
        game.lose(seat, "failed Legacy")
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
    target_key = province_key_of(game, seat, displaced.id)
    source_key = province_key_holding(game, seat, legacy_card.id)  # None when it came from the deck
    game.pending = None
    if source_key is not None:
        _defer_refill(game, source_key)
    # One effect per occurrence, so each announces itself where it happens. The placement is
    # deferred because the rules resolve what the displaced card leaving triggered before anything
    # fills the Province behind it.
    after_the_discard: list[Effect] = [PlaceInProvince(legacy_card.id, target_key)]
    if source_key is None:
        # The found card came out of the deck, so the deck the search read is no longer secret. It
        # shuffles behind the placement, which is what takes the card out of it.
        after_the_discard.append(ShuffleDeck(DeckKey(seat, Side.DYNASTY)))
    triggers.resolve_effects(game, [Discard(displaced.id, seat), Then(tuple(after_the_discard))])


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
    for a decision resolves fully first — which is the CR's order, since targets are chosen in step C
    of the Action Sequence, after costs are paid in step B. Good Faith is what makes the deferral
    safe: an action may only be announced when it could find a legal target, so the candidates
    ``legal_actions`` validated are still there to hit."""
    card = game.table.cards_by_id[card_id]
    ability = abilities.ability_for(card)
    if ability.timing is ActionTiming.RESPONSE:
        game.responded.add(card_id)
    _defer_ability(game, card, ability)
    run_stack(game)  # resolve the target, unless the cost's cascade paused for a decision first


def _defer_ability(game: GameState, card: L5RCard, ability: abilities.Ability) -> None:
    """Stack ``ability``'s effects behind its cost, and pay the cost.

    The cost resolves first and targeting follows it (CR, Action Sequence steps B and C), and an
    ``all_targets`` ability hits every one it found rather than pausing to be pointed at one.
    """
    targets = tuple(ability.targets(game, card))
    game.stack.append(
        ApplyAbilityEffects(card.id, targets)
        if ability.all_targets
        else SelectAbilityTarget(card.id, targets)
    )
    triggers.resolve_effects(game, ability.cost(game, card))


def _apply_ability_target(
    game: GameState, request: ChooseAbilityTarget, response: DecisionResponse
) -> None:
    source = game.table.cards_by_id[request.source_card_id]
    target = game.table.cards_by_id[response.choices[0]]
    ability = abilities.ability_for(source)
    game.pending = None
    triggers.resolve_effects(game, ability.effects(game, source, target))


def _apply_card_choice(
    game: GameState,
    request: ChooseCards | ChooseAmount | ChooseOption | ChooseDistribution | Confirm,
    response: DecisionResponse,
) -> None:
    game.pending = None
    item = game.stack.pop()  # the ResumeCascade this choice paused, always stacked atop it
    if not isinstance(item, ResumeCascade):
        raise RuntimeError("a card choice resumed without its stashed cascade")
    resolver = triggers.CHOICE_RESOLVERS[request.resolver]
    triggers.resume_cascade(
        game, item, resolver(game, request.source_id, response.choices, request.seat)
    )
    run_stack(game)  # finish any work deferred behind the choice, unless it paused again


def _end_turn(game: GameState) -> None:
    seat = game.active
    _resolve_delayed(game, END_OF_TURN)
    if game.pending is not None:
        # What is left of the end of the turn — Sincerity, the fate draw, the hand-size discard —
        # has nowhere to resume from, and setting the discard request would strand the paused
        # effect's own cascade behind it. Nothing delayed today asks a question.
        raise RuntimeError("a delayed effect paused the end of the turn, which cannot resume")
    _accrue_sincerity(game, seat)
    ops.draw_to_hand(game.table, seat)
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    excess = len(hand.cards) - MAX_HAND_SIZE
    if excess > 0:
        candidates = tuple(card.id for card in hand.cards)
        game.pending = DiscardToHandSize(seat, candidates, count=excess)
        return
    _begin_next_turn(game)


def _resolve_delayed(game: GameState, moment: Moment) -> None:
    """Resolve the effects held until ``moment``, and drop them whether they did anything or not.

    A held effect whose card has since left the table is a no-op, so one destroyed or banished
    earlier in the turn is not chased into the next.
    """
    held = [effect for held_until, effect in game.delayed if held_until == moment]
    if not held:
        return
    game.delayed = [entry for entry in game.delayed if entry[0] != moment]
    triggers.resolve_effects(game, held)


def _accrue_sincerity(game: GameState, seat: PlayerId) -> None:
    """Before ``seat``'s turn ends, give each face-up Sincerity card lingering in its Provinces a
    Sincerity token. A card that flushed (was recruited or discarded) or arrived face-down as a
    refill this turn is not face-up in a Province, so it does not accrue."""
    grants = [
        AdjustCounter(card.id, SINCERITY, 1)
        for key, zone in game.table.zones.items()
        if key.owner is seat and key.role is ZoneRole.PROVINCE
        for card in zone.cards
        if card.face_up and keywords.SINCERITY in effective_keywords(game, card)
    ]
    triggers.resolve_effects(game, grants)


def _begin_next_turn(game: GameState) -> None:
    # Drop until-end-of-turn modifiers as the turn ends; the comprehension keeps creation order so
    # the list rebuilds identically under replay.
    game.modifiers = [m for m in game.modifiers if m.duration is not Duration.UNTIL_END_OF_TURN]
    # Modifiers expiring can make the board illegal on their own, with no effect committing and so
    # no cascade to catch it. Settle that before the new turn starts and anything reads the board.
    triggers.enforce_state_rules(game)
    game.turn += 1
    game.active = _other(game.active)
    game.phase = Phase.ACTION
    _begin_turn(game)


def _begin_turn(game: GameState) -> None:
    """Open the turn: straighten, reveal the Provinces, and announce that the turn has begun.

    A card that may remain bowed is asked about first, since that is a choice its controller makes
    before each straightening (CR, May Remain Bowed). Pausing here leaves the rest of the turn's
    opening for the submit that answers.
    """
    open_round(game)
    offering = abilities.may_stay_bowed(game, game.active)
    if offering:
        game.pending = LeaveBowed(seat=game.active, candidates=offering)
        return
    _open_turn(game, frozenset())


def _open_turn(game: GameState, staying_bowed: frozenset[str]) -> None:
    """Straighten everything but ``staying_bowed`` and whatever may not straighten yet, reveal the
    Provinces, and open the turn.

    The prohibition outlives this step — it lifts when the Action Phase this straighten precedes has
    ended — so nothing is spent here.
    """
    straightened = ops.straighten(
        game.table, game.active, staying_bowed | game.straighten_delayed.keys()
    )
    for card_id in straightened:
        triggers.fire(game, Straightened(card_id))
    for card_id in ops.reveal_provinces(game.table, game.active):
        triggers.fire(game, Revealed(card_id))
    triggers.fire(game, TurnStarted(game.active))
    # Opening the turn is not an action, so what it just raised is nobody's to respond to.
    forget_action(game)


def _apply_discard(game: GameState, seat: PlayerId, card_ids: tuple[str, ...]) -> None:
    """Discard down to the maximum hand size at the end of the turn.

    The rulebook trims the hand, so the discard names no seat as its cause: it is a step of the turn
    rather than an action (CR, Drawing and Discarding Fate Cards), and a card reacting to "if the
    action was yours" has no action to claim.
    """
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    by_id = {card.id: card for card in hand.cards}
    missing = [card_id for card_id in card_ids if card_id not in by_id]
    if missing:
        raise ValueError(f"discard names cards not in {seat.name}'s hand: {missing}")
    for card_id in card_ids:
        card = by_id[card_id]
        ops.move_card(game.table, card, ZoneKey(seat, ZoneRole.FATE_DISCARD))
        triggers.fire(
            game,
            CardDiscarded(card_id, card.side, Rulebook.MAXIMUM_HAND_SIZE, from_hand_or_deck=True),
        )


def _other(seat: PlayerId) -> PlayerId:
    return PlayerId.P2 if seat is PlayerId.P1 else PlayerId.P1


def _yield_after_action(game: GameState) -> None:
    """Hand on the opportunity once an action has fully resolved. An action that paused for a
    decision has not finished, and a game that has ended has no round left to run.

    A Response Step comes first when the action left anyone something to respond with.
    """
    if game.awaiting_decision or game.game_over:
        return
    if open_response_window(game):
        return
    yield_priority(game, passed=False)


def _responders(game: GameState) -> list[PlayerId]:
    """Every seat holding a Response it could take against the action just resolved."""
    responding = frozenset({ActionTiming.RESPONSE})
    return [seat for seat in game.table.seats if abilities.activatable(game, seat, responding)]


def open_response_window(game: GameState) -> bool:
    """Open the Response Step over the round the action was taken in, and report whether it opened.

    Only when a seat actually holds a Response: a step nobody could act in is a pass nobody needs to
    be asked for. A Response is itself an action, and one taken inside the step opens no step of its
    own — the window that is already open is the one it belongs to.
    """
    if game.round_stack:
        return False
    # Cleared before the seats are polled, not after: a card still marked from the last Step would
    # not count as a responder, and so could never open another one.
    game.responded.clear()
    if not _responders(game):
        return False
    game.round_stack.append(game.round)
    game.round = ActionRound(timings=RESPONSE_TIMINGS, priority=game.active)
    return True


def close_response_window(game: GameState) -> None:
    """Close the Response Step and hand the opportunity on from the round it suspended."""
    game.round = game.round_stack.pop()
    yield_priority(game, passed=False)
