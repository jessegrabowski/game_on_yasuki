from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.decisions import (
    ChooseAbilityTarget,
    DecisionResponse,
)
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.cards.chaos_reigns_part_ii import HIYAMAKOS_CLAW, NAGA_FOLLOWER
from yasuki_core.engine.rules.economy import (
    effective_force,
    effective_gold_production,
    effective_keywords,
)
from yasuki_core.engine.rules.effects import Destroy
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.triggers import fire, resolve_effects
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint

from tests.yasuki_core.engine.builders import (
    attachment,
    end_phase,
    fate_card,
    holding,
    personality,
    put_in_play,
    register,
    token_template,
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


# --- Tarkasha ---


def _tarkasha_game(*, fallen=("dead_naga",), spare_follower=False):
    """Tarkasha in play with ``fallen`` Naga Followers in the Fate discard to reshuffle."""
    game = two_seat_game()
    token_template(
        game,
        NAGA_FOLLOWER,
        name="Naga",
        card_type="Follower",
        keywords=("Naga", "Nonhuman"),
        force=1,
    )
    put_in_play(
        game,
        personality(
            "tarkasha", printed_id="tarkasha", force=4, chi=2, keywords=("Commander", "Naga")
        ),
    )
    put_in_play(game, personality("scout", force=1, chi=2, keywords=("Naga",)))
    discard = game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)]
    for card_id in fallen:
        discard.add(
            register(
                game.table,
                attachment(
                    card_id,
                    attachment_type=AttachmentType.FOLLOWER,
                    keywords=("Naga", "Nonhuman"),
                ),
            )
        )
    if spare_follower:
        discard.add(
            register(
                game.table,
                attachment(
                    "ashigaru", attachment_type=AttachmentType.FOLLOWER, keywords=("Ashigaru",)
                ),
            )
        )
    return EngineSession.start(game.table, P1)


def test_tarkasha_reshuffles_a_fallen_naga_to_raise_a_new_one():
    session = _tarkasha_game()

    session.act(P1, ActivateAbility("tarkasha"))
    session.submit(P1, DecisionResponse(("tarkasha",)))  # the Commander, chosen at targeting
    session.submit(P1, DecisionResponse(("dead_naga",)))  # then the reshuffle its text calls for

    game = session.game
    raised = attachments_of(game, game.table.cards_by_id["tarkasha"])[0]
    assert raised.name == "Naga"
    assert [card.id for card in game.table.decks[DeckKey(P1, Side.FATE)].cards] == ["dead_naga"]
    assert game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].cards == []


def test_tarkasha_only_reshuffles_naga_followers():
    """The discard holds an Ashigaru too, and it is no Naga."""
    session = _tarkasha_game(spare_follower=True)

    session.act(P1, ActivateAbility("tarkasha"))
    session.submit(P1, DecisionResponse(("tarkasha",)))

    assert session.game.pending.candidates == ("dead_naga",)


def test_tarkasha_only_mounts_a_commander():
    """ "Your target Commander" — the plain Naga scout does not lead."""
    session = _tarkasha_game()

    session.act(P1, ActivateAbility("tarkasha"))

    assert session.game.pending.candidates == ("tarkasha",)


def test_tarkasha_raises_nothing_with_no_fallen_naga_to_reshuffle():
    """The reshuffle is written into the text, so it is an effect rather than a cost: the ability is
    announced as normal and stops when it finds nothing to reshuffle (CR, Action Sequence)."""
    session = _tarkasha_game(fallen=())

    session.act(P1, ActivateAbility("tarkasha"))
    session.submit(P1, DecisionResponse(("tarkasha",)))

    game = session.game
    assert game.pending is None
    assert attachments_of(game, game.table.cards_by_id["tarkasha"]) == ()


def test_tarkasha_replays_to_the_same_board():
    session = _tarkasha_game()
    session.act(P1, ActivateAbility("tarkasha"))
    session.submit(P1, DecisionResponse(("tarkasha",)))
    session.submit(P1, DecisionResponse(("dead_naga",)))

    assert replay(session.log).table == session.game.table


# --- Tetsuo Hiyamako (Experienced) ---


def _hiyamako_game():
    game = two_seat_game()
    token_template(
        game,
        HIYAMAKOS_CLAW,
        name="Hiyamako's Claw",
        card_type="Item",
        keywords=("Claw", "One-Handed", "Weapon"),
        force=1,
    )
    put_in_play(
        game,
        personality(
            "hiyamako", printed_id="tetsuo_hiyamako_experienced", force=2, chi=2, gold_cost=6
        ),
    )
    return game


def test_hiyamako_arrives_holding_two_claws():
    """Two Weapons where the rules allow one: her text says so, and card text beats the rules (CR,
    Cardinal Rule 1)."""
    game = _hiyamako_game()

    fire(game, EnteredPlay("hiyamako"))

    hiyamako = game.table.cards_by_id["hiyamako"]
    claws = attachments_of(game, hiyamako)
    assert [claw.name for claw in claws] == ["Hiyamako's Claw", "Hiyamako's Claw"]
    assert effective_force(game, hiyamako) == 4  # her two, and one from each Claw


def test_her_claws_are_two_distinct_cards():
    """Each is created in its own right, so destroying one leaves the other."""
    game = _hiyamako_game()
    fire(game, EnteredPlay("hiyamako"))
    first, second = attachments_of(game, game.table.cards_by_id["hiyamako"])

    resolve_effects(game, [Destroy(first.id, P1)])

    assert first.id not in game.table.cards_by_id
    assert attachments_of(game, game.table.cards_by_id["hiyamako"]) == (second,)


def test_another_personality_arriving_arms_nobody():
    game = _hiyamako_game()
    put_in_play(game, personality("bystander", force=2, chi=2))

    fire(game, EnteredPlay("bystander"))

    assert attachments_of(game, game.table.cards_by_id["hiyamako"]) == ()
    assert attachments_of(game, game.table.cards_by_id["bystander"]) == ()


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
