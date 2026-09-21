from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import (
    combat_segment,
    flip_stronghold,
    personality,
    put_in_play,
)

P1, P2 = PlayerId.P1, PlayerId.P2
HONORABLE_GARRISON = "the_honorable_garrison_of_the_lion"
IMPREGNABLE_FORTRESS = "the_impregnable_fortress_of_the_crab"


def _garrison_battle(*, flipped: bool = False) -> EngineSession:
    """P1's Lion Samurai (1F, 2 PH), a Crane Samurai and a Lion with no keyword opposed by P2's
    guard, the Honorable Garrison as P1's Stronghold."""
    cards = [
        flip_stronghold(HONORABLE_GARRISON, flipped=flipped),
        personality("lion", force=1, personal_honor=2, keywords=("Samurai",), clans=("Lion",)),
        personality("crane", personal_honor=2, keywords=("Samurai",), clans=("Crane",)),
        personality("ashigaru", personal_honor=2, clans=("Lion",)),
        personality("guard", owner=P2),
    ]
    return combat_segment(cards, {"lion": 0, "crane": 0, "ashigaru": 0}, {"guard": 0})


def test_the_garrison_gives_an_opposed_lion_samurai_force_equal_to_his_personal_honor():
    session = _garrison_battle()

    session.act(P1, ActivateAbility("sh"))
    assert session.game.pending.candidates == ("lion",)
    session.submit(P1, DecisionResponse(("lion",)))

    assert effective_force(session.game, session.game.table.cards_by_id["lion"]) == 3


def test_the_garrison_back_prints_the_same_ability():
    session = _garrison_battle(flipped=True)

    session.act(P1, ActivateAbility("sh"))
    session.submit(P1, DecisionResponse(("lion",)))

    assert effective_force(session.game, session.game.table.cards_by_id["lion"]) == 3


def _fortress_battle() -> EngineSession:
    """P1's Crab and Crane (2F each) opposed by P2's guard, a second Crab left at home, the
    Impregnable Fortress as P1's Stronghold."""
    cards = [
        flip_stronghold(IMPREGNABLE_FORTRESS),
        personality("crab", force=2, clans=("Crab",)),
        personality("crane", force=2, clans=("Crane",)),
        personality("guard", owner=P2),
    ]
    session = combat_segment(cards, {"crab": 0, "crane": 0}, {"guard": 0})
    put_in_play(session.game, personality("crab_at_home", force=2, clans=("Crab",)))
    return session


def test_the_fortress_gives_crab_personalities_a_force_while_opposed():
    game = _fortress_battle().game

    assert effective_force(game, game.table.cards_by_id["crab"]) == 3
    assert effective_force(game, game.table.cards_by_id["crane"]) == 2
    assert effective_force(game, game.table.cards_by_id["crab_at_home"]) == 2
