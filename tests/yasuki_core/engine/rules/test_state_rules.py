import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.paths import DATABASE_DIR
from yasuki_core.engine.rules import state_rules, triggers
from yasuki_core.engine.rules.effects import AdjustCounter, Choose, GainHonor, GrantModifier
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import counter_from_key
from yasuki_core.game_pieces.prints import PersonalityPrint

from tests.yasuki_core.engine.builders import (
    dealt_table,
    end_phase,
    holding,
    put_in_play,
    register,
    stronghold,
    two_seat_game,
)

P1 = PlayerId.P1
CARD_IDS = DATABASE_DIR / "card_ids.txt"


def _personality(
    card_id: str, *, chi: int = 3, printed_id: str | None = None, owner: PlayerId = P1
) -> L5RCard:
    return L5RCard.of(
        PersonalityPrint,
        id=card_id,
        name=card_id,
        side=Side.DYNASTY,
        owner=owner,
        printed_id=printed_id,
        force=2,
        chi=chi,
    )


def _in_play(*cards: L5RCard) -> GameState:
    game = two_seat_game()
    for card in cards:
        put_in_play(game, card)
    return game


def _battlefield(game: GameState) -> set[str]:
    return {card.id for card in game.table.battlefield.cards}


def test_a_personality_penalised_to_zero_chi_is_destroyed():
    samurai = _personality("doomed", chi=2)
    game = _in_play(samurai)

    triggers.enforce_state_rules(game)
    assert "doomed" in _battlefield(game)  # a live Personality is left alone

    game.modifiers.append(Modifier("src", "doomed", Stat.CHI, -2, Duration.UNTIL_END_OF_TURN))
    triggers.enforce_state_rules(game)

    assert "doomed" not in _battlefield(game)


def test_a_personality_at_one_chi_is_left_alone():
    """The off-by-one that would depopulate the board."""
    samurai = _personality("survivor", chi=3)
    game = _in_play(samurai)
    game.modifiers.append(Modifier("src", "survivor", Stat.CHI, -2, Duration.UNTIL_END_OF_TURN))

    triggers.enforce_state_rules(game)

    assert "survivor" in _battlefield(game)


def test_a_card_that_is_not_a_personality_is_never_chi_dead():
    """A Holding has no Chi, so it reads zero — and zero Chi means dead only for a Personality."""
    farm = holding("farm", gold_production=2)
    game = _in_play(farm)

    triggers.enforce_state_rules(game)

    assert "farm" in _battlefield(game)


def test_a_card_whose_own_text_exempts_it_survives_zero_chi():
    """Seven cards say in their own text that they are not destroyed for having 0 Chi, which the CR
    allows as a continuous effect. Two of them print a nonzero Chi and only need the exemption once
    something penalises them to zero, so the registry is not the set of cards printed at zero."""
    golem = _personality("breaker", chi=0, printed_id="stone_breaker")
    mortal = _personality("mortal", chi=0)
    game = _in_play(golem, mortal)

    triggers.enforce_state_rules(game)

    assert "breaker" in _battlefield(game)
    assert "mortal" not in _battlefield(game)


def test_one_death_causing_another_resolves_and_terminates():
    """The check is a fixpoint: the effects it demands re-enter the same walk, so a death that
    drives another Personality to zero Chi kills them in the same settle."""
    first = _personality("first", chi=1)
    second = _personality("second", chi=1)
    game = _in_play(first, second)
    game.modifiers.append(Modifier("src", "first", Stat.CHI, -1, Duration.UNTIL_END_OF_TURN))
    # The second is held up only by a grant from the first, which expires as it leaves play.
    game.modifiers.append(Modifier("src", "second", Stat.CHI, -1, Duration.UNTIL_END_OF_TURN))
    game.modifiers.append(Modifier("first", "second", Stat.CHI, 1, Duration.WHILE_SOURCE_IN_PLAY))

    triggers.enforce_state_rules(game)

    assert _battlefield(game) == set()


def test_a_state_rule_that_never_settles_names_itself_rather_than_hanging(monkeypatch):
    """A rule demanding an effect that does not satisfy it would spin forever. The walk is bounded
    and says what looped, the same way a runaway trigger cascade does."""

    def never_satisfied(game: GameState) -> list:
        return [GainHonor(P1, 1)]

    monkeypatch.setattr(state_rules, "STATE_RULES", (never_satisfied,))
    game = _in_play(_personality("bystander"))

    with pytest.raises(RuntimeError, match="state rules did not settle"):
        triggers.enforce_state_rules(game)


def test_nothing_gets_a_turn_between_reaching_zero_chi_and_dying():
    """The rule leaves no window: an effect queued behind the one that emptied a Personality's Chi
    finds him already gone, so nothing restores him after the fact."""
    samurai = _personality("doomed", chi=2)
    game = _in_play(samurai)

    triggers.resolve_effects(
        game,
        [
            GrantModifier("src", "doomed", Stat.CHI, -2, Duration.UNTIL_END_OF_TURN),
            GrantModifier("src", "doomed", Stat.CHI, 5, Duration.UNTIL_END_OF_TURN),
        ],
    )

    assert "doomed" not in _battlefield(game)  # the +5 arrived too late to save him


def test_no_zero_chi_personality_is_alive_while_the_engine_waits_on_a_seat():
    """The walk pauses between effects, so a rule enforced only once the cascade settled would leave
    a dead Personality standing for as long as a seat took to answer."""
    samurai = _personality("doomed", chi=1)
    game = _in_play(samurai)

    triggers.resolve_effects(
        game,
        [
            GrantModifier("src", "doomed", Stat.CHI, -1, Duration.UNTIL_END_OF_TURN),
            Choose(P1, ("doomed",), 1, 1, "probe", "src"),
        ],
    )

    assert game.pending is not None  # the engine is waiting
    assert "doomed" not in _battlefield(game)


def test_work_that_does_not_need_the_dead_personality_still_happens():
    """Only what required him is skipped; an unrelated step of the same cascade is untouched."""
    samurai = _personality("doomed", chi=1)
    game = _in_play(samurai)
    before = game.table.seats[P1].honor

    triggers.resolve_effects(
        game,
        [
            GrantModifier("src", "doomed", Stat.CHI, -1, Duration.UNTIL_END_OF_TURN),
            GainHonor(P1, 3),
        ],
    )

    assert "doomed" not in _battlefield(game)
    assert game.table.seats[P1].honor == before + 3


def test_a_trigger_on_the_dying_card_does_not_get_to_save_it(reacting):
    """Shuten Doji reads "after it enters play, but before destroying it for having 0 Chi, give it
    four +1F/+1C tokens" — a window this rule does not grant. Making that card work needs a
    replacement keyed to it, not a hole in the rule for every card to climb through.
    """
    doji = _personality("doji", chi=0, printed_id="state_rules_probe")
    game = two_seat_game()
    reacting(
        EnteredPlay,
        "state_rules_probe",
        lambda ctx: [AdjustCounter(ctx.card.id, counter_from_key("aura"), 4)],
    )

    # The order flow uses: the card lands, the rules are enforced, and only then is anything told
    # it arrived.
    put_in_play(game, doji)
    triggers.enforce_state_rules(game)
    triggers.fire(game, EnteredPlay("doji"))

    assert "doji" not in _battlefield(game)


def test_every_exempt_card_names_a_real_card():
    """The registry is a list of printed ids typed by hand; a typo would read as a card that is
    never exempt, which nothing else would catch."""
    known = set(CARD_IDS.read_text().split())

    assert state_rules.CHI_DEATH_EXEMPT <= known


def test_a_conditional_exemption_is_not_registered_as_a_plain_one():
    """Moto Chagatai and Moto Soro read "not destroyed for having 0 Chi *unless* his Chi is 0 after
    all penalties that last until your turn ends wear off" — a deferred check this rule cannot
    express. They take the rule as written rather than a wrong exemption."""
    assert "moto_chagatai" not in state_rules.CHI_DEATH_EXEMPT
    assert "moto_soro" not in state_rules.CHI_DEATH_EXEMPT


def test_a_game_in_which_a_personality_dies_of_zero_chi_replays_to_the_same_state():
    """The test most likely to catch a placement mistake. The rules are enforced from inside the
    cascade and from ``flow`` either side of it, so a check that fires at a different point during
    replay than during play leaves the rebuilt game holding a card the played one destroyed.
    """
    table = dealt_table(hand=0)
    put_in_play(table, stronghold(P1, gold_production=8))
    doomed = _personality("P1-doomed", chi=0)
    doomed.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(register(table, doomed))
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(table, P1, seed=4)

    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty, where a Recruit is on offer
    session.act(P1, Recruit("P1-doomed"))
    session.submit(P1, DecisionResponse(()))  # nothing to pay, but the offer is still made

    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert "P1-doomed" not in _battlefield(session.game)
    assert "P1-doomed" in {card.id for card in discard.cards}  # died as it arrived
    assert replay(session.log) == session.game


def test_an_arriving_personality_dies_before_its_own_enter_play_trigger_runs(reacting):
    """The flow-level half of the no-window rule. A card arrives on the battlefield through ``ops``
    rather than through an effect, so the walk never sees it land — ``flow`` has to enforce the
    rules between the arrival and announcing it, or an enter-play trait gets to save a Personality
    the rule has already killed.
    """
    table = dealt_table(hand=0)
    put_in_play(table, stronghold(P1, gold_production=8))
    doji = _personality("P1-doji", chi=0, printed_id="state_rules_recruit_probe")
    doji.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(register(table, doji))
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    reacting(
        EnteredPlay,
        "state_rules_recruit_probe",
        lambda ctx: [AdjustCounter(ctx.card.id, counter_from_key("aura"), 4)],
    )
    session = EngineSession.start(table, P1, seed=4)

    end_phase(session)
    end_phase(session)
    session.act(P1, Recruit("P1-doji"))
    session.submit(P1, DecisionResponse(()))

    assert "P1-doji" not in _battlefield(session.game)
    assert session.game.table.cards_by_id["P1-doji"].counters == {}  # never got its tokens


def test_a_zero_chi_personality_waiting_in_a_province_is_left_alone():
    """The rule reaches cards in play. A Personality revealed in a Province is not in play yet, so
    it sits there at zero Chi until someone recruits it — widening the scan to every card would
    destroy a card its owner has not brought out."""
    game = two_seat_game()
    waiting = _personality("waiting", chi=0)
    waiting.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(register(game.table, waiting))
    game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province

    triggers.enforce_state_rules(game)

    assert [card.id for card in province.cards] == ["waiting"]


def test_the_rule_reaches_the_opponents_personalities_too():
    """It is a condition on the board, not on a turn: scoping the scan to the active seat would let
    an opponent hold a dead Personality until their own turn came round."""
    mine = _personality("mine", chi=0)
    theirs = _personality("theirs", chi=0, owner=PlayerId.P2)
    game = _in_play(mine, theirs)

    triggers.enforce_state_rules(game)

    assert _battlefield(game) == set()
