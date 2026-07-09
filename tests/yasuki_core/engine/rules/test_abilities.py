from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding, DynastyPersonality
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.engine.rules.actions import ActivateAbility, Pass
from yasuki_core.engine.rules.decisions import ChooseAbilityTarget, DecisionResponse
from yasuki_core.engine.rules.effects import effective_gold_production
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession


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
