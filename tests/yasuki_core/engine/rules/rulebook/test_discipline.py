import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.effects import Destroy, GainHonor, GrantNegation, PutIntoPlay
from yasuki_core.engine.rules.gold.discounts import ACTION_DISCOUNTS, Purchase, action_discount
from yasuki_core.engine.rules.rulebook.discipline import (
    DISCIPLINE_GRANTS,
    DISCIPLINES,
    Reach,
    discipline_cost,
    discipline_grant,
    disciplined,
    reach,
    register_discipline,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.turn.structure import END_OF_TURN
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.rules.vocabulary.modifiers import Negation
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import (
    fate_card,
    holding,
    pay,
    personality,
    put_in_play,
    register,
    two_seat_game,
)
from tests.yasuki_core.engine.rules.conftest import probe_ability

P1, P2 = PlayerId.P1, PlayerId.P2
PRINTED = "discipline_probe"
GRANTER = "discipline_grant_probe"
WITHHELD = "withheld_discipline_probe"
DISCOUNTER = "discipline_discount_probe"
ENTERING = "entering_discipline_probe"

HONOR_ABILITY = Ability(
    timings=(ActionTiming.OPEN,),
    cost=no_cost,
    targets=lambda game, source: ["hero"],
    effects=lambda game, source, target: [GainHonor(source.owner, 1)],
    located_at=(CardLocation.HAND,),
)
ENTERING_ABILITY = Ability(
    timings=(ActionTiming.OPEN,),
    cost=no_cost,
    targets=lambda game, source: [source.id],
    effects=lambda game, source, target: [PutIntoPlay(source.id)],
    located_at=(CardLocation.HAND,),
    hits_every_target=True,
)


def _grants_discipline_1(game: GameState, granter: L5RCard, card: L5RCard) -> int:
    return 1


def _withheld(game: GameState, card: L5RCard) -> None:
    return None


def _one_less(game: GameState, granter: L5RCard, purchase: Purchase) -> int:
    return 1


@pytest.fixture
def probes():
    register_discipline(PRINTED, disciplined(3))
    register_discipline(WITHHELD, _withheld)
    register_discipline(ENTERING, disciplined(0))
    discipline_grant(GRANTER)(_grants_discipline_1)
    action_discount(DISCOUNTER)(_one_less)
    with (
        probe_ability(PRINTED, HONOR_ABILITY),
        probe_ability(WITHHELD, HONOR_ABILITY),
        probe_ability(ENTERING, ENTERING_ABILITY),
    ):
        yield
    for printed_id in (PRINTED, WITHHELD, ENTERING):
        DISCIPLINES.pop(printed_id)
    DISCIPLINE_GRANTS.pop(GRANTER)
    ACTION_DISCOUNTS.pop(DISCOUNTER)


def _pile_game(printed_id: str = PRINTED, *, beside: tuple[str, ...] = ()) -> EngineSession:
    """P1's Action Phase, with a Strategy printing ``printed_id`` in P1's Fate discard pile, a hero
    for it to target, a Holding producing 5 Gold, and a Holding for each of ``beside``."""
    state = TableState.empty_two_seat()
    put_in_play(state, personality("hero"))
    put_in_play(state, holding("mine", gold_production=5))
    for index, printed in enumerate(beside):
        put_in_play(state, holding(f"granter-{index}", printed_id=printed))
    strategy = L5RCard.of(
        ActionPrint, id="strategy", name="strategy", printed_id=printed_id, side=Side.FATE, owner=P1
    )
    state.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].add(register(state, strategy))
    return EngineSession.start(state, P1)


def _fate_pile(session: EngineSession, role: ZoneRole) -> list[str]:
    return [card.id for card in session.game.table.zones[ZoneKey(P1, role)].cards]


@pytest.mark.usefixtures("probes")
@pytest.mark.parametrize(
    ("printed_id", "granter_owner", "cost"),
    [
        (PRINTED, None, 3),
        (PRINTED, P1, 1),
        ("plain", P1, 1),
        ("plain", P2, None),
        ("plain", None, None),
        (WITHHELD, None, None),
    ],
    ids=["printed", "least_of_both", "granted", "opponents_grant", "none", "withheld"],
)
def test_a_card_has_the_least_discipline_its_text_and_its_owners_cards_give(
    printed_id, granter_owner, cost
):
    game = two_seat_game()
    card = register(game.table, fate_card(printed_id, P1))
    if granter_owner is not None:
        put_in_play(game, holding("granter", printed_id=GRANTER, owner=granter_owner))

    assert discipline_cost(game, card) == cost


@pytest.mark.usefixtures("probes")
@pytest.mark.parametrize(
    ("pile", "reached"),
    [(ZoneRole.FATE_DISCARD, Reach.PLAYED_UNDER_DISCIPLINE), (ZoneRole.DYNASTY_DISCARD, None)],
    ids=["fate_pile", "dynasty_pile"],
)
def test_discipline_plays_a_card_from_the_fate_discard_pile_only(pile, reached):
    game = two_seat_game()
    card = register(game.table, fate_card(PRINTED, P1))
    game.table.zones[ZoneKey(P1, pile)].add(card)

    hand = (CardLocation.HAND,)
    assert reach(game, CardLocation.DISCARD, card, hand, from_rulebook=False) is reached


@pytest.mark.usefixtures("probes")
@pytest.mark.parametrize(
    ("beside", "charged"),
    [((), 3), ((GRANTER,), 1), ((DISCOUNTER,), 2)],
    ids=["printed", "least_discipline", "discounted"],
)
def test_a_card_played_under_discipline_pays_its_discipline_and_is_removed_from_the_game(
    beside, charged
):
    session = _pile_game(beside=beside)
    game = session.game
    honor = game.table.seats[P1].honor

    session.act(P1, PlayStrategy("strategy", disciplined=True))
    assert game.pending.amount == charged
    pay(session, P1)
    session.submit(P1, DecisionResponse(("hero",)))

    assert game.table.seats[P1].honor == honor + 1
    assert _fate_pile(session, ZoneRole.FATE_BANISH) == ["strategy"]
    assert _fate_pile(session, ZoneRole.FATE_DISCARD) == []


@pytest.mark.usefixtures("probes")
def test_a_withheld_discipline_offers_nothing_from_the_pile():
    session = _pile_game(WITHHELD)

    assert PlayStrategy("strategy", disciplined=True) not in session.legal_actions(P1)


@pytest.mark.usefixtures("probes")
def test_backing_out_of_a_discipline_play_leaves_the_card_in_the_pile():
    session = _pile_game()

    session.act(P1, PlayStrategy("strategy", disciplined=True))
    session.cancel(P1)

    assert _fate_pile(session, ZoneRole.FATE_DISCARD) == ["strategy"]
    assert session.game.announced_cards == frozenset()
    assert PlayStrategy("strategy", disciplined=True) in session.legal_actions(P1)


@pytest.mark.usefixtures("probes")
def test_a_negated_discipline_play_is_still_removed_from_the_game():
    session = _pile_game()
    game = session.game
    honor = game.table.seats[P1].honor
    negation = Negation("mine", END_OF_TURN, source_kind=ActionPrint)
    resolve_effects(game, [GrantNegation(negation)])

    session.act(P1, PlayStrategy("strategy", disciplined=True))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("hero",)))

    assert game.table.seats[P1].honor == honor
    assert _fate_pile(session, ZoneRole.FATE_BANISH) == ["strategy"]


@pytest.mark.usefixtures("probes")
def test_a_card_that_put_itself_into_play_under_discipline_is_removed_when_it_leaves_play():
    session = _pile_game(ENTERING)
    game = session.game

    session.act(P1, PlayStrategy("strategy", disciplined=True))
    assert "strategy" in {card.id for card in game.table.battlefield.cards}
    resolve_effects(game, [Destroy("strategy", P2)])

    assert _fate_pile(session, ZoneRole.FATE_BANISH) == ["strategy"]
    assert _fate_pile(session, ZoneRole.FATE_DISCARD) == []
    assert game.banished_on_leaving_play == frozenset()
