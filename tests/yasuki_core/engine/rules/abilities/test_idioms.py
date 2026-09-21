from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import bow_cost
from yasuki_core.engine.rules.abilities.idioms import PITCH, register_entry, register_ring
from yasuki_core.engine.rules.abilities.model import Ability, itself
from yasuki_core.engine.rules.abilities.registry import abilities_for
from yasuki_core.engine.rules.effects import GainHonor
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility, PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint, RingPrint

from tests.yasuki_core.engine.builders import put_in_play, register, stronghold, two_seat_game

P1 = PlayerId.P1
P2 = PlayerId.P2
KIND = "Probe"

# Probes registered for the process, the way test_costs.py registers its pausing cost. Their ids
# belong to no card, so nothing else in the suite offers them.
register_entry("entry_probe")
register_entry("entry_probe_refused", condition=lambda game, source: False)
register_entry("entry_probe_clearing", clears=KIND)
register_entry(
    "entry_probe_gaining",
    timing=(ActionTiming.OPEN, ActionTiming.DYNASTY),
    extra_effects=lambda game, source: [GainHonor(source.owner, 2)],
)
register_entry("entry_probe_labeled", label="Custom")

RING_ABILITY = Ability(
    timings=(ActionTiming.OPEN,),
    label="Open: bow: gain 1 Honor",
    cost=bow_cost,
    targets=itself,
    effects=lambda game, source, target: [GainHonor(source.owner, 1)],
    hits_every_target=True,
    key="gain",
)
register_ring("ring_probe", ability=RING_ABILITY, pitch=True)
register_ring("ring_probe_unpitched", ability=RING_ABILITY, pitch=False)


def _probe(
    card_id: str, printed_id: str, owner: PlayerId = P1, *, keywords: tuple[str, ...] = ()
) -> L5RCard:
    return L5RCard.of(
        ActionPrint,
        id=card_id,
        name=printed_id,
        printed_id=printed_id,
        side=Side.FATE,
        owner=owner,
        gold_cost=0,
        keywords=keywords,
    )


def _game(held: L5RCard, *in_play: L5RCard) -> EngineSession:
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1)))
    for card in in_play:
        put_in_play(state, register(state, card))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, held))
    return EngineSession.start(state, P1)


def _enter(session: EngineSession, card_id: str, key: str | None = None) -> None:
    session.act(P1, PlayStrategy(card_id, key))
    while session.game.pending is not None:
        session.submit(P1, DecisionResponse(()))


def _in_play(session: EngineSession) -> set[str]:
    return {card.id for card in session.game.table.battlefield.cards}


def _discarded(session: EngineSession, seat: PlayerId) -> set[str]:
    return {
        card.id for card in session.game.table.zones[ZoneKey(seat, ZoneRole.FATE_DISCARD)].cards
    }


def test_an_entry_is_offered_from_hand_and_leaves_the_card_in_play():
    session = _game(_probe("held", "entry_probe"))
    assert PlayStrategy("held") in session.legal_actions(P1)

    _enter(session, "held")

    assert "held" in _in_play(session)
    assert "held" not in _discarded(session, P1)


def test_an_entry_whose_condition_fails_is_withheld():
    session = _game(_probe("held", "entry_probe_refused"))

    assert PlayStrategy("held") not in session.legal_actions(P1)


def test_clearing_discards_the_owners_other_cards_of_that_kind_only():
    session = _game(
        _probe("held", "entry_probe_clearing", keywords=(KIND,)),
        _probe("mine", "entry_probe", keywords=(KIND,)),
        _probe("plain", "entry_probe"),
        _probe("theirs", "entry_probe", P2, keywords=(KIND,)),
    )

    _enter(session, "held")

    assert _in_play(session) >= {"held", "plain", "theirs"}
    assert _discarded(session, P1) == {"mine"}


def test_extra_effects_resolve_after_the_card_enters():
    session = _game(_probe("held", "entry_probe_gaining"))

    _enter(session, "held")

    assert "held" in _in_play(session)
    assert session.game.table.seats[P1].honor == 2


def test_the_label_names_the_designators_and_the_kind_cleared_unless_given():
    game = two_seat_game()
    probes = [
        _probe("gaining", "entry_probe_gaining"),
        _probe("clearing", "entry_probe_clearing"),
        _probe("labeled", "entry_probe_labeled"),
    ]

    labels = [ability.label for probe in probes for ability in abilities_for(game, probe)]

    assert labels == [
        "Open/Dynasty: Put this card into play",
        "Open: Put this Probe into play",
        "Custom",
    ]


def _ring(card_id: str, printed_id: str) -> L5RCard:
    return L5RCard.of(
        RingPrint, id=card_id, name=printed_id, printed_id=printed_id, side=Side.FATE, owner=P1
    )


def test_a_rings_ability_in_play_bows_it():
    session = _game(_probe("held", "entry_probe"), _ring("ring", "ring_probe"))

    session.act(P1, ActivateAbility("ring", "gain"))
    while session.game.pending is not None:
        session.submit(P1, DecisionResponse(()))

    assert session.game.table.cards_by_id["ring"].bowed
    assert session.game.table.seats[P1].honor == 1


def test_a_pitched_ring_resolves_from_hand_and_is_discarded():
    session = _game(_ring("ring", "ring_probe"))
    assert PlayStrategy("ring", PITCH) in session.legal_actions(P1)

    _enter(session, "ring", PITCH)

    assert "ring" in _discarded(session, P1)
    assert "ring" not in _in_play(session)
    assert session.game.table.seats[P1].honor == 1


def test_a_ring_without_a_pitch_cannot_be_played_from_hand():
    session = _game(_ring("ring", "ring_probe_unpitched"))

    assert not any(
        action.card_id == "ring"
        for action in session.legal_actions(P1)
        if isinstance(action, PlayStrategy)
    )
