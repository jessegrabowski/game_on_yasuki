from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.decisions import (
    ChooseAbilityTarget,
    DecisionResponse,
)
from yasuki_core.engine.rules.economy import effective_gold_production, effective_keywords
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint

from tests.yasuki_core.engine.builders import (
    end_phase,
    fate_card,
    holding,
    put_in_play,
    register,
    two_seat_game,
)

P1 = PlayerId.P1


def _game():
    """A session in the Action phase with P1's Millet Farm and one other Farm in play. Returns the
    live card objects, since ``EngineSession.start`` rebuilds the table from a snapshot."""
    state = TableState.empty_two_seat()
    put_in_play(
        state, holding("millet", printed_id="millet_farm", keywords=("Farm",), gold_production=1)
    )
    put_in_play(
        state, holding("farm", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )  # no trigger of its own
    session = EngineSession.start(state, P1)
    live = session.game.table.cards_by_id
    return session, live["millet"], live["farm"]


def test_millet_farm_is_activatable_in_the_action_phase():
    session, millet, _ = _game()
    assert ActivateAbility(millet.id) in session.legal_actions(P1)


def test_millet_farm_is_not_activatable_while_bowed():
    session, millet, _ = _game()
    millet.bow()
    assert ActivateAbility(millet.id) not in session.legal_actions(P1)


def test_millet_farm_is_not_activatable_outside_the_action_phase():
    session, millet, _ = _game()
    end_phase(session)  # Action -> Battle
    assert ActivateAbility(millet.id) not in session.legal_actions(P1)


def test_activating_millet_farm_bows_it_and_asks_for_a_farm_target():
    session, millet, farm = _game()
    session.act(P1, ActivateAbility(millet.id))

    assert millet.bowed
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget)
    assert set(pending.candidates) == {
        millet.id,
        farm.id,
    }  # every Farm you control, itself included


def test_millet_farm_gives_its_target_two_gold_production():
    session, millet, farm = _game()
    session.act(P1, ActivateAbility(millet.id))
    session.submit(P1, DecisionResponse((farm.id,)))

    assert session.game.pending is None
    assert effective_gold_production(session.game, farm) == 2 + 2  # base 2 + the +2GP grant


def test_ability_activation_replays_to_the_same_state():
    session, millet, farm = _game()
    session.act(P1, ActivateAbility(millet.id))
    session.submit(P1, DecisionResponse((farm.id,)))

    assert replay(session.log) == session.game


def test_modifier_clear_replays_across_the_turn_boundary():
    session, millet, farm = _game()
    session.act(P1, ActivateAbility(millet.id))
    session.submit(P1, DecisionResponse((farm.id,)))
    for _ in range(3):  # end P1's turn, dropping the UEOT modifier
        end_phase(session)

    assert session.game.modifiers == []  # the grant was cleared
    assert replay(session.log) == session.game  # and the clear rebuilds deterministically


def test_millet_farm_grant_expires_at_end_of_turn():
    session, millet, farm = _game()
    session.act(P1, ActivateAbility(millet.id))
    session.submit(P1, DecisionResponse((farm.id,)))
    assert effective_gold_production(session.game, farm) == 4  # +2 this turn

    for _ in range(3):  # Action -> Battle -> Dynasty -> end of P1's turn
        end_phase(session)
    assert effective_gold_production(session.game, farm) == 2  # the UEOT modifier is gone


def test_modifier_grant_fires_no_counter_trigger():
    # A GP grant is a modifier, not a Wealth token, so a wealth-specific trigger must stay silent.
    # Aoki draws on your Holding's Wealth gain; the +2GP grant must not wake it.
    state = TableState.empty_two_seat()
    put_in_play(
        state, holding("millet", printed_id="millet_farm", keywords=("Farm",), gold_production=1)
    )
    put_in_play(
        state, holding("farm", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )
    put_in_play(
        state,
        L5RCard.of(
            PersonalityPrint,
            id="aoki",
            name="Aoki",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="shosuro_aoki_yoritomo_kayoko_experienced",
        ),
    )
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card("fd", P1))]
    session = EngineSession.start(state, P1)
    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)]
    before = len(hand.cards)

    session.act(P1, ActivateAbility("millet"))
    session.submit(P1, DecisionResponse(("farm",)))

    assert effective_gold_production(session.game, session.game.table.cards_by_id["farm"]) == 4
    assert len(hand.cards) == before  # Aoki did not draw — the grant is a modifier, not a token


# --- Fortified Farmlands ---


def _farmlands_game(*, other_farms: int = 1):
    """Fortified Farmlands in play, beside ``other_farms`` other Farm Holdings."""
    game = two_seat_game()
    put_in_play(game, holding("farmlands", printed_id="fortified_farmlands", keywords=("Farm",)))
    for index in range(other_farms):
        put_in_play(game, holding(f"farm{index}", keywords=("Farm",)))
    return game


def test_fortified_farmlands_has_renew_beside_another_farm():
    game = _farmlands_game()

    assert "Renew" in effective_keywords(game, game.table.cards_by_id["farmlands"])


def test_fortified_farmlands_has_no_renew_on_its_own():
    """ "Another Farm" excludes the card asking, so a lone Fortified Farmlands does not count itself
    — it carries the Farm keyword and would otherwise always satisfy its own condition."""
    game = _farmlands_game(other_farms=0)

    assert "Renew" not in effective_keywords(game, game.table.cards_by_id["farmlands"])


def test_fortified_farmlands_loses_renew_when_the_other_farm_goes():
    """The grant is read whenever the keyword is asked for, so it comes and goes with the board."""
    game = _farmlands_game()
    farmlands = game.table.cards_by_id["farmlands"]
    assert "Renew" in effective_keywords(game, farmlands)

    game.table.battlefield.remove(game.table.cards_by_id["farm0"])

    assert "Renew" not in effective_keywords(game, farmlands)
