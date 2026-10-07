import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import (
    DynastyPrint,
    FatePrint,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.effects import Recruit
from yasuki_core.engine.rules.interrupts import forecast
from yasuki_core.engine.rules.rulebook import recruit
from yasuki_core.engine.rules.triggers import resolve_action_effects
from yasuki_core.engine.rules.turn import sequence
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.rules.vocabulary.game_events import (
    CardDiscarded,
    HonorChanged,
)

from tests.yasuki_core.engine.builders import (
    province_card,
    two_seat_game,
    end_phase,
    holding,
    personality,
    put_in_play,
    register,
    stronghold,
)
from yasuki_core.game_pieces.prints import HoldingPrint
from yasuki_core.game_pieces.prints import StrongholdPrint


def _game(hand: int = 0, fate_deck: int = 1) -> GameState:
    """A two-seat game where P1 holds ``hand`` fate cards and each seat's fate deck holds
    ``fate_deck`` cards."""
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            register(
                state,
                L5RCard.of(
                    FatePrint,
                    id=f"{seat.name}-fd{i}",
                    printed_id=f"{seat.name}-fd{i}",
                    name="F",
                    side=Side.FATE,
                    owner=seat,
                ),
            )
            for i in range(fate_deck)
        ]
    hand_zone = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(hand):
        hand_zone.add(
            register(
                state,
                L5RCard.of(
                    FatePrint,
                    id=f"P1-h{i}",
                    printed_id=f"P1-h{i}",
                    name="H",
                    side=Side.FATE,
                    owner=PlayerId.P1,
                ),
            )
        )
    return GameState.start(state, PlayerId.P1)


def _advance_to_end_of_turn(game: GameState) -> None:
    sequence.advance(game)  # Action -> Battle
    sequence.advance(game)  # Battle -> Dynasty
    sequence.advance(game)  # Dynasty -> end of turn


def _bowed_on_battlefield(state: TableState, seat: PlayerId, card_id: str):
    card = register(
        state,
        L5RCard.of(
            DynastyPrint, id=card_id, printed_id=card_id, name="B", side=Side.DYNASTY, owner=seat
        ),
    )
    card.bow()
    state.battlefield.add(card)
    return card


def _facedown_in_province(state: TableState, seat: PlayerId, card_id: str):
    card = register(
        state,
        L5RCard.of(
            DynastyPrint, id=card_id, printed_id=card_id, name="P", side=Side.DYNASTY, owner=seat
        ),
    )
    card.turn_face_down()
    state.zones[ops.create_province(state, seat)].add(card)
    return card


@pytest.mark.parametrize(
    ("clans", "lost_honor", "recruitable_ids"),
    [
        (("Crab",), True, ["proud"]),
        (("Crane",), True, []),
        ((), True, []),
        (("Crab",), False, []),
    ],
    ids=["own clan", "off clan", "unaligned", "no loss taken"],
)
def test_lost_honor_waives_the_requirement_of_the_seats_own_clan(
    clans, lost_honor, recruitable_ids
):
    # CR, Honor Requirement: the waiver covers "Personalities with his or her Clan Alignment", so a
    # Crab seat that has lost Honor elsewhere still cannot reach a Crane at HR 5.
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, clan="Crab"))
    game.table.seats[PlayerId.P1].honor = -2
    game.table.seats[PlayerId.P1].lost_honor_from_elsewhere = lost_honor
    proud = register(game.table, personality("proud", clans=clans, honor_requirement=5))

    assert recruit.recruitable(game, proud) == recruitable_ids


def test_a_proclaimed_recruit_announces_its_honor_gain(reacting):
    game = _game()
    put_in_play(game.table, holding("P1-watcher", printed_id="honor_probe"))
    samurai = put_in_play(game.table, personality("P1-samurai", personal_honor=3))
    seen: list[HonorChanged] = []
    reacting(HonorChanged, "honor_probe", lambda ctx: seen.append(ctx.event) or [])

    resolve_action_effects(game, recruit.proclaim_gain_effects(game, samurai))

    assert seen == [HonorChanged(PlayerId.P1, 3)]


def test_proclaiming_a_dishonorable_personality_for_his_capped_honor_rehonors_nobody():
    # A dishonorable Personality's Personal Honor is capped at 0, so his Proclaim gains 0, and a
    # gain of 0 is not "one or more points of Honor" for the rehonoring to substitute (CR,
    # Rehonoring 0.1; Honor Gains and Losses). He stays dishonorable.
    game = _game()
    samurai = put_in_play(game.table, personality("P1-samurai", personal_honor=3))
    samurai.dishonor()

    resolve_action_effects(game, recruit.proclaim_gain_effects(game, samurai))

    assert samurai.dishonorable
    assert game.table.seats[PlayerId.P1].honor == 0


def test_proclaiming_a_dishonorable_personality_for_another_amount_rehonors_him_instead():
    # A card that Proclaims for an amount other than its Personal Honor gains that amount, which
    # the Recruit action's targeting of him substitutes (CR, Rehonoring 0.1).
    game = _game()
    samurai = put_in_play(
        game.table, personality("P1-samurai", printed_id="proclaim_probe", personal_honor=1)
    )
    samurai.dishonor()
    recruit.proclaim_gain("proclaim_probe")(lambda game, card: 3)
    try:
        resolve_action_effects(game, recruit.proclaim_gain_effects(game, samurai))
        submit(game, DecisionResponse((samurai.id,)))
    finally:
        recruit.PROCLAIM_GAINS.pop("proclaim_probe", None)

    assert not samurai.dishonorable
    assert game.table.seats[PlayerId.P1].honor == 0


# --- the Response Step ---


def _responder_game() -> GameState:
    """A game whose active seat holds one Response: a Caravansary answering its own Fate discard."""
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        holding(
            "caravansary",
            printed_id="caravansary",
            name="Caravansary",
            owner=PlayerId.P1,
            gold_production=2,
        ),
    )
    game = GameState.start(state, PlayerId.P1)
    game.action_events[:] = [CardDiscarded("some-fate", Side.FATE, PlayerId.P1)]
    return game


def _advance_turns(session, count: int) -> None:
    """Pass until ``count`` further turns have opened."""
    target = session.game.turn + count
    for _ in range(4 * count + 4):
        if session.game.turn == target:
            return
        end_phase(session)
    raise AssertionError(f"stuck on turn {session.game.turn}, wanted {target}")


def _discount_game(*, clan=None, first_player=PlayerId.P1, in_play=()):
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        L5RCard.of(
            StrongholdPrint,
            id="P1-SH",
            printed_id="P1-SH",
            name="SH",
            side=Side.STRONGHOLD,
            owner=PlayerId.P1,
            clan=clan,
        ),
    )
    for card in in_play:
        put_in_play(state, card)
    return GameState.start(state, first_player)


def _holding(printed_id: str, gold_cost: int, clan: str | None = None) -> L5RCard:
    return L5RCard.of(
        HoldingPrint,
        id=f"{printed_id}-inst",
        name="H",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        printed_id=f"{printed_id}-inst" if printed_id is None else printed_id,
        gold_cost=gold_cost,
        clan=clan,
    )


def test_a_cards_recruit_is_open_to_its_actions_interrupt_step():
    game = two_seat_game()
    target = province_card(game, "P1-target", gold_cost=2)

    foreseen = forecast(game, tuple(recruit.recruit_card(game, target)))

    assert [effect.card_id for effect in foreseen if isinstance(effect, Recruit)] == [target.id]


@pytest.mark.parametrize(
    ("honor", "arrives"), [(5, True), (6, True), (4, False)], ids=["meets", "exceeds", "short"]
)
def test_the_recruit_effect_itself_holds_a_personality_to_his_honor_requirement(honor, arrives):
    """The rulebook offers a Recruit only to a seat whose Honor reaches it, but a card that
    Recruits by returning the effect reaches it another way, so the effect carries the gate too."""
    game = two_seat_game()
    game.table.seats[PlayerId.P1].honor = honor
    proud = register(game.table, personality("proud", honor_requirement=5))

    resolve_action_effects(game, [Recruit("proud", from_province=None)])

    assert (proud in game.table.battlefield.cards) is arrives


def test_the_recruit_effect_lets_a_holding_in_whatever_the_seats_honor():
    """Only a Personality prints an Honor Requirement, so the gate has to let everything else
    past rather than reading a stat that is not there."""
    game = two_seat_game()
    game.table.seats[PlayerId.P1].honor = -10
    mine = register(game.table, holding("mine", gold_production=2))

    resolve_action_effects(game, [Recruit("mine", from_province=None)])

    assert mine in game.table.battlefield.cards


def test_a_waiver_in_play_carries_a_personality_past_the_recruit_effects_gate():
    """The waiver is read off the board as the Recruit resolves, so it reaches the effect's gate
    and not only the rulebook's offer."""
    game = two_seat_game()
    game.table.seats[PlayerId.P1].honor = 0
    put_in_play(game.table, holding("P1-sensei", printed_id="waiver_probe"))
    proud = register(game.table, personality("proud", honor_requirement=5))
    recruit.register_honor_requirement_waiver("waiver_probe")

    try:
        resolve_action_effects(game, [Recruit("proud", from_province=None)])
    finally:
        recruit.HONOR_REQUIREMENT_WAIVERS.discard("waiver_probe")

    assert proud in game.table.battlefield.cards
