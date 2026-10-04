from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import Location, ZoneKey, ZoneRole, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    combat_segment,
    personality,
    register,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Palm Strike ---


def _palm_strike_battle(*, armed_monk: bool = False) -> EngineSession:
    """P1's Monk against P2's guard and armed guard at the battlefield, P2's sentry at home, and
    Palm Strike in P1's hand."""
    session = combat_segment(
        [
            personality("monk", keywords=(keywords.MONK,)),
            personality("guard", owner=P2),
            personality("armed", owner=P2),
            personality("sentry", owner=P2),
        ],
        {"monk": 0},
        {"guard": 0, "armed": 0},
    )
    table = session.game.table
    attached(table, attachment("blade", owner=P2, keywords=(keywords.WEAPON,)), "armed")
    if armed_monk:
        attached(table, attachment("sword", keywords=(keywords.WEAPON,)), "monk")
    strike = L5RCard.of(
        FatePrint,
        id="strike",
        printed_id="palm_strike",
        name="Palm Strike",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
        keywords=(keywords.KIHO,),
    )
    table.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(table, strike))
    return session


def test_palm_strike_bows_an_unarmed_enemy_at_the_battlefield():
    session = _palm_strike_battle()

    session.act(P1, PlayStrategy("strike"))
    session.submit(P1, DecisionResponse(("monk",)))
    assert session.game.pending.candidates == ("guard",)
    session.submit(P1, DecisionResponse(("guard",)))

    assert session.game.table.cards_by_id["guard"].bowed
    assert not session.game.table.cards_by_id["monk"].bowed


def test_palm_strike_needs_an_unarmed_monk():
    session = _palm_strike_battle(armed_monk=True)

    assert PlayStrategy("strike") not in session.legal_actions(P1)


# --- Overwhelmed ---


def _overwhelmed_battle(champion="champion", enemy="second", *, aide_force=2, first_force=3):
    session = combat_segment(
        [
            personality("champion", printed_id=champion, force=5),
            personality("aide", force=aide_force),
            personality("first", owner=P2, force=first_force),
            personality("second", owner=P2, printed_id=enemy, force=4),
        ],
        {"champion": 0, "aide": 0},
        {"first": 0, "second": 0},
    )
    table = session.game.table
    overwhelmed = L5RCard.of(
        FatePrint,
        id="overwhelmed",
        printed_id="overwhelmed",
        name="Overwhelmed",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
    )
    table.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(table, overwhelmed))
    return session


def _on_table(session):
    return {card.id for card in session.game.table.battlefield.cards}


def test_overwhelmed_destroys_the_enemys_highest_force_personality_when_he_moves_none_home():
    session = _overwhelmed_battle()

    session.act(P1, PlayStrategy("overwhelmed"))
    pending = session.game.pending
    assert pending.seat is P2 and pending.decline_label == "Decline"
    session.submit(P2, DecisionResponse(()))

    assert _on_table(session) == {"aide", "first"}


def test_overwhelmed_destroys_nobody_when_the_enemy_moves_two_units_home():
    session = _overwhelmed_battle()

    session.act(P1, PlayStrategy("overwhelmed"))
    assert not session.game.pending.accepts(DecisionResponse(("first",)))
    session.submit(P2, DecisionResponse(("first", "second")))

    game = session.game
    assert _on_table(session) == {"aide", "first", "second"}
    assert all(
        location_of(game.table, game.table.cards_by_id[card_id]) == Location.home(P2)
        for card_id in ("first", "second")
    )


def test_overwhelmeds_destruction_raises_the_enemys_yu():
    session = _overwhelmed_battle(enemy="bayushi_purimu")

    session.act(P1, PlayStrategy("overwhelmed"))
    session.submit(P2, DecisionResponse(()))

    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.resolver == "bayushi_purimu"


def test_overwhelmeds_cost_raises_no_yu_for_your_own_personality():
    session = _overwhelmed_battle(champion="bayushi_purimu")

    session.act(P1, PlayStrategy("overwhelmed"))

    assert "champion" not in _on_table(session)
    assert session.game.pending.resolver == "overwhelmed_units"


def test_ashura_paid_for_overwhelmed_can_leave_the_enemy_too_few_units_to_move_home():
    session = _overwhelmed_battle(champion="ashura")

    session.act(P1, PlayStrategy("overwhelmed"))
    assert session.game.pending.resolver == "ashura"
    session.submit(P1, DecisionResponse(("first",)))

    assert session.game.pending is None
    assert _on_table(session) == {"aide"}


def test_overwhelmed_asks_each_side_to_choose_among_tied_highest_force():
    session = _overwhelmed_battle(aide_force=5, first_force=4)

    session.act(P1, PlayStrategy("overwhelmed"))
    assert set(session.game.pending.candidates) == {"champion", "aide"}
    session.submit(P1, DecisionResponse(("aide",)))
    session.submit(P2, DecisionResponse(()))
    assert set(session.game.pending.candidates) == {"first", "second"}
    session.submit(P2, DecisionResponse(("first",)))

    assert _on_table(session) == {"champion", "second"}
