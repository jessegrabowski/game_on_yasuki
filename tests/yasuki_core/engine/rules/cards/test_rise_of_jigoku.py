from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.rules.actions import ActivateAbility, Pass, Recruit
from yasuki_core.engine.rules.decisions import (
    ChooseAbilityTarget,
    Confirm,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.cards.rise_of_jigoku import CAVALRY_FOLLOWER, MISHIMES_ONI
from yasuki_core.engine.rules.economy import effective_keywords as keywords_of
from yasuki_core.engine.rules.economy import (
    effective_chi,
    effective_force,
    effective_gold_production,
    effective_province_strength,
)
from yasuki_core.engine.rules.effects import Destroy
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import HoldingPrint, SenseiPrint, StrongholdPrint

from tests.yasuki_core.engine.builders import (
    attachment,
    end_phase,
    end_turn,
    holding,
    pay,
    personality,
    put_in_play,
    register,
    stronghold,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


def _rural_market_game(wealth=1):
    state = TableState.empty_two_seat()
    counters = {"wealth": wealth} if wealth else {}
    put_in_play(
        state,
        holding("rm", printed_id="rural_market", keywords=("Farm", "Market"), counters=counters),
    )
    put_in_play(
        state, holding("bf", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )
    session = EngineSession.start(state, P1)
    session.game.table.cards_by_id["bf"].bow()  # bow after the start-of-turn straighten
    return session


def test_rural_market_pays_itself_for_another_farm_going_down():
    game = two_seat_game()
    market = put_in_play(
        game, holding("rm", printed_id="rural_market", keywords=("Farm", "Market"))
    )
    other = put_in_play(game, holding("bf", printed_id="plain_farm", keywords=("Farm",)))

    resolve_effects(game, [Destroy(other.id, P1)])

    assert market.counters == {"wealth": 1}


def test_rural_market_pays_itself_nothing_for_its_own_destruction():
    """It carries Farm itself and now hears its own destruction announced, but the token would land
    on a Holding already in the discard, which can hold none (CR, Tokens)."""
    game = two_seat_game()
    market = put_in_play(
        game, holding("rm", printed_id="rural_market", keywords=("Farm", "Market"))
    )

    resolve_effects(game, [Destroy(market.id, P1)])

    assert market.counters == {}


def test_rural_market_spends_a_wealth_token_to_straighten_a_farm():
    session = _rural_market_game(wealth=1)
    session.act(P1, ActivateAbility("rm"))
    session.submit(P1, DecisionResponse(("bf",)))

    table = session.game.table
    assert not table.cards_by_id["bf"].bowed  # straightened
    assert table.cards_by_id["rm"].counters.get("wealth", 0) == 0  # the token was spent


def test_rural_market_is_not_activatable_without_a_wealth_token():
    session = _rural_market_game(wealth=0)
    assert ActivateAbility("rm") not in session.legal_actions(P1)


def _harvested_game(other_farms: int = 2) -> EngineSession:
    state = TableState.empty_two_seat()
    put_in_play(
        state, holding("hl", printed_id="harvested_land", keywords=("Farm",), gold_production=2)
    )
    for i in range(other_farms):
        put_in_play(
            state, holding(f"f{i}", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
        )
    return EngineSession.start(state, P1)


def test_harvested_land_destroys_itself_to_boost_your_other_farms():
    session = _harvested_game(other_farms=2)
    session.act(P1, ActivateAbility("hl"))

    table = session.game.table
    assert session.game.pending is None  # untargeted — it hits every other Farm, no choice
    assert "hl" in {c.id for c in table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)].cards}
    assert effective_gold_production(session.game, table.cards_by_id["f0"]) == 3  # base 2 + 1
    assert effective_gold_production(session.game, table.cards_by_id["f1"]) == 3


def test_harvested_land_is_not_offered_without_another_farm():
    session = _harvested_game(other_farms=0)
    assert ActivateAbility("hl") not in session.legal_actions(P1)


def test_harvested_land_boost_expires_at_end_of_turn():
    session = _harvested_game(other_farms=1)
    session.act(P1, ActivateAbility("hl"))
    assert effective_gold_production(session.game, session.game.table.cards_by_id["f0"]) == 3

    for _ in range(3):  # end P1's turn — the boost outlives its destroyed source but not the turn
        end_phase(session)
    assert effective_gold_production(session.game, session.game.table.cards_by_id["f0"]) == 2


def test_harvested_land_activation_replays_to_the_same_state():
    session = _harvested_game(other_farms=2)
    session.act(P1, ActivateAbility("hl"))
    assert replay(session.log) == session.game


def _modest_farm_game(
    *,
    target_keywords=(),
    target_cost=2,
    with_producer=True,
    producer_gp=8,
    target_printed_id="plain_holding",
    extra_in_play=(),
):
    """An Action-phase session: P1's Modest Farm and a face-up Holding in a province to recruit
    through Modest Farm's ability. With ``with_producer`` a gold Holding of ``producer_gp`` yield is
    also in play to pay the recruit; without it, only Modest Farm's own (forfeited) production
    remains."""
    state = TableState.empty_two_seat()
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(
            state,
            L5RCard.of(HoldingPrint, id="refill", name="R", side=Side.DYNASTY, owner=P1),
        )
    ]
    if with_producer:
        put_in_play(
            state,
            L5RCard.of(
                HoldingPrint,
                id="SH",
                name="SH",
                side=Side.DYNASTY,
                owner=P1,
                gold_production=producer_gp,
            ),
        )
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="mf",
            name="Modest Farm",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="modest_farm",
            keywords=("Farm",),
            gold_production=1,
        ),
    )
    target = register(
        state,
        L5RCard.of(
            HoldingPrint,
            id="target",
            name="Target",
            side=Side.DYNASTY,
            owner=P1,
            printed_id=target_printed_id,
            keywords=target_keywords,
            gold_cost=target_cost,
            gold_production=2,
        ),
    )
    target.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(target)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    for card in extra_in_play:
        put_in_play(state, card)
    return EngineSession.start(state, P1)  # Action phase


def _drive_to_straighten_choice(session):
    session.act(P1, ActivateAbility("mf"))
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget) and pending.candidates == ("target",)
    session.submit(P1, DecisionResponse(("target",)))
    pending = session.game.pending
    assert isinstance(pending, ChoosePayment) and pending.amount == 2  # X = the target's cost
    pay(session, P1)
    pending = session.game.pending
    # Asked as a question naming both cards, not as a card to click on the board.
    assert isinstance(pending, Confirm)
    assert pending.prompt() == "Destroy Modest Farm to straighten Target?"
    assert pending.candidates == ("mf",)  # answering yes returns them; no returns none


def test_modest_farm_is_activatable_with_a_province_holding():
    session = _modest_farm_game()
    assert ActivateAbility("mf") in session.legal_actions(P1)


def test_modest_farm_is_not_activatable_while_bowed():
    session = _modest_farm_game()
    session.game.table.cards_by_id["mf"].bow()
    assert ActivateAbility("mf") not in session.legal_actions(P1)


def test_modest_farm_is_not_offered_when_no_target_is_affordable():
    # Modest Farm's cost is paying the target's recruit cost; with no producer to cover it (Modest
    # Farm bows itself out of the pool), the ability must not be offered — else the recruit would
    # wedge at an unpayable payment.
    session = _modest_farm_game(target_cost=3, with_producer=False)
    assert ActivateAbility("mf") not in session.legal_actions(P1)


def test_modest_farm_does_not_count_its_own_forfeited_production_as_affordability():
    # Producer gp2 + Modest Farm gp1 covers a cost-3 target only if Modest Farm's own yield counts —
    # but Modest Farm bows itself as the cost, so it cannot. The ability must not be offered.
    session = _modest_farm_game(target_cost=3, producer_gp=2)
    assert ActivateAbility("mf") not in session.legal_actions(P1)


def test_modest_farm_destroys_itself_to_recruit_the_target_unbowed():
    session = _modest_farm_game(target_keywords=("Farm",))
    _drive_to_straighten_choice(session)
    session.submit(P1, DecisionResponse(("mf",)))  # sacrifice Modest Farm

    table = session.game.table
    assert table.cards_by_id["target"] in table.battlefield.cards
    assert not table.cards_by_id["target"].bowed  # straightened by the sacrifice
    discard = table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert "mf" in {c.id for c in discard.cards}  # Modest Farm destroyed


def test_modest_farm_can_be_kept_leaving_the_recruit_bowed():
    session = _modest_farm_game()
    _drive_to_straighten_choice(session)
    session.submit(P1, DecisionResponse(()))  # decline the sacrifice

    table = session.game.table
    assert table.cards_by_id["target"].bowed  # recruits enter bowed
    mf = table.cards_by_id["mf"]
    assert mf in table.battlefield.cards and mf.bowed  # Modest Farm kept, still bowed by its cost


def test_modest_farm_grants_a_farm_target_renew_refilling_its_province_face_up():
    session = _modest_farm_game(target_keywords=("Farm",))
    _drive_to_straighten_choice(session)
    session.submit(P1, DecisionResponse(()))

    refill = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert refill.face_up  # Renew granted to the Farm target


def test_modest_farm_does_not_grant_renew_to_a_non_farm_target():
    session = _modest_farm_game(target_keywords=("Market",))
    _drive_to_straighten_choice(session)
    session.submit(P1, DecisionResponse(()))

    refill = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert not refill.face_up  # no Renew for a non-Farm target


def test_modest_farm_activation_replays_to_the_same_state():
    session = _modest_farm_game(target_keywords=("Farm",))
    _drive_to_straighten_choice(session)
    session.submit(P1, DecisionResponse(("mf",)))
    assert replay(session.log) == session.game


def test_recruiting_a_renew_keyword_card_refills_its_province_face_up():
    # The general Renew rule: a normally-recruited card with the Renew keyword refills face-up.
    state = TableState.empty_two_seat()
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(
            state,
            L5RCard.of(HoldingPrint, id="refill", name="R", side=Side.DYNASTY, owner=P1),
        )
    ]
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="SH",
            name="SH",
            side=Side.DYNASTY,
            owner=P1,
            gold_production=8,
        ),
    )
    renewer = register(
        state,
        L5RCard.of(
            HoldingPrint,
            id="warrens",
            name="W",
            side=Side.DYNASTY,
            owner=P1,
            keywords=("Renew",),
            gold_cost=1,
        ),
    )
    renewer.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(renewer)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty

    session.act(P1, Recruit("warrens"))
    pay(session, P1)
    refill = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert refill.face_up


def _decision_sequence(session, answers):
    """Drive the session with ``answers`` and record every decision it paused on, as
    ``(request type name, candidates)``."""
    recorded = []
    for answer in answers:
        pending = session.game.pending
        recorded.append((type(pending).__name__, tuple(pending.candidates)))
        session.submit(P1, DecisionResponse(answer))
    return recorded


def test_modest_farm_recruit_puts_its_questions_in_a_fixed_order():
    # A characterization test: the recruited card's own enter-play trait must resolve *before*
    # Modest Farm offers its sacrifice. Both orderings leave the same final board, so only the
    # question order distinguishes them.
    session = _modest_farm_game(
        target_keywords=("Farm",),
        target_printed_id="wheat_farm",
        # Must be dealt before the session starts: EngineSession.start snapshots the table into the
        # log, so a card added afterwards is absent on replay.
        extra_in_play=(
            L5RCard.of(
                HoldingPrint,
                id="other-farm",
                name="Other Farm",
                side=Side.DYNASTY,
                owner=P1,
                keywords=("Farm",),
            ),
        ),
    )

    session.act(P1, ActivateAbility("mf"))
    sequence = _decision_sequence(
        session,
        answers=[("target",), ("SH",), ("other-farm",), ("mf",)],
    )

    assert sequence == [
        ("ChooseAbilityTarget", ("target",)),  # which Province Holding to recruit
        ("ChoosePayment", ("SH",)),  # pay its cost
        ("ChooseCards", ("mf", "other-farm")),  # Wheat Farm's own enter-play trait
        ("Confirm", ("mf",)),  # only then: destroy Modest Farm to straighten it?
    ]
    assert session.game.pending is None
    assert replay(session.log) == session.game  # the whole interleaving rebuilds from the tape


def test_backing_out_of_modest_farm_unwinds_the_bow_it_already_paid():
    """The cost is paid before the target is chosen, so backing out at any later step has to undo
    it. Leaving the Farm bowed charged the seat for an ability that never resolved."""
    session = _modest_farm_game()
    session.act(P1, ActivateAbility("mf"))
    session.submit(P1, DecisionResponse(("target",)))  # past the target, into the payment
    assert session.game.table.cards_by_id["mf"].bowed

    session.cancel(P1)

    assert not session.game.table.cards_by_id["mf"].bowed
    assert session.game.pending is None
    assert ActivateAbility("mf") in session.legal_actions(P1)  # and it can be announced again


def test_backing_out_leaves_no_half_resolved_cascade_behind():
    """The deferred question outlived a cancelled payment and fired on the next action, offering to
    destroy the Farm to straighten a card that was never recruited."""
    session = _modest_farm_game()
    session.act(P1, ActivateAbility("mf"))
    session.submit(P1, DecisionResponse(("target",)))
    session.cancel(P1)

    assert session.game.stack == []
    session.act(P1, Pass())
    assert session.game.pending is None


def test_backing_out_of_the_first_step_unwinds_it_too():
    session = _modest_farm_game()
    session.act(P1, ActivateAbility("mf"))
    session.cancel(P1)  # at the target choice, before anything was picked

    assert not session.game.table.cards_by_id["mf"].bowed
    assert "target" not in {c.id for c in session.game.table.battlefield.cards}


# --- Mishime Sensei ---


def _mishime_game(*, chi=3, stronghold_production=6):
    """P1's Mishime Sensei in play with a Personality to feed it and a Stronghold that can raise the
    five gold the ability charges."""
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1, gold_production=stronghold_production))
    put_in_play(
        state,
        L5RCard.of(
            SenseiPrint,
            id="sensei",
            name="Mishime Sensei",
            side=Side.FATE,
            owner=P1,
            printed_id="mishime_sensei",
        ),
    )
    put_in_play(state, personality("victim", force=1, chi=chi))
    token_template(
        state,
        MISHIMES_ONI,
        name="Mishime's Oni",
        card_type="Personality",
        keywords=("Shadowlands", "Nonhuman", "Oni"),
        chi=2,
    )
    return EngineSession.start(state, P1)


def _summon_oni(session, *, destroy: bool):
    """Run the whole ability: pay, pick the Personality, then answer the destroy question."""
    session.act(P1, ActivateAbility("sensei"))
    pay(session, P1)  # bow the Stronghold for the five gold
    session.submit(P1, DecisionResponse(("victim",)))
    session.submit(P1, DecisionResponse(("victim",) if destroy else ()))
    return next(card for card in session.game.table.battlefield.cards if card.is_token)


def test_the_oni_takes_its_force_from_the_personality_it_was_made_from():
    """The token prints its Force as "*"; only the card creating it knows the number."""
    session = _mishime_game(chi=4)

    oni = _summon_oni(session, destroy=True)

    assert oni.name == "Mishime's Oni"
    assert effective_force(session.game, oni) == 4
    assert effective_chi(session.game, oni) == 2  # printed on the token, not copied


def test_destroying_the_personality_keeps_the_oni_past_the_turn():
    session = _mishime_game(chi=4)

    oni = _summon_oni(session, destroy=True)
    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert [card.id for card in discard.cards] == ["victim"]
    end_turn(session)

    assert oni.id in session.game.table.cards_by_id


def test_sparing_the_personality_lends_the_oni_for_one_turn():
    """ "Banish it unless you destroyed the target" — the Personality lives, bowed, and the Oni goes
    before the turn it arrived in ends."""
    session = _mishime_game(chi=4)

    oni = _summon_oni(session, destroy=False)
    assert session.game.table.cards_by_id["victim"].bowed is True
    end_turn(session)

    assert oni.id not in session.game.table.cards_by_id
    assert session.game.table.cards_by_id["victim"] in session.game.table.battlefield.cards


def test_the_oni_copies_the_chi_the_target_has_rather_than_the_chi_he_prints():
    """ "Force equal to the target's Chi" is his Chi as the board has it, so a Personality carrying a
    Chi bonus makes a bigger Oni than his printed line would."""
    session = _mishime_game(chi=3)
    session.game.modifiers.append(
        Modifier("sensei", "victim", Stat.CHI, 2, Duration.WHILE_SOURCE_IN_PLAY)
    )

    oni = _summon_oni(session, destroy=True)

    assert effective_force(session.game, oni) == 5


def test_mishime_is_withheld_when_the_seat_cannot_raise_five_gold():
    session = _mishime_game(stronghold_production=4)

    assert ActivateAbility("sensei") not in session.legal_actions(P1)


def test_mishime_does_not_target_a_bowed_personality():
    session = _mishime_game()
    session.game.table.cards_by_id["victim"].bow()

    assert ActivateAbility("sensei") not in session.legal_actions(P1)


def test_mishime_replays_to_the_same_board():
    session = _mishime_game(chi=4)
    _summon_oni(session, destroy=False)

    assert replay(session.log).table == session.game.table


# --- Shinjo Fields ---


def _fields_game():
    """The Fields in play beside a Personality with no Cavalry of his own."""
    state = TableState.empty_two_seat()
    token_template(
        state,
        CAVALRY_FOLLOWER,
        name="Cavalry",
        card_type="Follower",
        keywords=("Cavalry",),
        force=1,
    )
    put_in_play(state, stronghold(P1, gold_production=4))
    put_in_play(state, holding("fields", printed_id="shinjo_fields", name="the Fields"))
    put_in_play(state, personality("rider", force=2, chi=2, keywords=("Samurai",)))
    return EngineSession.start(state, P1)


def _give_cavalry(session, *, destroy: bool):
    """Bow the Fields, name the Personality, then answer the offer to spend the Holding."""
    session.act(P1, ActivateAbility("fields"))
    session.submit(P1, DecisionResponse(("rider",)))
    session.submit(P1, DecisionResponse(("rider",) if destroy else ()))


def test_the_fields_give_your_personality_cavalry():
    session = _fields_game()

    _give_cavalry(session, destroy=False)

    rider = session.game.table.cards_by_id["rider"]
    assert "Cavalry" in keywords_of(session.game, rider)


def test_the_granted_cavalry_lapses_when_the_turn_ends():
    """An ongoing effect naming no duration lasts to the end of the turn and no further (CR,
    Duration of Effects)."""
    session = _fields_game()
    _give_cavalry(session, destroy=False)

    end_turn(session)

    rider = session.game.table.cards_by_id["rider"]
    assert "Cavalry" not in keywords_of(session.game, rider)


def test_destroying_the_fields_equips_a_cavalry_follower():
    session = _fields_game()

    _give_cavalry(session, destroy=True)

    game = session.game
    rider = game.table.cards_by_id["rider"]
    assert attachments_of(game, rider)[0].name == "Cavalry"
    assert game.table.cards_by_id["fields"] not in game.table.battlefield.cards


def test_the_cavalry_outlives_the_fields_that_gave_it():
    """The grant is dated to the turn, not to the Holding, so spending the Holding does not take
    the keyword back with it."""
    session = _fields_game()

    _give_cavalry(session, destroy=True)

    rider = session.game.table.cards_by_id["rider"]
    assert "Cavalry" in keywords_of(session.game, rider)


def test_declining_keeps_the_fields_and_grants_no_follower():
    session = _fields_game()

    _give_cavalry(session, destroy=False)

    game = session.game
    assert attachments_of(game, game.table.cards_by_id["rider"]) == ()
    assert game.table.cards_by_id["fields"] in game.table.battlefield.cards


def test_the_fields_are_withheld_while_bowed():
    session = _fields_game()
    session.game.table.cards_by_id["fields"].bow()

    assert ActivateAbility("fields") not in session.legal_actions(P1)


def test_shinjo_fields_replays_to_the_same_board():
    session = _fields_game()
    _give_cavalry(session, destroy=True)

    assert replay(session.log).table == session.game.table


# --- Sapphire Mine (the Item clause) ---


def _mine_and_item(*, gold_cost, attachment_type=AttachmentType.ITEM):
    game = two_seat_game()
    mine = put_in_play(
        game, holding("mine", printed_id="sapphire_mine", gold_production=2, name="the Mine")
    )
    item = attachment("relic", attachment_type=attachment_type, gold_cost=gold_cost)
    return game, mine, item


def test_the_mine_adds_a_gold_for_a_single_item():
    game, mine, item = _mine_and_item(gold_cost=3)

    assert effective_gold_production(game, mine, targets=(item,)) == 3  # printed 2, +1


def test_the_mine_adds_two_for_an_item_costing_six_or_more():
    game, mine, item = _mine_and_item(gold_cost=6)

    assert effective_gold_production(game, mine, targets=(item,)) == 4  # printed 2, +1, +1


def test_the_mine_pays_its_printed_rate_for_a_follower():
    """ "A single Item only" — a Follower is an attachment, but it is not an Item."""
    game, mine, item = _mine_and_item(gold_cost=6, attachment_type=AttachmentType.FOLLOWER)

    assert effective_gold_production(game, mine, targets=(item,)) == 2


def test_the_mine_pays_its_printed_rate_for_two_cards_at_once():
    """ "Only" is about the whole payment: an Item bought alongside anything else is not a single
    Item on its own."""
    game, mine, item = _mine_and_item(gold_cost=3)
    other = attachment("second", gold_cost=1)

    assert effective_gold_production(game, mine, targets=(item, other)) == 2


def test_the_mine_pays_its_printed_rate_with_no_target():
    game, mine, _ = _mine_and_item(gold_cost=3)

    assert effective_gold_production(game, mine) == 2


# --- Makeshift Fortifications ---


def test_makeshift_fortifications_walls_the_province_it_was_recruited_from():
    """The card is the join between the two halves: Recruiting a Fortification attaches it to the
    Province it left, and being attached is what makes its "+3PS" reach that Province."""
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        register(
            state,
            L5RCard.of(
                StrongholdPrint,
                id="P1-SH",
                name="SH",
                side=Side.STRONGHOLD,
                owner=P1,
                gold_production=8,
                province_strength=4,
            ),
        ),
    )
    first = ZoneKey(P1, ZoneRole.PROVINCE, 0)
    wall = register(
        state,
        holding(
            "wall",
            printed_id="makeshift_fortifications",
            gold_cost=6,
            owner=P1,
            keywords=("Fortification",),
        ),
    )
    wall.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(wall)
    state.zones[first] = province
    session = EngineSession.start(state, P1)
    assert effective_province_strength(session.game, first) == 4
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty

    session.act(P1, Recruit("wall"))
    pay(session, P1)

    assert session.game.table.province_attachments == {"wall": first}
    assert effective_province_strength(session.game, first) == 7
