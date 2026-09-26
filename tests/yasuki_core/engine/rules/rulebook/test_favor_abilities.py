from dataclasses import replace

import pytest

from yasuki_core import ruleset
from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.abilities.costs import payable
from yasuki_core.engine.rules.abilities.registry import abilities_for, ability_for
from yasuki_core.engine.rules.rulebook.lobby import is_lobby
from yasuki_core.engine.rules.battle.records import AttackPhase, BattlefieldInfo
from yasuki_core.engine.rules.effects import GainHonor, TakeFavor
from yasuki_core.engine.rules.rulebook import proxies
from yasuki_core.engine.rules.rulebook.favor_abilities import is_favor_ability
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn import action_sequence
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.triggers import resolve_action_effects
from yasuki_core.engine.rules.turn.sequence import run_stack
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    DeclareAttack,
    Pass,
    PlayInterrupt,
)
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.table import (
    DeckKey,
    Location,
    TableState,
    ZoneKey,
    ZoneRole,
    location_of,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import (
    IMPERIAL_FAVOR_ID,
    ONYX_FAVOR_PROXY_ID,
    PRE_GOLD_FAVOR_PROXY_ID,
    Side,
)
from yasuki_core.game_pieces.prints import RulebookPrint

from tests.yasuki_core.engine.builders import (
    combat_segment,
    fate_card,
    personality,
    put_in_play,
    register,
    wind,
)

P1 = PlayerId.P1
P2 = PlayerId.P2

# The arcs dealing the datasheet's Favor proxy. Shattered Empire inherits it from Onyx.
datasheet_arcs = pytest.mark.parametrize(
    "arc",
    [ruleset.ONYX, ruleset.SHATTERED_EMPIRE],
    ids=["onyx", "shattered_empire"],
)
pre_gold_arc = pytest.mark.parametrize("arc", [ruleset.IMPERIAL], ids=["imperial"])


@pytest.fixture
def arc() -> ruleset.Ruleset:
    return ruleset.SHATTERED_EMPIRE


@pytest.fixture
def game(arc, monkeypatch) -> GameState:
    monkeypatch.setattr(ruleset, "ACTIVE", arc)
    game = GameState.start(TableState.empty_two_seat(), P1, seed=0)
    game.table.creatable_tokens[IMPERIAL_FAVOR_ID] = RulebookPrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    proxies.spawn_rulebook_proxies(game)
    return game


def _proxy(game: GameState, seat: PlayerId = P1) -> L5RCard:
    zone = game.table.zones[ZoneKey(seat, ZoneRole.RULEBOOK)]
    return next(
        card
        for card in zone.cards
        if card.printed_id in (ONYX_FAVOR_PROXY_ID, PRE_GOLD_FAVOR_PROXY_ID)
    )


def _favor(game: GameState, key: str, seat: PlayerId = P1) -> ActivateAbility:
    return ActivateAbility(_proxy(game, seat).id, key)


def _hand(game: GameState, seat: PlayerId = P1):
    return game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards


def _add_to_hand(game: GameState, *card_ids: str, seat: PlayerId = P1) -> None:
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    for card_id in card_ids:
        hand.add(register(game.table, fate_card(card_id, seat)))


def _payable(game: GameState, key: str, seat: PlayerId = P1) -> bool:
    proxy = _proxy(game, seat)
    ability = ability_for(game, proxy, key)
    assert ability is not None
    return payable(game, ability.cost(game, proxy))


def _priority_back_to(game: GameState, seat: PlayerId) -> None:
    while game.round.priority is not seat:
        action_sequence.perform(game, Pass())


def _offered(game: GameState, seat: PlayerId = P1) -> set[str | None]:
    return {
        action.ability_key
        for action in legality.legal_actions(game, seat)
        if is_favor_ability(action)
    }


@pytest.mark.parametrize(
    ("arc", "proxy_id", "keys"),
    [
        (ruleset.ONYX, ONYX_FAVOR_PROXY_ID, ["discard_to_draw", "send_attacker_home"]),
        (ruleset.SHATTERED_EMPIRE, ONYX_FAVOR_PROXY_ID, ["discard_to_draw", "send_attacker_home"]),
        # prevent_honor_loss needs honor-loss prevention, which the engine does not model.
        (ruleset.IMPERIAL, PRE_GOLD_FAVOR_PROXY_ID, ["draw", "restore_honor", "send_unit_home"]),
    ],
    ids=["onyx", "shattered_empire", "imperial"],
)
def test_the_arc_decides_which_favor_proxy_is_dealt(game, proxy_id, keys):
    proxy = _proxy(game)

    assert proxy.printed_id == proxy_id
    assert [ability.key for ability in abilities_for(game, proxy)] == keys


@pre_gold_arc
def test_a_cards_own_ability_under_a_favor_key_is_no_favor_ability(game):
    # Divination Bowl prints an ability keyed "draw", as the pre-Gold Favor draw is.
    assert is_favor_ability(_favor(game, "draw"))
    assert not is_favor_ability(ActivateAbility("P1-bowl", "draw"))


@pytest.mark.parametrize(
    ("arc", "key", "designator"),
    [
        (ruleset.SHATTERED_EMPIRE, "discard_to_draw", ActionTiming.OPEN),
        (ruleset.IMPERIAL, "draw", ActionTiming.LIMITED),
    ],
    ids=["shattered_empire", "imperial"],
)
def test_the_shared_draw_ability_is_designated_differently_by_arc(game, key, designator):
    # Pre-Gold the draw is a Limited, and ShE makes it an Open restricted to your own turn.
    assert legality.timings_of(game, _favor(game, key)) == {designator}


@pytest.mark.parametrize(
    "arc",
    [ruleset.ONYX, ruleset.SHATTERED_EMPIRE, ruleset.IMPERIAL],
    ids=["onyx", "shattered_empire", "imperial"],
)
def test_every_favor_ability_is_political(game):
    # ShE datasheet: "Political Open, (Favor)" and "Political Battle, (Favor)". The pre-Gold
    # glossary makes "using the Imperial Favor" a Political action.
    proxy = _proxy(game)

    assert {ability.keywords for ability in abilities_for(game, proxy)} == {
        frozenset({keywords.POLITICAL})
    }


@pytest.mark.parametrize(
    ("arc", "key"),
    [(ruleset.ONYX, "discard_to_draw"), (ruleset.IMPERIAL, "draw")],
    ids=["onyx", "imperial"],
)
def test_swapping_the_arc_swaps_which_abilities_are_offered(game, key):
    # Changing the active ruleset is the whole switch: no engine code names an arc.
    TakeFavor(P1).perform(game)
    _add_to_hand(game, "spare")

    assert _offered(game) == {key}


@pre_gold_arc
def test_restore_honor_is_offered_with_any_players_dishonorable_personality(game):
    TakeFavor(P1).perform(game)
    put_in_play(game, personality("P1-p"))
    rival = put_in_play(game, personality("P2-p", owner=P2))

    assert "restore_honor" not in _offered(game)

    rival.dishonor()
    assert "restore_honor" in _offered(game)


@pre_gold_arc
def test_restore_honor_rehonors_the_chosen_personality(game):
    TakeFavor(P1).perform(game)
    hero = put_in_play(game, personality("P1-p"))
    hero.dishonor()

    action_sequence.perform(game, _favor(game, "restore_honor"))
    submit(game, DecisionResponse((hero.id,)))
    run_stack(game)

    assert not hero.dishonorable
    assert game.favor_holder is None


@pytest.mark.parametrize(
    "arc",
    [ruleset.ONYX, ruleset.SHATTERED_EMPIRE, ruleset.IMPERIAL],
    ids=["onyx", "shattered_empire", "imperial"],
)
def test_a_favor_ability_is_not_offered_without_a_way_to_pay(game):
    # Good Faith: no Favor and no payer means the ability is never announceable.
    _add_to_hand(game, "spare")

    assert _offered(game) == set()


@pre_gold_arc
def test_the_imperial_draw_costs_only_the_favor(game):
    # Pre-Gold: "Limited: Draw a Fate card." Nothing is discarded alongside it.
    game.table.decks[DeckKey(P1, Side.FATE)].add_to_top(
        [register(game.table, fate_card("drawn", P1))]
    )
    TakeFavor(P1).perform(game)

    action_sequence.perform(game, _favor(game, "draw"))
    run_stack(game)

    assert game.favor_holder is None, "the Favor was given up"
    assert [card.id for card in _hand(game)] == ["drawn"], "and nothing was discarded for it"


@datasheet_arcs
def test_the_datasheet_draw_discards_a_fate_card_as_well(game):
    # ShE datasheet: "discard a Fate card to draw a card", on top of the Favor in the cost block.
    # Two, so the discard is a genuine choice the seat is asked rather than a foregone one.
    _add_to_hand(game, "spare", "keeper")
    game.table.decks[DeckKey(P1, Side.FATE)].add_to_top(
        [register(game.table, fate_card("drawn", P1))]
    )
    TakeFavor(P1).perform(game)

    action_sequence.perform(game, _favor(game, "discard_to_draw"))
    submit(game, DecisionResponse(choices=("spare",)))

    assert game.favor_holder is None
    held = [card.id for card in _hand(game)]
    assert "spare" not in held, "the Fate card it asked for was discarded"
    assert "drawn" in held, "and one was drawn for it"


def _at_battle(game: GameState, *, attacker_ids=(), defender_ids=()) -> None:
    """Put a battle in progress at battlefield 0, with each named Personality standing in it."""
    game.attack = AttackPhase(
        attacker=P1,
        defender=P2,
        battlefields=(BattlefieldInfo(province=ZoneKey(P2, ZoneRole.PROVINCE, 0)),),
        current=0,
    )
    for owner, ids in ((P1, attacker_ids), (P2, defender_ids)):
        for card_id in ids:
            card = put_in_play(game, personality(card_id, owner=owner))
            ops.set_location(game.table, card, Location.at_battlefield(0))


@datasheet_arcs
def test_the_datasheet_battle_ability_sends_an_attacker_home(game):
    # ShE datasheet: "Political Battle, (Favor): Move a target attacking enemy Personality home".
    _at_battle(game, attacker_ids=("raider",))
    TakeFavor(P2).perform(game)
    # The Defender is the seat with a reason to use it, so it is the one holding priority here.
    game.round = replace(game.round, priority=P2)

    action_sequence.perform(game, _favor(game, "send_attacker_home", seat=P2))
    submit(game, DecisionResponse(choices=("raider",)))

    assert location_of(game.table, game.table.cards_by_id["raider"]).is_home
    assert game.table.cards_by_id["raider"].bowed is False, "the datasheet ability does not bow"


@datasheet_arcs
def test_the_datasheet_battle_ability_will_not_send_a_defender_home(game):
    # It names an *attacking* enemy Personality, so the Attacker cannot use it to clear the
    # Defender's army off its own Province.
    _at_battle(game, defender_ids=("guard",))
    TakeFavor(P1).perform(game)

    assert not _payable(game, "send_attacker_home")


@pre_gold_arc
def test_the_imperial_battle_ability_sends_an_enemy_home_bowed(game):
    # Pre-Gold: "Battle: Send a unit home from a battle, bowed." A defender as well as an attacker,
    # and it bows.
    _at_battle(game, defender_ids=("guard",))
    TakeFavor(P1).perform(game)

    action_sequence.perform(game, _favor(game, "send_unit_home"))
    submit(game, DecisionResponse(choices=("guard",)))

    assert location_of(game.table, game.table.cards_by_id["guard"]).is_home
    assert game.table.cards_by_id["guard"].bowed is True, "the pre-Gold ability bows it"


@pytest.mark.parametrize(
    ("arc", "key"),
    [
        (ruleset.ONYX, "send_attacker_home"),
        (ruleset.SHATTERED_EMPIRE, "send_attacker_home"),
        (ruleset.IMPERIAL, "send_unit_home"),
    ],
    ids=["onyx", "shattered_empire", "imperial"],
)
def test_a_battle_ability_offers_nothing_outside_a_battle(game, key):
    # A Battle designator opens in a battle, and with no battle there is nobody to send home.
    TakeFavor(P1).perform(game)

    assert not _payable(game, key)


@datasheet_arcs
def test_the_datasheet_draw_is_withheld_with_no_fate_card_to_discard(game):
    # Its cost is the Favor *and* a discarded Fate card, so holding the Favor alone does not make it
    # announceable. Taking it then would spend the Favor for nothing.
    TakeFavor(P1).perform(game)
    assert [card.printed_id for card in _hand(game)] == [IMPERIAL_FAVOR_ID], "only the Favor"

    assert not _payable(game, "discard_to_draw")
    assert _offered(game) == set()


@datasheet_arcs
def test_the_datasheet_draw_is_not_offered_on_another_seats_turn(game):
    # ShE datasheet: "If it is your turn". An Open designator does not restrict to the active seat
    # on its own, so the rulebook's own condition is what withholds it from the rival.
    _add_to_hand(game, "spare", seat=P2)
    TakeFavor(P2).perform(game)
    game.round = replace(game.round, priority=P2)
    assert legality.permits(game, P2, ActionTiming.OPEN), "the round permits the rival"

    assert _offered(game, P2) == set()


@pre_gold_arc
def test_the_imperial_draw_is_not_limited_to_the_active_seat(game):
    # The pre-Gold draw carries no "If it is your turn", so only its Limited designator gates it:
    # the rival's proxy is a target on another seat's turn.
    rivals = _proxy(game, P2)
    draw = ability_for(game, rivals, "draw")

    assert draw is not None
    assert draw.targets(game, rivals) == [rivals.id]


@pytest.mark.parametrize(
    ("arc", "key"),
    [
        (ruleset.ONYX, "discard_to_draw"),
        (ruleset.SHATTERED_EMPIRE, "discard_to_draw"),
        (ruleset.IMPERIAL, "draw"),
    ],
    ids=["onyx", "shattered_empire", "imperial"],
)
def test_a_wind_bars_the_rulebook_favor_abilities(game, key):
    # ShE datasheet, Winds: "While you have a Wind in play, you may not take rulebook Favor
    # actions." The seat otherwise qualifies outright, so the Wind is the only thing withholding it.
    _add_to_hand(game, "spare")
    TakeFavor(P1).perform(game)
    assert _offered(game) == {key}, "it is on offer before the Wind arrives"

    put_in_play(game, wind(P1))

    assert _offered(game) == set()


@datasheet_arcs
def test_a_rivals_wind_does_not_bar_your_own_favor_abilities(game):
    # 'you have a Wind in play': it is the acting seat's own Wind that stops them.
    _add_to_hand(game, "spare")
    TakeFavor(P1).perform(game)
    put_in_play(game, wind(P2))

    assert _offered(game) == {"discard_to_draw"}


def test_a_wind_does_not_bar_lobbying(game):
    # The bar names rulebook Favor actions. Lobby is the rulebook's own ability for taking the Favor
    # rather than one that pays it, and the datasheet lists it under its own heading.
    game.table.seats[P1].honor = 10
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, wind(P1))

    assert any(is_lobby(action) for action in legality.legal_actions(game, P1))


@datasheet_arcs
def test_a_favor_ability_is_once_per_turn_per_player(game):
    # CR, Using Abilities 0.3: player abilities may only be taken once per turn per player.
    TakeFavor(P1).perform(game)
    _add_to_hand(game, "first", "second")
    action_sequence.perform(game, _favor(game, "discard_to_draw"))
    submit(game, DecisionResponse(choices=("first",)))
    _priority_back_to(game, P1)
    TakeFavor(P1).perform(game)

    assert "discard_to_draw" not in _offered(game)


@pre_gold_arc
def test_the_pre_gold_arc_lets_a_favor_ability_repeat(game):
    TakeFavor(P1).perform(game)
    action_sequence.perform(game, _favor(game, "draw"))
    _priority_back_to(game, P1)
    TakeFavor(P1).perform(game)

    assert "draw" in _offered(game)


def test_the_imperial_battle_ability_is_offered_to_a_seat_with_no_units_there(monkeypatch):
    # Pre-Gold: "You can do this in a battle in which you have no units."
    monkeypatch.setattr(ruleset, "ACTIVE", ruleset.IMPERIAL)
    session = combat_segment([personality("raider")], attackers={"raider": 0}, defenders={})
    game = session.game
    TakeFavor(P2).perform(game)
    game.round = replace(game.round, priority=P2)

    assert "send_unit_home" in _offered(game, P2)


@pre_gold_arc
def test_the_imperial_favor_prevents_another_players_honor_loss(game):
    # Pre-Gold: "Political Reaction: Prevent a Family Honor loss." Any player's loss, not only the
    # holder's (Accumulated Rulings, Imperial Favor).
    TakeFavor(P1).perform(game)
    honor = game.table.seats[P2].honor
    game.action = DeclareAttack()
    resolve_action_effects(game, [GainHonor(P2, -3)])
    game.round = replace(game.round, priority=P1)
    prevent = PlayInterrupt(_proxy(game).id)
    assert prevent in legality.legal_actions(game, P1)

    action_sequence.perform(game, prevent)
    while game.round.kind is RoundKind.INTERRUPT:
        action_sequence.perform(game, Pass())
    run_stack(game)

    assert game.table.seats[P2].honor == honor
    assert game.favor_holder is None
    assert not game.action_is_favor, "the Interrupt's Favor payment is not the attack's"


@pre_gold_arc
def test_the_imperial_favor_does_not_answer_an_honor_gain(game):
    TakeFavor(P1).perform(game)
    game.action = DeclareAttack()
    resolve_action_effects(game, [GainHonor(P2, 3)])

    assert game.round.kind is not RoundKind.INTERRUPT


@pre_gold_arc
def test_no_seat_can_prevent_a_loss_while_nobody_holds_the_favor(game):
    game.action = DeclareAttack()
    resolve_action_effects(game, [GainHonor(P2, -3)])

    assert game.round.kind is not RoundKind.INTERRUPT
