from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.cards.gates_of_tengoku import SASADAS_OROCHI
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.triggers import fire
from yasuki_core.engine.rules.units import unit_force

from tests.yasuki_core.engine.builders import (
    personality,
    put_in_play,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


# --- Sasada, Pearl Champion ---


def _sasada_game():
    game = two_seat_game()
    token_template(
        game,
        SASADAS_OROCHI,
        name="Sasada's Orochi",
        card_type="Follower",
        keywords=("Nonhuman", "Orochi"),
        force=2,
    )
    put_in_play(
        game,
        personality("sasada", printed_id="sasada_pearl_champion_experienced", force=2, chi=3),
    )
    return game


def test_sasada_arrives_with_her_orochi():
    game = _sasada_game()

    fire(game, EnteredPlay("sasada"))

    sasada = game.table.cards_by_id["sasada"]
    orochi = attachments_of(game, sasada)[0]
    assert orochi.name == "Sasada's Orochi"
    assert unit_force(game, sasada) == 4  # her 2, plus the Orochi's own 2


def test_another_personality_arriving_does_not_summon_the_orochi():
    """The trigger fires for every event, so it has to check the arrival is Sasada's own."""
    game = _sasada_game()
    put_in_play(game, personality("sailor", force=1, chi=2))

    fire(game, EnteredPlay("sailor"))

    assert attachments_of(game, game.table.cards_by_id["sasada"]) == ()
    assert attachments_of(game, game.table.cards_by_id["sailor"]) == ()
