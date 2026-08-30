from dataclasses import dataclass

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import _ABILITIES, Ability, CardLocation, itself
from yasuki_core.engine.rules.actions import ActionTiming, PlayStrategy
from yasuki_core.engine.rules.decisions import ChoosePayment, DecisionResponse
from yasuki_core.engine.rules.effects import AdjustCounter, Effect
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import end_phase, holding, put_in_play, register

SEAT = PlayerId.P1

# A Strategy that puts a Wealth token on a target Holding. Its whole text is one effect the engine
# already has, so what these tests exercise is playing it rather than what it does.
_ABILITIES["test_strategy"] = Ability(
    timing=ActionTiming.OPEN,
    label="test",
    cost=lambda game, source: [],
    targets=lambda game, card: [
        held.id for held in game.table.battlefield.cards if held.owner is card.owner
    ],
    effects=lambda game, source, target: [AdjustCounter(target.id, WEALTH, 1)],
    located_at=(CardLocation.HAND,),
)


@dataclass(frozen=True, slots=True)
class _PutItIntoPlay(Effect):
    """A Terrain's own text, in miniature: the played card ends up on the battlefield."""

    card_id: str

    def describe(self) -> str:
        return f"{self.card_id} enters play"

    def perform(self, game):
        ops.move_card(game.table, game.table.cards_by_id[self.card_id], ops.BATTLEFIELD)
        return []


_ABILITIES["test_kata_strategy"] = Ability(
    timing=ActionTiming.OPEN,
    label="test",
    cost=lambda game, source: [],
    targets=itself,
    effects=lambda game, source, target: [_PutItIntoPlay(source.id)],
    all_targets=True,
    located_at=(CardLocation.HAND,),
)


def _strategy(state: TableState, card_id: str = "plan", gold_cost: int = 1) -> L5RCard:
    """Put the test Strategy in the seat's hand at ``gold_cost``."""
    card = register(
        state,
        L5RCard.of(
            ActionPrint,
            id=card_id,
            name=card_id,
            printed_id="test_strategy",
            side=Side.FATE,
            owner=SEAT,
            gold_cost=gold_cost,
        ),
    )
    state.zones[ZoneKey(SEAT, ZoneRole.HAND)].add(card)
    return card


def _session(*, gold_cost: int = 1, production: int = 2) -> tuple[EngineSession, L5RCard]:
    """A seat holding the test Strategy, with one Holding to pay with and to target."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("farm", owner=SEAT, gold_production=production))
    card = _strategy(state, gold_cost=gold_cost)
    return EngineSession.start(state, SEAT), card


def _hand(session: EngineSession) -> list[str]:
    return [card.id for card in session.game.table.zones[ZoneKey(SEAT, ZoneRole.HAND)].cards]


def _discard(session: EngineSession) -> list[str]:
    zone = session.game.table.zones[ZoneKey(SEAT, ZoneRole.FATE_DISCARD)]
    return [card.id for card in zone.cards]


def test_a_strategy_in_hand_is_offered_when_it_is_affordable():
    session, card = _session(gold_cost=1, production=2)

    assert PlayStrategy(card.id) in session.legal_actions(SEAT)


def test_a_strategy_beyond_the_seats_gold_is_not_offered():
    """`gold_reach` counts what the seat could raise, so an unaffordable card is withheld rather
    than offered and then refused at the payment."""
    session, card = _session(gold_cost=5, production=2)

    assert PlayStrategy(card.id) not in session.legal_actions(SEAT)


def test_a_strategy_with_no_legal_target_is_not_offered():
    state = TableState.empty_two_seat()
    card = _strategy(state)  # nothing in play for it to target
    session = EngineSession.start(state, SEAT)

    assert PlayStrategy(card.id) not in session.legal_actions(SEAT)


def test_playing_one_pauses_for_its_gold_cost():
    session, card = _session()

    session.act(SEAT, PlayStrategy(card.id))

    assert isinstance(session.game.pending, ChoosePayment)
    assert _hand(session) == [card.id]  # still in hand until it resolves


def test_it_resolves_its_ability_and_then_goes_to_the_discard():
    session, card = _session()
    session.act(SEAT, PlayStrategy(card.id))
    while session.game.pending is not None:
        asked = session.game.pending
        session.submit(asked.seat, DecisionResponse(asked.candidates[:1]))

    assert session.game.table.cards_by_id["farm"].counters.get(WEALTH.key) == 1
    assert _hand(session) == []
    assert _discard(session) == [card.id]


def test_backing_out_of_the_payment_leaves_the_card_in_hand():
    """The cancel path. Nothing has moved when the payment is asked, and the unwind truncates the
    tape to before the announcement — so the card is where it was and nothing was discarded."""
    session, card = _session()
    session.act(SEAT, PlayStrategy(card.id))
    assert isinstance(session.game.pending, ChoosePayment)

    session.cancel(SEAT)

    assert _hand(session) == [card.id]
    assert _discard(session) == []
    assert session.game.pending is None
    assert PlayStrategy(card.id) in session.legal_actions(SEAT)


def test_a_strategy_is_not_offered_outside_a_round_its_designator_permits():
    """`legality` gates on the card's own designator, so an Open Strategy is gone by the Dynasty
    phase. Asserted because the handler must not assume the round was checked."""
    session, card = _session()
    end_phase(session)  # into the Attack Phase, which permits only attack timing
    end_phase(session)  # and on into the Dynasty Phase

    assert PlayStrategy(card.id) not in session.legal_actions(SEAT)


def test_the_target_is_the_one_the_seat_chose():
    """Two Holdings, one token: the ability has to hit the card the answer named."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("first", owner=SEAT, gold_production=3))
    put_in_play(state, holding("second", owner=SEAT, gold_production=0))
    card = _strategy(state)
    session = EngineSession.start(state, SEAT)

    session.act(SEAT, PlayStrategy(card.id))
    while session.game.pending is not None:
        asked = session.game.pending
        wanted = ("second",) if "second" in asked.candidates else asked.candidates[:1]
        session.submit(asked.seat, DecisionResponse(wanted))

    assert session.game.table.cards_by_id["second"].counters.get(WEALTH.key) == 1
    assert session.game.table.cards_by_id["first"].counters.get(WEALTH.key) is None


def test_an_untargeted_strategy_still_resolves_before_it_is_discarded():
    """An `all_targets` ability pauses for nothing, so the whole play drains in one pass and the
    ordering rests entirely on the discard being stacked under the ability's own work."""
    _ABILITIES["test_untargeted_strategy"] = Ability(
        timing=ActionTiming.OPEN,
        label="test",
        cost=lambda game, source: [],
        targets=lambda game, card: [
            held.id for held in game.table.battlefield.cards if held.owner is card.owner
        ],
        effects=lambda game, source, target: [AdjustCounter(target.id, WEALTH, 1)],
        all_targets=True,
        located_at=(CardLocation.HAND,),
    )
    state = TableState.empty_two_seat()
    put_in_play(state, holding("first", owner=SEAT, gold_production=3))
    put_in_play(state, holding("second", owner=SEAT, gold_production=0))
    card = register(
        state,
        L5RCard.of(
            ActionPrint,
            id="sweep",
            name="sweep",
            printed_id="test_untargeted_strategy",
            side=Side.FATE,
            owner=SEAT,
            gold_cost=1,
        ),
    )
    state.zones[ZoneKey(SEAT, ZoneRole.HAND)].add(card)
    session = EngineSession.start(state, SEAT)

    session.act(SEAT, PlayStrategy(card.id))
    while session.game.pending is not None:
        asked = session.game.pending
        session.submit(asked.seat, DecisionResponse(asked.candidates[:1]))

    held = session.game.table.cards_by_id
    assert held["first"].counters.get(WEALTH.key) == 1  # it hit every target it found
    assert held["second"].counters.get(WEALTH.key) == 1
    assert _discard(session) == [card.id]


def test_a_free_strategy_needs_no_payment_and_still_discards():
    """Nothing to pay is the boundary the payment path can skip over: a Strategy costing zero must
    still resolve and still leave the hand."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("farm", owner=SEAT, gold_production=0))
    card = _strategy(state, gold_cost=0)
    session = EngineSession.start(state, SEAT)

    session.act(SEAT, PlayStrategy(card.id))
    while session.game.pending is not None:
        asked = session.game.pending
        session.submit(asked.seat, DecisionResponse(asked.candidates[:1]))

    assert session.game.table.cards_by_id["farm"].counters.get(WEALTH.key) == 1
    assert _hand(session) == []
    assert _discard(session) == [card.id]


# Where the played card sat while its own effects ran, recorded by the ability below. A list rather
# than a return value because an effect reports nothing back to its caller.
_RESOLVED_FROM: list[ZoneRole | None] = []


def _note_where_the_source_sits(game, source, target):
    """Record the played card's zone as the ability resolves, then do the ability's actual work."""
    _RESOLVED_FROM.append(
        next(
            (key.role for key, zone in game.table.zones.items() if source in zone.cards),
            None,
        )
    )
    return [AdjustCounter(target.id, WEALTH, 1)]


_ABILITIES["test_probes_its_own_zone"] = Ability(
    timing=ActionTiming.OPEN,
    label="test",
    cost=lambda game, source: [],
    targets=lambda game, card: [
        held.id for held in game.table.battlefield.cards if held.owner is card.owner
    ],
    effects=_note_where_the_source_sits,
    located_at=(CardLocation.HAND,),
)


def test_a_strategy_resolves_before_it_is_discarded_rather_than_after():
    """The CR order, and the reason the discard is stacked under the ability's own work. Reversed,
    the card would already be in the discard pile while its text was still resolving — which a
    Response reading "after this was discarded" would see happen too early."""
    _RESOLVED_FROM.clear()
    state = TableState.empty_two_seat()
    put_in_play(state, holding("farm", owner=SEAT, gold_production=2))
    card = register(
        state,
        L5RCard.of(
            ActionPrint,
            id="probe",
            name="probe",
            printed_id="test_probes_its_own_zone",
            side=Side.FATE,
            owner=SEAT,
            gold_cost=1,
        ),
    )
    state.zones[ZoneKey(SEAT, ZoneRole.HAND)].add(card)
    session = EngineSession.start(state, SEAT)

    session.act(SEAT, PlayStrategy(card.id))
    while session.game.pending is not None:
        asked = session.game.pending
        session.submit(asked.seat, DecisionResponse(asked.candidates[:1]))

    assert _RESOLVED_FROM == [ZoneRole.HAND]  # still in hand while its own text ran
    assert _discard(session) == [card.id]  # and in the discard once it was done


def test_a_strategy_that_put_itself_into_play_is_not_discarded():
    """CR, Action Sequence step F: the played card is discarded "unless it is now in play". A
    Terrain reads "Put this card into play there", so discarding it afterward would undo the card."""
    state = TableState.empty_two_seat()
    card = register(
        state,
        L5RCard.of(
            ActionPrint,
            id="kata",
            name="kata",
            printed_id="test_kata_strategy",
            side=Side.FATE,
            owner=SEAT,
            gold_cost=0,
        ),
    )
    state.zones[ZoneKey(SEAT, ZoneRole.HAND)].add(card)
    session = EngineSession.start(state, SEAT)

    session.act(SEAT, PlayStrategy(card.id))
    while session.game.pending is not None:
        asked = session.game.pending
        session.submit(asked.seat, DecisionResponse(asked.candidates[:1]))

    assert card.id in {held.id for held in session.game.table.battlefield.cards}
    assert _discard(session) == []
    assert _hand(session) == []
