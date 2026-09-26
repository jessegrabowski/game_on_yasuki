import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.action_record import action_keywords
from yasuki_core.engine.rules.board.queries import rulebook_proxy
from yasuki_core.engine.rules.rulebook import proxies
from yasuki_core.engine.rules.rulebook.lobby import LOBBY
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import (
    ActivateAbility,
    Recruit,
)

from yasuki_core.game_pieces.constants import ONYX_LOBBY_PROXY_ID

from tests.yasuki_core.engine.builders import (
    datasheet_favor_ability,
    holding,
    put_in_play,
    two_seat_game,
)

P1 = PlayerId.P1


def test_no_action_has_no_keywords():
    assert action_keywords(two_seat_game()) == frozenset()


def test_an_ability_carries_the_keywords_its_registration_declares():
    game = two_seat_game()
    put_in_play(game, holding("court", printed_id="training_court"))
    game.action = ActivateAbility("court")

    assert action_keywords(game) == {keywords.POLITICAL}


def test_lobby_is_political():
    # ShE datasheet: "Political Open: ... Lobby".
    game = two_seat_game()
    proxies.spawn_rulebook_proxies(game)

    game.action = ActivateAbility(rulebook_proxy(game, P1, ONYX_LOBBY_PROXY_ID).id, LOBBY)
    assert action_keywords(game) == {keywords.POLITICAL}


@pytest.mark.parametrize("arc", [ruleset.ONYX, ruleset.SHATTERED_EMPIRE])
@pytest.mark.parametrize("key", ["discard_to_draw", "send_attacker_home"])
def test_the_datasheet_favor_abilities_are_political(monkeypatch, arc, key):
    # ShE datasheet: "Political Open, (Favor): ..." and "Political Battle, (Favor): ...".
    monkeypatch.setattr(ruleset, "ACTIVE", arc)
    game = two_seat_game()
    proxies.spawn_rulebook_proxies(game)
    game.action = datasheet_favor_ability(key)

    assert action_keywords(game) == {keywords.POLITICAL}


def test_a_recruit_carries_no_keywords():
    game = two_seat_game()
    game.action = Recruit("anything")

    assert action_keywords(game) == frozenset()
