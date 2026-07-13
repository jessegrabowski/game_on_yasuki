from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding, DynastyPersonality
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.engine.rules.abilities import Ability, _ABILITIES
from yasuki_core.engine.rules.actions import ActivateAbility, Pass
from yasuki_core.engine.rules.decisions import ChooseAbilityTarget, ChooseCards, DecisionResponse
from yasuki_core.engine.rules.effects import effective_gold_production
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.state import Phase
from yasuki_core.engine.rules.triggers import AdjustCounter, Choose, choice_resolver
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.counters import WEALTH


def _register(state: TableState, card):
    state.cards_by_id[card.id] = card
    return card


def _farm(card_id: str, printed_id: str, gp: int) -> DynastyHolding:
    return DynastyHolding(
        id=card_id,
        name="Farm",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        printed_id=printed_id,
        keywords=("Farm",),
        gold_production=gp,
    )


def _game():
    """A session in the Action phase with P1's Millet Farm and one other Farm in play. Returns the
    live card objects, since ``EngineSession.start`` rebuilds the table from a snapshot."""
    state = TableState.empty_two_seat()
    state.battlefield.add(_register(state, _farm("millet", "millet_farm", gp=1)))
    state.battlefield.add(
        _register(state, _farm("farm", "plain_farm", gp=2))
    )  # no trigger of its own
    session = EngineSession.start(state, PlayerId.P1)
    live = session.game.table.cards_by_id
    return session, live["millet"], live["farm"]


def test_millet_farm_is_activatable_in_the_action_phase():
    session, millet, _ = _game()
    assert ActivateAbility(millet.id) in session.legal_actions(PlayerId.P1)


def test_millet_farm_is_not_activatable_while_bowed():
    session, millet, _ = _game()
    millet.bow()
    assert ActivateAbility(millet.id) not in session.legal_actions(PlayerId.P1)


def test_millet_farm_is_not_activatable_outside_the_action_phase():
    session, millet, _ = _game()
    session.act(PlayerId.P1, Pass())  # Action -> Attack
    assert ActivateAbility(millet.id) not in session.legal_actions(PlayerId.P1)


def test_activating_millet_farm_bows_it_and_asks_for_a_farm_target():
    session, millet, farm = _game()
    session.act(PlayerId.P1, ActivateAbility(millet.id))

    assert millet.bowed
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget)
    assert set(pending.candidates) == {
        millet.id,
        farm.id,
    }  # every Farm you control, itself included


def test_millet_farm_gives_its_target_two_gold_production():
    session, millet, farm = _game()
    session.act(PlayerId.P1, ActivateAbility(millet.id))
    session.submit(PlayerId.P1, DecisionResponse((farm.id,)))

    assert session.game.pending is None
    assert effective_gold_production(session.game, farm) == 2 + 2  # base 2 + the +2GP grant


def test_ability_activation_replays_to_the_same_state():
    session, millet, farm = _game()
    session.act(PlayerId.P1, ActivateAbility(millet.id))
    session.submit(PlayerId.P1, DecisionResponse((farm.id,)))

    assert replay(session.log) == session.game


def test_modifier_clear_replays_across_the_turn_boundary():
    session, millet, farm = _game()
    session.act(PlayerId.P1, ActivateAbility(millet.id))
    session.submit(PlayerId.P1, DecisionResponse((farm.id,)))
    for _ in range(3):  # end P1's turn, dropping the UEOT modifier
        session.act(PlayerId.P1, Pass())

    assert session.game.modifiers == []  # the grant was cleared
    assert replay(session.log) == session.game  # and the clear rebuilds deterministically


def test_millet_farm_grant_expires_at_end_of_turn():
    session, millet, farm = _game()
    session.act(PlayerId.P1, ActivateAbility(millet.id))
    session.submit(PlayerId.P1, DecisionResponse((farm.id,)))
    assert effective_gold_production(session.game, farm) == 4  # +2 this turn

    for _ in range(3):  # Action -> Attack -> Dynasty -> end of P1's turn
        session.act(PlayerId.P1, Pass())
    assert effective_gold_production(session.game, farm) == 2  # the UEOT modifier is gone


def test_modifier_grant_fires_no_counter_trigger():
    # A GP grant is a modifier, not a Wealth token, so a wealth-specific trigger must stay silent.
    # Aoki draws on your Holding's Wealth gain; the +2GP grant must not wake it.
    state = TableState.empty_two_seat()
    state.battlefield.add(_register(state, _farm("millet", "millet_farm", gp=1)))
    state.battlefield.add(_register(state, _farm("farm", "plain_farm", gp=2)))
    state.battlefield.add(
        _register(
            state,
            DynastyPersonality(
                id="aoki",
                name="Aoki",
                side=Side.DYNASTY,
                owner=PlayerId.P1,
                printed_id="shosuro_aoki_yoritomo_kayoko_experienced",
            ),
        )
    )
    state.decks[DeckKey(PlayerId.P1, Side.FATE)].cards = [
        _register(state, FateCard(id="fd", name="F", side=Side.FATE, owner=PlayerId.P1))
    ]
    session = EngineSession.start(state, PlayerId.P1)
    hand = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    before = len(hand.cards)

    session.act(PlayerId.P1, ActivateAbility("millet"))
    session.submit(PlayerId.P1, DecisionResponse(("farm",)))

    assert effective_gold_production(session.game, session.game.table.cards_by_id["farm"]) == 4
    assert len(hand.cards) == before  # Aoki did not draw — the grant is a modifier, not a token


def _holding(card_id, printed_id, keywords=(), counters=None, gp=0):
    return DynastyHolding(
        id=card_id,
        name=card_id,
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        printed_id=printed_id,
        keywords=keywords,
        gold_production=gp,
        counters=counters or {},
    )


def _otokoshi_game():
    state = TableState.empty_two_seat()
    state.battlefield.add(_register(state, _holding("oto", "otokoshi_district", gp=2)))
    state.battlefield.add(_register(state, _holding("mkt", "market", keywords=("Market",), gp=1)))
    state.decks[DeckKey(PlayerId.P1, Side.FATE)].cards = [
        _register(state, FateCard(id="fd", name="F", side=Side.FATE, owner=PlayerId.P1))
    ]
    return EngineSession.start(state, PlayerId.P1)


def test_otokoshi_destroys_itself_to_draw_and_seed_a_market():
    session = _otokoshi_game()
    hand = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    before = len(hand.cards)

    session.act(PlayerId.P1, ActivateAbility("oto"))
    session.submit(PlayerId.P1, DecisionResponse(("mkt",)))

    table = session.game.table
    discard = table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)]
    assert "oto" in {c.id for c in discard.cards}  # destroyed itself as the cost
    assert len(hand.cards) == before + 1  # drew a card
    assert table.cards_by_id["mkt"].counters.get("wealth") == 1  # market seeded a wealth token


def test_otokoshi_is_not_activatable_without_a_market():
    state = TableState.empty_two_seat()
    state.battlefield.add(_register(state, _holding("oto", "otokoshi_district", gp=2)))
    session = EngineSession.start(state, PlayerId.P1)
    assert ActivateAbility("oto") not in session.legal_actions(PlayerId.P1)


def test_otokoshi_activation_replays_to_the_same_state():
    session = _otokoshi_game()
    session.act(PlayerId.P1, ActivateAbility("oto"))
    session.submit(PlayerId.P1, DecisionResponse(("mkt",)))
    assert replay(session.log) == session.game


def _rural_market_game(wealth=1):
    state = TableState.empty_two_seat()
    counters = {"wealth": wealth} if wealth else {}
    state.battlefield.add(
        _register(
            state, _holding("rm", "rural_market", keywords=("Farm", "Market"), counters=counters)
        )
    )
    state.battlefield.add(_register(state, _holding("bf", "plain_farm", keywords=("Farm",), gp=2)))
    session = EngineSession.start(state, PlayerId.P1)
    session.game.table.cards_by_id["bf"].bow()  # bow after the start-of-turn straighten
    return session


def test_rural_market_spends_a_wealth_token_to_straighten_a_farm():
    session = _rural_market_game(wealth=1)
    session.act(PlayerId.P1, ActivateAbility("rm"))
    session.submit(PlayerId.P1, DecisionResponse(("bf",)))

    table = session.game.table
    assert not table.cards_by_id["bf"].bowed  # straightened
    assert table.cards_by_id["rm"].counters.get("wealth", 0) == 0  # the token was spent


def test_rural_market_is_not_activatable_without_a_wealth_token():
    session = _rural_market_game(wealth=0)
    assert ActivateAbility("rm") not in session.legal_actions(PlayerId.P1)


def test_a_non_bow_ability_is_activatable_while_bowed():
    # Tireless: a destroy/spend cost does not require an unbowed card (unlike a bow cost).
    session = _otokoshi_game()
    session.game.table.cards_by_id["oto"].bow()
    assert ActivateAbility("oto") in session.legal_actions(PlayerId.P1)


@choice_resolver("test_cost_pauses")
def _test_cost_grant(game, source_id, chosen):
    return [AdjustCounter(card_id, WEALTH, 1) for card_id in chosen]


# A synthetic ability whose cost pauses for a choice. It exercises the deferred target selection: the
# cost's own decision must resolve before the ability's target is asked, neither clobbering the
# other. No real card pays a cost that pauses yet.
_ABILITIES["test_cost_pauses"] = Ability(
    phase=Phase.ACTION,
    label="test",
    cost=lambda source: [Choose(source.owner, (source.id,), 0, 1, "test_cost_pauses", source.id)],
    targets=lambda game, card: [
        c.id
        for c in game.table.battlefield.cards
        if c.owner is card.owner and c is not card and "Farm" in c.keywords
    ],
    effects=lambda source, target: [AdjustCounter(target.id, WEALTH, 1)],
)


def test_a_cost_that_pauses_resolves_before_the_ability_target():
    state = TableState.empty_two_seat()
    state.battlefield.add(_register(state, _holding("src", "test_cost_pauses")))
    state.battlefield.add(_register(state, _holding("tgt", "plain_farm", keywords=("Farm",), gp=2)))
    session = EngineSession.start(state, PlayerId.P1)

    session.act(PlayerId.P1, ActivateAbility("src"))
    assert isinstance(session.game.pending, ChooseCards)  # the cost's choice comes first
    assert session.game.pending.candidates == ("src",)

    session.submit(PlayerId.P1, DecisionResponse(("src",)))
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget)  # the target, deferred until the cost resolved
    assert pending.candidates == ("tgt",)
    assert session.game.table.cards_by_id["src"].counters == {"wealth": 1}  # cost choice applied

    session.submit(PlayerId.P1, DecisionResponse(("tgt",)))
    assert session.game.pending is None
    assert session.game.table.cards_by_id["tgt"].counters == {"wealth": 1}  # ability effect applied
    assert replay(session.log) == session.game  # the deferred-cost chain replays deterministically


def _harvested_game(other_farms: int = 2) -> EngineSession:
    state = TableState.empty_two_seat()
    state.battlefield.add(
        _register(state, _holding("hl", "harvested_land", keywords=("Farm",), gp=2))
    )
    for i in range(other_farms):
        state.battlefield.add(
            _register(state, _holding(f"f{i}", "plain_farm", keywords=("Farm",), gp=2))
        )
    return EngineSession.start(state, PlayerId.P1)


def test_harvested_land_destroys_itself_to_boost_your_other_farms():
    session = _harvested_game(other_farms=2)
    session.act(PlayerId.P1, ActivateAbility("hl"))

    table = session.game.table
    assert session.game.pending is None  # untargeted — it hits every other Farm, no choice
    assert "hl" in {c.id for c in table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)].cards}
    assert effective_gold_production(session.game, table.cards_by_id["f0"]) == 3  # base 2 + 1
    assert effective_gold_production(session.game, table.cards_by_id["f1"]) == 3


def test_harvested_land_is_not_offered_without_another_farm():
    session = _harvested_game(other_farms=0)
    assert ActivateAbility("hl") not in session.legal_actions(PlayerId.P1)


def test_harvested_land_boost_expires_at_end_of_turn():
    session = _harvested_game(other_farms=1)
    session.act(PlayerId.P1, ActivateAbility("hl"))
    assert effective_gold_production(session.game, session.game.table.cards_by_id["f0"]) == 3

    for _ in range(3):  # end P1's turn — the boost outlives its destroyed source but not the turn
        session.act(PlayerId.P1, Pass())
    assert effective_gold_production(session.game, session.game.table.cards_by_id["f0"]) == 2


def test_harvested_land_activation_replays_to_the_same_state():
    session = _harvested_game(other_farms=2)
    session.act(PlayerId.P1, ActivateAbility("hl"))
    assert replay(session.log) == session.game


def _ichiba_game(fate_cards: int = 1, ports: int = 1) -> EngineSession:
    state = TableState.empty_two_seat()
    state.battlefield.add(
        _register(state, _holding("ich", "ichiba_district", keywords=("Market",), gp=1))
    )
    for i in range(ports):
        state.battlefield.add(
            _register(state, _holding(f"port{i}", "island_wharf", keywords=("Port",), gp=2))
        )
    state.decks[DeckKey(PlayerId.P1, Side.FATE)].cards = [
        _register(state, FateCard(id=f"fd{i}", name="F", side=Side.FATE, owner=PlayerId.P1))
        for i in range(fate_cards)
    ]
    return EngineSession.start(state, PlayerId.P1)


def test_ichiba_banishes_the_top_fate_card_then_boosts_a_target_port():
    session = _ichiba_game(fate_cards=2, ports=1)
    session.act(PlayerId.P1, ActivateAbility("ich"))

    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget) and pending.candidates == ("port0",)
    table = session.game.table
    banished = table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_BANISH)]
    assert [c.id for c in banished.cards] == ["fd1"]  # the top (drawn end), not the bottom
    assert [c.id for c in table.decks[DeckKey(PlayerId.P1, Side.FATE)].cards] == ["fd0"]  # the rest

    session.submit(PlayerId.P1, DecisionResponse(("port0",)))
    assert effective_gold_production(session.game, table.cards_by_id["port0"]) == 3  # base 2 + 1


def test_ichiba_is_not_activatable_with_an_empty_fate_deck():
    session = _ichiba_game(fate_cards=0, ports=1)
    assert ActivateAbility("ich") not in session.legal_actions(PlayerId.P1)


def test_ichiba_is_not_activatable_without_a_port():
    session = _ichiba_game(fate_cards=1, ports=0)
    assert ActivateAbility("ich") not in session.legal_actions(PlayerId.P1)


def test_ichiba_activation_replays_to_the_same_state():
    session = _ichiba_game(fate_cards=2, ports=1)
    session.act(PlayerId.P1, ActivateAbility("ich"))
    session.submit(PlayerId.P1, DecisionResponse(("port0",)))
    assert replay(session.log) == session.game
