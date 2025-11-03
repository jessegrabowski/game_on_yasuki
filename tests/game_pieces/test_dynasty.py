from app.game_pieces.dynasty import DynastyCard, DynastyPersonality, DynastyHolding, DynastyEvent
from app.game_pieces.constants import Side


def test_dynastycard_basic_construction():
    ok = DynastyCard(id="d1", name="OK", side=Side.DYNASTY, gold_cost=0)
    assert ok.gold_cost == 0


def test_dynasty_personality_stats():
    p = DynastyPersonality(id="p1", name="OK", side=Side.DYNASTY, force=3, chi=2, personal_honor=1)
    assert (p.force, p.chi, p.personal_honor) == (3, 2, 1)


def test_holding_gold_production_field():
    h = DynastyHolding(id="h1", name="Farm", side=Side.DYNASTY, gold_production=2)
    assert h.gold_production == 2


def test_dynasty_event_constructs():
    e = DynastyEvent(id="e1", name="Epic Event", side=Side.DYNASTY)
    assert e.side is Side.DYNASTY
