import pytest

from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.abilities import (
    _ABILITIES,
    Ability,
    itself,
    no_cost,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming, ActivateAbility, DynastyDiscard, Pass
from yasuki_core.engine.rules.effects import Discard
from yasuki_core.engine.rules.events import CardDiscarded
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_core.engine.builders import (
    fate_card,
    holding,
    province_card,
    put_in_play,
    register,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2
PROBE = "fate_discard_probe"


@pytest.fixture(autouse=True)
def _clear_probe_registration():
    """The ability registry is module-global, so a probe left behind would follow later tests."""
    yield
    _ABILITIES.pop(PROBE, None)


def _discard_from_hand(game, source, target):
    """Discard the first Fate card its controller holds."""
    hand = game.table.zones[ZoneKey(source.owner, ZoneRole.HAND)]
    return [Discard(hand.cards[0].id, source.owner)] if hand.cards else []


def _register_probe() -> None:
    """Register an Open action that discards a Fate card from its controller's hand.

    Nothing shipped discards a Fate card, and the Caravansary answers only an action that did, so
    the action it answers is built here rather than borrowed from a real card.
    """
    register_ability(
        PROBE,
        Ability(
            timing=ActionTiming.OPEN,
            label="Open: discard a card from hand",
            cost=no_cost,
            targets=itself,
            effects=_discard_from_hand,
            all_targets=True,
        ),
    )


def _hand_a_fate_card(table, seat, card_id):
    register(table, fate_card(card_id, seat))
    table.zones[ZoneKey(seat, ZoneRole.HAND)].add(table.cards_by_id[card_id])


# --- Caravansary ---


def _caravansary_game(*, wealth=0, discarder=P1, in_hand=1):
    """The Caravansary in play, beside ``discarder``\'s probe and the Fate card it will discard."""
    game = two_seat_game()
    caravansary = put_in_play(
        game,
        holding("caravansary", printed_id="caravansary", name="Caravansary", gold_production=2),
    )
    if wealth:
        caravansary.adjust_counter("wealth", wealth)
    put_in_play(game, holding("probe", printed_id=PROBE, owner=discarder, name="Probe"))
    for index in range(in_hand):
        _hand_a_fate_card(game.table, discarder, f"spare-fate-{index}")
    _register_probe()
    return EngineSession.start(game.table, P1)


def _step_is_open(session) -> bool:
    return bool(session.game.round_stack)


def test_the_caravansary_is_offered_after_your_action_discards_a_fate_card():
    session = _caravansary_game()

    session.act(P1, ActivateAbility("probe"))

    assert _step_is_open(session)
    assert ActivateAbility("caravansary") in session.legal_actions(P1)


def test_taking_the_response_banks_a_wealth_token():
    session = _caravansary_game()
    session.act(P1, ActivateAbility("probe"))

    session.act(P1, ActivateAbility("caravansary"))

    assert session.game.table.cards_by_id["caravansary"].counters == {"wealth": 1}


def test_passing_the_response_leaves_the_token_unclaimed():
    """A Response is an action: declining the Step is declining the token."""
    session = _caravansary_game()
    session.act(P1, ActivateAbility("probe"))

    session.act(P1, Pass())

    assert session.game.table.cards_by_id["caravansary"].counters == {}


def test_the_response_answers_one_discard_once():
    """Nothing else rations it — it costs no bow — so the Step itself does."""
    session = _caravansary_game()
    session.act(P1, ActivateAbility("probe"))

    session.act(P1, ActivateAbility("caravansary"))

    assert ActivateAbility("caravansary") not in session.legal_actions(P1)


def test_a_later_step_offers_the_response_again():
    """The once-a-Step limit is scoped to the Step, so a second discarding action offers the card
    again rather than spending it for the rest of the turn."""
    session = _caravansary_game(in_hand=2)
    session.act(P1, ActivateAbility("probe"))
    session.act(P1, ActivateAbility("caravansary"))
    session.act(P2, Pass())
    session.act(P1, Pass())  # both pass, so the Step closes
    session.act(P2, Pass())  # priority back around to P1

    session.act(P1, ActivateAbility("probe"))

    assert _step_is_open(session)
    assert ActivateAbility("caravansary") in session.legal_actions(P1)


def test_an_opponents_discard_offers_you_nothing():
    """ "If the action was yours" — the Caravansary reads whose action it was, not merely that a Fate
    card reached a pile."""
    session = _caravansary_game(discarder=P2)

    session.act(P1, Pass())
    session.act(P2, ActivateAbility("probe"))

    assert not _step_is_open(session)


def test_a_dynasty_discard_offers_nothing():
    game = two_seat_game()
    put_in_play(
        game,
        holding("caravansary", printed_id="caravansary", name="Caravansary", gold_production=2),
    )
    province_card(game, "spare-dynasty", seat=P1, name="Spare")
    session = EngineSession.start(game.table, P1)
    flow.advance(session.game)  # Action -> Battle
    flow.advance(session.game)  # Battle -> Dynasty, where a Province card may be discarded

    session.act(P1, DynastyDiscard("spare-dynasty"))

    assert not _step_is_open(session)


def test_a_discard_no_player_made_offers_nothing():
    """Trimming to the maximum hand size is a step of the turn rather than an action (CR, Drawing
    and Discarding Fate Cards), so "if the action was yours" has no action to claim — and turn
    structure opens no Response Step at all."""
    session = _caravansary_game()
    game = session.game

    flow._apply_discard(game, P1, ("spare-fate-0",))

    assert game.action_events[-1] == CardDiscarded(
        "spare-fate-0", Side.FATE, Rulebook.MAXIMUM_HAND_SIZE, from_hand_or_deck=True
    )
    assert not _step_is_open(session)


def test_a_caravansary_already_at_three_is_not_offered():
    session = _caravansary_game(wealth=3)

    session.act(P1, ActivateAbility("probe"))

    assert not _step_is_open(session)
