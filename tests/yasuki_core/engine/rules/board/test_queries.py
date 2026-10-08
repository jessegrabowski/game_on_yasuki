import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.counts_as import (
    COUNTS_AS,
    AskedBy,
    Asking,
    CountsAs,
    register_counts_as,
    while_in_play,
)
from yasuki_core.engine.rules.board.queries import (
    battle_history,
    equipped_from_hand_since_last_turn,
    different_elements,
    controls_terrain_at,
    has_keyword,
    honorably_dead,
    owned_carrying,
    outnumbered_at,
    owned_holdings,
    phase_history,
    province_key_of,
    rings_in_play,
    terrains_at,
)
from yasuki_core.engine.rules.stats.keyword_grants import keyword_grant, KEYWORD_GRANTS
from yasuki_core.engine.rules.turn.structure import Phase
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.rules.vocabulary.game_events import (
    BattleSegmentStarted,
    Destroyed,
    EnteredPlay,
    LastKnownState,
    PhaseStarted,
)
from yasuki_core.engine.rules.effects import Destroy, Discard, Dishonor
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.table import BATTLEFIELD, Location
from yasuki_core.game_pieces.constants import AttachmentType, Element
from yasuki_core.game_pieces.prints import RingPrint

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    combat_segment,
    doro_no_oni,
    holding,
    personality,
    province_card,
    put_in_play,
    stronghold,
    terrain_at,
    two_seat_game,
)


def test_owned_holdings_without_a_keyword_takes_them_all():
    """Kitsu Watanabe spends "your target Holding", any of them, so the lookup answers that too
    rather than making the card scan the battlefield for itself."""
    game = two_seat_game()
    quay = put_in_play(game, holding("P1-quay", owner=PlayerId.P1, keywords=("Port",)))
    plain = put_in_play(game, holding("P1-plain", owner=PlayerId.P1))
    put_in_play(game, holding("P2-theirs", owner=PlayerId.P2))
    put_in_play(game, stronghold(PlayerId.P1, gold_production=5))

    assert owned_holdings(game, PlayerId.P1) == [quay, plain]


def test_owned_carrying_takes_followers_and_personalities_alike():
    game = two_seat_game()
    monk = put_in_play(game, personality("monk", keywords=("Monk",)))
    put_in_play(game, personality("samurai"))
    put_in_play(game, personality("theirs", owner=PlayerId.P2, keywords=("Shugenja",)))
    follower = attachment(
        "follower", attachment_type=AttachmentType.FOLLOWER, keywords=("Shugenja",)
    )
    attached(game.table, follower, "samurai")

    assert owned_carrying(game, PlayerId.P1, "Monk", "Shugenja") == (monk, follower)


def test_a_keyword_lookup_sees_a_keyword_the_card_grants_itself():
    """Keyword lookups read effective keywords, so a card whose own condition grants one is found by
    the same searches as a card that prints it. Registered here rather than leaning on a real
    card: today only Shrine of Courtesy grants anything, and it grants Legacy, which no lookup
    asks for."""
    game = two_seat_game()
    granted = put_in_play(game, holding("P1-docks", owner=PlayerId.P1, printed_id="keyword_probe"))
    printed = put_in_play(game, holding("P1-quay", owner=PlayerId.P1, keywords=("Port",)))

    assert owned_holdings(game, PlayerId.P1, "Port") == [printed]

    @keyword_grant("keyword_probe")
    def _grants_port(game, granting, card):
        return ("Port",) if card is granting else ()

    try:
        assert owned_holdings(game, PlayerId.P1, "Port") == [granted, printed]
    finally:
        KEYWORD_GRANTS.pop("keyword_probe", None)


def test_has_keyword_ignores_case_on_both_sides():
    """The case-insensitive match is the only thing separating this from ``keyword in
    effective_keywords``, and card text spells a keyword however the printing did."""
    game = two_seat_game()
    card = put_in_play(game, holding("P1-quay", owner=PlayerId.P1, keywords=("Port",)))

    assert has_keyword(game, card, "port") is True
    assert has_keyword(game, card, "PORT") is True
    assert has_keyword(game, card, "Harbor") is False


def test_province_key_of_raises_when_no_province_holds_the_card():
    """The raising variant exists so a caller that already knows the card is in a Province does not
    carry an impossible None. A card in play is in no Province at all."""
    game = two_seat_game()
    provincial = province_card(game, "P1-farm", seat=PlayerId.P1)
    in_play = put_in_play(game, holding("P1-built", owner=PlayerId.P1))

    assert province_key_of(game, PlayerId.P1, provincial.id).owner is PlayerId.P1

    with pytest.raises(ValueError, match=in_play.id):
        province_key_of(game, PlayerId.P1, in_play.id)


def test_a_terrain_is_found_and_controlled_only_at_its_own_battlefield():
    game = two_seat_game()
    ground = terrain_at(game, "ground", battlefield=0, owner=PlayerId.P1)
    hero = put_in_play(game, personality("P1-hero", owner=PlayerId.P1))
    ops.set_location(game.table, hero, Location.at_battlefield(0))

    assert terrains_at(game, battlefield=0) == [ground]
    assert terrains_at(game, battlefield=1) == []
    assert controls_terrain_at(game, PlayerId.P1, battlefield=0)
    assert not controls_terrain_at(game, PlayerId.P2, battlefield=0)
    assert not controls_terrain_at(game, PlayerId.P1, battlefield=1)


def test_a_terrain_named_only_by_its_ability_keyword_is_a_terrain():
    game = two_seat_game()
    doro = put_in_play(game, doro_no_oni("doro", owner=PlayerId.P2))
    ops.set_location(game.table, doro, Location.at_battlefield(0))

    assert terrains_at(game, battlefield=0) == [doro]
    assert controls_terrain_at(game, PlayerId.P2, battlefield=0)


def test_an_army_is_outnumbered_only_by_an_opposing_army_with_more_units():
    cards = [personality(card_id, owner=PlayerId.P2) for card_id in ("d1", "d2", "d3")]
    cards.append(personality("a", owner=PlayerId.P1))
    session = combat_segment(cards, {"a": 0}, {"d1": 0, "d2": 0, "d3": 1})
    game = session.game

    assert outnumbered_at(game, 0, PlayerId.P1)
    assert not outnumbered_at(game, 0, PlayerId.P2)
    assert not outnumbered_at(game, 1, PlayerId.P1)
    assert not outnumbered_at(game, 1, PlayerId.P2)


def test_the_phase_history_holds_what_happened_since_the_latest_phase_began():
    game = two_seat_game()
    stood = LastKnownState(Location.home(PlayerId.P1), PlayerId.P1, force=2, chi=0)
    earlier, later = Destroyed("a", PlayerId.P1, stood), Destroyed("b", PlayerId.P1, stood)
    game.turn_events = (
        earlier,
        PhaseStarted(Phase.ACTION),
        earlier,
        PhaseStarted(Phase.BATTLE),
        later,
    )

    assert phase_history(game) == (later,)


def test_the_battle_history_holds_what_happened_since_the_latest_battle_there_began():
    game = two_seat_game()
    stood = LastKnownState(Location.home(PlayerId.P1), PlayerId.P1, force=2, chi=0)
    earlier, later = Destroyed("a", PlayerId.P1, stood), Destroyed("b", PlayerId.P1, stood)
    game.turn_events = (
        BattleSegmentStarted(BattleSegment.ENGAGE, 0),
        earlier,
        BattleSegmentStarted(BattleSegment.ENGAGE, 1),
        earlier,
        BattleSegmentStarted(BattleSegment.ENGAGE, 0),
        BattleSegmentStarted(BattleSegment.COMBAT, 0),
        later,
    )

    assert battle_history(game, 0) == (BattleSegmentStarted(BattleSegment.COMBAT, 0), later)
    assert battle_history(game, 2) == ()


def test_rings_in_play_takes_a_card_counting_as_a_ring_for_the_asker():
    game = two_seat_game()
    heart = put_in_play(game, holding("P1-heart", owner=PlayerId.P1, printed_id="ring_probe"))
    put_in_play(game, holding("P1-plain", owner=PlayerId.P1))
    register_counts_as(
        "ring_probe", CountsAs(RingPrint, frozenset({AskedBy.ACTION}), while_in_play)
    )

    try:
        assert rings_in_play(game, PlayerId.P1, Asking.action(heart)) == (heart,)
        assert rings_in_play(game, PlayerId.P1, Asking.trait(heart)) == ()
        assert rings_in_play(game, PlayerId.P2, Asking.action(heart)) == ()
    finally:
        COUNTS_AS.pop("ring_probe")


AIR, FIRE, VOID = Element.AIR, Element.FIRE, Element.VOID


@pytest.mark.parametrize(
    ("rings", "count"),
    [
        ([], 0),
        ([{AIR}, {AIR}], 1),
        ([{AIR}, {AIR, FIRE}], 2),
        ([{AIR, FIRE}, {AIR, FIRE}, {AIR, FIRE}], 2),
        ([{AIR, FIRE}, {FIRE}, {AIR, VOID}], 3),
    ],
    ids=["none", "same_element", "a_second_keyword_frees_one", "two_elements_three_rings", "chain"],
)
def test_different_elements_counts_rings_each_standing_for_a_different_element(rings, count):
    assert different_elements([frozenset(elements) for elements in rings]) == count


@pytest.mark.parametrize(
    ("disgraced", "dead"),
    [(False, True), (True, False)],
    ids=["honorable", "dishonorable"],
)
def test_only_a_card_destroyed_without_disgrace_is_honorably_dead(disgraced, dead):
    game = two_seat_game()
    put_in_play(game, personality("fallen"))
    if disgraced:
        resolve_effects(game, [Dishonor("fallen", PlayerId.P1)])
    resolve_effects(game, [Destroy("fallen", PlayerId.P1)])

    assert honorably_dead(game, game.table.cards_by_id["fallen"]) is dead


def test_a_card_discarded_out_of_a_province_is_not_honorably_dead():
    """A Personality who never left a Province never stood in play, so nothing remembers him and
    the pile cannot be asked."""
    game = two_seat_game()
    province_card(game, "unplayed", seat=PlayerId.P1)

    resolve_effects(game, [Discard("unplayed", PlayerId.P1)])

    assert not honorably_dead(game, game.table.cards_by_id["unplayed"])


def test_a_card_discarded_out_of_play_is_not_honorably_dead():
    """The pile holds it either way and it is remembered either way. Only the record of how it
    left tells a death from a discard."""
    game = two_seat_game()
    put_in_play(game, personality("spent"))

    resolve_effects(game, [Discard("spent", PlayerId.P1)])

    assert not honorably_dead(game, game.table.cards_by_id["spent"])


def test_a_card_brought_back_into_play_is_no_longer_dead():
    game = two_seat_game()
    put_in_play(game, personality("risen"))
    resolve_effects(game, [Destroy("risen", PlayerId.P1)])

    ops.move_card(game.table, game.table.cards_by_id["risen"], BATTLEFIELD)

    assert not honorably_dead(game, game.table.cards_by_id["risen"])


def test_equipped_from_hand_since_last_turn_spans_the_previous_turn_and_skips_other_entries():
    game = two_seat_game()
    mine = [put_in_play(game, attachment(card_id)) for card_id in ("before", "now", "put")]
    theirs = put_in_play(game, attachment("theirs", owner=PlayerId.P2))
    game.previous_turn_events = (EnteredPlay("before", from_hand=True, equipped=True),)
    game.turn_events = (
        EnteredPlay("now", from_hand=True, equipped=True),
        EnteredPlay("put", from_hand=True),
        EnteredPlay(theirs.id, from_hand=True, equipped=True),
    )

    assert equipped_from_hand_since_last_turn(game, PlayerId.P1) == (mine[0], mine[1])
