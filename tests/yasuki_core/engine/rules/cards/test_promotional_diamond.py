from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.cards.promotional_diamond import SUITEIRUS_PODLING
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.units import unit_force
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import (
    personality,
    put_in_play,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


# --- Suiteiru no Oni ---


def _suiteiru_game(*, victim_chi: int = 3, victim_id: str | None = None, bearers: int = 2):
    """Suiteiru in play beside ``bearers`` other Personalities and the victim his ability destroys.

    ``victim_id`` is the victim's printed id, which only a test putting him at zero Chi needs — he
    has to be one of the prints the Chi Death Rule spares, or the board destroys him before the
    ability can.
    """
    game = two_seat_game()
    token_template(
        game,
        SUITEIRUS_PODLING,
        name="Suiteiru's Podling",
        card_type="Follower",
        keywords=("Nonhuman", "Oni", "Shadowlands"),
        force=1,
    )
    put_in_play(game, personality("suiteiru", printed_id="suiteiru_no_oni", force=5, chi=3))
    put_in_play(game, personality("victim", printed_id=victim_id, chi=victim_chi))
    for index in range(bearers):
        put_in_play(game, personality(f"bearer{index}", force=2, chi=2))
    return EngineSession.start(game.table, P1)


def _followers_on(game, personality_id: str) -> int:
    return len(attachments_of(game, game.table.cards_by_id[personality_id]))


def test_suiteiru_divides_the_followers_as_the_answer_names_them():
    """Chi 3 makes three Podlings, and naming a Personality twice puts two on him — the whole of the
    "attach them to one or more of your Personalities" choice."""
    session = _suiteiru_game()

    session.act(P1, ActivateAbility("suiteiru"))
    session.submit(P1, DecisionResponse(("victim",)))  # the destroy target
    session.submit(P1, DecisionResponse(("bearer0", "bearer0", "bearer1")))

    game = session.game
    assert _followers_on(game, "bearer0") == 2
    assert _followers_on(game, "bearer1") == 1


def test_the_created_followers_are_one_force_oni():
    session = _suiteiru_game()
    session.act(P1, ActivateAbility("suiteiru"))
    session.submit(P1, DecisionResponse(("victim",)))

    session.submit(P1, DecisionResponse(("bearer0",) * 3))

    game = session.game
    podling = attachments_of(game, game.table.cards_by_id["bearer0"])[0]
    assert podling.is_token is True
    assert set(podling.keywords) == {"Nonhuman", "Oni", "Shadowlands"}
    assert unit_force(game, game.table.cards_by_id["bearer0"]) == 5  # 2 printed, +1 per Podling


def test_suiteiru_costs_honor_for_every_follower_created():
    session = _suiteiru_game(victim_chi=4)

    session.act(P1, ActivateAbility("suiteiru"))
    session.submit(P1, DecisionResponse(("victim",)))
    session.submit(P1, DecisionResponse(("bearer0", "bearer0", "bearer1", "bearer1")))

    assert session.game.table.seats[P1].honor == -4


def test_the_destroyed_personality_carries_none_of_what_his_death_creates():
    session = _suiteiru_game()

    session.act(P1, ActivateAbility("suiteiru"))
    session.submit(P1, DecisionResponse(("victim",)))

    assert "victim" not in session.game.pending.candidates


def test_suiteiru_may_take_the_followers_himself():
    """He is a Personality of his controller's like any other, so he is his own legal bearer."""
    session = _suiteiru_game(bearers=0)

    session.act(P1, ActivateAbility("suiteiru"))
    session.submit(P1, DecisionResponse(("victim",)))
    session.submit(P1, DecisionResponse(("suiteiru",) * 3))

    assert _followers_on(session.game, "suiteiru") == 3


def test_a_victim_with_no_chi_creates_nothing_to_divide():
    """Nothing is created, so nothing is asked and no Honor is paid — the destroy is all of it."""
    session = _suiteiru_game(victim_chi=0, victim_id="earthen_golem")

    session.act(P1, ActivateAbility("suiteiru"))
    session.submit(P1, DecisionResponse(("victim",)))

    game = session.game
    assert game.pending is None
    assert game.table.seats[P1].honor == 0
    assert "victim" not in {card.id for card in game.table.battlefield.cards}


def test_destroying_the_last_bearer_asks_nothing():
    """Suiteiru alone on the board and targeting himself leaves the Followers nowhere to attach, and
    a decision with no candidate could never be answered."""
    game = two_seat_game()
    token_template(
        game,
        SUITEIRUS_PODLING,
        name="Suiteiru's Podling",
        card_type="Follower",
        keywords=("Nonhuman", "Oni", "Shadowlands"),
        force=1,
    )
    put_in_play(game, personality("suiteiru", printed_id="suiteiru_no_oni", force=5, chi=3))
    session = EngineSession.start(game.table, P1)

    session.act(P1, ActivateAbility("suiteiru"))
    session.submit(P1, DecisionResponse(("suiteiru",)))

    assert session.game.pending is None
    assert session.game.table.seats[P1].honor == 0


def test_suiteiru_replays_to_the_same_board():
    session = _suiteiru_game()
    session.act(P1, ActivateAbility("suiteiru"))
    session.submit(P1, DecisionResponse(("victim",)))
    session.submit(P1, DecisionResponse(("bearer0", "bearer1", "bearer1")))

    assert replay(session.log).table == session.game.table


def test_the_count_follows_the_victims_chi_as_it_stands():
    """ "Equal to their Chi" reads the board, so a Personality carrying a Chi penalty when he is
    destroyed makes that many fewer Followers — and costs that much less Honor."""
    session = _suiteiru_game()
    session.game.modifiers.append(
        Modifier("penalty", "victim", Stat.CHI, -1, Duration.UNTIL_END_OF_TURN)
    )

    session.act(P1, ActivateAbility("suiteiru"))
    session.submit(P1, DecisionResponse(("victim",)))
    assert session.game.pending.count == 2  # printed Chi 3, one of it penalised away

    session.submit(P1, DecisionResponse(("bearer0", "bearer1")))

    assert session.game.table.seats[P1].honor == -2
