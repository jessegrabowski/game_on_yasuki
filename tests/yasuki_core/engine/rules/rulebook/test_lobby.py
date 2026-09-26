from dataclasses import replace

import pytest

from yasuki_core import ruleset
from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import legality, triggers
from yasuki_core.engine.rules.abilities.registry import ability_for, ability_registrations
from yasuki_core.engine.rules.action_record import action_keywords
from yasuki_core.engine.rules.board.queries import rulebook_proxy
from yasuki_core.engine.rules.effects import GrantLobbyBonus
from yasuki_core.engine.rules.rulebook import proxies
from yasuki_core.engine.rules.rulebook.lobby import (
    LOBBY,
    LOBBY_BARS,
    is_lobby,
    lobby_amount,
    lobby_bar,
    lobby_candidates,
    lobby_key,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn import action_sequence
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility
from yasuki_core.engine.rules.vocabulary.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.rules.vocabulary.modifiers import Duration
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import IMPERIAL_LOBBY_PROXY_ID, ONYX_LOBBY_PROXY_ID
from yasuki_gui.services.game_runner import GameRunner

from tests.yasuki_core.engine.builders import holding, personality, put_in_play, sensei

P1 = PlayerId.P1
P2 = PlayerId.P2

LOBBY_PROXIES = {
    ruleset.SHATTERED_EMPIRE.name: ONYX_LOBBY_PROXY_ID,
    ruleset.IMPERIAL.name: IMPERIAL_LOBBY_PROXY_ID,
}


@pytest.fixture(params=[ruleset.SHATTERED_EMPIRE, ruleset.IMPERIAL], ids=lambda arc: arc.name)
def arc(request, monkeypatch) -> ruleset.Ruleset:
    """Run the test under each arc's Lobby: the Onyx proxy's Open one and the Imperial Limited
    one."""
    monkeypatch.setattr(ruleset, "ACTIVE", request.param)
    return request.param


@pytest.fixture
def imperial(monkeypatch) -> None:
    monkeypatch.setattr(ruleset, "ACTIVE", ruleset.IMPERIAL)


def _game(*, p1_honor: int = 10, p2_honor: int = 5) -> GameState:
    """A two-seat game on P1's turn, with P1 ahead on Family Honor unless a test says otherwise, and
    each seat holding the active arc's Lobby proxy."""
    game = GameState.start(TableState.empty_two_seat(), P1, seed=0)
    game.table.seats[P1].honor = p1_honor
    game.table.seats[P2].honor = p2_honor
    proxies.spawn_rulebook_proxies(game)
    return game


def _lobby(game: GameState, seat: PlayerId = P1) -> ActivateAbility:
    proxy = rulebook_proxy(game, seat, LOBBY_PROXIES[ruleset.ACTIVE.name])
    return ActivateAbility(proxy.id, LOBBY)


def _lobbies(game: GameState, seat: PlayerId = P1) -> list[ActivateAbility]:
    return [action for action in legality.legal_actions(game, seat) if is_lobby(action)]


def _lobby_with(game: GameState, card_id: str) -> None:
    action_sequence.perform(game, _lobby(game))
    submit(game, DecisionResponse((card_id,)))


def test_each_arc_deals_its_own_lobby_proxy(arc):
    game = _game()

    dealt = {
        printed_id
        for printed_id in LOBBY_PROXIES.values()
        if rulebook_proxy(game, P1, printed_id) is not None
    }
    assert dealt == {LOBBY_PROXIES[arc.name]}


def test_onyx_deals_the_open_lobby_proxy_it_passes_on_to_shattered_empire():
    assert ONYX_LOBBY_PROXY_ID in ruleset.ONYX.rulebook_proxies
    assert ruleset.SHATTERED_EMPIRE.rulebook_proxies == ruleset.ONYX.rulebook_proxies


@pytest.mark.parametrize(
    ("printed_id", "timing"),
    [(ONYX_LOBBY_PROXY_ID, ActionTiming.OPEN), (IMPERIAL_LOBBY_PROXY_ID, ActionTiming.LIMITED)],
)
def test_each_arcs_lobby_is_a_political_rulebook_ability_under_its_designator(printed_id, timing):
    [ability] = ability_registrations()[printed_id]

    assert (ability.timings, ability.keywords) == ((timing,), frozenset({keywords.POLITICAL}))
    assert ability.from_rulebook


def test_lobby_is_offered_once_however_many_personalities_could_pay_for_it(arc):
    # The ability is one action. Which Personality it bows is chosen as its cost is paid.
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, personality("champion", personal_honor=1))

    assert _lobbies(game) == [_lobby(game)]


def test_the_cost_offers_every_personality_that_could_pay(arc):
    # ShE datasheet: "your target unbowed Personality with 1 or more Personal Honor". The pre-Gold
    # rulebook's "over 0 Personal Honor" draws the same line.
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, personality("champion", personal_honor=1))
    put_in_play(game, personality("peasant", personal_honor=0))

    action_sequence.perform(game, _lobby(game))

    assert isinstance(game.pending, ChooseCards)
    assert set(game.pending.candidates) == {"courtier", "champion"}


def test_the_onyx_lobby_is_not_offered_on_another_seats_turn():
    # ShE datasheet: "If it is your turn". The rival holds priority in the open round, so the
    # round permits them an Open action, and only the printed condition withholds the Lobby.
    game = _game(p1_honor=5, p2_honor=10)
    put_in_play(game, personality("courtier", owner=P2, personal_honor=2))
    game.round = replace(game.round, priority=P2)
    assert legality.permits(game, P2, ActionTiming.OPEN), "the round must permit the rival"

    assert _lobbies(game, P2) == []


@pytest.mark.parametrize("rival_honor", [10, 11], ids=["tied", "ahead"])
def test_the_onyx_lobby_needs_strictly_higher_family_honor_than_every_rival(rival_honor):
    game = _game(p1_honor=10, p2_honor=rival_honor)
    put_in_play(game, personality("courtier", personal_honor=2))

    assert _lobbies(game) == []


@pytest.mark.parametrize("rival_honor", [10, 11], ids=["tied", "ahead"])
def test_the_imperial_lobby_is_offered_without_the_highest_family_honor(imperial, rival_honor):
    # The pre-Gold rulebook conditions the outcome on Family Honor, never the lobbying itself.
    game = _game(p1_honor=10, p2_honor=rival_honor)
    put_in_play(game, personality("courtier", personal_honor=2))

    assert _lobbies(game) == [_lobby(game)]


@pytest.mark.parametrize("rival_honor", [10, 11], ids=["tied", "ahead"])
def test_an_imperial_lobby_without_the_highest_family_honor_leaves_the_favor(imperial, rival_honor):
    game = _game(p1_honor=10, p2_honor=rival_honor)
    game.favor_holder = P2
    courtier = put_in_play(game, personality("courtier", personal_honor=2))

    _lobby_with(game, "courtier")

    assert courtier.bowed
    assert game.favor_holder is P2
    assert game.has_used(lobby_key(P1, game.turn))


def test_the_imperial_lobby_is_not_offered_to_the_seat_holding_the_favor(imperial):
    # Official L5R FAQ 3.10: a seat may lobby "if ... you don't already have the Favor".
    game = _game()
    game.favor_holder = P1
    put_in_play(game, personality("courtier", personal_honor=2))

    assert _lobbies(game) == []


def test_the_imperial_lobby_is_limited_to_the_seats_own_turn(imperial):
    game = _game(p1_honor=5, p2_honor=10)
    put_in_play(game, personality("courtier", owner=P2, personal_honor=2))
    game.round = replace(game.round, priority=P2)

    assert _lobbies(game, P2) == []


def test_lobby_is_not_offered_without_a_personality_to_bow(arc):
    game = _game()

    assert _lobbies(game) == []


def test_a_bowed_personality_cannot_pay_for_lobby(arc):
    game = _game()
    bowed = put_in_play(game, personality("courtier", personal_honor=2))
    bowed.bow()

    assert _lobbies(game) == []


def test_a_personality_with_no_personal_honor_cannot_pay_for_lobby(arc):
    # Neither rulebook lets a Personality with 0 Personal Honor pay.
    game = _game()
    put_in_play(game, personality("peasant", personal_honor=0))

    assert _lobbies(game) == []


def test_answering_the_cost_bows_the_personality_and_takes_the_favor(arc):
    game = _game()
    courtier = put_in_play(game, personality("courtier", personal_honor=2))

    _lobby_with(game, "courtier")

    assert courtier.bowed
    assert game.favor_holder is P1


def test_taking_lobby_takes_the_favor_from_the_seat_that_held_it(arc):
    # Twenty Festivals CR: one player controls the Favor and changes of control are instantaneous,
    # so the rival loses it as this seat gains it.
    game = _game()
    game.favor_holder = P2
    put_in_play(game, personality("courtier", personal_honor=2))

    _lobby_with(game, "courtier")

    assert game.favor_holder is P1


def test_the_lobby_is_political_while_it_resolves(arc):
    # Both rulebooks print Political on it, and a card reading "a Political action" sees it.
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))

    action_sequence.perform(game, _lobby(game))

    assert action_keywords(game) == frozenset({keywords.POLITICAL})


def test_the_board_menu_offers_lobby_with_its_printed_wording():
    session = EngineSession.start(TableState.empty_two_seat(), P1)
    game = session.game
    game.table.seats[P1].honor = 10
    game.table.seats[P2].honor = 5
    put_in_play(game, personality("courtier", name="Doji Kuwanan", personal_honor=2))
    runner = GameRunner(session, P1)

    assert (
        "Political Open: If it is your turn and you have higher Family Honor than each other "
        "player, bow your target unbowed Personality with 1 or more Personal Honor to take the "
        "Imperial Favor.",
        _lobby(game),
    ) in runner.board_menu()


def test_taking_lobby_spends_its_once_per_turn_use(arc):
    # ShE datasheet: no player may take more than one Lobby action per turn, and the pre-Gold
    # rulebook lobbies "once per turn". Asserts the claim rather than that a second Lobby is
    # unavailable, because the resolved action closes the Action Round on its own.
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))

    _lobby_with(game, "courtier")

    assert game.has_used(lobby_key(P1, game.turn))


def test_cancelling_the_bow_leaves_lobby_unspent():
    # The bow is picked while the cost is paid, after the Lobby is spent for the turn, so backing
    # out has to unwind the spend with it.
    state = TableState.empty_two_seat()
    state.seats[P1].honor = 10
    put_in_play(state, personality("courtier", personal_honor=2))
    session = EngineSession.start(state, P1)
    session.act(P1, _lobby(session.game))

    session.cancel(P1)

    game = session.game
    assert not game.has_used(lobby_key(P1, game.turn))
    assert not game.table.cards_by_id["courtier"].bowed
    assert _lobby(game) in session.legal_actions(P1)


def test_a_spent_lobby_is_not_offered_again_until_the_next_turn(arc):
    # Any Lobby action spends the seat's one Lobby for the turn, whatever granted it. The key is
    # scoped to the turn, so it resets without clearing ``once_per``.
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    game.use_once(lobby_key(P1, game.turn))
    assert _lobbies(game) == []

    game.turn += 2

    assert _lobbies(game) == [_lobby(game)]


def test_shigekawas_court_wins_a_comparison_its_seat_would_otherwise_lose():
    # Shigekawa's Court (ShE): "You have a +5 Lobby Bonus." The datasheet considers the amount
    # checked higher, so 8 + 5 beats 10.
    game = _game(p1_honor=8, p2_honor=10)
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, holding("court", printed_id="shigekawas_court"))

    assert _lobbies(game) == [_lobby(game)]


def test_a_penalty_on_a_rival_wins_a_comparison_its_seat_would_otherwise_lose():
    # The datasheet adjusts whichever player the amount is about, so a Penalty on the rival
    # settles this one and leaves the acting seat's own honor untouched.
    game = _game(p1_honor=8, p2_honor=10)
    put_in_play(game, personality("courtier", personal_honor=2))
    source = put_in_play(game, holding("agitator"))
    GrantLobbyBonus(source.id, P2, -3, Duration.WHILE_SOURCE_IN_PLAY).perform(game)

    assert _lobbies(game) == [_lobby(game)]


def test_a_lobby_bonus_is_not_an_honor_gain():
    # The datasheet says so. Writing the adjustment back to the seat would fire every trigger and
    # Victory check that watches Family Honor.
    game = _game(p1_honor=8, p2_honor=10)
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, holding("court", printed_id="shigekawas_court"))

    assert _lobbies(game) == [_lobby(game)], "the bonus is being read"
    assert game.table.seats[P1].honor == 8


@pytest.fixture
def bar_on():
    """Register a Lobby bar on ``test_lobby_bar`` that stops the one seat it is handed."""

    def register(stops: PlayerId) -> None:
        lobby_bar("test_lobby_bar")(lambda game, card, seat: seat is stops)

    yield register
    LOBBY_BARS.pop("test_lobby_bar", None)


def test_a_card_can_forbid_a_seat_to_lobby(arc, bar_on):
    bar_on(P1)
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, holding("edict", printed_id="test_lobby_bar"))

    assert _lobbies(game) == []


def test_a_bar_stops_only_the_seats_it_names(arc, bar_on):
    # One card stops its controller's rivals and another stops its controller, so the rule asks
    # the card about the seat.
    bar_on(P2)
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, holding("edict", printed_id="test_lobby_bar"))

    assert _lobbies(game) == [_lobby(game)]


def test_a_lobby_bonus_adjusts_whatever_amount_is_checked():
    # The rulebook Lobby checks Family Honor, but each Wind's own Lobby checks something else, and
    # the datasheet adjusts "any amount checked during any Lobby action".
    game = _game()
    put_in_play(game, holding("court", printed_id="shigekawas_court"))

    assert lobby_amount(game, P1, 3) == 8, "a hand of 3 cards is checked as 8"
    assert lobby_amount(game, P2, 3) == 3, "the Bonus is the checked player's, not P1's"


def _court_targets(game: GameState, court: L5RCard) -> list[str]:
    return legality.legal_targets(game, court, ability_for(game, court, None))


def test_shigekawas_court_straightens_the_personality_that_lobbied():
    # "Open, :bow: Straighten a target Personality who Lobbied this turn." The Lobby bowed him as
    # its cost, so this hands him back.
    game = _game()
    courtier = put_in_play(game, personality("courtier", personal_honor=2))
    court = put_in_play(game, holding("court", printed_id="shigekawas_court"))
    _lobby_with(game, "courtier")
    assert courtier.bowed, "the Lobby bowed him"

    assert _court_targets(game, court) == ["courtier"]
    action_sequence.perform(game, ActivateAbility("court"))
    submit(game, DecisionResponse(("courtier",)))

    assert not courtier.bowed
    assert court.bowed, "bowing the Court is the cost"


def test_shigekawas_court_offers_nobody_who_has_not_lobbied():
    game = _game()
    courtier = put_in_play(game, personality("courtier", personal_honor=2))
    court = put_in_play(game, holding("court", printed_id="shigekawas_court"))
    courtier.bow()

    assert _court_targets(game, court) == []


def test_the_lobbied_mark_does_not_survive_the_turn():
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    court = put_in_play(game, holding("court", printed_id="shigekawas_court"))
    _lobby_with(game, "courtier")

    game.turn += 1

    assert _court_targets(game, court) == []


def test_a_lobby_penalty_stops_when_the_card_granting_it_leaves_play():
    # A Lobby Bonus rests on a player, who never leaves the table, so the sweep that forgets a
    # departed card's modifiers has to keep it and let the duration decide instead.
    game = _game(p1_honor=8, p2_honor=10)
    put_in_play(game, personality("courtier", personal_honor=2))
    source = put_in_play(game, holding("agitator"))
    GrantLobbyBonus(source.id, P2, -3, Duration.WHILE_SOURCE_IN_PLAY).perform(game)
    assert _lobbies(game) == [_lobby(game)], "the Penalty is being read"

    ops.remove_card(game.table, source)
    triggers.resolve_effects(game, [])

    assert lobby_amount(game, P2, 10) == 10, "the Penalty went with its source"
    assert _lobbies(game) == []


def test_a_personality_printed_may_not_lobby_is_not_a_candidate(arc):
    # Daytiba (Onyx): "Daytiba cannot Lobby." The bar is on him rather than on his controller, so
    # the action stays open to anyone else the seat could bow.
    game = _game()
    put_in_play(game, personality("daytiba", printed_id="daytiba", personal_honor=2))
    put_in_play(game, personality("courtier", personal_honor=2))

    assert [card.id for card in lobby_candidates(game, P1)] == ["courtier"]
    assert _lobbies(game) == [_lobby(game)]


def test_a_seat_whose_only_personality_may_not_lobby_is_not_offered_it(arc):
    game = _game()
    put_in_play(game, personality("chen", printed_id="moto_chen", personal_honor=2))

    assert _lobbies(game) == []


def test_wasp_sensei_stops_its_own_controller_lobbying(arc):
    # Spirit Wars: "You may not Lobby."
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, sensei(printed_id="wasp_sensei"))

    assert _lobbies(game) == []


def test_miya_shoin_leaves_his_own_controller_lobbying(arc):
    # Winds of Change: "Other players may not Lobby."
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, personality("shoin", printed_id="miya_shoin", personal_honor=2))

    assert _lobbies(game) == [_lobby(game)]


def test_miya_shoin_stops_every_other_player(arc):
    # The rival qualifies outright (their turn, ahead on honor, a Personality to bow), so Shoin is
    # the only thing withholding it.
    game = _game(p1_honor=0, p2_honor=10)
    game.active = P2
    game.round = replace(game.round, priority=P2)
    put_in_play(game, personality("rival", owner=P2, personal_honor=2))
    assert _lobbies(game, P2) == [_lobby(game, P2)], "the rival Lobbies before Shoin arrives"

    put_in_play(game, personality("shoin", printed_id="miya_shoin", personal_honor=2))

    assert _lobbies(game, P2) == []
