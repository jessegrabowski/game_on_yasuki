import pytest

from yasuki_core.engine.rules.rulebook.recruit import RECRUIT, RECRUIT_WITH_INVEST
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import ability_for
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.effects import (
    DelayedEffect,
    Destroy,
    Dishonor,
    Effect,
    Evaluate,
    StartDuel,
)
from yasuki_core.engine.rules.turn.structure import DUEL_CONSEQUENCES
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    DeclareAttack,
    Pass,
    PlayStrategy,
)
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.cards.chaos_reigns_part_iii import (
    FUSHICHO,
    HANSHIRO_LOWER,
    HANSHIRO_RAISE,
    IKARICHIS_UNDEAD,
    KANPEKI_DYNASTY,
    NAGA_ZEALOT,
    ZOMBIE_FOLLOWER,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    ArrangeCards,
    ChooseCards,
    ChooseDiscard,
    ChooseNextTrigger,
    ChooseOption,
    DecisionResponse,
    FocusOrStrike,
    STRIKE,
    focus_token,
)
from yasuki_core.engine.rules.gold.production import effective_gold_production
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.stats.province_strength import effective_province_strength
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver, fire, resolve_effects
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole, location_of
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import ActionPrint, EventPrint, WindPrint

from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.rules.cards.test_lotus_edition import (
    _answer_everything,
    _hired_killer,
    _table,
)
from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    combat_segment,
    end_phase,
    end_turn,
    fate_card,
    focus_card,
    holding,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
    stronghold,
    terrain_at,
    token_template,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Chuda Jomei ---


def _jomei_game():
    """Jomei in play beside a Human Personality and a Nonhuman one."""
    game = two_seat_game()
    put_in_play(game, personality("jomei", printed_id="chuda_jomei", name="Chuda Jomei"))
    put_in_play(game, personality("monk", keywords=("Monk",)))
    put_in_play(game, personality("oni", keywords=("Nonhuman", "Oni")))
    return EngineSession.start(game.table, P1)


def test_chuda_jomei_costs_three_honor_to_enter_play():
    session = _jomei_game()

    fire(session.game, EnteredPlay("jomei"))

    assert session.game.table.seats[P1].honor == -3


def test_chuda_jomei_offers_only_human_personalities():
    """ "A target Human Personality": Human is the absence of Nonhuman (CR, Human), and Jomei is
    one himself."""
    session = _jomei_game()

    session.act(P1, ActivateAbility("jomei"))

    assert set(session.game.pending.candidates) == {"jomei", "monk"}


def test_chuda_jomei_gives_shadowlands_until_the_end_of_the_turn():
    session = _jomei_game()

    session.act(P1, ActivateAbility("jomei"))
    session.submit(P1, DecisionResponse(("monk",)))

    monk = session.game.table.cards_by_id["monk"]
    assert "Shadowlands" in effective_keywords(session.game, monk)

    end_turn(session)
    assert "Shadowlands" not in effective_keywords(session.game, monk)


# --- Kengun Grounds ---


def _kengun_game():
    """The Grounds in play beside a tainted Personality and a clean one."""
    game = two_seat_game()
    token_template(
        game,
        ZOMBIE_FOLLOWER,
        name="Zombie Follower",
        card_type="Follower",
        keywords=("Nonhuman", "Shadowlands", "Undead"),
        force=1,
    )
    put_in_play(game, holding("grounds", printed_id="kengun_grounds", name="Kengun Grounds"))
    put_in_play(game, personality("tainted", force=2, chi=3, keywords=("Shadowlands",)))
    put_in_play(game, personality("clean", force=2, chi=3, keywords=("Samurai",)))
    return EngineSession.start(game.table, P1)


def test_kengun_grounds_costs_two_honor_to_open():
    session = _kengun_game()

    fire(session.game, EnteredPlay("grounds"))

    assert session.game.table.seats[P1].honor == -2


def test_kengun_grounds_raises_a_zombie_for_a_shadowlands_personality():
    session = _kengun_game()

    session.act(P1, ActivateAbility("grounds"))
    session.submit(P1, DecisionResponse(("tainted",)))

    game = session.game
    zombie = attachments_of(game, game.table.cards_by_id["tainted"])[0]
    assert zombie.name == "Zombie Follower"
    assert game.table.cards_by_id["grounds"].bowed is True  # the cost
    assert game.table.seats[P1].honor == 0  # a tainted master pays nothing extra


def test_giving_the_zombie_to_an_untainted_personality_costs_five_honor():
    session = _kengun_game()

    session.act(P1, ActivateAbility("grounds"))
    session.submit(P1, DecisionResponse(("clean",)))

    assert attachments_of(session.game, session.game.table.cards_by_id["clean"])
    assert session.game.table.seats[P1].honor == -5


def test_kengun_grounds_is_withheld_on_another_seats_turn():
    session = _kengun_game()
    end_turn(session)
    session.act(P2, Pass())

    assert session.game.round.priority is P1
    assert ActivateAbility("grounds") not in session.legal_actions(P1)


# --- Moto Ikarichi, Bloodseeker ---


def _ikarichi_game(*, wind: str | None = None):
    """Ikarichi face-up in a Province with the Invest affordable, under ``wind`` if a Wind is in
    play."""
    state = TableState.empty_two_seat()
    token_template(
        state,
        IKARICHIS_UNDEAD,
        name="Ikarichi's Undead",
        card_type="Follower",
        keywords=("Cavalry", "Nonhuman", "Shadowlands", "Undead"),
        force=2,
    )
    put_in_play(state, stronghold(P1, gold_production=8))
    if wind is not None:
        put_in_play(
            state,
            L5RCard.of(
                WindPrint, id="P1-wind", name="Wind", side=Side.FATE, owner=P1, printed_id=wind
            ),
        )
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [register(state, holding("refill", owner=P1))]
    ikarichi = register(
        state,
        personality(
            "ikarichi", printed_id="moto_ikarichi_bloodseeker", force=3, chi=2, gold_cost=5
        ),
    )
    ikarichi.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(ikarichi)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    return session


def _resolve_arrival(session):
    while isinstance(session.game.pending, ChooseNextTrigger):
        session.submit(P1, DecisionResponse(session.game.pending.candidates[:1]))


def test_ikarichi_invests_two_gold_for_an_undead_outrider():
    session = _ikarichi_game()

    session.act(P1, ActivateAbility("ikarichi", RECRUIT_WITH_INVEST))
    payment = session.game.pending
    pay(session, P1)
    _resolve_arrival(session)

    game = session.game
    assert payment.amount == 7  # his five Gold Cost, plus the two the Invest charges
    outrider = attachments_of(game, game.table.cards_by_id["ikarichi"])[0]
    assert outrider.name == "Ikarichi's Undead"


def test_the_kanpeki_dynasty_rides_him_in_for_nothing():
    """'Invest :g2:, or :g0: if your Wind is The Kanpeki Dynasty'. The Wind is a card in play, so
    the Invest reads the board rather than a printed number alone."""
    session = _ikarichi_game(wind=KANPEKI_DYNASTY)

    session.act(P1, ActivateAbility("ikarichi", RECRUIT_WITH_INVEST))
    payment = session.game.pending
    pay(session, P1)
    _resolve_arrival(session)

    game = session.game
    assert payment.amount == 5  # his Gold Cost alone
    outrider = attachments_of(game, game.table.cards_by_id["ikarichi"])[0]
    assert outrider.name == "Ikarichi's Undead"  # paid nothing, and still got the Follower


def test_another_wind_leaves_the_invest_at_its_printed_price():
    session = _ikarichi_game(wind="some_other_wind")

    session.act(P1, ActivateAbility("ikarichi", RECRUIT_WITH_INVEST))

    assert session.game.pending.amount == 7


@pytest.mark.parametrize("key", [RECRUIT, RECRUIT_WITH_INVEST], ids=["plain", "invested"])
def test_ikarichi_costs_two_honor_however_he_arrives(key):
    """The Honor is his entry's price, not the Invest's, so it is charged once either way."""
    session = _ikarichi_game()

    session.act(P1, ActivateAbility("ikarichi", key))
    pay(session, P1)
    _resolve_arrival(session)

    assert session.game.table.seats[P1].honor == -2


def test_ikarichi_replays_to_the_same_board():
    """His Invest mints a card mid-recruit, and a replayed game has to mint the same one."""
    session = _ikarichi_game()
    session.act(P1, ActivateAbility("ikarichi", RECRUIT_WITH_INVEST))
    pay(session, P1)

    assert replay(session.log).table == session.game.table


# --- Walk with Tengoku ---


def _tengoku_game():
    """The Spell on a Shugenja, ready to bow."""
    game = two_seat_game()
    token_template(
        game,
        FUSHICHO,
        name="Fushicho",
        card_type="Personality",
        keywords=("Cavalry", "Fire", "Fushicho", "Nonhuman"),
        force=3,
        chi=2,
    )
    put_in_play(game, personality("shugenja", force=1, chi=4, keywords=("Shugenja",)))
    attached(game, attachment("spell", printed_id="walk_with_tengoku"), "shugenja")
    return EngineSession.start(game.table, P1)


def _fushicho_of(session):
    return next(card for card in session.game.table.battlefield.cards if card.is_token)


def test_walk_with_tengoku_calls_a_fushicho():
    session = _tengoku_game()

    session.act(P1, ActivateAbility("spell"))

    fushicho = _fushicho_of(session)
    assert fushicho.name == "Fushicho"
    assert effective_force(session.game, fushicho) == 3
    assert session.game.table.cards_by_id["spell"].bowed is True  # the cost bows the Spell


def test_the_fushicho_burns_out_before_the_turn_ends():
    session = _tengoku_game()

    session.act(P1, ActivateAbility("spell"))
    fushicho = _fushicho_of(session)
    end_turn(session)

    assert fushicho.id not in session.game.table.cards_by_id


def test_walk_with_tengoku_asks_for_no_target():
    """The Spell names none, so announcing it resolves the whole thing."""
    session = _tengoku_game()

    session.act(P1, ActivateAbility("spell"))

    assert session.game.pending is None


def test_walk_with_tengoku_replays_to_the_same_board():
    session = _tengoku_game()
    session.act(P1, ActivateAbility("spell"))

    assert replay(session.log).table == session.game.table


# --- Moto Traders ---


def _traders_game(*, in_deck=2):
    """The Traders in play with ``in_deck`` cards to draw from."""
    game = two_seat_game()
    put_in_play(
        game,
        holding("traders", printed_id="moto_traders", gold_production=5, name="the Traders"),
    )
    game.table.decks[DeckKey(P1, Side.FATE)].cards = [
        register(game.table, fate_card(f"f{index}", P1)) for index in range(in_deck)
    ]
    return EngineSession.start(game.table, P1)


def _hand_size(session):
    return len(session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards)


def test_bowing_the_traders_draws_a_card():
    session = _traders_game()
    before = _hand_size(session)

    session.act(P1, ActivateAbility("traders"))

    assert _hand_size(session) == before + 1
    assert session.game.table.cards_by_id["traders"].bowed is True


def test_the_traders_are_withheld_while_bowed():
    session = _traders_game()
    session.game.table.cards_by_id["traders"].bow()

    assert ActivateAbility("traders") not in session.legal_actions(P1)


def test_the_traders_replay_to_the_same_board():
    session = _traders_game()
    session.act(P1, ActivateAbility("traders"))

    assert replay(session.log).table == session.game.table


# --- Tanuki Band ---


def _band_game(*, mine=1, theirs=3):
    """The Band in play, with ``mine`` cards in P1's hand and ``theirs`` in P2's."""
    game = two_seat_game()
    put_in_play(game, holding("band", printed_id="tanuki_band", gold_production=1))
    for seat, count in ((P1, mine), (P2, theirs)):
        hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
        for index in range(count):
            hand.add(register(game.table, fate_card(f"{seat.name}-h{index}", seat)))
    return EngineSession.start(game.table, P1)


def _hand(session, seat):
    return [card.id for card in session.game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards]


def test_the_band_makes_a_player_holding_more_cards_discard_one_they_choose():
    session = _band_game()
    session.act(P1, ActivateAbility("band"))
    named = session.game.pending
    assert isinstance(named, ChooseOption) and len(named.candidates) == 1

    session.submit(P1, DecisionResponse(named.candidates))
    discard = session.game.pending
    assert isinstance(discard, ChooseDiscard) and discard.seat is P2 and discard.cause is P1
    session.submit(P2, DecisionResponse(("P2-h1",)))

    assert _hand(session, P2) == ["P2-h0", "P2-h2"]
    assert [
        card.id for card in session.game.table.zones[ZoneKey(P2, ZoneRole.FATE_DISCARD)].cards
    ] == ["P2-h1"]


def test_the_band_is_withheld_while_no_player_holds_more_cards_than_you():
    session = _band_game(mine=3, theirs=3)

    assert ActivateAbility("band") not in session.legal_actions(P1)


def test_the_band_asks_nothing_once_no_player_still_holds_more_cards_than_you():
    # The hands can even out between announcement and resolution.
    session = _band_game(mine=3, theirs=3)
    band = session.game.table.cards_by_id["band"]

    resolve_effects(session.game, ability_for(session.game, band).effects(session.game, band, band))

    assert session.game.pending is None
    assert len(_hand(session, P2)) == 3


@pytest.mark.parametrize(
    "clans, produced",
    [((), 1), (("Crane",), 2), (("Crane", "Lion"), 3), (("Crane", "Lion", "Phoenix"), 3)],
    ids=["one", "two", "three", "four"],
)
def test_the_band_produces_more_for_each_clan_alignment_you_control(clans, produced):
    game = two_seat_game()
    put_in_play(game, stronghold(P1, clan="Crab"))
    band = put_in_play(game, holding("band", printed_id="tanuki_band", gold_production=1))
    for clan in clans:
        put_in_play(game, personality(f"{clan}-p", clans=(clan,)))

    assert effective_gold_production(game, band) == produced


def test_the_band_replays_to_the_same_board():
    session = _band_game()
    session.act(P1, ActivateAbility("band"))
    session.submit(P1, DecisionResponse(session.game.pending.candidates))
    session.submit(P2, DecisionResponse(("P2-h0",)))

    assert replay(session.log).table == session.game.table


# --- Doji Maya (Experienced) ---


def _maya_game(*, courtier=True, filler=1):
    """Maya face-up in a Province, her Invest affordable, with a Courtier in the Dynasty deck.

    Three other Provinces are stocked so the only short one is the seat she vacates, which is how
    her refill finds its target.
    """
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1, gold_production=12))
    for index in range(1, 4):
        province_card(state, f"filler{index}", seat=P1, index=index)
    sought = personality("kakita", keywords=("Courtier",) if courtier else ("Bushi",))
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(state, sought),
        *(register(state, holding(f"plain-refill{i}", owner=P1)) for i in range(filler)),
    ]
    maya = register(
        state,
        personality("maya", printed_id="doji_maya_experienced", force=3, chi=4, gold_cost=6),
    )
    maya.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(maya)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)
    return session


def _province(session, index):
    return session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, index)].cards


def test_mayas_invest_refills_the_province_she_left_with_what_it_found():
    """ "Search your Dynasty deck for a Courtier or Tanuki Clan Personality and refill it with them,
    face-up." The Province she vacated is the one still short when the Invest resolves."""
    session = _maya_game()

    session.act(P1, ActivateAbility("maya", RECRUIT_WITH_INVEST))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("kakita",)))

    placed = _province(session, 0)
    assert [card.id for card in placed] == ["kakita"]
    assert placed[0].face_up
    deck = session.game.table.decks[DeckKey(P1, Side.DYNASTY)].cards
    assert "kakita" not in {card.id for card in deck}  # it left the deck to reach the Province


def test_mayas_invest_offers_only_the_personalities_her_card_names():
    """A Bushi in the deck is no candidate, so a deck holding nothing she names leaves the Province
    to the ordinary refill rather than putting the wrong card in it."""
    session = _maya_game(courtier=False)

    session.act(P1, ActivateAbility("maya", RECRUIT_WITH_INVEST))
    pay(session, P1)

    assert session.game.pending is None
    assert [card.id for card in _province(session, 0)] == ["plain-refill0"]


def test_mayas_invest_shuffles_the_dynasty_deck_it_read():
    """The search shows the seat their whole Dynasty deck, so its order is no longer secret."""
    session = _maya_game(filler=8)
    before = [card.id for card in session.game.table.decks[DeckKey(P1, Side.DYNASTY)].cards]

    session.act(P1, ActivateAbility("maya", RECRUIT_WITH_INVEST))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("kakita",)))

    after = [card.id for card in session.game.table.decks[DeckKey(P1, Side.DYNASTY)].cards]
    assert set(after) == set(before) - {"kakita"}  # same cards, minus the one she took
    assert after != [card for card in before if card != "kakita"]  # and not in the read order


def test_walk_with_tengoku_is_offered_under_both_of_its_designators():
    session = _tengoku_game()
    spell = session.game.table.cards_by_id["spell"]

    for designator in (ActionTiming.OPEN, ActionTiming.BATTLE):
        offered = legality.activatable(session.game, P1, frozenset({designator}))
        assert (spell, ability_for(session.game, spell, None)) in offered


# --- Hungry Moon ---


def _hungry_moon_game() -> EngineSession:
    state = TableState.empty_two_seat()
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                ActionPrint,
                id="moon",
                name="Hungry Moon",
                printed_id="hungry_moon",
                side=Side.FATE,
                owner=P1,
                gold_cost=0,
            ),
        )
    )
    put_in_play(state, personality("standing", owner=P2))
    put_in_play(state, personality("kneeling", owner=P2))
    put_in_play(state, holding("market", owner=P2, counters={"wealth": 2}))
    put_in_play(state, holding("farm", owner=P2))
    session = EngineSession.start(state, P1)
    session.game.table.cards_by_id["kneeling"].bow()
    return session


def test_hungry_moon_dishonors_only_a_bowed_personality():
    session = _hungry_moon_game()

    session.act(P1, PlayStrategy("moon", "dishonor"))
    asked = session.game.pending
    assert asked is not None and asked.candidates == ("kneeling",)
    session.submit(P1, DecisionResponse(("kneeling",)))

    assert session.game.table.cards_by_id["kneeling"].dishonorable


def test_hungry_moon_strips_a_holdings_wealth_and_names_who_pays():
    session = _hungry_moon_game()

    session.act(P1, PlayStrategy("moon", "wealth"))
    session.submit(P1, DecisionResponse(("market",)))
    session.submit(P1, DecisionResponse(("P2",)))

    assert session.game.table.cards_by_id["market"].counters == {}
    assert session.game.table.seats[P2].honor == -3


def test_hungry_moon_on_a_holding_with_no_wealth_asks_nobody_to_pay():
    session = _hungry_moon_game()

    session.act(P1, PlayStrategy("moon", "wealth"))
    session.submit(P1, DecisionResponse(("farm",)))

    assert session.game.pending is None
    assert session.game.table.seats[P2].honor == 0


# --- Doji Teru ---


def _teru_game() -> EngineSession:
    state = TableState.empty_two_seat()
    put_in_play(state, personality("teru", printed_id="doji_teru", force=3))
    put_in_play(state, personality("own", owner=P1))
    put_in_play(state, personality("theirs", owner=P2))
    put_in_play(state, personality("upright", owner=P2))
    session = EngineSession.start(state, P1)
    session.game.table.cards_by_id["own"].dishonor()
    session.game.table.cards_by_id["theirs"].dishonor()
    return session


def test_teru_targets_only_another_players_dishonorable_personality():
    session = _teru_game()

    session.act(P1, ActivateAbility("teru"))

    assert session.game.pending.candidates == ("theirs",)


def test_teru_gains_honor_when_the_controller_rehonors_their_personality():
    # Rehonoring is the action's own effect, so it is not substituted for the gain (CR, Rehonoring
    # 0.1): both happen.
    session = _teru_game()

    session.act(P1, ActivateAbility("teru"))
    session.submit(P1, DecisionResponse(("theirs",)))
    asked = session.game.pending
    assert asked.seat is P2
    session.submit(P2, DecisionResponse(asked.candidates))

    assert not session.game.table.cards_by_id["theirs"].dishonorable
    assert session.game.table.seats[P1].honor == 2
    assert effective_force(session.game, session.game.table.cards_by_id["teru"]) == 3


def test_teru_gets_force_when_the_controller_declines():
    session = _teru_game()

    session.act(P1, ActivateAbility("teru"))
    session.submit(P1, DecisionResponse(("theirs",)))
    session.submit(P2, DecisionResponse())

    assert session.game.table.cards_by_id["theirs"].dishonorable
    assert session.game.table.seats[P1].honor == 0
    assert effective_force(session.game, session.game.table.cards_by_id["teru"]) == 5


# --- Bayushi Gihei ---

GIHEI_PROBE = "probe_gihei_battle_dishonor"
GIHEI_ABILITY = Ability(
    timings=(ActionTiming.BATTLE,),
    label="Battle: dishonor a target enemy Personality",
    cost=no_cost,
    targets=lambda game, source: [
        card.id for card in personalities_in_play(game) if card.owner is not source.owner
    ],
    effects=lambda game, source, target: [Dishonor(target.id, source.owner)],
)


def _gihei_at_the_battle(*, gihei_assigned: bool) -> EngineSession:
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=P2, index=0)
    put_in_play(state, personality("gihei", printed_id="bayushi_gihei", force=3))
    put_in_play(state, personality("prober", printed_id=GIHEI_PROBE, force=3))
    put_in_play(state, personality("guard", owner=P2, force=1))
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    attackers = ("prober@0", "gihei@0") if gihei_assigned else ("prober@0",)
    session.submit(P1, DecisionResponse(attackers))
    session.submit(P2, DecisionResponse(("guard@0",)))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    session.act(P2, Pass())
    return session


def test_gihei_reacts_to_his_controllers_action_dishonoring_a_card_where_he_stands():
    with probe_ability(GIHEI_PROBE, GIHEI_ABILITY):
        session = _gihei_at_the_battle(gihei_assigned=True)
        session.act(P1, ActivateAbility("prober"))
        session.submit(P1, DecisionResponse(("guard",)))

        assert session.game.pending.seat is P1
        session.submit(P1, DecisionResponse(("P2",)))

    game = session.game
    assert effective_force(game, game.table.cards_by_id["gihei"]) == 5
    assert game.table.seats[P2].honor == -1


def test_gihei_at_home_ignores_a_dishonoring_at_the_battlefield():
    with probe_ability(GIHEI_PROBE, GIHEI_ABILITY):
        session = _gihei_at_the_battle(gihei_assigned=False)
        session.act(P1, ActivateAbility("prober"))
        session.submit(P1, DecisionResponse(("guard",)))

    game = session.game
    assert game.pending is None
    assert effective_force(game, game.table.cards_by_id["gihei"]) == 3


def test_gihei_reacts_to_a_destruction_where_he_stood_by_reading_the_event():
    # A card in his controller's home shares Gihei's location; it is in its discard when the event
    # fires, so the event carries where it stood. Another seat's home is a different location.
    game = two_seat_game()
    gihei = put_in_play(game, personality("gihei", printed_id="bayushi_gihei", force=3))
    own = put_in_play(game, personality("own"))
    theirs = put_in_play(game, personality("theirs", owner=P2))

    resolve_effects(game, [Destroy(theirs.id, P1)])
    assert game.pending is None

    resolve_effects(game, [Destroy(own.id, P1)])
    assert isinstance(game.pending, ChooseOption)
    assert effective_force(game, gihei) == 5


def test_gihei_ignores_the_other_seats_action():
    game = two_seat_game()
    gihei = put_in_play(game, personality("gihei", printed_id="bayushi_gihei", force=3))
    own = put_in_play(game, personality("own"))

    resolve_effects(game, [Destroy(own.id, P2)])

    assert game.pending is None
    assert effective_force(game, gihei) == 3


# --- Comprehensive Education ---


def _education_game(deck) -> EngineSession:
    """P1 holding Comprehensive Education over a Fate deck reading ``deck`` from the top, each
    entry an id or an (id, keyword) pair."""
    state = TableState.empty_two_seat()
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                ActionPrint,
                id="education",
                name="Comprehensive Education",
                printed_id="comprehensive_education",
                side=Side.FATE,
                owner=P1,
                gold_cost=0,
                keywords=("Unique",),
            ),
        )
    )
    cards = []
    for entry in deck:
        card_id, keyword = entry if isinstance(entry, tuple) else (entry, None)
        keywords = (keyword,) if keyword else ()
        cards.append(
            register(
                state,
                L5RCard.of(
                    ActionPrint,
                    id=card_id,
                    printed_id=card_id,
                    name=card_id,
                    side=Side.FATE,
                    owner=P1,
                    keywords=keywords,
                ),
            )
        )
    state.decks[DeckKey(P1, Side.FATE)].cards = list(reversed(cards))
    return EngineSession.start(state, P1)


def _education_fate_deck(session: EngineSession) -> list[str]:
    return [card.id for card in reversed(session.game.table.decks[DeckKey(P1, Side.FATE)].cards)]


def _play_education(session: EngineSession) -> None:
    session.act(P1, PlayStrategy("education"))


def test_comprehensive_education_walks_take_then_discard_then_bottom():
    session = _education_game(
        [("edict1", "Edict"), "plain1", ("kata1", "Kata"), ("edict2", "Edict"), "plain2", "deep"]
    )
    _play_education(session)
    pending = session.game.pending
    assert isinstance(pending, ChooseCards)
    assert pending.candidates == ("edict1", "kata1", "edict2")
    assert pending.minimum == 0

    session.submit(P1, DecisionResponse(("kata1",)))
    pending = session.game.pending
    assert isinstance(pending, ChooseCards)
    assert pending.candidates == ("edict1", "edict2") and pending.maximum == 2
    assert session.game.table.cards_by_id["kata1"].shown

    session.submit(P1, DecisionResponse(("edict2",)))
    pending = session.game.pending
    assert isinstance(pending, ArrangeCards) and pending.to_bottom
    assert pending.candidates == ("edict1", "plain1", "plain2")

    session.submit(P1, DecisionResponse(("plain2", "edict1", "plain1")))

    hand = [card.id for card in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards]
    assert hand == ["kata1"]
    discard = [
        card.id for card in session.game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].cards
    ]
    assert "edict2" in discard
    assert _education_fate_deck(session) == ["deep", "plain2", "edict1", "plain1"]
    assert session.game.look is None
    assert session.log.replay() == session.game


def test_comprehensive_education_with_no_edict_or_kata_goes_straight_to_the_bottom():
    session = _education_game(["a", "b", "c", "d", "e", "deep"])
    _play_education(session)

    pending = session.game.pending
    assert isinstance(pending, ArrangeCards) and pending.candidates == ("a", "b", "c", "d", "e")
    session.submit(P1, DecisionResponse(pending.unchanged))
    assert _education_fate_deck(session) == ["deep", "a", "b", "c", "d", "e"]


def test_comprehensive_education_declining_both_may_questions_still_buries_the_rest():
    session = _education_game([("edict1", "Edict"), "plain", "p2", "p3", "p4", "deep"])
    _play_education(session)

    session.submit(P1, DecisionResponse(()))  # take none
    session.submit(P1, DecisionResponse(()))  # discard none
    pending = session.game.pending
    assert isinstance(pending, ArrangeCards)
    assert pending.candidates == ("edict1", "plain", "p2", "p3", "p4")
    session.submit(P1, DecisionResponse(pending.unchanged))

    assert _education_fate_deck(session) == ["deep", "edict1", "plain", "p2", "p3", "p4"]
    assert session.game.look is None


# --- Bayushi Purimu ---


def test_bayushi_purimu_dishonors_a_personality_anywhere_and_costs_its_controller_3_honor():
    game = two_seat_game()
    put_in_play(game, personality("purimu", owner=PlayerId.P2, printed_id="bayushi_purimu"))
    far = put_in_play(game, personality("far", personal_honor=2))

    resolve_effects(game, [Destroy("purimu", Rulebook.BATTLE_RESOLUTION)])
    assert isinstance(game.pending, ChooseCards) and game.pending.seat is PlayerId.P2
    assert "far" in game.pending.candidates
    submit(game, DecisionResponse(("far",)))

    assert far.dishonorable
    assert game.table.seats[PlayerId.P1].honor == -3


def test_bayushi_purimu_raises_no_yu_when_hired_killer_destroys_him_outside_battle():
    state = _table()
    put_in_play(
        state, personality("purimu", owner=PlayerId.P2, printed_id="bayushi_purimu", gold_cost=3)
    )
    put_in_play(state, personality("witness"))
    killer = _hired_killer(state)
    session = EngineSession.start(state, PlayerId.P1)
    honor = session.game.table.seats[PlayerId.P2].honor

    session.act(PlayerId.P1, PlayStrategy(killer.id))
    _answer_everything(session, amount=5)

    game = session.game
    assert "purimu" not in {card.id for card in game.table.battlefield.cards}
    assert not any(card.dishonorable for card in game.table.cards_by_id.values())
    assert game.table.seats[PlayerId.P2].honor == honor


# --- Ijathilu Zealots ---


def test_ijathilu_zealots_create_two_zealots_in_their_home_as_they_die():
    units = [personality("attacker", force=5), personality("leader", owner=P2)]
    game = combat_segment(units, {"attacker": 0}, {"leader": 0}).game
    token_template(
        game,
        NAGA_ZEALOT,
        name="Naga Zealot",
        card_type="Personality",
        keywords=("Naga", "Nonhuman", "Zealot"),
        force=2,
        chi=2,
    )
    zealots = attachment(
        "zealots",
        owner=P2,
        printed_id="ijathilu_zealots",
        attachment_type=AttachmentType.FOLLOWER,
        force=3,
    )
    attached(game, zealots, "leader")

    resolve_effects(game, [Destroy("zealots", P1)])

    created = [card for card in personalities_in_play(game) if card.name == "Naga Zealot"]
    assert len(created) == 2
    assert all(card.owner is P2 for card in created)
    assert all(location_of(game.table, card).battlefield is None for card in created)


def test_ijathilu_zealots_fear_3_bows_an_enemy_of_force_3():
    units = [personality("leader"), personality("enemy", owner=P2, force=3)]
    session = combat_segment(units, {"leader": 0}, {"enemy": 0})
    zealots = attachment(
        "zealots", printed_id="ijathilu_zealots", attachment_type=AttachmentType.FOLLOWER, force=3
    )
    attached(session.game, zealots, "leader")

    session.act(P1, ActivateAbility("zealots"))
    session.submit(P1, DecisionResponse(("enemy",)))

    assert session.game.table.cards_by_id["enemy"].bowed


# --- Matsu Hanshiro ---


@pytest.mark.parametrize(("option", "change"), [(HANSHIRO_LOWER, -4), (HANSHIRO_RAISE, 4)])
def test_matsu_hanshiro_changes_the_province_he_dies_at(option, change):
    units = [
        personality("attacker", force=5),
        personality("hanshiro", owner=P2, printed_id="matsu_hanshiro"),
    ]
    game = combat_segment(units, {"attacker": 0}, {"hanshiro": 0}).game
    put_in_play(game, stronghold(P2, province_strength=6))
    province = ZoneKey(P2, ZoneRole.PROVINCE, 0)
    strength = effective_province_strength(game, province)

    resolve_effects(game, [Destroy("hanshiro", P1)])
    assert isinstance(game.pending, ChooseOption) and game.pending.seat is P2
    submit(game, DecisionResponse((option,)))

    assert effective_province_strength(game, province) == strength + change


@pytest.mark.parametrize("deathseeker_fell", [True, False])
def test_matsu_hanshiro_melees_again_only_after_his_deathseeker_falls_this_battle(
    deathseeker_fell,
):
    units = [
        personality("hanshiro", printed_id="matsu_hanshiro", force=4),
        personality("kin", keywords=("Deathseeker",)),
        personality("first", owner=P2),
        personality("second", owner=P2),
    ]
    session = combat_segment(units, {"hanshiro": 0, "kin": 0}, {"first": 0, "second": 0})
    session.act(P1, ActivateAbility("hanshiro"))
    session.submit(P1, DecisionResponse(("first",)))

    if deathseeker_fell:
        resolve_effects(session.game, [Destroy("kin", P2)])
    session.act(P2, Pass())

    assert (ActivateAbility("hanshiro") in session.legal_actions(P1)) is deathseeker_fell


# --- With Regards ---


def _with_regards_game(*, chi: int = 3, victim_cost: int = 5) -> EngineSession:
    """P1 holding With Regards with two unbowed Merchants in play, and an enemy Personality whose
    Gold Cost the Merchants' combined Chi is measured against."""
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1)))
    put_in_play(state, register(state, holding("mine", owner=P1, gold_production=4)))
    for card_id in ("first", "second"):
        # Priced out of the action's own reach, so only the enemy Personality is ever a victim.
        put_in_play(state, personality(card_id, chi=chi, gold_cost=9, keywords=("Merchant",)))
    put_in_play(state, personality("victim", owner=P2, gold_cost=victim_cost))
    regards = L5RCard.of(
        ActionPrint,
        id="regards",
        printed_id="with_regards",
        name="With Regards",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
    )
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, regards))
    return EngineSession.start(state, P1)


def test_with_regards_destroys_a_personality_under_the_targets_combined_chi():
    session = _with_regards_game(chi=3, victim_cost=5)

    session.act(P1, PlayStrategy("regards"))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("first", "second")))
    session.submit(P1, DecisionResponse(("victim",)))

    discard = session.game.table.zones[ZoneKey(P2, ZoneRole.DYNASTY_DISCARD)]
    assert "victim" in {card.id for card in discard.cards}
    assert session.game.favor_holder is P1


def test_with_regards_bows_its_merchants_when_taken_as_an_open():
    session = _with_regards_game()

    session.act(P1, PlayStrategy("regards"))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("first", "second")))
    session.submit(P1, DecisionResponse(("victim",)))

    cards = session.game.table.cards_by_id
    assert cards["first"].bowed and cards["second"].bowed


def test_with_regards_offers_only_what_the_merchants_combined_chi_outreaches():
    session = _with_regards_game(chi=2, victim_cost=5)

    session.act(P1, PlayStrategy("regards"))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("first", "second")))

    # A combined Chi of 4 reaches nothing at Gold Cost 5, so the second phrase targets nothing and
    # the action resolves having destroyed no one.
    assert session.game.pending is None
    assert "victim" in session.game.table.cards_by_id


def test_with_regards_takes_at_least_two_merchants():
    session = _with_regards_game()

    session.act(P1, PlayStrategy("regards"))
    pay(session, P1)

    pending = session.game.pending
    assert pending.minimum == 2
    assert pending.accepts(DecisionResponse(("first",))) is False


def test_with_regards_is_withheld_with_only_one_merchant():
    session = _with_regards_game()
    session.game.table.cards_by_id["second"].bow()

    assert PlayStrategy("regards") not in session.legal_actions(P1)


def test_with_regards_backs_out_of_its_second_phrase_to_its_first():
    session = _with_regards_game()
    session.act(P1, PlayStrategy("regards"))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("first", "second")))
    taped = len(session.log.entries)

    assert session.abort(P1) is True

    # Targeting changes nothing on the board, so only the answer that settled the first phrase
    # comes off the tape and that phrase is asked again.
    pending = session.game.pending
    assert pending.settled == ()
    assert set(pending.candidates) == {"first", "second"}
    assert len(session.log.entries) == taped - 1


def test_with_regards_leaves_its_merchants_unbowed_in_a_battle():
    regards = L5RCard.of(
        ActionPrint,
        id="regards",
        printed_id="with_regards",
        name="With Regards",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
    )
    session = combat_segment(
        [
            personality("first", chi=3, gold_cost=9, keywords=("Merchant",)),
            personality("second", chi=3, gold_cost=9, keywords=("Merchant",)),
            personality("victim", owner=P2, gold_cost=5),
            holding("mine", owner=P1, gold_production=4),
        ],
        {"first": 0, "second": 0},
        {"victim": 0},
        in_hand=[regards],
    )

    session.act(P1, PlayStrategy("regards"))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("first", "second")))
    session.submit(P1, DecisionResponse(("victim",)))

    # "bow them if this is Open": taken as a Battle action, the Merchants stay standing.
    cards = session.game.table.cards_by_id
    assert not cards["first"].bowed and not cards["second"].bowed
    discard = session.game.table.zones[ZoneKey(P2, ZoneRole.DYNASTY_DISCARD)]
    assert "victim" in {card.id for card in discard.cards}


# --- Yasuki Soden, Captain of the <i>Horokabe</i> (Experienced) ---


def _soden_battle():
    soden = personality(
        "soden", printed_id="yasuki_soden_captain_of_the_i_horokabe_i_experienced", force=4
    )
    units = [
        soden,
        personality("captain", keywords=("Commander",)),
        personality("enemy", owner=P2, force=4),
    ]
    session = combat_segment(units, {"soden": 0, "captain": 0}, {"enemy": 0})
    zealots = attachment(
        "zealots", printed_id="ijathilu_zealots", attachment_type=AttachmentType.FOLLOWER, force=3
    )
    attached(session.game, zealots, "soden")
    return session


def test_yasuki_soden_gives_your_dying_commander_a_yu_that_draws_a_card():
    game = _soden_battle().game
    game.table.decks[DeckKey(P1, Side.FATE)].cards = [fate_card("drawn", P1)]

    resolve_effects(game, [Destroy("captain", P2)])

    hand = game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert [card.id for card in hand] == ["drawn"]


@pytest.mark.parametrize(("follower_keywords", "drawn"), [(("Courage",), ["drawn"]), ((), [])])
def test_yasuki_soden_gives_a_yu_to_a_courage_follower_only(follower_keywords, drawn):
    game = _soden_battle().game
    game.table.decks[DeckKey(P1, Side.FATE)].cards = [fate_card("drawn", P1)]
    spear = attachment("spear", attachment_type=AttachmentType.FOLLOWER, keywords=follower_keywords)
    attached(game, spear, "captain")

    resolve_effects(game, [Destroy("spear", P2)])

    hand = game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert [card.id for card in hand] == drawn


def test_yasuki_soden_gives_an_enemy_minus_3_force_and_an_action_from_your_follower():
    session = _soden_battle()

    session.act(P1, ActivateAbility("soden"))
    session.submit(P1, DecisionResponse(("enemy",)))

    offered = {
        action for action in session.legal_actions(P1) if isinstance(action, ActivateAbility)
    }
    assert effective_force(session.game, session.game.table.cards_by_id["enemy"]) == 1
    assert offered == {ActivateAbility("zealots")}


# --- A Good Day to Die (2) ---


def _kurutta_battle():
    units = [
        personality("kurutta", printed_id="matsu_kurutta", keywords=("Deathseeker",)),
        personality("enemy", owner=P2),
    ]
    return combat_segment(units, {"kurutta": 0}, {"enemy": 0}).game


def test_a_good_day_to_die_resolves_a_yu_your_own_action_destroyed():
    without = _kurutta_battle()
    with_good_day = _kurutta_battle()
    terrain_at(with_good_day, "a_good_day_to_die_2", 0)

    resolve_effects(without, [Destroy("kurutta", P1)])
    resolve_effects(with_good_day, [Destroy("kurutta", P1)])

    assert without.pending is None
    assert with_good_day.pending.resolver == "matsu_kurutta"


GOOD_DAY_PROBE = "probe_battle_duel"


@choice_resolver("probe_destroy_duel_loser")
def _resolve_probe_destroy_duel_loser(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    duel = game.duel
    return [Destroy(duel.duelist_of(loser), seat) for loser in duel.outcome.losers]


def _battle_duel(*, loser_destroyed: bool) -> Ability:
    """A Battle challenge of the guard whose consequence destroys the loser, or does nothing."""

    def effects(game, source, target):
        challenge = [StartDuel(source.id, target.id, source.id)]
        if not loser_destroyed:
            return challenge
        destroy = Evaluate("probe_destroy_duel_loser", source.id, source.owner)
        return [*challenge, DelayedEffect(destroy, DUEL_CONSEQUENCES)]

    return Ability(
        timings=(ActionTiming.BATTLE,),
        label="Battle: challenge the guard to a duel",
        cost=no_cost,
        targets=lambda game, source: ["guard"],
        effects=effects,
    )


@pytest.mark.parametrize("loser_destroyed", [True, False])
def test_a_good_day_to_die_destroys_a_battle_duels_winner_only_with_its_loser(loser_destroyed):
    units = [
        personality("raider", printed_id=GOOD_DAY_PROBE, chi=5),
        personality("guard", owner=P2),
    ]
    hand = [
        focus_card("good_day", P1, 2, printed_id="a_good_day_to_die_2"),
        focus_card("P2-fv", P2, 1),
    ]
    with probe_ability(GOOD_DAY_PROBE, _battle_duel(loser_destroyed=loser_destroyed)):
        session = combat_segment(units, {"raider": 0}, {"guard": 0}, in_hand=hand)
        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("guard",)))
        while isinstance(session.game.pending, FocusOrStrike):
            pending = session.game.pending
            wanted = focus_token("good_day" if pending.seat is P1 else "P2-fv")
            answer = wanted if wanted in pending.candidates else STRIKE
            session.submit(pending.seat, DecisionResponse((answer,)))

    on_table = {card.id for card in session.game.table.battlefield.cards}
    assert session.game.duel.outcome.winners == (P1,)
    assert ("raider" in on_table) is not loser_destroyed


# --- The Taisen Sorrow ---


def _sorrow_game():
    """The Event face-up in P1's Province, over a board of Personalities at a range of Gold Costs
    and a Follower on each side of the line."""
    game = two_seat_game()
    province_card(game, "sorrow", printed_id="the_taisen_sorrow", name="The Taisen Sorrow")
    put_in_play(game, personality("cheap", gold_cost=4))
    put_in_play(game, personality("dear", gold_cost=5))
    put_in_play(game, personality("tainted", gold_cost=2, keywords=("Shadowlands",)))
    put_in_play(game, personality("their-cheap", owner=P2, gold_cost=1))
    put_in_play(game, personality("host", owner=P2, gold_cost=9))
    attached(game, attachment("levy", attachment_type=AttachmentType.FOLLOWER, gold_cost=3), "host")
    attached(
        game,
        attachment(
            "oni",
            owner=P2,
            attachment_type=AttachmentType.FOLLOWER,
            gold_cost=1,
            keywords=("Shadowlands",),
        ),
        "host",
    )
    return EngineSession.start(game.table, P1)


def _on_board(session):
    return {card.id for card in session.game.table.battlefield.cards}


def test_the_taisen_sorrow_destroys_cheap_personalities_on_every_side():
    session = _sorrow_game()

    session.act(P1, ActivateAbility("sorrow"))

    assert {"cheap", "their-cheap"}.isdisjoint(_on_board(session))
    assert {"dear", "tainted", "host"} <= _on_board(session)


def test_the_taisen_sorrow_spares_shadowlands_followers_and_takes_the_rest():
    session = _sorrow_game()

    session.act(P1, ActivateAbility("sorrow"))

    assert "levy" not in _on_board(session)
    assert "oni" in _on_board(session)


def test_the_taisen_sorrow_banishes_itself_rather_than_discarding():
    session = _sorrow_game()

    session.act(P1, ActivateAbility("sorrow"))

    banished = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_BANISH)]
    assert [card.id for card in banished.cards] == ["sorrow"]


# --- Tsudao's Grave ---


def _grave_game(*, in_deck=True, in_discard=False):
    """The Grave in play, an occupied Province beside it, and an Event to find in the Dynasty deck,
    the discard pile, or neither."""
    game = two_seat_game()
    put_in_play(game, holding("grave", printed_id="tsudaos_grave"))
    province_card(game, "standing", gold_cost=2, index=1)
    event = register(
        game.table,
        L5RCard.of(
            EventPrint, id="event", printed_id="event", name="E", side=Side.DYNASTY, owner=P1
        ),
    )
    if in_deck:
        game.table.decks[DeckKey(P1, Side.DYNASTY)].cards = [event]
    if in_discard:
        game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)].add(event)
    return EngineSession.start(game.table, P1)


def _grave_province(session, index):
    return [
        card.id for card in session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, index)].cards
    ]


def test_tsudaos_grave_refills_the_named_province_face_up_with_what_it_found():
    session = _grave_game()

    session.act(P1, ActivateAbility("grave"))
    session.submit(P1, DecisionResponse(("event",)))
    session.submit(P1, DecisionResponse((ZoneKey(P1, ZoneRole.PROVINCE, 1).token,)))

    assert _grave_province(session, 1) == ["event"]
    assert session.game.table.cards_by_id["event"].face_up


def test_tsudaos_grave_discards_the_card_already_standing_in_that_province():
    session = _grave_game()

    session.act(P1, ActivateAbility("grave"))
    session.submit(P1, DecisionResponse(("event",)))
    session.submit(P1, DecisionResponse((ZoneKey(P1, ZoneRole.PROVINCE, 1).token,)))

    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert "standing" in {card.id for card in discard.cards}


def test_tsudaos_grave_searches_the_discard_pile_as_well_as_the_deck():
    session = _grave_game(in_deck=False, in_discard=True)

    session.act(P1, ActivateAbility("grave"))

    assert session.game.pending.candidates == ("event",)


def test_tsudaos_grave_fills_nothing_when_the_named_province_is_gone():
    """The Province is named at one decision and filled at the next, so it can be destroyed in
    between."""
    session = _grave_game()
    session.act(P1, ActivateAbility("grave"))
    session.submit(P1, DecisionResponse(("event",)))
    named = ZoneKey(P1, ZoneRole.PROVINCE, 1)
    del session.game.table.zones[named]

    session.submit(P1, DecisionResponse((named.token,)))

    assert session.game.pending is None
    assert "event" not in _on_board(session)


def test_tsudaos_grave_leaves_the_province_alone_when_the_refill_is_declined():
    session = _grave_game()

    session.act(P1, ActivateAbility("grave"))
    session.submit(P1, DecisionResponse(("event",)))
    session.submit(P1, DecisionResponse(()))

    assert _grave_province(session, 1) == ["standing"]
    assert session.game.pending is None


def test_tsudaos_grave_is_spent_even_when_the_search_finds_nothing():
    session = _grave_game(in_deck=False)

    session.act(P1, ActivateAbility("grave"))

    assert session.game.pending is None
    assert "grave" not in _on_board(session)
