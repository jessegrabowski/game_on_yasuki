import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.engine.rules.vocabulary.actions import Recruit
from yasuki_core.engine.rules.rulebook import equip
from yasuki_core.engine.rules.turn import action_sequence
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChoosePayment,
    Confirm,
    DecisionResponse,
)
from yasuki_core.engine.rules.gold.production import gold_handler, GOLD_HANDLERS
from yasuki_core.engine.rules.gold.self_grants import GOLD_SELF_GRANT, register_self_grant
from yasuki_core.engine.rules.board.seats import seat_controls_printed
from yasuki_core.engine.rules.effects import (
    Ask,
    Destroy,
    GrantModifier,
)
from yasuki_core.engine.rules.vocabulary.events import (
    ProducedGold,
    ProducingGold,
)
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary.work import ContinuePayment
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.zones import ProvinceZone

from tests.yasuki_core.engine.builders import (
    attachment,
    dealt_table,
    end_phase,
    holding,
    personality,
    put_in_play,
    register,
    two_seat_game,
)


from yasuki_core.engine.rules.gold.payment import (
    can_afford,
    payment_in_flight,
    refusal_would_strand,
)
from yasuki_core.engine.rules.rulebook import costs


def test_affordability_counts_the_pool_and_every_unbowed_producer():
    game = two_seat_game()
    game.gold[PlayerId.P1] = 1
    put_in_play(game, holding("P1-farm", owner=PlayerId.P1, gold_production=2))
    bowed = put_in_play(game, holding("P1-bowed", owner=PlayerId.P1, gold_production=4))
    bowed.bow()
    put_in_play(game, holding("P2-farm", owner=PlayerId.P2, gold_production=9))

    assert can_afford(game, PlayerId.P1, 3) is True
    assert can_afford(game, PlayerId.P1, 4) is False


def test_a_producer_the_cost_itself_bows_cannot_also_pay_for_it():
    # An ability priced "bow this Holding" cannot spend the same bow twice, so counting the producer
    # would offer a purchase the seat provably cannot complete.
    game = two_seat_game()
    farm = put_in_play(game, holding("P1-farm", owner=PlayerId.P1, gold_production=2))

    assert can_afford(game, PlayerId.P1, 2) is True
    assert can_afford(game, PlayerId.P1, 2, bowed_by_cost=frozenset({farm.id})) is False


def test_nothing_is_stranded_when_no_payment_is_in_flight():
    game = two_seat_game()

    assert payment_in_flight(game, PlayerId.P1) is None
    assert refusal_would_strand(game, PlayerId.P1, 2) is False


def test_refusing_a_grant_the_cost_needs_would_strand_the_payment():
    """Affordability counts a self-grant, so announcing a purchase only that grant reaches commits
    the seat to taking it: declining is no longer a way out and cancelling is."""
    game = two_seat_game()
    game.gold[PlayerId.P1] = 0
    put_in_play(
        game, holding("P1-mine", owner=PlayerId.P1, printed_id="strand_probe", gold_production=1)
    )
    register_self_grant("strand_probe", 2)
    game.stack.append(ContinuePayment(seat=PlayerId.P1, amount=3, label="a purchase"))

    try:
        assert refusal_would_strand(game, PlayerId.P1, 2) is True
        assert refusal_would_strand(game, PlayerId.P1, 0) is False
    finally:
        GOLD_SELF_GRANT.pop("strand_probe", None)


def _dynasty_phase(producers: list[L5RCard], *, cost: int) -> EngineSession:
    """A Dynasty phase with ``producers`` in play and one face-up target costing ``cost``."""
    state = dealt_table()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        register(state, holding("refill", owner=PlayerId.P1))
    ]
    for producer in producers:
        put_in_play(state, producer)
    target = register(state, holding("tgt", owner=PlayerId.P1, gold_cost=cost))
    target.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(target)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, PlayerId.P1)
    end_phase(session)
    end_phase(session)
    return session


def test_a_payment_stranded_by_its_own_answer_raises():
    """Affordability sums yields that cannot all be realised: destroying one producer as the price
    of its own grant drops what another is worth. Answering one producer at a time re-quotes the
    rest, so the shortfall surfaces here rather than silently underpaying — and it has to be loud,
    because the alternative is a seat holding a question with no legal answer and no way to know why.
    """
    try:
        register_self_grant("self_destroying_probe", 2)

        @triggers.on(ProducingGold, "self_destroying_probe")
        def _grant(ctx):
            if ctx.event.card_id != ctx.card.id:
                return []
            return [
                GrantModifier(
                    ctx.card.id, ctx.card.id, Stat.GOLD_PRODUCTION, 2, Duration.UNTIL_END_OF_TURN
                )
            ]

        @triggers.on(ProducedGold, "self_destroying_probe")
        def _price(ctx):
            if ctx.event.card_id != ctx.card.id:
                return []
            return [Destroy(ctx.card.id, ctx.card.owner)]

        @gold_handler("paired_probe")
        def _paired(card, game_, seat, targets):
            paired = seat_controls_printed(game_, seat, "Probe", other_than=card)
            return card.gold_production + (1 if paired else 0)

        # Quoted 4 (sd with its own grant) + 3 (pp, paired with sd) = 7. Once sd has destroyed
        # itself, pp is worth 2 and the pool can only reach 6.
        session = _dynasty_phase(
            [
                holding(
                    "sd",
                    owner=PlayerId.P1,
                    printed_id="self_destroying_probe",
                    keywords=("Probe",),
                    gold_production=2,
                ),
                holding(
                    "pp",
                    owner=PlayerId.P1,
                    printed_id="paired_probe",
                    keywords=("Probe",),
                    gold_production=2,
                ),
            ],
            cost=7,
        )
        session.act(PlayerId.P1, Recruit("tgt"))

        with pytest.raises(RuntimeError, match="cannot make up the difference"):
            session.submit(PlayerId.P1, DecisionResponse(("sd",)))
    finally:
        GOLD_SELF_GRANT.pop("self_destroying_probe", None)
        triggers._TRIGGERS.get(ProducingGold, {}).pop("self_destroying_probe", None)
        triggers._TRIGGERS.get(ProducedGold, {}).pop("self_destroying_probe", None)
        GOLD_HANDLERS.pop("paired_probe", None)


@choice_resolver("test_grant_price_question")
def _grant_price_question(game, source_id, chosen, seat):
    return []


def test_a_price_that_asks_a_question_keeps_its_decision():
    """A grant's price resolves inside the payment, and an interrupting one leaves a decision
    pending. Clearing the payment's own decision afterwards must not erase it."""
    try:
        register_self_grant("asking_probe", 2)

        @triggers.on(ProducingGold, "asking_probe")
        def _grant(ctx):
            if ctx.event.card_id != ctx.card.id:
                return []
            return [
                GrantModifier(
                    ctx.card.id, ctx.card.id, Stat.GOLD_PRODUCTION, 2, Duration.UNTIL_END_OF_TURN
                )
            ]

        @triggers.on(ProducedGold, "asking_probe")
        def _price(ctx):
            if ctx.event.card_id != ctx.card.id:
                return []
            return [
                Ask(ctx.card.owner, "Answer this?", "test_grant_price_question", (ctx.card.id,))
            ]

        session = _dynasty_phase(
            [holding("ap", owner=PlayerId.P1, printed_id="asking_probe", gold_production=2)],
            cost=4,
        )
        session.act(PlayerId.P1, Recruit("tgt"))
        session.submit(PlayerId.P1, DecisionResponse(("ap",)))

        assert isinstance(session.game.pending, Confirm)
        assert session.game.pending.question == "Answer this?"

        session.submit(PlayerId.P1, DecisionResponse(("ap",)))
        assert session.game.table.cards_by_id["tgt"] in session.game.table.battlefield.cards
    finally:
        GOLD_SELF_GRANT.pop("asking_probe", None)
        triggers._TRIGGERS.get(ProducingGold, {}).pop("asking_probe", None)
        triggers._TRIGGERS.get(ProducedGold, {}).pop("asking_probe", None)


def test_a_producer_that_grants_itself_nothing_is_not_made_to_pay():
    """The payment path exacts no price of its own. A card that raises its own yield and names no
    consequence keeps its production and stays in play — Outlying Farms' text is Outlying Farms'."""
    try:
        register_self_grant("free_grant_probe", 3)

        @triggers.on(ProducingGold, "free_grant_probe")
        def _grant(ctx):
            if ctx.event.card_id != ctx.card.id:
                return []
            return [
                GrantModifier(
                    ctx.card.id, ctx.card.id, Stat.GOLD_PRODUCTION, 3, Duration.UNTIL_END_OF_TURN
                )
            ]

        session = _dynasty_phase(
            [holding("fg", owner=PlayerId.P1, printed_id="free_grant_probe", gold_production=2)],
            cost=5,
        )
        session.act(PlayerId.P1, Recruit("tgt"))
        session.submit(PlayerId.P1, DecisionResponse(("fg",)))

        probe = session.game.table.cards_by_id["fg"]
        assert probe.bowed
        assert probe in session.game.table.battlefield.cards
    finally:
        GOLD_SELF_GRANT.pop("free_grant_probe", None)
        triggers._TRIGGERS.get(ProducingGold, {}).pop("free_grant_probe", None)


def test_an_equip_offers_every_grant_its_legality_counted():
    """`_equips` gates on `gold_reach`, which counts what each producer could raise itself to. A
    payment that leaves that out can be unanswerable for a cost the legality check allowed."""
    game = two_seat_game()
    put_in_play(
        game, holding("of", owner=PlayerId.P1, printed_id="outlying_farms", gold_production=2)
    )
    hero = put_in_play(game, personality("hero", owner=PlayerId.P1))
    blade = attachment("blade", owner=PlayerId.P1, gold_cost=4)
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(register(game.table, blade))

    payment = equip.announce_equip(game, blade, PlayerId.P1, hero.id)

    # The cost is 4 and the Farm makes 2, so the payment is answerable only because it quotes the
    # ceiling the Farm can still reach for itself.
    assert payment.grantable == (("of", 2),)
    assert payment.accepts(DecisionResponse(("of",)))


def test_producing_gold_fires_before_the_yield_is_read():
    """The window is the whole point: a grant made there has to count toward the production it
    interrupts, or no card can raise its own yield as it bows."""

    try:

        @triggers.on(ProducingGold, "granting_probe")
        def _grant(ctx):
            if ctx.event.card_id != ctx.card.id:
                return []
            return [
                GrantModifier(
                    ctx.card.id, ctx.card.id, Stat.GOLD_PRODUCTION, 2, Duration.UNTIL_END_OF_TURN
                )
            ]

        # Prints 2 for a cost of 2. The change left in the pool is the measurement: four produced
        # means the window's grant landed before the yield was read, zero means it did not.
        # The cost stays inside the printed yield because affordability cannot see the grant:
        # `gold_reach` has no way to project what a window trigger would give.
        session = _dynasty_phase(
            [holding("gp", owner=PlayerId.P1, printed_id="granting_probe", gold_production=2)],
            cost=2,
        )
        session.act(PlayerId.P1, Recruit("tgt"))
        session.submit(PlayerId.P1, DecisionResponse(("gp",)))

        assert session.game.table.cards_by_id["tgt"] in session.game.table.battlefield.cards
        assert session.game.gold[PlayerId.P1] == 2  # produced 4, spent 2
    finally:
        triggers._TRIGGERS.get(ProducingGold, {}).pop("granting_probe", None)


def test_a_price_on_produced_gold_resolves_after_the_bow():
    """Outlying Farms' shape without Outlying Farms: raise the yield in the window, then pay for
    having done so once the Gold has landed. The price must not cost the card its own production."""

    try:

        @triggers.on(ProducingGold, "self_pricing_probe")
        def _grant(ctx):
            if ctx.event.card_id != ctx.card.id:
                return []
            return [
                GrantModifier(
                    ctx.card.id, ctx.card.id, Stat.GOLD_PRODUCTION, 2, Duration.UNTIL_END_OF_TURN
                )
            ]

        announced: list[int] = []

        @triggers.on(ProducedGold, "self_pricing_probe")
        def _price(ctx):
            if ctx.event.card_id != ctx.card.id:
                return []
            announced.append(ctx.event.amount)
            return [Destroy(ctx.card.id, ctx.card.owner)]

        session = _dynasty_phase(
            [holding("sp", owner=PlayerId.P1, printed_id="self_pricing_probe", gold_production=2)],
            cost=2,
        )
        session.act(PlayerId.P1, Recruit("tgt"))
        session.submit(PlayerId.P1, DecisionResponse(("sp",)))

        table = session.game.table
        assert table.cards_by_id["tgt"] in table.battlefield.cards
        assert session.game.gold[PlayerId.P1] == 2  # its raised yield still counted
        assert announced == [4]  # the event reports what it made, not what it prints
        assert table.cards_by_id["sp"] not in table.battlefield.cards  # and it paid for it
    finally:
        triggers._TRIGGERS.get(ProducingGold, {}).pop("self_pricing_probe", None)
        triggers._TRIGGERS.get(ProducedGold, {}).pop("self_pricing_probe", None)


def test_production_raises_its_events_once_per_producer():
    """A payment that bows two producers opens two windows and announces two yields, each naming its
    own card — not one pair for the payment."""
    opened: list[str] = []
    landed: list[tuple[str, int]] = []

    try:

        @triggers.on(ProducingGold, "counting_probe")
        def _opened(ctx):
            if ctx.event.card_id == ctx.card.id:
                opened.append(ctx.event.card_id)
            return []

        @triggers.on(ProducedGold, "counting_probe")
        def _landed(ctx):
            if ctx.event.card_id == ctx.card.id:
                landed.append((ctx.event.card_id, ctx.event.amount))
            return []

        session = _dynasty_phase(
            [
                holding("c1", owner=PlayerId.P1, printed_id="counting_probe", gold_production=2),
                holding("c2", owner=PlayerId.P1, printed_id="counting_probe", gold_production=3),
            ],
            cost=5,
        )
        session.act(PlayerId.P1, Recruit("tgt"))
        session.submit(PlayerId.P1, DecisionResponse(("c1",)))
        session.submit(PlayerId.P1, DecisionResponse(("c2",)))

        assert opened == ["c1", "c2"]
        assert landed == [("c1", 2), ("c2", 3)]
    finally:
        triggers._TRIGGERS.get(ProducingGold, {}).pop("counting_probe", None)
        triggers._TRIGGERS.get(ProducedGold, {}).pop("counting_probe", None)


def test_a_single_producer_that_covers_the_cost_pays_in_one_step():
    """One answer is still enough when one producer covers the whole cost — the payment only comes
    back round while something is still owed."""
    session = _dynasty_phase([holding("a", owner=PlayerId.P1, gold_production=5)], cost=5)
    session.act(PlayerId.P1, Recruit("tgt"))
    session.submit(PlayerId.P1, DecisionResponse(("a",)))

    assert session.game.pending is None
    assert session.game.table.cards_by_id["tgt"] in session.game.table.battlefield.cards


def test_a_partial_payment_re_raises_for_the_remainder():
    session = _dynasty_phase(
        [
            holding("a", owner=PlayerId.P1, gold_production=2),
            holding("b", owner=PlayerId.P1, gold_production=3),
        ],
        cost=5,
    )
    session.act(PlayerId.P1, Recruit("tgt"))
    session.submit(PlayerId.P1, DecisionResponse(("a",)))

    again = session.game.pending
    assert isinstance(again, ChoosePayment)
    assert again.available == 2  # what the first producer put in the pool
    assert again.candidates == ("b",)  # and only what is left to bow

    session.submit(PlayerId.P1, DecisionResponse(("b",)))
    assert session.game.table.cards_by_id["tgt"] in session.game.table.battlefield.cards


def test_a_payment_that_runs_out_of_producers_raises():
    """`accepts` refuses an answer that would strand a payment, so reaching this means affordability
    was wrong before the action was ever announced. Louder than handing the seat the card for free.
    """
    game = two_seat_game()
    game.stack.append(ContinuePayment(PlayerId.P1, amount=3, label="probe"))

    with pytest.raises(RuntimeError, match="cannot make up the difference"):
        action_sequence.run_stack(game)


def test_a_rulebook_cost_resolves_its_effects_after_a_partial_payment():
    """The completion is queued above whatever the announcing action left on the stack, so a cost
    that buys effects rather than a card still resolves them once the pool catches up."""
    game = two_seat_game()
    put_in_play(game, holding("a", owner=PlayerId.P1, gold_production=1))
    put_in_play(game, holding("b", owner=PlayerId.P1, gold_production=2))
    victim = put_in_play(game, holding("victim", owner=PlayerId.P1))

    game.pending = costs.announce_rulebook_cost(
        game, PlayerId.P1, 3, "probe", (Destroy("victim", PlayerId.P1),)
    )
    action_sequence.submit(game, DecisionResponse(("a",)))  # one of the three

    assert isinstance(game.pending, ChoosePayment)
    assert victim in game.table.battlefield.cards  # the effects wait for the rest

    action_sequence.submit(game, DecisionResponse(("b",)))
    assert victim not in game.table.battlefield.cards


def test_a_trigger_fired_by_the_first_producer_changes_the_second_yield():
    """What the loop is for: a producer's own window opens between one bow and the next, so what it
    grants can reach a producer that has not bowed yet."""

    try:

        @triggers.on(ProducingGold, "raising_probe")
        def _raise_the_other(ctx):
            if ctx.event.card_id != ctx.card.id:
                return []
            return [GrantModifier("b", "b", Stat.GOLD_PRODUCTION, 3, Duration.UNTIL_END_OF_TURN)]

        session = _dynasty_phase(
            [
                holding("a", owner=PlayerId.P1, printed_id="raising_probe", gold_production=2),
                holding("b", owner=PlayerId.P1, gold_production=1),
            ],
            # Inside the printed 2 + 1, because affordability cannot see what the window would give.
            cost=3,
        )
        session.act(PlayerId.P1, Recruit("tgt"))
        session.submit(PlayerId.P1, DecisionResponse(("a",)))  # a's window raises b to 4

        again = session.game.pending
        assert dict(again.produced)["b"] == 4  # quoted at what a's window made it worth
        session.submit(PlayerId.P1, DecisionResponse(("b",)))
        assert session.game.table.cards_by_id["tgt"] in session.game.table.battlefield.cards
        assert session.game.gold[PlayerId.P1] == 3  # 2 + 4 produced, 3 spent
    finally:
        triggers._TRIGGERS.get(ProducingGold, {}).pop("raising_probe", None)


@choice_resolver("test_window_grant")
def _window_grant(game, source_id, chosen, seat):
    if not chosen:
        return []
    return [
        GrantModifier(chosen[0], chosen[0], Stat.GOLD_PRODUCTION, 2, Duration.UNTIL_END_OF_TURN)
    ]


def test_a_production_window_trigger_may_pause_for_a_decision():
    """The capability the narrowing exists for. A producer's trait asks its controller a question as
    it bows, and the yield is read on the far side of the answer — so what the seat says still
    counts toward the production it interrupted."""
    try:

        @triggers.on(ProducingGold, "asking_window_probe")
        def _ask(ctx):
            if ctx.event.card_id != ctx.card.id:
                return []
            return [Ask(ctx.card.owner, "Raise this?", "test_window_grant", (ctx.card.id,))]

        session = _dynasty_phase(
            [holding("aw", owner=PlayerId.P1, printed_id="asking_window_probe", gold_production=2)],
            cost=2,
        )
        session.act(PlayerId.P1, Recruit("tgt"))
        session.submit(PlayerId.P1, DecisionResponse(("aw",)))

        asked = session.game.pending
        assert isinstance(asked, Confirm)
        assert asked.question == "Raise this?"
        assert not session.game.table.cards_by_id["aw"].bowed  # the yield is not read yet

        session.submit(PlayerId.P1, DecisionResponse(("aw",)))  # yes

        table = session.game.table
        assert table.cards_by_id["tgt"] in table.battlefield.cards
        assert session.game.gold[PlayerId.P1] == 2  # produced 4 after the grant, spent 2
    finally:
        triggers._TRIGGERS.get(ProducingGold, {}).pop("asking_window_probe", None)
