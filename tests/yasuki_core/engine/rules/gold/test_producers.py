import dataclasses

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.gold.production import GOLD_HANDLERS, gold_handler
from yasuki_core.engine.rules.gold.producers import gold_producers, gold_reach, reachable_gold
from yasuki_core.engine.rules.legality import recruit_cost

from tests.yasuki_core.engine.builders import (
    holding,
    put_in_play,
    sensei,
    stronghold,
    two_seat_game,
)


def test_a_bowed_producer_and_a_sensei_are_not_sources():
    # A Sensei's printed Gold Production is a delta the Stronghold already receives, so counting it
    # would pay the seat twice for one characteristic.
    game = two_seat_game()
    farm = put_in_play(game, holding("P1-farm", owner=PlayerId.P1, gold_production=2))
    bowed = put_in_play(game, holding("P1-bowed", owner=PlayerId.P1, gold_production=2))
    bowed.bow()
    put_in_play(game, holding("P1-barren", owner=PlayerId.P1, gold_production=0))
    put_in_play(game, sensei(PlayerId.P1))

    assert gold_producers(game, PlayerId.P1) == [farm]


def test_gold_reach_splits_the_producers_that_still_need_a_target():
    """A producer whose yield can vary with what it pays for cannot be totalled before the purchase
    is known, so it comes back separately instead of being folded into the fixed sum."""
    game = two_seat_game()
    game.gold[PlayerId.P1] = 1
    put_in_play(game, holding("P1-plain", owner=PlayerId.P1, gold_production=2))
    varies = put_in_play(
        game, holding("P1-varies", owner=PlayerId.P1, printed_id="reach_probe", gold_production=3)
    )

    @gold_handler("reach_probe")
    def _varies(card, game_, seat, targets):
        return 5 if targets else card.gold_production

    try:
        fixed, variable = gold_reach(game, PlayerId.P1)

        assert fixed == 1 + 2, "the pool and the target-independent producer only"
        assert variable == (varies,)
        assert reachable_gold(game, PlayerId.P1) == 3 + 3
        assert reachable_gold(game, PlayerId.P1, varies) == 3 + 5
    finally:
        GOLD_HANDLERS.pop("reach_probe", None)


def test_the_off_clan_surcharge_follows_the_active_ruleset(monkeypatch):
    # Read at call time rather than frozen at import, so swapping the arc swaps the price with it.
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, clan="lion"))
    off_clan = put_in_play(game, holding("P1-crane", owner=PlayerId.P1, gold_cost=4, clan="crane"))

    base = recruit_cost(game, off_clan)
    monkeypatch.setattr(
        ruleset, "ACTIVE", dataclasses.replace(ruleset.ACTIVE, off_clan_surcharge=7)
    )

    assert recruit_cost(game, off_clan) == base - ruleset.SHATTERED_EMPIRE.off_clan_surcharge + 7
