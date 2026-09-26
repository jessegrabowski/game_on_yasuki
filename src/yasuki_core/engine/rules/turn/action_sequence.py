from yasuki_core import ruleset
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.activation import apply_ability_target, activate
from yasuki_core.engine.rules.abilities.strategy import (
    play_strategy,
)
from yasuki_core.engine.debug import (
    ChooseDebugSeat,
    PlaceDebugCard,
    apply_debug_placement,
    apply_debug_seat,
)
from yasuki_core.engine.rules.vocabulary.actions import (
    Action,
    ActivateAbility,
    Cycle,
    DeclareAttack,
    DiscardToInterrupt,
    DynastyDiscard,
    Equip,
    Inheritance,
    Legacy,
    Lobby,
    Pass,
    PlayInterrupt,
    PlayStrategy,
    Recruit,
    UseFavorAbility,
)
from yasuki_core.engine.rules.battle import resolution
from yasuki_core.engine.rules.duel import procedure as duel_procedure
from yasuki_core.engine.rules.vocabulary.decisions import (
    ArrangeCards,
    AssignUnits,
    ChooseAbilityTarget,
    ChooseAmount,
    ChooseBattlefield,
    FocusOrStrike,
    ChooseCards,
    ChooseDistribution,
    ChooseEquipTarget,
    ChooseFortificationProvince,
    ChooseInheritanceTarget,
    ChooseInterruptAdjustment,
    ChooseInterruptEffect,
    ChooseInterruptTarget,
    ChooseInvestAmount,
    ChooseLobbyTarget,
    ChooseOption,
    ChoosePayment,
    Confirm,
    DecisionResponse,
    DiscardToHandSize,
    LeaveBowed,
)
from yasuki_core.engine.rules.rulebook.equip import apply_equip_target, equip
from yasuki_core.engine.rules.gold.production import produce_gold
from yasuki_core.engine.rules.rulebook.recruit import (
    apply_fortification_province,
    apply_invest_amount,
    recruit,
)
from yasuki_core.engine.rules.rulebook.cycle import cycle
from yasuki_core.engine.rules.rulebook.dynasty_discard import dynasty_discard
from yasuki_core.engine.rules.rulebook.favor_payment import use_favor_ability
from yasuki_core.engine.rules.interrupts import (
    apply_interrupt_adjustment,
    apply_interrupt_effect,
    apply_interrupt_target,
    discard_to_interrupt,
    play_interrupt,
)
from yasuki_core.engine.rules.rulebook.inheritance import apply_inheritance_target, inheritance
from yasuki_core.engine.rules.rulebook.legacy import legacy
from yasuki_core.engine.rules.rulebook.lobby import apply_lobby_target, lobby
from yasuki_core.engine.rules.effects import PayGold
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.sequence import (
    BeginNextTurn,
    apply_discard,
    open_turn,
    run_stack,
    yield_after_action,
    yield_priority,
)
from yasuki_core.engine.rules.turn.structure import RoundKind

# Imported for the registrations it performs: every entry point reaches the engine through
# this dispatcher, and a registry read before the card modules load is silently empty.
# Guarded by test_importing_the_engine_registers_the_cards.
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.engine.rules.rulebook import dishonor  # noqa: F401


# How each action reads when a Response Step names the thing it answers. A Response is taken against
# an action, so the wording is the action's rather than any one effect it had.
_ACTION_WORDING: dict[type, str] = {
    Recruit: "the Recruit of",
    Equip: "the Equip of",
    ActivateAbility: "the ability on",
    DynastyDiscard: "the discard of",
    PlayStrategy: "the Strategy",
    Legacy: "Legacy",
    Cycle: "Cycle",
    Inheritance: "Inheritance",
    Lobby: "Lobby",
    DeclareAttack: "the attack",
}


def describe_action(game: GameState, action: Action) -> str:
    """``action`` worded for a player: "the Recruit of Courts of Otosan Uchi"."""
    if isinstance(action, UseFavorAbility):
        return f"the Imperial Favor's ability to {_favor_ability_label(action.key)}"
    wording = _ACTION_WORDING.get(type(action), type(action).__name__)
    card = game.table.cards_by_id.get(getattr(action, "card_id", ""))
    return f"{wording} {card.name}" if card is not None else wording


def _favor_ability_label(key: str) -> str:
    return next(ability.label for ability in ruleset.ACTIVE.favor_abilities if ability.key == key)


def perform(game: GameState, action: Action) -> None:
    """Apply a chosen action, dispatching to its handler. The single action-apply dispatch,
    mirroring :func:`~.submit` for decisions. Raise ``ValueError`` for an action with no handler."""
    # Read before the handler runs: one that opens a round of its own leaves that round on
    # `game.round`, and the round to hand on from is the one the action was taken in.
    acted_in = game.round
    # An Interrupt or a Response answers "the action", which stays the one it answers.
    if not isinstance(action, Pass) and game.round.kind not in (
        RoundKind.RESPONSE,
        RoundKind.INTERRUPT,
    ):
        game.action_events.clear()
        game.action_resolved = False
        game.action_taken = describe_action(game, action)
        game.action_seat = game.round.priority
        game.action_targets = ()
        game.action_is_favor = False
        game.action = action
        game.interrupts_taken.clear()
        game.interrupts_offered = False
        game.modifications.clear()
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
        case Lobby():
            lobby(game)
        case UseFavorAbility(key=key):
            use_favor_ability(game, key)
        case ActivateAbility(card_id=card_id, ability_key=ability_key):
            activate(game, card_id, ability_key)
            # Resolve the target, unless the cost's cascade paused for a decision first.
            run_stack(game)
        case PlayStrategy(card_id=card_id, ability_key=ability_key):
            play_strategy(game, card_id, ability_key)
        case DeclareAttack():
            resolution.declare_attack(game)
            resolution.open_maneuvers(game)
        case PlayInterrupt(card_id=card_id):
            play_interrupt(game, acted_in.priority, card_id)
        case DiscardToInterrupt(card_id=card_id, key=key):
            discard_to_interrupt(game, acted_in.priority, card_id, key)
        case _:
            raise ValueError(f"no handler for action {type(action).__name__}")
    # An action resolves fully before the next input; one that paused for a decision leaves its
    # remainder for the submit that answers it.
    run_stack(game)
    if not isinstance(action, Pass):
        yield_after_action(game, acted_in)


def submit(game: GameState, response: DecisionResponse) -> None:
    """Answer the pending decision and resume the engine.

    Clear the request, dispatch on its type to its apply-handler, then continue: an end-of-turn
    discard begins the next turn, while a cost payment drains the stack to finish the action that
    paused for it. The clear comes first, and here only, because a handler may raise a question of
    its own, and the request it sets has to be the one pending when this returns.

    Raise ``RuntimeError`` if no decision is pending, or ``ValueError`` if the answer is malformed
    or illegal against the game state.
    """
    request = game.pending
    if request is None:
        raise RuntimeError("no decision is pending")
    if not request.accepts(response):
        raise ValueError("malformed answer to the pending decision")
    acted_in = game.round
    outside_action = game.asked_outside_action
    if isinstance(request, DiscardToHandSize) and game.stack:
        raise RuntimeError("the turn is ending with work still queued")
    game.pending = None
    match request:
        case DiscardToHandSize():
            game.stack.append(BeginNextTurn())
            apply_discard(game, request.seat, response.choices)
        case LeaveBowed():
            open_turn(game, frozenset(response.choices))
        case ChoosePayment():
            _apply_payment(game, request, response)
            run_stack(game)
        case PlaceDebugCard():
            apply_debug_placement(game, request, response)
        case ChooseDebugSeat():
            apply_debug_seat(game, request, response)
        case ChooseAbilityTarget():
            apply_ability_target(game, request, response)
        case ChooseEquipTarget():
            apply_equip_target(game, request, response)
        case ChooseInheritanceTarget():
            apply_inheritance_target(game, request, response)
        case ChooseLobbyTarget():
            apply_lobby_target(game, request, response)
        case ChooseFortificationProvince():
            apply_fortification_province(game, request, response)
        case ChooseInterruptTarget():
            apply_interrupt_target(game, request, response)
        case ChooseInterruptEffect():
            apply_interrupt_effect(game, request, response)
        case ChooseInterruptAdjustment():
            apply_interrupt_adjustment(game, request, response)
        case ChooseCards():
            _apply_card_choice(game, request, response)
        case ChooseAmount():
            _apply_amount_choice(game, request, response)
        case ChooseOption():
            _apply_card_choice(game, request, response)
        case ChooseDistribution():
            _apply_card_choice(game, request, response)
        case ArrangeCards():
            _apply_card_choice(game, request, response)
        case Confirm():
            _apply_card_choice(game, request, response)
        case ChooseInvestAmount():
            apply_invest_amount(game, request, response)
        case AssignUnits():
            resolution.apply_assignment(game, request, response)
        case ChooseBattlefield():
            resolution.fight_battle(game, int(response.choices[0]))
        case FocusOrStrike():
            duel_procedure.apply_focus_or_strike(game, request, response)
        case _:
            raise ValueError(f"no handler for decision {type(request).__name__}")
    # Symmetric with `perform`: an answered decision resolves fully before the next input. A
    # question asked by turn structure resolves into a round it was not asked in, which is how
    # `yield_after_action` knows there is no opportunity to hand on.
    run_stack(game)
    if game.pending is None:
        game.asked_outside_action = False
    if not outside_action:
        yield_after_action(game, acted_in)


def cancel(game: GameState) -> None:
    """Replay a recorded ``Cancel``, dropping the work the decision was queued in front of.

    Live play does not reach this: ``EngineSession.abort`` unwinds by truncating the tape, so no
    new ``Cancel`` is ever written. It stays to replay tapes that already hold one.

    The request is cleared once, here, after the undo: nothing a cancel does can ask a question,
    and a cancel that is refused leaves the question where it was.

    Raise ``RuntimeError`` if no decision is pending, or ``ValueError`` if the pending decision
    cannot be canceled.
    """
    request = game.pending
    if request is None:
        raise RuntimeError("no decision is pending")
    match request:
        case ChoosePayment(target_id=target_id):
            game.announced_from_hand -= {target_id}
            _cancel_payment(game)
        case ChooseInvestAmount():
            pass  # the recruit is not yet announced; nothing to undo
        case _:
            raise ValueError(f"{type(request).__name__} cannot be canceled")
    game.pending = None


def _cancel_payment(game: GameState) -> None:
    """Drop the work the canceled payment stands in front of, whatever queued it: a Recruit's
    :class:`~.ResolveRecruit` or a rulebook cost's :class:`~.ApplyEffects`.

    The item is always the top of the stack: announcing a cost pushes exactly one, and the engine is
    paused on the payment from that moment until it is answered or canceled, so nothing can have
    pushed since.
    """
    if not game.stack:
        raise ValueError("the pending payment has no queued work to undo")
    game.stack.pop()


def _apply_payment(game: GameState, request: ChoosePayment, response: DecisionResponse) -> None:
    """Bow the producer the answer names, adding what it makes to the seat's pool.

    An answer names at most one, none when the pool already covers the cost, and the payment
    comes back round for whatever is still owed.

    Nothing here knows what a producer is worth. A card that can raise its own yield is asked in the
    window :func:`~.produce_gold` opens, and what it owes for saying yes is settled on the far side
    of the bow, both the card's own business, neither the payment's.
    """
    target_ids = (request.target_id,) if request.target_id in game.table.cards_by_id else ()
    for card_id in response.choices:
        produce_gold(game, card_id, target_ids)


def _apply_amount_choice(
    game: GameState, request: ChooseAmount, response: DecisionResponse
) -> None:
    """Charge the declared amount less the action's discount, then hand the declared amount to the
    card's resolver, which reads it. A charge discounted to nothing is not asked for."""
    resolver = triggers.CHOICE_RESOLVERS[request.resolver]
    charged = max(0, int(response.choices[0]) - request.discount)
    source = game.table.cards_by_id[request.source_id]
    payment = [PayGold(request.seat, charged, source.name)] if charged else []
    produced = resolver(game, request.source_id, response.choices, request.seat)
    triggers.resume_paused_cascade(game, [*payment, *produced])
    run_stack(game)


def _apply_card_choice(
    game: GameState,
    request: ChooseCards
    | ChooseAmount
    | ChooseOption
    | ChooseDistribution
    | ArrangeCards
    | Confirm,
    response: DecisionResponse,
) -> None:
    resolver = triggers.CHOICE_RESOLVERS[request.resolver]
    # Passed only when the choice carries one, so a resolver whose card asks a single question
    # never declares a parameter it would not read.
    carried = request.resolver_context if isinstance(request, ChooseOption) else ()
    context = {"resolver_context": carried} if carried else {}
    produced = resolver(game, request.source_id, response.choices, request.seat, **context)
    triggers.resume_paused_cascade(game, produced)
    run_stack(game)  # finish any work deferred behind the choice, unless it paused again
