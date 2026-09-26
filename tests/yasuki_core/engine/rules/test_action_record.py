from dataclasses import replace

import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.registry import (
    _ABILITIES,
    GRANTED_ABILITIES,
    granted_ability,
)
from yasuki_core.engine.rules.action_record import action_keywords, is_printed_action
from yasuki_core.engine.rules.board.queries import rulebook_proxy
from yasuki_core.engine.rules.rulebook import proxies
from yasuki_core.engine.rules.rulebook.lobby import LOBBY
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import (
    ActivateAbility,
    PlayInterrupt,
    Recruit,
)
from yasuki_core.engine.rules.vocabulary.modifiers import AbilityGrant, Duration
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint

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


def test_a_cards_own_ability_and_an_interrupt_from_a_card_are_printed_actions():
    game = two_seat_game()
    put_in_play(game, holding("court", printed_id="training_court"))

    assert is_printed_action(game, ActivateAbility("court"))
    assert is_printed_action(game, PlayInterrupt("court"))


def test_a_trait_a_rulebook_ability_and_a_rulebook_interrupt_are_no_printed_actions():
    game = two_seat_game()
    proxies.spawn_rulebook_proxies(game)
    lobby_proxy = rulebook_proxy(game, P1, ONYX_LOBBY_PROXY_ID)
    edict = L5RCard.of(
        ActionPrint,
        id="crane",
        name="Way of the Crane",
        printed_id="way_of_the_crane_experienced",
        side=Side.FATE,
        owner=P1,
    )
    put_in_play(game, edict)

    assert not is_printed_action(game, ActivateAbility("crane", "draw"))
    assert not is_printed_action(game, ActivateAbility(lobby_proxy.id, LOBBY))
    assert not is_printed_action(game, PlayInterrupt(lobby_proxy.id))


def test_an_ability_another_card_grants_is_no_printed_action():
    plain = _ABILITIES["millet_farm"][0]
    granted_ability("grant_probe")(lambda game, card, context: replace(plain, key="granted"))
    try:
        game = two_seat_game()
        granting = put_in_play(game, holding("granting", printed_id="grant_probe"))
        farm = put_in_play(game, holding("farm"))
        game.ongoing.append(AbilityGrant(granting.id, farm.id, (), Duration.WHILE_SOURCE_IN_PLAY))

        assert not is_printed_action(game, ActivateAbility("farm", "granted"))
    finally:
        GRANTED_ABILITIES.pop("grant_probe", None)
