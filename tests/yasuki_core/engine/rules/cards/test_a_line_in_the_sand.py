from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Equip
from yasuki_core.engine.rules.decisions import ChooseCards, ChoosePayment, DecisionResponse
from yasuki_core.engine.rules.economy import effective_gold_cost
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import AttachmentPrint, PersonalityPrint, StrongholdPrint

from tests.yasuki_core.engine.builders import register

P1 = PlayerId.P1


def _weapon(state, card_id: str) -> L5RCard:
    return register(
        state,
        L5RCard.of(
            AttachmentPrint,
            id=card_id,
            name="Stockpiled Weapon",
            side=Side.FATE,
            owner=P1,
            printed_id="stockpiled_weapon",
            gold_cost=3,
            keywords=("Weapon", "One-Handed", "Sword"),
        ),
    )


def _sand_game(*, production=8, in_deck=("spare",)) -> EngineSession:
    """P1 holding a Stockpiled Weapon, a bearer for it, and ``in_deck`` copies to fetch."""
    state = TableState.empty_two_seat()
    state.battlefield.add(
        register(
            state,
            L5RCard.of(
                StrongholdPrint,
                id="P1-SH",
                name="SH",
                side=Side.STRONGHOLD,
                owner=P1,
                gold_production=production,
            ),
        )
    )
    state.battlefield.add(
        register(
            state,
            L5RCard.of(
                PersonalityPrint,
                id="bearer",
                name="Bearer",
                side=Side.DYNASTY,
                owner=P1,
                force=2,
                chi=3,
            ),
        )
    )
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(_weapon(state, "weapon"))
    for card_id in in_deck:
        state.decks[DeckKey(P1, Side.FATE)].cards.append(_weapon(state, card_id))
    return EngineSession.start(state, P1)


def test_stockpiled_weapon_offers_equip_with_and_without_the_invest():
    session = _sand_game()

    offered = [a for a in session.legal_actions(P1) if isinstance(a, Equip)]

    assert offered == [Equip("weapon"), Equip("weapon", invest=True)]


def test_investing_raises_the_price_by_the_invest_cost():
    session = _sand_game()

    session.act(P1, Equip("weapon", invest=True))
    session.submit(P1, DecisionResponse(("bearer",)))

    pending = session.project(P1).pending
    assert isinstance(pending, ChoosePayment)
    assert pending.amount == 4  # 3 Gold Cost plus the 1 it Invests


def test_investing_fetches_another_copy_out_of_the_fate_deck():
    session = _sand_game()
    session.act(P1, Equip("weapon", invest=True))
    session.submit(P1, DecisionResponse(("bearer",)))
    session.submit(P1, DecisionResponse(("P1-SH",)))

    pending = session.project(P1).pending
    assert isinstance(pending, ChooseCards)
    assert pending.candidates == ("spare",)
    session.submit(P1, DecisionResponse(("spare",)))

    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert session.game.table.cards_by_id["spare"] in hand


def test_investing_raises_the_cards_gold_cost_permanently():
    """ "Permanently increase the Gold Cost by the Invest cost" (CR, Invest) — the surcharge is a
    lasting property of the card in play, not a one-off payment."""
    session = _sand_game()
    session.act(P1, Equip("weapon", invest=True))
    session.submit(P1, DecisionResponse(("bearer",)))
    session.submit(P1, DecisionResponse(("P1-SH",)))
    session.submit(P1, DecisionResponse(("spare",)))

    weapon = session.game.table.cards_by_id["weapon"]
    assert effective_gold_cost(session.game, weapon) == 4


def test_equipping_without_the_invest_leaves_the_cost_and_the_deck_alone():
    session = _sand_game()
    session.act(P1, Equip("weapon"))
    session.submit(P1, DecisionResponse(("bearer",)))
    session.submit(P1, DecisionResponse(("P1-SH",)))

    assert session.project(P1).pending is None  # no search was raised
    assert effective_gold_cost(session.game, session.game.table.cards_by_id["weapon"]) == 3


def test_the_invest_is_withheld_when_only_the_bare_cost_is_affordable():
    session = _sand_game(production=3)

    offered = [a for a in session.legal_actions(P1) if isinstance(a, Equip)]

    assert offered == [Equip("weapon")]
