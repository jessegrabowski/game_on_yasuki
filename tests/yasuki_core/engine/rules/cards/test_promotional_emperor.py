from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.cards.promotional_emperor import ASHIGARU
from yasuki_core.engine.rules.decisions import ChoosePayment, DecisionResponse
from yasuki_core.engine.rules.economy import effective_recruit_discount
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.units import unit_force
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import (
    holding,
    personality,
    put_in_play,
    stronghold,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


def _farm_game(*, stronghold_production: int = 5, clan: str | None = None):
    """P1's Colonial Farm in play beside a Personality, with a Stronghold that can raise the three
    gold its ability charges."""
    game = two_seat_game()
    token_template(
        game, ASHIGARU, name="Ashigaru", card_type="Follower", keywords=("Ashigaru",), force=1
    )
    put_in_play(game, stronghold(P1, gold_production=stronghold_production, clan=clan))
    put_in_play(
        game,
        holding("farm", printed_id="colonial_farm", name="Colonial Farm", gold_production=5),
    )
    put_in_play(game, personality("hero", force=2, chi=3))
    return game


def test_colonial_farm_creates_an_ashigaru_on_the_chosen_personality():
    session = EngineSession.start(_farm_game().table, P1)

    session.act(P1, ActivateAbility("farm"))
    session.submit(P1, DecisionResponse(("P1-SH",)))  # bow the Stronghold for the three gold
    session.submit(P1, DecisionResponse(("hero",)))

    game = session.game
    hero = game.table.cards_by_id["hero"]
    ashigaru = attachments_of(game, hero)[0]
    assert ashigaru.name == "Ashigaru"
    assert ashigaru.is_token is True
    assert unit_force(game, hero) == 3  # the Personality's 2, plus the Follower's own 1


def test_colonial_farm_charges_three_gold_before_it_creates_anything():
    session = EngineSession.start(_farm_game().table, P1)

    session.act(P1, ActivateAbility("farm"))

    payment = session.game.pending
    assert isinstance(payment, ChoosePayment)
    assert payment.amount == 3
    assert payment.label == "Colonial Farm"  # the prompt names the card, not its id
    assert not attachments_of(session.game, session.game.table.cards_by_id["hero"])


def test_colonial_farm_leaves_the_change_from_its_payment_in_the_pool():
    """The Stronghold makes five for a cost of three: gold produced over a cost stays in the pool for
    the rest of the phase rather than evaporating."""
    session = EngineSession.start(_farm_game().table, P1)

    session.act(P1, ActivateAbility("farm"))
    session.submit(P1, DecisionResponse(("P1-SH",)))

    assert session.game.gold[P1] == 2


def test_colonial_farm_is_withheld_when_the_seat_cannot_raise_three_gold():
    """The farm has already bowed for its own gold and the Stronghold makes two, so nothing on the
    board reaches three."""
    session = EngineSession.start(_farm_game(stronghold_production=2).table, P1)
    session.game.table.cards_by_id["farm"].bow()

    assert ActivateAbility("farm") not in session.legal_actions(P1)


def test_colonial_farm_is_offered_when_the_pool_alone_covers_the_cost():
    """Gold already in the pool pays, so a seat with nothing left to bow can still use the farm."""
    session = EngineSession.start(_farm_game(stronghold_production=2).table, P1)
    session.game.table.cards_by_id["farm"].bow()
    session.game.add_gold(P1, 3)

    assert ActivateAbility("farm") in session.legal_actions(P1)


def test_colonial_farm_enters_play_for_one_less_for_a_lion():
    game = _farm_game(clan="Lion")

    assert effective_recruit_discount(game, game.table.cards_by_id["farm"]) == 1


def test_colonial_farm_charges_everyone_else_full_price():
    game = _farm_game(clan="Crab")

    assert effective_recruit_discount(game, game.table.cards_by_id["farm"]) == 0


def test_colonial_farm_replays_to_the_same_board():
    session = EngineSession.start(_farm_game().table, P1)
    session.act(P1, ActivateAbility("farm"))
    session.submit(P1, DecisionResponse(("P1-SH",)))
    session.submit(P1, DecisionResponse(("hero",)))

    assert replay(session.log).table == session.game.table
