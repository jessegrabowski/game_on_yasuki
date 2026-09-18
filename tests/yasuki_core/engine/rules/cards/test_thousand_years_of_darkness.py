from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId, Trait
from yasuki_core.engine.rules.effects import Destroy
from yasuki_core.engine.rules.triggers import fire, resolve_effects
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.vocabulary.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.rules.vocabulary.game_events import Destroyed, EnteredPlay
from yasuki_core.engine.table import Location, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    personality,
    put_in_play,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Ashura ---


def test_ashura_costs_five_honor_as_he_enters_play():
    game = two_seat_game()
    ashura = put_in_play(game, personality("ashura", printed_id="ashura"))

    fire(game, EnteredPlay(ashura.id))

    assert game.table.seats[P1].honor == -5


def test_ashura_destroyed_at_a_battlefield_reaches_followers_and_unguarded_personalities(reacting):
    # Either army's: an ally, a bare enemy, and an enemy's Follower are reachable; the Personality
    # behind that Follower and the enemy at home are not.
    seen: list[Trait | PlayerId] = []
    reacting(Destroyed, "cause_probe", lambda ctx: seen.append(ctx.event.cause) or [])
    game = two_seat_game()
    put_in_play(game, personality("probe", printed_id="cause_probe"))
    ashura = put_in_play(game, personality("ashura", printed_id="ashura"))
    ally = put_in_play(game, personality("ally"))
    bare = put_in_play(game, personality("bare", owner=P2))
    guarded = put_in_play(game, personality("guarded", owner=P2))
    attached(
        game, attachment("guard", attachment_type=AttachmentType.FOLLOWER, owner=P2), "guarded"
    )
    put_in_play(game, personality("home", owner=P2))
    for card in (ashura, ally, bare, guarded):
        ops.set_location(game.table, card, Location.at_battlefield(0))

    resolve_effects(game, [Destroy("ashura", P2)])

    pending = game.pending
    assert isinstance(pending, ChooseCards)
    assert pending.seat is P1
    assert set(pending.candidates) == {"ally", "bare", "guard"}
    submit(game, DecisionResponse(("guard",)))
    assert (
        game.table.cards_by_id["guard"]
        in game.table.zones[ZoneKey(P2, ZoneRole.FATE_DISCARD)].cards
    )
    assert seen == [P2, Trait("ashura")]


def test_ashura_destroyed_at_home_reaches_nothing():
    game = two_seat_game()
    put_in_play(game, personality("ashura", printed_id="ashura"))
    put_in_play(game, personality("bare", owner=P2))

    resolve_effects(game, [Destroy("ashura", P2)])

    assert game.pending is None
