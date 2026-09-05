from dataclasses import replace

import pytest

from yasuki_core import ruleset
from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import favor_abilities, legality
from yasuki_core.engine.rules.actions import ActionTiming, Lobby, UseFavorAbility
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.effects import TakeFavor
from yasuki_core.engine.rules.flow import submit, use_favor_ability
from yasuki_core.engine.rules.state import AttackPhase, BattlefieldInfo, GameState
from yasuki_core.engine.table import (
    DeckKey,
    Location,
    TableState,
    ZoneKey,
    ZoneRole,
    location_of,
)
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, Side
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import (
    fate_card,
    personality,
    put_in_play,
    register,
    wind,
)


@pytest.fixture
def game() -> GameState:
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=0)
    game.table.creatable_tokens[IMPERIAL_FAVOR_ID] = FatePrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    return game


@pytest.fixture
def imperial(monkeypatch):
    """Swap the arc for the pre-Gold rulebook, which granted four uses of the Favor."""
    monkeypatch.setattr(ruleset, "ACTIVE", ruleset.IMPERIAL)


def _hand(game: GameState, seat: PlayerId = PlayerId.P1):
    return game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards


def _payable(game: GameState, seat: PlayerId, key: str) -> bool:
    """Whether ``seat`` could pay everything the Favor ability named ``key`` charges."""
    cost = favor_abilities.favor_ability_cost(game, seat, key)
    return all(effect.is_payable(game) for effect in cost)


def _offered(game: GameState, seat: PlayerId = PlayerId.P1) -> set[str]:
    return {
        action.key
        for action in legality.legal_actions(game, seat)
        if isinstance(action, UseFavorAbility)
    }


def test_the_arc_decides_which_favor_abilities_exist():
    """The pre-Gold rulebook granted four uses; the Onyx/ShE datasheet grants two."""
    assert [a.key for a in ruleset.SHATTERED_EMPIRE.favor_abilities] == [
        "discard_to_draw",
        "send_attacker_home",
    ]
    assert [a.key for a in ruleset.IMPERIAL.favor_abilities] == [
        "draw",
        "restore_honor",
        "send_unit_home",
        "prevent_honor_loss",
    ]


def test_the_shared_draw_ability_is_designated_differently_by_arc():
    """The same use reads under a different designator per arc, which is the whole reason the
    designator is configuration: pre-Gold it is a Limited, and ShE makes it an Open restricted to
    your own turn."""
    she = {a.key: a for a in ruleset.SHATTERED_EMPIRE.favor_abilities}["discard_to_draw"]
    imperial = {a.key: a for a in ruleset.IMPERIAL.favor_abilities}["draw"]

    assert (she.timing, she.active_seat_only) == (ActionTiming.OPEN, True)
    assert (imperial.timing, imperial.active_seat_only) == (ActionTiming.LIMITED, False)


def test_swapping_the_arc_swaps_which_abilities_are_offered(game, imperial):
    """Changing the active ruleset is the whole switch: no engine code names an arc."""
    TakeFavor(PlayerId.P1).perform(game)
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(
        register(game.table, fate_card("spare", PlayerId.P1))
    )

    assert _offered(game) == {"draw"}


def test_the_shattered_empire_arc_offers_its_own_draw(game):
    TakeFavor(PlayerId.P1).perform(game)
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(
        register(game.table, fate_card("spare", PlayerId.P1))
    )

    assert _offered(game) == {"discard_to_draw"}


def test_an_ability_the_engine_cannot_perform_yet_is_not_offered(game, imperial):
    """``restore_honor`` and ``prevent_honor_loss`` need a Dishonored status and honor-loss
    prevention, neither of which the engine models, so the arc names them and they stay off."""
    TakeFavor(PlayerId.P1).perform(game)

    assert {a.key for a in favor_abilities.available_favor_abilities()} == {
        "draw",
        "send_unit_home",
    }


def test_a_favor_ability_is_not_offered_without_a_way_to_pay(game):
    """Good Faith: no Favor and no payer means the ability is never announceable."""
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(
        register(game.table, fate_card("spare", PlayerId.P1))
    )

    assert _offered(game) == set()


def test_the_imperial_draw_costs_only_the_favor(game, imperial):
    """Pre-Gold: "Limited: Draw a Fate card." Nothing is discarded alongside it."""
    game.table.decks[DeckKey(PlayerId.P1, Side.FATE)].add_to_top(
        [register(game.table, fate_card("drawn", PlayerId.P1))]
    )
    TakeFavor(PlayerId.P1).perform(game)

    use_favor_ability(game, "draw")

    assert game.favor_holder is None, "the Favor was given up"
    assert [card.id for card in _hand(game)] == ["drawn"], "and nothing was discarded for it"


def test_the_datasheet_draw_discards_a_fate_card_as_well(game):
    """ShE datasheet: "discard a Fate card to draw a card", on top of the Favor in the cost block."""
    hand = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    # Two, so the discard is a genuine choice the seat is asked rather than a foregone one.
    for card_id in ("spare", "keeper"):
        hand.add(register(game.table, fate_card(card_id, PlayerId.P1)))
    game.table.decks[DeckKey(PlayerId.P1, Side.FATE)].add_to_top(
        [register(game.table, fate_card("drawn", PlayerId.P1))]
    )
    TakeFavor(PlayerId.P1).perform(game)

    use_favor_ability(game, "discard_to_draw")
    submit(game, DecisionResponse(choices=("spare",)))

    assert game.favor_holder is None
    held = [card.id for card in _hand(game)]
    assert "spare" not in held, "the Fate card it asked for was discarded"
    assert "drawn" in held, "and one was drawn for it"


def _at_battle(game: GameState, *, attacker_ids=(), defender_ids=()) -> None:
    """Put a battle in progress at battlefield 0, with each named Personality standing in it."""
    game.attack = AttackPhase(
        attacker=PlayerId.P1,
        defender=PlayerId.P2,
        battlefields=(BattlefieldInfo(province=ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0)),),
        current=0,
    )
    for owner, ids in ((PlayerId.P1, attacker_ids), (PlayerId.P2, defender_ids)):
        for card_id in ids:
            card = put_in_play(game, personality(card_id, owner=owner))
            ops.set_location(game.table, card, Location.at_battlefield(0))


def test_the_datasheet_battle_ability_sends_an_attacker_home(game):
    """ShE datasheet: "Political Battle, (Favor): Move a target attacking enemy Personality home"."""
    _at_battle(game, attacker_ids=("raider",))
    TakeFavor(PlayerId.P2).perform(game)
    # The Defender is the seat with a reason to use it, so it is the one holding priority here.
    game.round = replace(game.round, priority=PlayerId.P2)

    use_favor_ability(game, "send_attacker_home")
    submit(game, DecisionResponse(choices=("raider",)))

    assert location_of(game.table, game.table.cards_by_id["raider"]).is_home
    assert game.table.cards_by_id["raider"].bowed is False, "the datasheet ability does not bow"


def test_the_datasheet_battle_ability_will_not_send_a_defender_home(game):
    """It names an *attacking* enemy Personality, so the Attacker cannot use it to clear the
    Defender's army off its own Province."""
    _at_battle(game, defender_ids=("guard",))
    TakeFavor(PlayerId.P1).perform(game)

    assert not _payable(game, PlayerId.P1, "send_attacker_home")


def test_the_imperial_battle_ability_sends_either_army_home_bowed(game, imperial):
    """Pre-Gold: "Battle: Send a unit home from a battle, bowed." Either side, and it bows."""
    _at_battle(game, defender_ids=("guard",))
    TakeFavor(PlayerId.P1).perform(game)

    use_favor_ability(game, "send_unit_home")
    submit(game, DecisionResponse(choices=("guard",)))

    assert location_of(game.table, game.table.cards_by_id["guard"]).is_home
    assert game.table.cards_by_id["guard"].bowed is True, "the pre-Gold ability bows it"


def test_a_battle_ability_offers_nothing_outside_a_battle(game):
    """A Battle designator opens in a battle, and with no battle there is nobody to send home."""
    TakeFavor(PlayerId.P1).perform(game)

    assert not _payable(game, PlayerId.P1, "send_attacker_home")


def test_the_datasheet_draw_is_withheld_with_no_fate_card_to_discard(game):
    """Its cost is the Favor *and* a discarded Fate card, so holding the Favor alone does not make
    it announceable -- taking it then would spend the Favor for nothing."""
    TakeFavor(PlayerId.P1).perform(game)
    assert [card.printed_id for card in _hand(game)] == [IMPERIAL_FAVOR_ID], "only the proxy"

    assert not _payable(game, PlayerId.P1, "discard_to_draw")
    assert _offered(game) == set()


def test_the_datasheet_draw_is_not_offered_on_another_seats_turn(game):
    """ShE datasheet: "If it is your turn". An Open designator does not restrict to the active seat
    on its own, so the rulebook's own condition is what withholds it from the rival."""
    hand = game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)]
    hand.add(register(game.table, fate_card("spare", PlayerId.P2)))
    TakeFavor(PlayerId.P2).perform(game)
    game.round = replace(game.round, priority=PlayerId.P2)
    assert legality.permits(game, PlayerId.P2, ActionTiming.OPEN), "the round permits the rival"

    assert _offered(game, PlayerId.P2) == set()


def test_the_imperial_draw_is_offered_to_whoever_the_round_permits(imperial, game):
    """The pre-Gold draw carries no such condition, so a Limited round is the only thing gating it
    -- which is the difference the ``active_seat_only`` flag exists to carry."""
    imperial_draw = {a.key: a for a in ruleset.IMPERIAL.favor_abilities}["draw"]

    assert imperial_draw.active_seat_only is False


def test_a_wind_bars_the_rulebook_favor_abilities(game):
    """ShE datasheet, Winds: "While you have a Wind in play, you may not take rulebook Favor
    actions." The seat otherwise qualifies outright, so the Wind is the only thing withholding it."""
    hand = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    hand.add(register(game.table, fate_card("spare", PlayerId.P1)))
    TakeFavor(PlayerId.P1).perform(game)
    assert _offered(game) == {"discard_to_draw"}, "it is on offer before the Wind arrives"

    put_in_play(game, wind(PlayerId.P1))

    assert _offered(game) == set()


def test_a_rivals_wind_does_not_bar_your_own_favor_abilities(game):
    """ "you have a Wind in play" — it is the acting seat's own Wind that stops them."""
    hand = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    hand.add(register(game.table, fate_card("spare", PlayerId.P1)))
    TakeFavor(PlayerId.P1).perform(game)
    put_in_play(game, wind(PlayerId.P2))

    assert _offered(game) == {"discard_to_draw"}


def test_a_wind_does_not_bar_lobbying(game):
    """The bar names rulebook Favor actions. Lobby is the rulebook's own ability for taking the
    Favor rather than one that pays it, and the datasheet lists it under its own heading."""
    game.table.seats[PlayerId.P1].honor = 10
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, wind(PlayerId.P1))

    assert Lobby() in legality.legal_actions(game, PlayerId.P1)
