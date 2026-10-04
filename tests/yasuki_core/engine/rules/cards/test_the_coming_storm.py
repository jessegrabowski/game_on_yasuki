from yasuki_core.engine.rules.rulebook.recruit import RECRUIT
from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import can_pay
from yasuki_core.engine.rules.abilities.registry import ability_for
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    PlayStrategy,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseCards,
    ChooseOption,
    DecisionResponse,
    focus_token,
)
from yasuki_core.engine.rules.stats.province_strength import effective_province_strength
from yasuki_core.engine.rules.gold.discounts import effective_recruit_discount
from yasuki_core.engine.rules.gold.production import effective_gold_production
from yasuki_core.engine.rules.legality import recruit_cost
from yasuki_core.engine.rules.effects import GainHonor, TakeFavor
from yasuki_core.engine.rules.cards.the_coming_storm import (
    RELENTLESS_STRONGER,
    RELENTLESS_WEAKER,
)
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, Side
from yasuki_core.game_pieces.prints import RulebookPrint, StrongholdPrint

from contextlib import contextmanager
from dataclasses import replace

from tests.yasuki_core.engine.builders import (
    combat_segment,
    end_phase,
    focus_card,
    holding,
    pay,
    personality,
    put_in_play,
    register,
    stronghold,
)
from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.rules.duel.conftest import CHALLENGE_ABILITY, CHALLENGE_PROBE
from tests.yasuki_core.engine.rules.duel.test_focus_effects import probe_focus_effect

P1, P2 = PlayerId.P1, PlayerId.P2
FIRST = ZoneKey(P1, ZoneRole.PROVINCE, 0)


def _memorial_game() -> EngineSession:
    """Defensive Memorial face-up in P1's first Province, with gold enough to Recruit it."""
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        register(
            state,
            L5RCard.of(
                StrongholdPrint,
                id="P1-SH",
                printed_id="P1-SH",
                name="SH",
                side=Side.STRONGHOLD,
                owner=P1,
                gold_production=8,
                province_strength=3,
            ),
        ),
    )
    memorial = register(
        state,
        holding(
            "memorial",
            printed_id="defensive_memorial",
            owner=P1,
            gold_cost=2,
            gold_production=2,
            keywords=("Fortification",),
        ),
    )
    memorial.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(memorial)
    state.zones[FIRST] = province
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    return session


def test_defensive_memorial_adds_two_to_the_province_it_defends():
    session = _memorial_game()
    assert effective_province_strength(session.game, FIRST) == 3

    session.act(P1, ActivateAbility("memorial", RECRUIT))
    pay(session, P1)

    assert session.game.table.province_attachments == {"memorial": FIRST}
    assert effective_province_strength(session.game, FIRST) == 5


def test_defensive_memorial_enters_bowed_and_still_produces_its_gold():
    """Its two other lines need no handler: the rulebook bows a Holding entering play, and
    ":bow:: Produce 2 Gold" is the Gold Production it prints."""
    session = _memorial_game()

    session.act(P1, ActivateAbility("memorial", RECRUIT))
    pay(session, P1)

    memorial = session.game.table.cards_by_id["memorial"]
    assert memorial.bowed
    assert effective_gold_production(session.game, memorial) == 2


def _natsuyo_game(*, holds_favor: bool = True) -> GameState:
    """Doji Natsuyo in play, her controller holding the Imperial Favor unless a test says not."""
    state = TableState.empty_two_seat()
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = RulebookPrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    put_in_play(
        state, register(state, personality("natsuyo", printed_id="doji_natsuyo", gold_cost=5))
    )
    game = GameState.start(state, P1, seed=0)
    if holds_favor:
        TakeFavor(P1).perform(game)
    return game


def _natsuyo_ability(game: GameState):
    natsuyo = game.table.cards_by_id["natsuyo"]
    return natsuyo, ability_for(game, natsuyo, None)


def test_doji_natsuyo_discards_the_favor_to_gain_an_honor():
    """ShE: "Political Open, :bow:, :favor:: Gain 1 Honor." The Favor is half the cost, so it goes
    when the ability is taken and does not pass to anyone."""
    game = _natsuyo_game()
    natsuyo, ability = _natsuyo_ability(game)

    resolve_effects(game, [*ability.cost(game, natsuyo), *ability.effects(game, natsuyo, natsuyo)])

    assert game.table.seats[P1].honor == 1
    assert natsuyo.bowed
    assert game.favor_holder is None


def test_doji_natsuyo_cannot_pay_without_the_favor():
    """Bowing alone does not buy it. Nothing else in play can pay a Favor cost here, so the whole
    cost is unpayable and the ability is never offered."""
    game = _natsuyo_game(holds_favor=False)
    natsuyo, ability = _natsuyo_ability(game)

    assert not can_pay(game, natsuyo, ability.cost)


def test_doji_natsuyo_costs_a_gold_less_against_a_scorpion():
    """ "Natsuyo enters play for :g1: less if another player is Scorpion Clan." """
    game = _natsuyo_game()
    natsuyo = game.table.cards_by_id["natsuyo"]
    put_in_play(game.table, register(game.table, stronghold(PlayerId.P2, clan=ruleset.SCORPION)))

    assert effective_recruit_discount(game, natsuyo) == 1
    assert recruit_cost(game, natsuyo) == 4


def test_doji_natsuyo_is_not_discounted_by_her_own_players_clan():
    """ "another player" excludes a Crane player who is themselves Scorpion (or the only Scorpion at
    the table), so that player pays her in full."""
    game = _natsuyo_game()
    natsuyo = game.table.cards_by_id["natsuyo"]
    put_in_play(game.table, register(game.table, stronghold(P1, clan=ruleset.SCORPION)))
    put_in_play(game.table, register(game.table, stronghold(PlayerId.P2, clan=ruleset.CRANE)))

    assert effective_recruit_discount(game, natsuyo) == 0
    assert recruit_cost(game, natsuyo) == 5


# --- Relentless ---

RELENTLESS_HONOR_PROBE = "probe_focus_effect_gains_honor_beside_relentless"
RELENTLESS_HONOR_GAIN = 3


@contextmanager
def _relentless_duel(*, in_battle: bool):
    """A duel between P1's challenger and P2's rival with Relentless and one plain card in P1's
    hand, fought inside a battle or outside one.

    P2 holds two cards so the alternation reaches P1 twice, since a seat with nothing left to focus
    strikes and ends the focusing for both.
    """
    cards = [
        personality("challenger", owner=P1, chi=3, printed_id=CHALLENGE_PROBE),
        personality("rival", owner=P2, chi=3),
    ]
    held = [
        focus_card("relentless", P1, 2, printed_id="relentless"),
        focus_card("P1-honor", P1, 1, printed_id=RELENTLESS_HONOR_PROBE),
        focus_card("P2-a", P2, 1),
        focus_card("P2-b", P2, 1),
    ]
    honor = [GainHonor(P1, RELENTLESS_HONOR_GAIN)]
    # The shared challenge probe is an Open action, which a Combat Segment does not permit.
    challenge = (
        replace(CHALLENGE_ABILITY, timings=(ActionTiming.BATTLE,))
        if in_battle
        else CHALLENGE_ABILITY
    )
    with (
        probe_ability(CHALLENGE_PROBE, challenge),
        probe_focus_effect(RELENTLESS_HONOR_PROBE, lambda game, card: honor),
    ):
        if in_battle:
            session = combat_segment(cards, {"challenger": 0}, {"rival": 0}, in_hand=held)
        else:
            state = TableState.empty_two_seat()
            for card in cards:
                put_in_play(state, card)
            for card in held:
                state.zones[ZoneKey(card.owner, ZoneRole.HAND)].add(register(state, card))
            session = EngineSession.start(state, P1)
        session.act(P1, ActivateAbility("challenger"))
        session.submit(P1, DecisionResponse(("rival",)))
        session.submit(P2, DecisionResponse((focus_token("P2-a"),)))
        session.submit(P1, DecisionResponse((focus_token("relentless"),)))
        session.submit(P2, DecisionResponse((focus_token("P2-b"),)))
        session.submit(P1, DecisionResponse((focus_token("P1-honor"),)))
        yield session


def test_relentless_ends_a_duel_fought_outside_a_battle_without_resolution():
    with _relentless_duel(in_battle=False) as session:
        # The active player orders the two Focus Effects, and Relentless goes first.
        session.submit(session.game.pending.seat, DecisionResponse(("relentless",)))

        outcome = session.game.duel.outcome
        assert outcome.winners == () and outcome.losers == ()
        assert outcome.totals == {}


def test_the_other_focus_effects_resolve_after_relentless_ends_the_duel():
    # "(Other Focus Effects resolve.)" The duel's remaining steps are dropped by an early exit and
    # the Focus Effects of the revealed cards are not.
    with _relentless_duel(in_battle=False) as session:
        session.submit(session.game.pending.seat, DecisionResponse(("relentless",)))

        assert session.game.table.seats[P1].honor == RELENTLESS_HONOR_GAIN


def test_relentless_does_nothing_to_a_duel_fought_during_a_battle():
    with _relentless_duel(in_battle=True) as session:
        session.submit(session.game.pending.seat, DecisionResponse(("relentless",)))

        outcome = session.game.duel.outcome
        assert outcome.totals == {P1: 3 + 2 + 1, P2: 3 + 1 + 1}
        assert outcome.winners == (P1,) and outcome.losers == (P2,)


def _relentless_battle() -> EngineSession:
    """A battle with P1's bowed Personality opposed by P2's, a Follower on P2's, and Relentless in
    P1's hand."""
    cards = [
        personality("mine", owner=P1, force=3),
        personality("theirs", owner=P2, force=3),
    ]
    held = [focus_card("relentless_card", P1, 2, printed_id="relentless")]
    session = combat_segment(cards, {"mine": 0}, {"theirs": 0}, in_hand=held)
    session.game.table.cards_by_id["mine"].bow()
    return session


def test_relentless_straightens_your_card_and_moves_a_force_the_way_you_choose():
    session = _relentless_battle()

    session.act(P1, PlayStrategy("relentless_card"))
    session.submit(P1, DecisionResponse(("mine",)))
    assert isinstance(session.game.pending, ChooseCards)
    session.submit(P1, DecisionResponse(("theirs",)))
    pending = session.game.pending
    assert isinstance(pending, ChooseOption)
    session.submit(P1, DecisionResponse((RELENTLESS_WEAKER,)))

    cards = session.game.table.cards_by_id
    assert not cards["mine"].bowed
    assert effective_force(session.game, cards["theirs"]) == 2


def test_relentless_can_strengthen_instead():
    session = _relentless_battle()

    session.act(P1, PlayStrategy("relentless_card"))
    session.submit(P1, DecisionResponse(("mine",)))
    session.submit(P1, DecisionResponse(("mine",)))
    session.submit(P1, DecisionResponse((RELENTLESS_STRONGER,)))

    assert effective_force(session.game, session.game.table.cards_by_id["mine"]) == 4


def test_relentless_is_not_offered_outside_a_battle():
    state = TableState.empty_two_seat()
    put_in_play(state, personality("mine", owner=P1))
    card = focus_card("relentless_card", P1, 2, printed_id="relentless")
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, card))
    session = EngineSession.start(state, P1)

    assert PlayStrategy("relentless_card") not in session.legal_actions(P1)
