from dataclasses import replace

import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine import ops
from yasuki_core.engine.rules import legality, triggers
from yasuki_core.engine.rules.abilities import LOBBY_BARS
from yasuki_core.engine.rules.legality import lobby_key
from yasuki_core.engine.rules.actions import Lobby
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.economy import lobby_amount
from yasuki_core.engine.rules.effects import GrantLobbyBonus
from yasuki_core.engine.rules.modifiers import Duration
from yasuki_core.engine.rules.flow import lobby, submit
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.runner import GameRunner
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState

from tests.yasuki_core.engine.builders import holding, personality, put_in_play


def _game(*, p1_honor: int = 10, p2_honor: int = 5) -> GameState:
    """A two-seat game on P1's turn, with P1 ahead on Family Honor unless a test says otherwise."""
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=0)
    game.table.seats[PlayerId.P1].honor = p1_honor
    game.table.seats[PlayerId.P2].honor = p2_honor
    return game


def _lobbies(game: GameState, seat: PlayerId = PlayerId.P1) -> list[Lobby]:
    return [action for action in legality.legal_actions(game, seat) if isinstance(action, Lobby)]


def test_lobby_is_offered_once_however_many_personalities_could_pay_for_it():
    """The ability is one action; which Personality it bows is chosen when it resolves."""
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, personality("champion", personal_honor=1))

    assert _lobbies(game) == [Lobby()]


def test_the_target_decision_offers_every_personality_that_could_pay():
    """ShE datasheet: bow your target unbowed Personality with 1 or more Personal Honor."""
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, personality("champion", personal_honor=1))
    put_in_play(game, personality("peasant", personal_honor=0))

    lobby(game)

    assert set(game.pending.candidates) == {"courtier", "champion"}


def test_lobby_is_not_offered_on_another_seats_turn():
    """ShE datasheet states the condition explicitly: "If it is your turn".

    The rival is given priority in the open round, so the round itself permits them to act. Without
    that, an Open designator would let the non-active seat Lobby on someone else's turn -- which is
    exactly why the datasheet spells the condition out.
    """
    game = _game(p1_honor=5, p2_honor=10)
    put_in_play(game, personality("courtier", owner=PlayerId.P2, personal_honor=2))
    game.round = replace(game.round, priority=PlayerId.P2)
    assert legality.permits(game, PlayerId.P2, ruleset.ACTIVE.lobby_timing), (
        "the round has to permit the rival, or this proves nothing"
    )

    assert _lobbies(game, PlayerId.P2) == []


@pytest.mark.parametrize("rival_honor", [10, 11], ids=["tied", "ahead"])
def test_lobby_needs_strictly_higher_family_honor_than_every_rival(rival_honor):
    """ShE datasheet: higher Family Honor than each other player, so a tie does not qualify."""
    game = _game(p1_honor=10, p2_honor=rival_honor)
    put_in_play(game, personality("courtier", personal_honor=2))

    assert _lobbies(game) == []


def test_lobby_is_not_offered_without_a_personality_to_bow():
    game = _game()

    assert _lobbies(game) == []


def test_a_bowed_personality_cannot_pay_for_lobby():
    game = _game()
    bowed = put_in_play(game, personality("courtier", personal_honor=2))
    bowed.bow()

    assert _lobbies(game) == []


def test_a_personality_with_no_personal_honor_cannot_pay_for_lobby():
    """Zero is the boundary the datasheet draws: 1 or more Personal Honor, not simply any."""
    game = _game()
    put_in_play(game, personality("peasant", personal_honor=0))

    assert _lobbies(game) == []


def test_answering_the_target_bows_the_personality_and_takes_the_favor():
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    lobby(game)

    submit(game, DecisionResponse(choices=("courtier",)))

    assert game.table.cards_by_id["courtier"].bowed is True
    assert game.favor_holder is PlayerId.P1


def test_taking_lobby_takes_the_favor_from_the_seat_that_held_it():
    """Twenty Festivals CR: one player controls the Favor and changes of control are instantaneous,
    so the rival loses it as this seat gains it."""
    game = _game()
    game.favor_holder = PlayerId.P2
    put_in_play(game, personality("courtier", personal_honor=2))
    lobby(game)

    submit(game, DecisionResponse(choices=("courtier",)))

    assert game.favor_holder is PlayerId.P1


def test_the_board_menu_offers_lobby_once():
    """The Favor belongs to no card, so the empty board is the only place Lobby can be offered."""
    session = EngineSession.start(TableState.empty_two_seat(), PlayerId.P1)
    game = session.game
    game.table.seats[PlayerId.P1].honor = 10
    game.table.seats[PlayerId.P2].honor = 5
    put_in_play(game, personality("courtier", name="Doji Kuwanan", personal_honor=2))
    runner = GameRunner(session, PlayerId.P1)

    assert ("Lobby: bow a Personality to take the Imperial Favor", Lobby()) in runner.board_menu()


def test_taking_lobby_spends_its_once_per_turn_use():
    """ShE datasheet: player abilities may only be taken once per turn per player by default, and
    the Lobby keyword caps a player at one Lobby action per turn besides.

    Asserts the claim rather than that a second Lobby is unavailable: the resolved action closes the
    Action Round on its own, so an offering check here would pass with the cap removed entirely.
    """
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    lobby(game)

    submit(game, DecisionResponse(choices=("courtier",)))

    assert game.has_used(lobby_key(PlayerId.P1, game.turn))


def test_a_spent_lobby_is_not_offered_again_until_the_next_turn():
    """The usage key is scoped to the turn, so it resets without clearing ``once_per``."""
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    game.use_once(lobby_key(PlayerId.P1, game.turn))
    assert _lobbies(game) == []

    game.turn += 2  # back round to this seat's next turn

    assert _lobbies(game) == [Lobby()]


def test_shigekawas_court_wins_a_comparison_its_seat_would_otherwise_lose():
    """Shigekawa's Court (ShE): "You have a +5 Lobby Bonus." Read against the datasheet's wide
    wording rather than the CR's — the amount checked is considered higher, so 8 + 5 beats 10."""
    game = _game(p1_honor=8, p2_honor=10)
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, holding("court", printed_id="shigekawas_court"))

    assert _lobbies(game) == [Lobby()]


def test_a_penalty_on_a_rival_wins_a_comparison_its_seat_would_otherwise_lose():
    """The datasheet adjusts whichever player the amount is about, so a Penalty on the rival is what
    settles this one — the acting seat's own honor is untouched."""
    game = _game(p1_honor=8, p2_honor=10)
    put_in_play(game, personality("courtier", personal_honor=2))
    source = put_in_play(game, holding("agitator"))
    GrantLobbyBonus(source.id, PlayerId.P2, -3, Duration.WHILE_SOURCE_IN_PLAY).perform(game)

    assert _lobbies(game) == [Lobby()]


def test_a_lobby_bonus_is_not_an_honor_gain():
    """The datasheet says so explicitly. Writing the adjustment back to the seat would fire every
    trigger and Victory check that watches Family Honor."""
    game = _game(p1_honor=8, p2_honor=10)
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, holding("court", printed_id="shigekawas_court"))

    assert _lobbies(game) == [Lobby()], "the bonus is being read"
    assert game.table.seats[PlayerId.P1].honor == 8


def test_a_card_can_forbid_a_seat_to_lobby():
    """The hook a card reaches for to say "this player may not Lobby". The seat otherwise qualifies
    outright, so the bar is the only thing withholding the action."""
    LOBBY_BARS["test_lobby_bar"] = lambda game, card, seat: seat is PlayerId.P1
    try:
        game = _game()
        put_in_play(game, personality("courtier", personal_honor=2))
        put_in_play(game, holding("edict", printed_id="test_lobby_bar"))

        assert _lobbies(game) == []
    finally:
        LOBBY_BARS.pop("test_lobby_bar", None)


def test_a_bar_stops_only_the_seats_it_names():
    """A bar is the card's judgment, not a blanket switch: one card stops its controller's rivals
    and another stops its controller, so the rule asks the card about the seat."""
    LOBBY_BARS["test_lobby_bar"] = lambda game, card, seat: seat is PlayerId.P2
    try:
        game = _game()
        put_in_play(game, personality("courtier", personal_honor=2))
        put_in_play(game, holding("edict", printed_id="test_lobby_bar"))

        assert _lobbies(game) == [Lobby()]
    finally:
        LOBBY_BARS.pop("test_lobby_bar", None)


def test_a_lobby_bonus_adjusts_whatever_amount_is_checked():
    """The rulebook Lobby checks Family Honor, but each Wind's own Lobby checks something else —
    cards in hand for House of Suikihime, the total Gold Cost of attachments for Kano's Alliance,
    the total Force of unbowed units for The Kanpeki Dynasty. The datasheet adjusts "any amount
    checked during any Lobby action", so the Bonus is read against those too."""
    game = _game()
    put_in_play(game, holding("court", printed_id="shigekawas_court"))

    assert lobby_amount(game, PlayerId.P1, 3) == 8, "a hand of 3 cards is checked as 8"
    assert lobby_amount(game, PlayerId.P2, 3) == 3, "the Bonus is the checked player's, not P1's"


def test_a_lobby_penalty_stops_when_the_card_granting_it_leaves_play():
    """A Lobby Bonus rests on a player, who never leaves the table, so the sweep that forgets a
    departed card's modifiers has to keep it and let the duration decide instead."""
    game = _game(p1_honor=8, p2_honor=10)
    put_in_play(game, personality("courtier", personal_honor=2))
    source = put_in_play(game, holding("agitator"))
    GrantLobbyBonus(source.id, PlayerId.P2, -3, Duration.WHILE_SOURCE_IN_PLAY).perform(game)
    assert _lobbies(game) == [Lobby()], "the Penalty is being read"

    ops.remove_card(game.table, source)
    triggers.resolve_effects(game, [])

    assert lobby_amount(game, PlayerId.P2, 10) == 10, "the Penalty went with its source"
    assert _lobbies(game) == []
