from dataclasses import replace

import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId, Rulebook, Trait
from yasuki_core.engine.rules.abilities.costs import bow_cost
from yasuki_core.engine.rules.abilities.idioms import (
    PITCH,
    declarable_gold,
    register_entry,
    register_ring,
    register_trait_entry,
    register_yu,
    register_yu_widening,
    YuWidening,
)
from yasuki_core.engine.rules.abilities.model import Ability, itself
from yasuki_core.engine.rules.abilities.registry import printed_line_without_cost, abilities_for
from yasuki_core.engine.rules.abilities.costs import declare_amount, declared_gold_discount
from yasuki_core.engine.rules.effects import (
    Destroy,
    GainHonor,
    GrantNegation,
    PayGold,
    Simultaneously,
)
from yasuki_core.engine.rules.projection import project
from yasuki_core.engine.rules.triggers import fire, resolve_effects
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.turn.structure import END_OF_TURN
from yasuki_core.engine.rules.vocabulary.decisions import ChooseNextTrigger, Confirm
from yasuki_core.engine.rules.vocabulary.game_events import Destroying, FavorDiscarded
from yasuki_core.engine.rules.vocabulary.modifiers import Negation
from yasuki_core.ruleset import RingEntry
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility, PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint, FatePrint, RingPrint

from tests.yasuki_core.engine.builders import (
    combat_segment,
    holding,
    personality,
    put_in_play,
    register,
    sensei,
    stronghold,
    two_seat_game,
)
from tests.yasuki_core.engine.rules.conftest import probe_ability

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
register_ring("ring_probe", ability=RING_ABILITY, pitch=printed_line_without_cost)
register_ring("ring_probe_unpitched", ability=RING_ABILITY, pitch=None)
register_trait_entry(
    "trait_entry_probe", FavorDiscarded, lambda ctx: ctx.event.seat is ctx.card.owner
)


def _probe(
    card_id: str, printed_id: str, owner: PlayerId = P1, *, keywords: tuple[str, ...] = ()
) -> L5RCard:
    return L5RCard.of(
        ActionPrint,
        id=card_id,
        name=printed_id,
        printed_id=card_id if printed_id is None else printed_id,
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


def test_the_entry_shows_its_printed_ability_unless_a_label_is_given():
    game = two_seat_game()
    probes = [
        _probe("gaining", "entry_probe_gaining"),
        _probe("clearing", "entry_probe_clearing"),
        _probe("labeled", "entry_probe_labeled"),
    ]

    labels = [ability.label for probe in probes for ability in abilities_for(game, probe)]

    assert labels == [None, None, "Custom"]


def _ring(card_id: str, printed_id: str) -> L5RCard:
    return L5RCard.of(
        RingPrint,
        id=card_id,
        name=printed_id,
        printed_id=card_id if printed_id is None else printed_id,
        side=Side.FATE,
        owner=P1,
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


def _trait_probe_game():
    game = two_seat_game()
    held = L5RCard.of(
        FatePrint, id="held", name="Probe", printed_id="trait_entry_probe", side=Side.FATE, owner=P1
    )
    game.table.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(game.table, held))
    return game


def test_a_trait_entry_asks_its_owner_alone_when_the_guard_holds():
    game = _trait_probe_game()

    fire(game, FavorDiscarded(P1))

    assert isinstance(game.pending, Confirm) and game.pending.seat is P1
    assert project(game, P2).pending is None


def test_a_trait_entry_stays_quiet_when_the_guard_fails():
    game = _trait_probe_game()

    fire(game, FavorDiscarded(P2))

    assert game.pending is None


def test_declining_a_trait_entry_leaves_the_card_in_hand_for_the_next_time():
    game = _trait_probe_game()
    fire(game, FavorDiscarded(P1))

    submit(game, DecisionResponse(()))
    assert "held" in {card.id for card in game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards}

    fire(game, FavorDiscarded(P1))
    assert isinstance(game.pending, Confirm)
    submit(game, DecisionResponse(("held",)))

    assert "held" in {card.id for card in game.table.battlefield.cards}


def test_a_ruleset_reading_the_trait_as_an_action_is_refused(monkeypatch):
    monkeypatch.setattr(ruleset, "ACTIVE", replace(ruleset.ACTIVE, ring_entry=RingEntry.AS_ACTION))
    game = _trait_probe_game()

    with pytest.raises(NotImplementedError, match="AS_ACTION"):
        fire(game, FavorDiscarded(P1))


def _variable_cost_game(ability_keywords, fixed_gold):
    """P1 with 5 Gold, Mishime Sensei's discount, and a probe ability costing ``fixed_gold`` plus an
    X offered up to what the seat can declare."""
    game = two_seat_game()
    put_in_play(game, stronghold(P1, gold_production=5))
    put_in_play(game, sensei(P1, printed_id="mishime_sensei", keywords=("Shadowlands",)))
    source = put_in_play(game, holding("source", printed_id="variable_probe"))
    ability = Ability(
        timings=(ActionTiming.OPEN,),
        cost=lambda game, source: [
            *([PayGold(source.owner, fixed_gold, "probe")] if fixed_gold else []),
            declare_amount(source, tuple(range(declarable_gold(game, source) + 1)), "How much?"),
        ],
        targets=itself,
        effects=lambda game, source, target: [],
        keywords=ability_keywords,
    )
    return game, source, ability


@pytest.mark.parametrize(
    ("ability_keywords", "discount", "most"),
    [(frozenset({"Maho"}), 2, 7), (frozenset({"maho"}), 2, 7), (frozenset(), 0, 5)],
    ids=["maho ability", "maho spelled in lowercase", "plain ability"],
)
def test_a_variable_cost_reads_the_keywords_printed_on_its_ability(
    ability_keywords, discount, most
):
    game, source, ability = _variable_cost_game(ability_keywords, fixed_gold=0)

    with probe_ability("variable_probe", ability):
        (asked,) = ability.discounted_cost(game, source, plays_card=False)

    assert declared_gold_discount(asked) == discount
    assert max(asked.amounts) == most


def test_fixed_gold_spends_the_discount_before_a_variable_amount_in_the_same_cost():
    game, source, ability = _variable_cost_game(frozenset({"Maho"}), fixed_gold=2)

    with probe_ability("variable_probe", ability):
        (asked,) = ability.discounted_cost(game, source, plays_card=False)

    assert declared_gold_discount(asked) == 0
    assert max(asked.amounts) == 5


def _standing(game, card_id):
    return any(card.id == card_id for card in game.table.battlefield.cards)


# A test-only Yu: its controller gains 1 Honor, and only while the card still stands.
register_yu(
    "yu_probe",
    lambda ctx: [GainHonor(ctx.card.owner, 1)] if _standing(ctx.game, ctx.card.id) else [],
)


def _in_combat():
    units = [
        personality("attacker"),
        personality("defender", owner=PlayerId.P2),
        personality("yu", owner=PlayerId.P2, printed_id="yu_probe"),
    ]
    return combat_segment(units, {"attacker": 0}, {"defender": 0, "yu": 0}).game


def test_a_yu_resolves_before_battle_resolution_destroys_its_card():
    game = two_seat_game()
    put_in_play(game, personality("yu", printed_id="yu_probe"))

    resolve_effects(game, [Destroy("yu", Rulebook.BATTLE_RESOLUTION)])

    assert game.table.seats[PlayerId.P1].honor == 1
    assert not _standing(game, "yu")


def test_a_yu_resolves_before_another_players_battle_action_destroys_its_card():
    game = _in_combat()
    honor = game.table.seats[PlayerId.P2].honor

    resolve_effects(game, [Destroy("yu", PlayerId.P1)])

    assert game.table.seats[PlayerId.P2].honor == honor + 1


def _own_action_in_battle():
    return _in_combat(), PlayerId.P2


def _a_trait_in_battle():
    return _in_combat(), Trait("attacker")


def _another_players_action_outside_battle():
    game = two_seat_game()
    put_in_play(game, personality("yu", owner=PlayerId.P2, printed_id="yu_probe"))
    return game, PlayerId.P1


@pytest.mark.parametrize(
    "board",
    [_own_action_in_battle, _a_trait_in_battle, _another_players_action_outside_battle],
    ids=["own-action", "trait", "outside-battle"],
)
def test_no_yu_resolves_for_a_destruction_the_trait_does_not_name(board):
    game, cause = board()
    honor = game.table.seats[PlayerId.P2].honor

    resolve_effects(game, [Destroy("yu", cause)])

    assert game.table.seats[PlayerId.P2].honor == honor
    assert not _standing(game, "yu")


# Test-only widenings: the controller's own action resolves their cards' Yu, outright or by choice.
def _covers_your_cards(game, source, card):
    return card.owner is source.owner


register_yu_widening("widening_probe", YuWidening(covers=_covers_your_cards, chosen=False))
register_yu_widening("chosen_widening_probe", YuWidening(covers=_covers_your_cards, chosen=True))
register_yu("empty_yu_probe", lambda ctx: [])


def test_an_outright_widening_resolves_the_yu_beside_a_chosen_one():
    game = _in_combat()
    put_in_play(game, personality("outright", owner=PlayerId.P2, printed_id="widening_probe"))
    put_in_play(game, personality("chosen", owner=PlayerId.P2, printed_id="chosen_widening_probe"))
    honor = game.table.seats[PlayerId.P2].honor

    resolve_effects(game, [Destroy("yu", PlayerId.P2)])

    assert game.pending is None
    assert game.table.seats[PlayerId.P2].honor == honor + 1


def _chosen_widening_negated():
    game = _in_combat()
    put_in_play(game, personality("chosen", owner=PlayerId.P2, printed_id="chosen_widening_probe"))
    negation = Negation("chosen", END_OF_TURN, effect_kind=Destroy, subject_id="yu")
    resolve_effects(game, [GrantNegation(negation)])
    return game, "yu"


def _opponents_widening():
    game = _in_combat()
    put_in_play(game, personality("theirs", printed_id="widening_probe"))
    return game, "yu"


def _widening_outside_battle():
    game = two_seat_game()
    put_in_play(game, personality("yu", owner=PlayerId.P2, printed_id="yu_probe"))
    put_in_play(game, personality("outright", owner=PlayerId.P2, printed_id="widening_probe"))
    return game, "yu"


def _chosen_widening_over_an_empty_yu():
    game = _in_combat()
    put_in_play(game, personality("empty", owner=PlayerId.P2, printed_id="empty_yu_probe"))
    put_in_play(game, personality("chosen", owner=PlayerId.P2, printed_id="chosen_widening_probe"))
    return game, "empty"


@pytest.mark.parametrize(
    "board",
    [
        _chosen_widening_negated,
        _opponents_widening,
        _widening_outside_battle,
        _chosen_widening_over_an_empty_yu,
    ],
    ids=["negated", "opponents-widening", "outside-battle", "empty-yu"],
)
def test_a_widening_raises_nothing_where_the_yu_would_not_resolve(board):
    game, dying = board()
    honor = game.table.seats[PlayerId.P2].honor

    resolve_effects(game, [Destroy(dying, PlayerId.P2)])

    assert game.pending is None
    assert game.table.seats[PlayerId.P2].honor == honor


def test_a_negation_granted_before_the_yu_resolves_prevents_it(reacting):
    game = two_seat_game()
    put_in_play(game, personality("ward", printed_id="ward_probe"))
    put_in_play(game, personality("yu", printed_id="yu_probe"))
    reacting(
        Destroying,
        "ward_probe",
        lambda ctx: [
            GrantNegation(Negation(ctx.card.id, END_OF_TURN, effect_kind=Destroy, subject_id="yu"))
        ]
        if ctx.event.card_id == ctx.card.id
        else [],
    )

    resolve_effects(
        game,
        [
            Simultaneously(
                (
                    Destroy("ward", Rulebook.BATTLE_RESOLUTION),
                    Destroy("yu", Rulebook.BATTLE_RESOLUTION),
                )
            )
        ],
    )
    assert isinstance(game.pending, ChooseNextTrigger)
    submit(game, DecisionResponse(("ward",)))

    assert _standing(game, "yu")
    assert game.table.seats[PlayerId.P1].honor == 0
