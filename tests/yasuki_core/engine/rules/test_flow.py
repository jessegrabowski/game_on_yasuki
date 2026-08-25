import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import (
    DynastyPrint,
    FatePrint,
    HoldingPrint,
    PersonalityPrint,
    SenseiPrint,
    StrongholdPrint,
)
from yasuki_core.engine.rules.actions import ActionTiming, ActivateAbility, Legacy, Pass, Recruit
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState, Phase, RESPONSE_TIMINGS
from yasuki_core.engine.rules.decisions import (
    ChoosePayment,
    Confirm,
    DiscardToHandSize,
    DecisionResponse,
    LeaveBowed,
)
from yasuki_core.engine.rules.economy import (
    GOLD_HANDLERS,
    GOLD_SELF_GRANT,
    gold_handler,
    register_self_grant,
)
from yasuki_core.engine.rules.effects import Ask, Destroy, GrantModifier
from yasuki_core.engine.rules import flow, legality
from yasuki_core.engine.rules.projection import project
from yasuki_core.engine.rules.events import (
    CardDiscarded,
    ProducedGold,
    ProducingGold,
    Straightened,
)
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.work import ContinuePayment
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


def _game(hand: int = 0, fate_deck: int = 1) -> GameState:
    """A two-seat game where P1 holds ``hand`` fate cards and each seat's fate deck holds
    ``fate_deck`` cards."""
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            register(
                state,
                L5RCard.of(
                    FatePrint, id=f"{seat.name}-fd{i}", name="F", side=Side.FATE, owner=seat
                ),
            )
            for i in range(fate_deck)
        ]
    hand_zone = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(hand):
        hand_zone.add(
            register(
                state,
                L5RCard.of(FatePrint, id=f"P1-h{i}", name="H", side=Side.FATE, owner=PlayerId.P1),
            )
        )
    return GameState.start(state, PlayerId.P1)


def _advance_to_end_of_turn(game: GameState) -> None:
    flow.advance(game)  # Action -> Battle
    flow.advance(game)  # Battle -> Dynasty
    flow.advance(game)  # Dynasty -> end of turn


def test_advance_walks_the_three_phases():
    game = _game()
    assert game.phase is Phase.ACTION
    flow.advance(game)
    assert game.phase is Phase.BATTLE
    flow.advance(game)
    assert game.phase is Phase.DYNASTY


def test_advance_past_dynasty_draws_fate_and_passes_the_turn():
    game = _game(hand=0, fate_deck=1)

    _advance_to_end_of_turn(game)

    assert game.turn == 2
    assert game.active is PlayerId.P2
    assert game.phase is Phase.ACTION
    assert len(game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards) == 1
    # Only the active player draws at their turn-end; the opponent's hand is untouched.
    assert game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].cards == []


def test_empty_fate_deck_draws_nothing_and_still_passes_the_turn():
    game = _game(hand=0, fate_deck=0)

    _advance_to_end_of_turn(game)

    assert game.turn == 2 and game.active is PlayerId.P2
    assert game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards == []


def test_advance_empties_the_gold_pool_on_each_phase_change():
    game = _game()
    game.add_gold(PlayerId.P1, 5)
    flow.advance(game)
    assert game.gold[PlayerId.P1] == 0


def test_the_end_of_turn_discard_is_not_the_seats_own_action():
    """A card that pays its controller "if the action was yours and discarded a Fate card" must not
    be paid for the rulebook trimming their hand — there was no action."""
    game = _game(hand=flow.MAX_HAND_SIZE, fate_deck=1)
    caravansary = holding(
        "P1-caravansary", printed_id="caravansary", name="Caravansary", owner=PlayerId.P1
    )
    put_in_play(game, caravansary)

    _advance_to_end_of_turn(game)
    victim = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards[0].id
    flow.submit(game, DecisionResponse((victim,)))

    assert caravansary.counters == {}


def test_overfull_hand_pauses_for_discard_then_resumes():
    game = _game(hand=flow.MAX_HAND_SIZE, fate_deck=1)  # 8 held + 1 drawn = 9

    _advance_to_end_of_turn(game)

    assert game.awaiting_decision
    assert isinstance(game.pending, DiscardToHandSize) and game.pending.count == 1
    # The request offers the whole hand as candidates.
    hand_cards = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    assert set(game.pending.candidates) == {card.id for card in hand_cards}
    assert game.turn == 1 and game.active is PlayerId.P1  # turn not yet passed

    hand = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    victim = hand.cards[0].id
    flow.submit(game, DecisionResponse((victim,)))

    assert not game.awaiting_decision
    assert game.turn == 2 and game.active is PlayerId.P2
    assert len(hand.cards) == flow.MAX_HAND_SIZE
    discard = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)]
    assert any(card.id == victim for card in discard.cards)


def test_cannot_advance_while_a_decision_is_pending():
    game = _game(hand=flow.MAX_HAND_SIZE, fate_deck=1)
    _advance_to_end_of_turn(game)
    assert game.awaiting_decision
    with pytest.raises(RuntimeError):
        flow.advance(game)


def test_submit_rejects_a_malformed_or_illegal_answer():
    game = _game(hand=flow.MAX_HAND_SIZE, fate_deck=1)
    _advance_to_end_of_turn(game)

    with pytest.raises(ValueError):  # wrong count: must discard exactly one
        flow.submit(game, DecisionResponse(()))
    with pytest.raises(ValueError):  # right count, but the card is not in hand
        flow.submit(game, DecisionResponse(("not-in-hand",)))
    assert game.awaiting_decision  # both rejections leave the game paused


def _bowed_on_battlefield(state: TableState, seat: PlayerId, card_id: str):
    card = register(
        state, L5RCard.of(DynastyPrint, id=card_id, name="B", side=Side.DYNASTY, owner=seat)
    )
    card.bow()
    state.battlefield.add(card)
    return card


def _facedown_in_province(state: TableState, seat: PlayerId, card_id: str):
    card = register(
        state, L5RCard.of(DynastyPrint, id=card_id, name="P", side=Side.DYNASTY, owner=seat)
    )
    card.turn_face_down()
    state.zones[ops.create_province(state, seat)].add(card)
    return card


def test_begin_game_straightens_and_reveals_only_the_active_board():
    state = TableState.empty_two_seat()
    mine_bowed = _bowed_on_battlefield(state, PlayerId.P1, "P1-bf")
    mine_facedown = _facedown_in_province(state, PlayerId.P1, "P1-pv")
    foe_bowed = _bowed_on_battlefield(state, PlayerId.P2, "P2-bf")
    foe_facedown = _facedown_in_province(state, PlayerId.P2, "P2-pv")

    game = GameState.start(state, PlayerId.P1)
    flow.begin_game(game)

    assert mine_bowed.bowed is False and mine_facedown.face_up is True
    # The opponent's board is untouched at the active player's start of turn.
    assert foe_bowed.bowed is True and foe_facedown.face_up is False


def test_the_turn_start_straighten_announces_each_card_it_stands_up(reacting):
    """A card that watches for its own straightening has to hear about the one the rulebook does,
    not only the one an effect does — Culling Grounds gives up its Personality either way."""
    state = TableState.empty_two_seat()
    bowed = put_in_play(state, holding("P1-bowed", printed_id="straighten_probe"))
    bowed.bow()
    already_up = put_in_play(state, holding("P1-up", printed_id="plain_farm"))
    seen: list[str] = []
    reacting(Straightened, "straighten_probe", lambda ctx: seen.append(ctx.event.card_id) or [])

    game = GameState.start(state, PlayerId.P1)
    flow.begin_game(game)

    # One probe hears every Straightened raised, whichever card it names, so a card announced
    # for standing up when it was never bowed would show up here as a second entry.
    assert seen == [bowed.id]
    assert already_up.bowed is False


def _game_with_stronghold_clan(clan: str | None) -> GameState:
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        L5RCard.of(
            StrongholdPrint,
            id="P1-SH",
            name="SH",
            side=Side.STRONGHOLD,
            owner=PlayerId.P1,
            clan=clan,
        ),
    )
    return GameState.start(state, PlayerId.P1)


def test_recruit_cost_adds_the_off_clan_surcharge_only_for_a_different_clan():
    game = _game_with_stronghold_clan("crab")
    same = L5RCard.of(
        HoldingPrint,
        id="h1",
        name="H",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_cost=4,
        clan="crab",
    )
    other = L5RCard.of(
        HoldingPrint,
        id="h2",
        name="H",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_cost=4,
        clan="crane",
    )

    assert legality.recruit_cost(game, same) == 4
    assert legality.recruit_cost(game, other) == 4 + legality.OFF_CLAN_SURCHARGE


def test_recruit_cost_charges_no_surcharge_when_clan_alignment_is_unknown():
    game = _game_with_stronghold_clan(None)
    holding = L5RCard.of(
        HoldingPrint,
        id="h",
        name="H",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_cost=4,
        clan="crane",
    )
    assert legality.recruit_cost(game, holding) == 4  # no Stronghold clan to compare against


def _personality(clans: tuple[str, ...], **kwargs) -> L5RCard:
    return L5RCard.of(
        PersonalityPrint,
        id="p",
        name="P",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_cost=5,
        clan=clans[0] if clans else None,
        clans=clans,
        **kwargs,
    )


def test_recruit_cost_reads_every_listed_clan_not_just_the_first():
    # Bayushi Aramoro is printed Ninja and Scorpion; the alignment that matters is second in the list.
    game = _game_with_stronghold_clan("Scorpion")
    aramoro = _personality(("Ninja", "Scorpion"))
    assert legality.recruit_cost(game, aramoro) == 5


def test_recruit_cost_treats_naga_and_akasha_as_one_alignment():
    game = _game_with_stronghold_clan("Naga")
    akasha_personality = _personality(("Akasha",))
    assert legality.recruit_cost(game, akasha_personality) == 5


def test_recruit_cost_charges_no_surcharge_for_an_unaligned_personality():
    game = _game_with_stronghold_clan("Scorpion")
    # A clan name that is not a legal alignment (a minor clan) leaves the card unaligned.
    assert legality.recruit_cost(game, _personality(("Fox",))) == 5
    assert legality.recruit_cost(game, _personality(())) == 5


def test_recruit_cost_surcharges_a_personality_aligned_to_another_clan():
    game = _game_with_stronghold_clan("Scorpion")
    assert legality.recruit_cost(game, _personality(("Crane",))) == 5 + legality.OFF_CLAN_SURCHARGE


def test_a_stronghold_printing_several_clans_surcharges_none_of_them():
    """A Stronghold is a card, and a card may print more than one clan (the debug fixture prints all
    ten). Every alignment it carries is one the seat plays, so none of them is off-clan."""
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        L5RCard.of(
            StrongholdPrint,
            id="P1-SH",
            name="SH",
            side=Side.STRONGHOLD,
            owner=PlayerId.P1,
            clans=("Lion", "Crane"),
        ),
    )
    game = GameState.start(state, PlayerId.P1)

    assert legality.recruit_cost(game, _personality(("Lion",))) == 5
    assert legality.recruit_cost(game, _personality(("Crane",))) == 5
    assert (
        legality.recruit_cost(game, _personality(("Scorpion",))) == 5 + legality.OFF_CLAN_SURCHARGE
    )


def test_a_stronghold_with_no_legal_alignment_neither_surcharges_nor_proclaims():
    # A Shadowlands / minor-clan Stronghold has no legal Clan Alignment, so it has nothing to compare
    # against: an aligned Personality costs face value and none can be Proclaimed.
    game = _game_with_stronghold_clan("Shadowlands")
    assert legality.recruit_cost(game, _personality(("Crab",))) == 5
    assert not legality.can_proclaim(game, _personality(("Crab",)))


def test_can_proclaim_accepts_any_shared_alignment_of_a_multi_clan_personality():
    doji = _personality(("Crane", "Mantis"))  # a legal Crane/Mantis Personality
    assert legality.can_proclaim(_game_with_stronghold_clan("Crane"), doji)
    assert legality.can_proclaim(_game_with_stronghold_clan("Mantis"), doji)


def test_can_proclaim_rejects_off_clan_and_unaligned_personalities():
    game = _game_with_stronghold_clan("Scorpion")
    assert not legality.can_proclaim(game, _personality(("Crane",)))  # off-clan
    assert not legality.can_proclaim(game, _personality(("Fox",)))  # unaligned (minor clan only)
    assert not legality.can_proclaim(game, _personality(()))  # unaligned (no clan)


def _begun_game_with_sensei(sensei_printed_id: str) -> GameState:
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        L5RCard.of(StrongholdPrint, id="P1-SH", name="SH", side=Side.STRONGHOLD, owner=PlayerId.P1),
    )
    put_in_play(
        state,
        L5RCard.of(
            SenseiPrint,
            id="P1-SE",
            name="Sensei",
            side=Side.FATE,
            owner=PlayerId.P1,
            printed_id=sensei_printed_id,
        ),
    )
    game = GameState.start(state, PlayerId.P1)
    flow.begin_game(game)
    return game


def test_begin_game_grants_mishimes_ignore_honor_requirements_waiver():
    game = _begun_game_with_sensei("mishime_sensei")
    assert game.table.seats[PlayerId.P1].ignores_honor_requirements is True


def test_begin_game_leaves_an_ordinary_seat_enforcing_honor_requirements():
    game = _begun_game_with_sensei("some_other_sensei")
    assert game.table.seats[PlayerId.P1].ignores_honor_requirements is False


def _discount_game(*, clan=None, first_player=PlayerId.P1, in_play=()):
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        L5RCard.of(
            StrongholdPrint,
            id="P1-SH",
            name="SH",
            side=Side.STRONGHOLD,
            owner=PlayerId.P1,
            clan=clan,
        ),
    )
    for card in in_play:
        put_in_play(state, card)
    return GameState.start(state, first_player)


def _holding(printed_id: str, gold_cost: int, clan: str | None = None) -> L5RCard:
    return L5RCard.of(
        HoldingPrint,
        id=f"{printed_id}-inst",
        name="H",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        printed_id=printed_id,
        gold_cost=gold_cost,
        clan=clan,
    )


def test_colonial_farm_discounts_one_for_a_lion_player():
    farm = _holding("colonial_farm", gold_cost=6)
    assert legality.recruit_cost(_discount_game(clan="Lion"), farm) == 5
    assert legality.recruit_cost(_discount_game(clan="Crab"), farm) == 6  # no discount off-clan


def test_fantastic_gardens_discounts_two_for_a_crane_player():
    gardens = _holding("fantastic_gardens", gold_cost=7)
    assert legality.recruit_cost(_discount_game(clan="Crane"), gardens) == 5
    assert legality.recruit_cost(_discount_game(clan="Lion"), gardens) == 7


def test_moto_traders_discounts_with_another_merchant_caravan_in_play():
    caravan = L5RCard.of(
        HoldingPrint,
        id="mc",
        name="C",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        keywords=("Merchant Caravan",),
    )
    traders = _holding("moto_traders", gold_cost=5)
    assert legality.recruit_cost(_discount_game(in_play=(caravan,)), traders) == 4
    assert legality.recruit_cost(_discount_game(), traders) == 5


def test_shrine_of_courtesy_discounts_three_when_you_went_second():
    shrine = _holding("shrine_of_courtesy", gold_cost=4)
    assert (
        legality.recruit_cost(_discount_game(first_player=PlayerId.P2), shrine) == 1
    )  # P1 went second
    assert legality.recruit_cost(_discount_game(first_player=PlayerId.P1), shrine) == 4


def test_recruit_discount_floors_the_cost_at_zero():
    cheap = _holding("shrine_of_courtesy", gold_cost=2)  # a -3 discount would go negative
    assert legality.recruit_cost(_discount_game(first_player=PlayerId.P2), cheap) == 0


def test_recruit_discount_stacks_additively_with_the_off_clan_surcharge():
    caravan = L5RCard.of(
        HoldingPrint,
        id="mc",
        name="C",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        keywords=("Merchant Caravan",),
    )
    game = _discount_game(clan="Crab", in_play=(caravan,))
    traders = _holding(
        "moto_traders", gold_cost=5, clan="Unicorn"
    )  # off-clan from the Crab stronghold
    # Both apply and sum: +2 off-clan surcharge, -1 Merchant Caravan discount.
    assert legality.recruit_cost(game, traders) == 5 + legality.OFF_CLAN_SURCHARGE - 1


def test_recruit_rejects_invest_and_proclaim_together():
    # legal_actions never offers the pair, but a decoded tape could still carry it; recruit must
    # fail loudly rather than silently drop the Proclaim.
    game = _discount_game(clan="Crab")
    holding = register(game.table, _holding("teahouse", gold_cost=2))
    with pytest.raises(ValueError, match="Invest and Proclaim"):
        flow.recruit(game, holding.id, invest=True, proclaim=True)


# --- the Response Step ---


def _responder_game() -> GameState:
    """A game whose active seat holds one Response — a Caravansary answering its own Fate discard."""
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        holding(
            "caravansary",
            printed_id="caravansary",
            name="Caravansary",
            owner=PlayerId.P1,
            gold_production=2,
        ),
    )
    game = GameState.start(state, PlayerId.P1)
    game.action_events[:] = [CardDiscarded("some-fate", Side.FATE, PlayerId.P1)]
    return game


def test_a_response_step_opens_only_when_a_seat_holds_a_response():
    """A Step nobody could act in is a pass nobody needs to be asked for."""
    game = _responder_game()
    game.action_events.clear()  # the discard the Caravansary answers never happened

    assert flow.open_response_window(game) is False
    assert game.round_stack == []


def test_a_response_step_is_open_to_every_seat_and_to_nothing_else():
    """Any player may respond, and no one may take an Open action inside someone else's Step."""
    game = _responder_game()

    assert flow.open_response_window(game) is True

    assert game.round.timings == RESPONSE_TIMINGS
    for seat in PlayerId:
        assert legality.permits(game, seat, ActionTiming.RESPONSE)
        assert not legality.permits(game, seat, ActionTiming.OPEN)


def test_passing_a_response_step_returns_to_the_round_it_suspended():
    """The Step is a round over a round: passing it out closes it and hands the opportunity back,
    rather than passing the phase out from under the action that opened it."""
    game = _responder_game()
    suspended = game.round
    flow.open_response_window(game)

    for _ in PlayerId:
        flow.perform(game, Pass())

    assert game.phase is Phase.ACTION
    assert game.round_stack == []
    assert game.round.timings == suspended.timings


def test_a_new_phase_leaves_no_response_step_open():
    game = _responder_game()
    flow.open_response_window(game)

    flow.open_round(game)

    assert game.round_stack == []


def test_an_action_is_worded_for_the_seat_that_must_answer_it():
    """What the Step's banner says. Each action names itself and the card it was taken on, so a seat
    passing the Step is told what it is declining."""
    game = _responder_game()

    assert flow.describe_action(game, Recruit("caravansary")) == "the Recruit of Caravansary"
    assert (
        flow.describe_action(game, ActivateAbility("caravansary")) == "the ability on Caravansary"
    )
    assert flow.describe_action(game, Legacy()) == "Legacy"


def test_no_response_step_leaves_the_view_naming_nothing():
    game = _responder_game()

    assert project(game, PlayerId.P1).responding_to is None


def test_answering_the_turn_start_question_keeps_your_own_first_opportunity():
    """Turn structure is not an action. Answering it must not hand the opportunity on, or a seat
    holding a card that may remain bowed forfeits the opening action of each of its own turns."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("grounds", printed_id="culling_grounds", owner=PlayerId.P1))
    game = GameState.start(state, PlayerId.P1)
    game.table.cards_by_id["grounds"].bow()
    flow._begin_turn(game)
    assert isinstance(game.pending, LeaveBowed)

    flow.submit(game, DecisionResponse(("grounds",)))

    assert game.active is PlayerId.P1
    assert game.round.priority is PlayerId.P1


def test_a_turn_boundary_forgets_the_action_a_response_would_answer():
    """A Step opens on what the action just resolved did. An event still recorded a turn later is
    not that, and would open a Step on an action long gone."""
    game = _responder_game()
    game.action_taken = "the Recruit of something"

    flow._begin_turn(game)

    assert game.action_events == []
    assert game.action_taken == ""
    assert flow.open_response_window(game) is False


def test_opening_a_turn_records_none_of_its_own_events_as_an_action():
    """Straightening and revealing are steps of the turn, not something a seat may respond to."""
    game = _responder_game()

    flow._begin_turn(game)

    assert game.action_events == []


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
        def _paired(card, me, opponents, targets):
            return card.gold_production + (1 if me.controls("Probe", other_than=card) else 0)

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

    payment = flow.announce_equip(game, blade, PlayerId.P1, hero.id)

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
        flow.run_stack(game)


def test_a_rulebook_cost_resolves_its_effects_after_a_partial_payment():
    """The completion is queued above whatever the announcing action left on the stack, so a cost
    that buys effects rather than a card still resolves them once the pool catches up."""
    game = two_seat_game()
    put_in_play(game, holding("a", owner=PlayerId.P1, gold_production=1))
    put_in_play(game, holding("b", owner=PlayerId.P1, gold_production=2))
    victim = put_in_play(game, holding("victim", owner=PlayerId.P1))

    game.pending = flow.announce_rulebook_cost(
        game, PlayerId.P1, 3, "probe", (Destroy("victim", PlayerId.P1),)
    )
    flow.submit(game, DecisionResponse(("a",)))  # one of the three

    assert isinstance(game.pending, ChoosePayment)
    assert victim in game.table.battlefield.cards  # the effects wait for the rest

    flow.submit(game, DecisionResponse(("b",)))
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
