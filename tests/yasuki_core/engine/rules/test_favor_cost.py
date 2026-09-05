import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import abilities
from yasuki_core.engine.rules.abilities import (
    FAVOR_PAYERS,
    can_pay,
    favor_cost,
    favor_payers,
    is_favor_action,
)
from yasuki_core.engine.rules.actions import ActivateAbility, Recruit
from yasuki_core.engine.rules.flow import forget_action
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.effects import (
    AskOption,
    Bow,
    DiscardFavor,
    PayFavorCost,
    TakeFavor,
    Unpayable,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces import keywords
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

    assert favor_cost(game, _source(game)) == [PayFavorCost(), DiscardFavor(PlayerId.P1)]


def test_a_payer_pays_without_the_favor(game):
    """Good Faith 0.4: a Favor action's player may have "an alternate effect, substitute, or
    waiver" instead of controlling the Favor."""
    put_in_play(game, personality("helper", printed_id=FREE_PAYER))

    assert favor_cost(game, _source(game)) == [PayFavorCost()]


def test_the_seat_chooses_when_both_the_favor_and_a_payer_are_available(game):
    TakeFavor(PlayerId.P1).perform(game)
    put_in_play(game, personality("helper", name="Helper", printed_id=FREE_PAYER))

    cost = favor_cost(game, _source(game))

    assert isinstance(cost[1], AskOption)
    assert set(cost[1].options) == {"Discard the Imperial Favor", "Helper"}


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


def _resolve(game: GameState, action, effects) -> None:
    """Announce ``action`` and pay ``effects``, the way perform does before an ability resolves."""
    game.action = action
    game.action_is_favor = False
    resolve_effects(game, effects)


def test_an_action_that_pays_a_favor_cost_is_a_favor_action(game):
    """ShE datasheet: paying the Favor is what makes it one, and it stays one however the cost was
    settled — here by a payer rather than by discarding the Favor."""
    put_in_play(game, personality("helper", printed_id=FREE_PAYER))
    source = _source(game)

    _resolve(game, ActivateAbility("actor"), favor_cost(game, source))

    assert is_favor_action(game)


def test_an_alternate_cost_paid_the_other_way_is_not_a_favor_action(game):
    """ "Bow your Yojimbo or discard the Favor" is a Favor action only on the branch that discards
    it, which is why the marker rides on the cost instead of the announcement."""
    TakeFavor(PlayerId.P1).perform(game)
    yojimbo = put_in_play(game, personality("yojimbo"))

    _resolve(game, ActivateAbility("actor"), [Bow(yojimbo.id)])

    assert not is_favor_action(game)


def test_a_favor_designated_ability_is_a_favor_action_whatever_it_paid(game):
    """The designator settles it, so a card printed Favor is not reclassified by which half of an
    alternate cost its controller reached for."""
    source = put_in_play(game, personality("actor", keywords=(keywords.FAVOR,)))

    _resolve(game, ActivateAbility(source.id), [])

    assert is_favor_action(game)


def test_the_next_action_is_not_a_favor_action_by_inheritance(game):
    """The flag is about the action now resolving. Left standing, every later action in the turn
    would read as a Favor action and every card that watches for one would misfire."""
    TakeFavor(PlayerId.P1).perform(game)
    _resolve(game, ActivateAbility("actor"), favor_cost(game, _source(game)))
    assert is_favor_action(game)

    forget_action(game)

    assert not is_favor_action(game)


def test_recruiting_a_favor_designated_card_is_not_a_favor_action(game):
    """The designator is on the ability, not on the card carrying it. Read off any action naming a
    card, buying that card would announce a Favor action and fire every trigger watching for one."""
    source = put_in_play(game, personality("actor", keywords=(keywords.FAVOR,)))

    _resolve(game, Recruit(source.id), [])

    assert not is_favor_action(game)
