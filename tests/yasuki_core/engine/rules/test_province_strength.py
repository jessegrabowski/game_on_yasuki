import json

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.economy import effective_province_strength
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.snapshot import InitialRecord, decode_initial, encode_initial
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import StrongholdPrint

from tests.yasuki_core.engine.builders import attached, holding, put_in_play, two_seat_game

P1 = PlayerId.P1
FIRST = ZoneKey(P1, ZoneRole.PROVINCE, 0)


def _walled_game(*, printed_strength: int = 3, provinces: int = 2):
    """A board with a Stronghold printing ``printed_strength`` and empty Provinces to defend."""
    game = two_seat_game()
    put_in_play(
        game,
        L5RCard.of(
            StrongholdPrint,
            id="SH",
            name="SH",
            side=Side.STRONGHOLD,
            owner=P1,
            province_strength=printed_strength,
        ),
    )
    for index in range(provinces):
        game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, index)] = ProvinceZone(owner=P1)
    return game


def test_a_province_starts_at_the_strength_its_stronghold_prints():
    """ "A stat of a Stronghold, or of a Province" (CR) — the Stronghold sets where every one of its
    Provinces begins."""
    game = _walled_game(printed_strength=4)

    assert effective_province_strength(game, FIRST) == 4


def test_a_wall_token_raises_the_province_it_rests_on_and_no_other():
    game = _walled_game(printed_strength=3)

    ops.adjust_province_counter(game.table, FIRST, "wall", 2)

    assert effective_province_strength(game, FIRST) == 5
    assert effective_province_strength(game, ZoneKey(P1, ZoneRole.PROVINCE, 1)) == 3


def test_a_fortification_grants_its_province_the_strength_its_text_names():
    """Makeshift Fortifications reads "This Province has +3PS". The grant is derived from the
    board, so it lasts exactly as long as the card stays attached."""
    game = _walled_game(printed_strength=3)
    attached(game, holding("wall", printed_id="makeshift_fortifications"), FIRST)

    assert effective_province_strength(game, FIRST) == 6


def test_a_fortification_grants_nothing_to_the_provinces_it_is_not_on():
    """The grant is looked up per Province, so a Fortification on one must not lift its neighbor."""
    game = _walled_game(printed_strength=3)
    attached(game, holding("wall", printed_id="makeshift_fortifications"), FIRST)

    assert effective_province_strength(game, ZoneKey(P1, ZoneRole.PROVINCE, 1)) == 3


def test_a_fortification_stops_granting_once_it_detaches():
    game = _walled_game(printed_strength=3)
    fort = attached(game, holding("wall", printed_id="makeshift_fortifications"), FIRST)

    ops.detach(game.table, fort)

    assert effective_province_strength(game, FIRST) == 3


def test_a_grant_on_the_stronghold_lifts_every_province_at_once():
    """A Sensei raises the Stronghold's Province Strength, and that is the stat each Province starts
    from — so one grant reaches them all rather than needing a per-Province effect."""
    game = _walled_game(printed_strength=3)
    put_in_play(game, holding("sensei"))
    game.modifiers.append(
        Modifier("sensei", "SH", Stat.PROVINCE_STRENGTH, 1, Duration.WHILE_SOURCE_IN_PLAY)
    )

    assert effective_province_strength(game, FIRST) == 4
    assert effective_province_strength(game, ZoneKey(P1, ZoneRole.PROVINCE, 1)) == 4


def test_province_strength_floors_at_zero():
    """The CR's Calculating Stats order: the sum takes the minimum, not each term."""
    game = _walled_game(printed_strength=2)

    ops.adjust_province_counter(game.table, FIRST, "erosion", 5)

    assert effective_province_strength(game, FIRST) == 0


def test_a_seat_with_no_stronghold_has_only_what_rests_on_the_province():
    game = two_seat_game()
    game.table.zones[FIRST] = ProvinceZone(owner=P1)

    ops.adjust_province_counter(game.table, FIRST, "wall", 1)

    assert effective_province_strength(game, FIRST) == 1


def test_a_provinces_counters_survive_the_log_and_the_view():
    """A Wall token is board state a replay has to reproduce and a client has to see. Neither the
    snapshot nor the redacted view carried anything keyed on a zone before."""
    game = _walled_game(printed_strength=3)
    ops.adjust_province_counter(game.table, FIRST, "wall", 2)
    session = EngineSession.start(game.table, P1)

    assert session.game.table.province_counters == {FIRST: {"wall": 2}}
    assert session.log.replay().table.province_counters == {FIRST: {"wall": 2}}
    assert session.project(P1).table.province_counters == {FIRST: {"wall": 2}}
    assert effective_province_strength(session.game, FIRST) == 5


def test_a_provinces_counters_survive_a_round_trip_through_real_json():
    """A Province is keyed by a ZoneKey, which JSON cannot use as an object key — hence the pairs
    the save format stores. Nothing else round-trips a zone-keyed map, so without this the encoding
    is only ever exercised in memory, where a dict keyed by the tuple works fine."""
    state = _walled_game().table
    ops.adjust_province_counter(state, FIRST, "wall", 2)

    payload = json.loads(json.dumps(encode_initial(InitialRecord.from_state(state))))

    assert decode_initial(payload).province_counters == {FIRST: {"wall": 2}}


def test_a_counter_spent_to_zero_leaves_no_trace_on_the_province():
    """Floored at zero and pruned, the way a card's counters are — an empty entry would replay as a
    board that differs from the one it came from."""
    game = _walled_game()
    ops.adjust_province_counter(game.table, FIRST, "wall", 1)

    assert ops.adjust_province_counter(game.table, FIRST, "wall", -5) == 0
    assert game.table.province_counters == {}


def test_destroying_a_province_takes_its_counters_with_it():
    game = _walled_game()
    ops.adjust_province_counter(game.table, FIRST, "wall", 3)

    ops.destroy_province(game.table, P1, FIRST)

    assert game.table.province_counters == {}
