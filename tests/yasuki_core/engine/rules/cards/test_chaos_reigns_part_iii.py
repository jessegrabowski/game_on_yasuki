import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility, Recruit
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.cards.chaos_reigns_part_iii import (
    FUSHICHO,
    IKARICHIS_UNDEAD,
    KANPEKI_DYNASTY,
    ZOMBIE_FOLLOWER,
)
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.economy import effective_force
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.triggers import fire
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import WindPrint

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    end_turn,
    fate_card,
    holding,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
    stronghold,
    token_template,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2


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
    """ "If it is your turn" — read before the ability is offered rather than resolving to nothing."""
    session = _kengun_game()
    end_turn(session)  # hand the turn to P2; the Grounds is still P1's to bow

    assert session.game.active is P2
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


def test_ikarichi_invests_two_gold_for_an_undead_outrider():
    session = _ikarichi_game()

    session.act(P1, Recruit("ikarichi", invest=True))
    payment = session.game.pending
    pay(session, P1)

    game = session.game
    assert payment.amount == 7  # his five Gold Cost, plus the two the Invest charges
    outrider = attachments_of(game, game.table.cards_by_id["ikarichi"])[0]
    assert outrider.name == "Ikarichi's Undead"


def test_the_kanpeki_dynasty_rides_him_in_for_nothing():
    """ "Invest :g2:, or :g0: if your Wind is The Kanpeki Dynasty" — the Wind is a card in play, so
    the Invest reads the board rather than a printed number alone."""
    session = _ikarichi_game(wind=KANPEKI_DYNASTY)

    session.act(P1, Recruit("ikarichi", invest=True))
    payment = session.game.pending
    pay(session, P1)

    game = session.game
    assert payment.amount == 5  # his Gold Cost alone
    outrider = attachments_of(game, game.table.cards_by_id["ikarichi"])[0]
    assert outrider.name == "Ikarichi's Undead"  # paid nothing, and still got the Follower


def test_another_wind_leaves_the_invest_at_its_printed_price():
    session = _ikarichi_game(wind="some_other_wind")

    session.act(P1, Recruit("ikarichi", invest=True))

    assert session.game.pending.amount == 7


@pytest.mark.parametrize("invest", [False, True], ids=["plain", "invested"])
def test_ikarichi_costs_two_honor_however_he_arrives(invest):
    """The Honor is his entry's price, not the Invest's, so it is charged once either way."""
    session = _ikarichi_game()

    session.act(P1, Recruit("ikarichi", invest=invest))
    pay(session, P1)

    assert session.game.table.seats[P1].honor == -2


def test_ikarichi_replays_to_the_same_board():
    """His Invest mints a card mid-recruit, and a replayed game has to mint the same one."""
    session = _ikarichi_game()
    session.act(P1, Recruit("ikarichi", invest=True))
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

    session.act(P1, Recruit("maya", invest=True))
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

    session.act(P1, Recruit("maya", invest=True))
    pay(session, P1)

    assert session.game.pending is None
    assert [card.id for card in _province(session, 0)] == ["plain-refill0"]


def test_mayas_invest_shuffles_the_dynasty_deck_it_read():
    """The search shows the seat their whole Dynasty deck, so its order is no longer secret."""
    session = _maya_game(filler=8)
    before = [card.id for card in session.game.table.decks[DeckKey(P1, Side.DYNASTY)].cards]

    session.act(P1, Recruit("maya", invest=True))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("kakita",)))

    after = [card.id for card in session.game.table.decks[DeckKey(P1, Side.DYNASTY)].cards]
    assert set(after) == set(before) - {"kakita"}  # same cards, minus the one she took
    assert after != [card for card in before if card != "kakita"]  # and not in the read order
