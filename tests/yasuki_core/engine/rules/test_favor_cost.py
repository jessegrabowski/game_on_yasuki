import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import abilities
from yasuki_core.engine.rules.abilities import FAVOR_PAYERS, can_pay, favor_cost, favor_payers
from yasuki_core.engine.rules.effects import AskOption, Bow, DiscardFavor, TakeFavor, Unpayable
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, Side
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import personality, put_in_play

FREE_PAYER = "free_payer"
BOWING_PAYER = "bowing_payer"


@pytest.fixture
def game() -> GameState:
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=0)
    game.table.creatable_tokens[IMPERIAL_FAVOR_ID] = FatePrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    return game


@pytest.fixture(autouse=True)
def payers():
    """Stand-ins for the cards step 7 brings: one that pays for nothing, one that bows to pay."""
    FAVOR_PAYERS[FREE_PAYER] = lambda game, card: []
    FAVOR_PAYERS[BOWING_PAYER] = lambda game, card: None if card.bowed else [Bow(card.id)]
    try:
        yield
    finally:
        del FAVOR_PAYERS[FREE_PAYER], FAVOR_PAYERS[BOWING_PAYER]


def _source(game: GameState, owner: PlayerId = PlayerId.P1):
    return put_in_play(game, personality("actor", owner=owner))


def test_holding_the_favor_pays_by_discarding_it(game):
    """With nothing else on offer there is nothing to ask, so the cost is simply the discard."""
    TakeFavor(PlayerId.P1).perform(game)

    assert favor_cost(game, _source(game)) == [DiscardFavor(PlayerId.P1)]


def test_a_payer_pays_without_the_favor(game):
    """Good Faith 0.4: a Favor action's player may have "an alternate effect, substitute, or
    waiver" instead of controlling the Favor."""
    put_in_play(game, personality("helper", printed_id=FREE_PAYER))

    assert favor_cost(game, _source(game)) == []


def test_the_seat_chooses_when_both_the_favor_and_a_payer_are_available(game):
    TakeFavor(PlayerId.P1).perform(game)
    put_in_play(game, personality("helper", name="Helper", printed_id=FREE_PAYER))

    cost = favor_cost(game, _source(game))

    assert isinstance(cost[0], AskOption)
    assert set(cost[0].options) == {"Discard the Imperial Favor", "Helper"}


def test_choosing_a_payer_leaves_the_favor_where_it_is(game):
    """The assertion that separates a real alternate payment from a discount: the Favor is not
    spent, so its holder still holds it."""
    TakeFavor(PlayerId.P1).perform(game)
    put_in_play(game, personality("helper", name="Helper", printed_id=FREE_PAYER))

    charged = abilities._resolve_favor_payment(game, "actor", ("Helper",), PlayerId.P1)

    assert charged == []
    assert game.favor_holder is PlayerId.P1


def test_choosing_the_favor_discards_it(game):
    TakeFavor(PlayerId.P1).perform(game)
    put_in_play(game, personality("helper", name="Helper", printed_id=FREE_PAYER))

    charged = abilities._resolve_favor_payment(
        game, "actor", ("Discard the Imperial Favor",), PlayerId.P1
    )

    assert charged == [DiscardFavor(PlayerId.P1)]


def test_a_payer_that_cannot_pay_right_now_is_not_offered(game):
    """A payer prices itself, and one that cannot meet its own price is no payer at all."""
    bowed = put_in_play(game, personality("manjodh", name="Manjodh", printed_id=BOWING_PAYER))
    bowed.bow()

    assert favor_payers(game, PlayerId.P1) == {}


def test_another_seats_payer_does_not_pay_for_you(game):
    put_in_play(game, personality("helper", owner=PlayerId.P2, printed_id=FREE_PAYER))

    assert favor_payers(game, PlayerId.P1) == {}


def test_a_favor_cost_nobody_can_pay_is_unpayable(game):
    """Good Faith: an action whose Favor cost nobody can meet is never offered."""
    cost = favor_cost(game, _source(game))

    assert isinstance(cost[0], Unpayable)
    assert not can_pay(game, _source(game), favor_cost)
