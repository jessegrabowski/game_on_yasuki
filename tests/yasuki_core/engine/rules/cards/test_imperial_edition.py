from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.actions import (
    ActivateAbility,
    DeclareAttack,
    Pass,
    PlayStrategy,
)
from yasuki_core.engine.rules.duel.records import DuelOutcome
from yasuki_core.engine.rules.stats.card_values import effective_chi
from yasuki_core.engine.rules.vocabulary.decisions import (
    STRIKE,
    ChooseAbilityTarget,
    DecisionResponse,
)
from yasuki_core.engine.rules.battle.records import AttackKind
from yasuki_core.engine.rules.effects import Move
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.turn.structure import Phase, RoundKind
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import Location, TableState, ZoneKey, ZoneRole, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.game_pieces.prints import ActionPrint, FatePrint

from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.rules.duel.conftest import CHALLENGE_ABILITY, CHALLENGE_PROBE
from tests.yasuki_core.engine.builders import (
    attached,
    end_phase,
    end_turn,
    attachment,
    holding,
    personality,
    province_card,
    put_in_play,
    register,
    stronghold,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Fantastic Gardens ---


def _gardens_game():
    """The Gardens in play, in the Action phase a Limited ability is taken in."""
    game = two_seat_game()
    put_in_play(game, holding("gardens", printed_id="fantastic_gardens", name="the Gardens"))
    return EngineSession.start(game.table, P1)


def test_bowing_the_gardens_gains_two_honor():
    session = _gardens_game()

    session.act(P1, ActivateAbility("gardens"))

    game = session.game
    assert game.table.seats[P1].honor == 2
    assert game.table.cards_by_id["gardens"].bowed is True


def test_the_gardens_may_be_bowed_again_the_same_turn():
    """Repeatable: bowing is the only thing rationing it, so a Gardens straightened again pays out
    a second time."""
    session = _gardens_game()

    session.act(P1, ActivateAbility("gardens"))
    session.game.table.cards_by_id["gardens"].unbow()
    session.act(PlayerId.P2, Pass())  # priority alternates; the turn is still P1's

    session.act(P1, ActivateAbility("gardens"))

    assert session.game.table.seats[P1].honor == 4


def test_the_gardens_are_withheld_while_bowed():
    session = _gardens_game()
    session.game.table.cards_by_id["gardens"].bow()

    assert ActivateAbility("gardens") not in session.legal_actions(P1)


def test_the_gardens_are_withheld_on_another_seats_turn():
    """Limited rather than Open: only the active player may take it, so its own controller cannot
    use it while the turn belongs to someone else."""
    session = _gardens_game()
    end_turn(session)

    assert session.game.active is PlayerId.P2
    assert ActivateAbility("gardens") not in session.legal_actions(P1)


def test_the_gardens_replay_to_the_same_board():
    session = _gardens_game()
    session.act(P1, ActivateAbility("gardens"))

    assert replay(session.log).table == session.game.table


# --- Sneak Attack ---

ATTACKER, DEFENDER = PlayerId.P1, PlayerId.P2


def _sneak_attack_battle(*, holder: PlayerId = ATTACKER) -> EngineSession:
    """The Engage Segment of P1's attack, with Sneak Attack in ``holder``'s hand."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    province_card(state, "def-prov1", seat=DEFENDER, index=1)
    put_in_play(state, personality("raider", owner=ATTACKER, force=3))
    put_in_play(state, personality("scout", owner=ATTACKER, force=1))
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    put_in_play(state, personality("watch", owner=DEFENDER, force=1))
    state.zones[ZoneKey(holder, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                ActionPrint,
                id="sneak_attack",
                name="Sneak Attack",
                printed_id="sneak_attack",
                side=Side.FATE,
                owner=holder,
            ),
        )
    )
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("raider@0", "scout@1")))
    session.submit(DEFENDER, DecisionResponse(("guard@0", "watch@1")))
    session.submit(ATTACKER, DecisionResponse(("0",)))
    return session


def _close_the_engage_segment(session: EngineSession) -> None:
    """Pass out of the Engage Segment, whoever is holding the opportunity as it goes round."""
    for _ in range(4):
        if session.game.attack.battle_segment is not BattleSegment.ENGAGE:
            return
        session.act(session.game.round.priority, Pass())
    raise AssertionError("the Engage Segment would not close")


def _play_sneak_attack(session: EngineSession, holder: PlayerId) -> None:
    """Take the card from ``holder``'s hand. Both battle segments open on the Defender, so the
    Attacker is handed the opportunity before it can play anything."""
    if session.game.round.priority is not holder:
        session.act(session.game.round.priority, Pass())
    session.act(holder, PlayStrategy("sneak_attack"))


def test_the_combat_segment_opens_on_the_defender_without_it():
    """The baseline the card overturns: both segments start with the Defender (CR, Battle
    Sequence)."""
    session = _sneak_attack_battle()

    _close_the_engage_segment(session)

    assert session.game.attack.battle_segment is BattleSegment.COMBAT
    assert session.game.round.priority is DEFENDER


def test_it_hands_the_attacker_the_first_battle_action():
    session = _sneak_attack_battle()

    _play_sneak_attack(session, ATTACKER)
    _close_the_engage_segment(session)

    assert session.game.attack.battle_segment is BattleSegment.COMBAT
    assert session.game.round.priority is ATTACKER


def test_it_leaves_the_engage_segment_it_is_played_in_alone():
    """ "The first opportunity to take a Battle action" is the Combat Segment's, so the round the
    card is played in goes on handing the opportunity round as it was."""
    session = _sneak_attack_battle()

    _play_sneak_attack(session, ATTACKER)

    assert session.game.attack.battle_segment is BattleSegment.ENGAGE
    assert session.game.round.priority is DEFENDER


def test_the_defender_playing_it_still_names_the_attacker():
    """The card names the Attacker rather than its player, so a Defender holding it hands the
    opportunity to the other seat."""
    session = _sneak_attack_battle(holder=DEFENDER)

    _play_sneak_attack(session, DEFENDER)
    _close_the_engage_segment(session)

    assert session.game.round.priority is ATTACKER


def test_it_lasts_the_one_battle_it_was_played_in():
    """ "In this battle" holds for one battle only, so the next battle of the phase opens its Combat
    Segment on the Defender again, because a held effect is spent when it fires."""
    session = _sneak_attack_battle()
    _play_sneak_attack(session, ATTACKER)
    _close_the_engage_segment(session)
    while session.game.attack.battle_segment is BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())

    session.submit(ATTACKER, DecisionResponse(("1",)))
    _close_the_engage_segment(session)

    assert session.game.attack.battle_segment is BattleSegment.COMBAT
    assert session.game.round.priority is DEFENDER


# --- Touch of Death ---


def _touch_game(*, caster_chi=3, victims=((4, True),)):
    """P1's Touch of Death on a Shugenja, against ``victims`` of ``(chi, bowed)`` owned by P2.

    A victim bowed here stays bowed: the turn-start straighten reaches the active player's cards
    only, and P1 is active.
    """
    game = two_seat_game()
    put_in_play(game, personality("caster", force=2, chi=caster_chi))
    for index, (chi, bowed) in enumerate(victims):
        victim = put_in_play(
            game, personality(f"victim{index}", force=2, chi=chi, owner=PlayerId.P2)
        )
        if bowed:
            victim.bow()
    attached(game, attachment("spell", printed_id="touch_of_death"), "caster")
    return game


def test_touch_of_death_destroys_a_bowed_personality_with_lower_chi():
    game = _touch_game(caster_chi=4, victims=((3, True),))
    session = EngineSession.start(game.table, P1)

    session.act(P1, ActivateAbility("spell"))
    session.submit(P1, DecisionResponse(("victim0",)))

    table = session.game.table
    assert table.cards_by_id["victim0"] not in table.battlefield.cards
    assert table.cards_by_id["caster"].bowed is True
    assert table.cards_by_id["spell"] not in table.battlefield.cards


def test_touch_of_death_does_not_target_a_personality_with_higher_chi():
    """
    "Equal or lower" is measured against the caster, so a hardier Personality is out of reach.
    """
    game = _touch_game(caster_chi=2)  # the victim's Chi 4 is above it
    session = EngineSession.start(game.table, P1)

    assert ActivateAbility("spell") not in session.legal_actions(P1)


def test_touch_of_death_targets_a_personality_with_equal_chi():
    """The boundary the card names. An off-by-one here would exclude every equal-Chi target."""
    game = _touch_game(caster_chi=3, victims=((3, True),))
    session = EngineSession.start(game.table, P1)

    assert ActivateAbility("spell") in session.legal_actions(P1)


def test_touch_of_death_does_not_target_an_unbowed_personality():
    # Chi 4 against a caster of 5, so only the standing puts him out of reach.
    game = _touch_game(caster_chi=5, victims=((4, False),))
    session = EngineSession.start(game.table, P1)

    assert ActivateAbility("spell") not in session.legal_actions(P1)


def test_touch_of_death_is_withheld_while_its_shugenja_is_bowed():
    """His bow is the cost, so an already-bowed Shugenja cannot pay it whatever the target's Chi."""
    game = _touch_game(caster_chi=5)
    session = EngineSession.start(game.table, P1)
    session.game.table.cards_by_id["caster"].bow()

    assert ActivateAbility("spell") not in session.legal_actions(P1)


def test_touch_of_death_replays_to_the_same_board():
    game = _touch_game(caster_chi=4, victims=((3, True),))
    session = EngineSession.start(game.table, P1)
    session.act(P1, ActivateAbility("spell"))
    session.submit(P1, DecisionResponse(("victim0",)))

    assert replay(session.log).table == session.game.table


# --- Poisoned Weapon ---


def _poisoned_weapon_duel(*, chi: int = 5) -> EngineSession:
    """A duel P1's challenger starts against P2's rival, with Poisoned Weapon in P2's hand.

    The duel is created by an ability rather than written onto the game, so every input is on the
    tape and the whole thing replays.
    """
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1)))
    put_in_play(
        state, register(state, personality("mine", owner=P1, printed_id=CHALLENGE_PROBE, chi=chi))
    )
    put_in_play(state, register(state, personality("theirs", owner=P2, chi=3)))
    weapon = register(
        state,
        L5RCard.of(
            FatePrint,
            id="poison",
            printed_id="poisoned_weapon",
            name="Poisoned Weapon",
            side=Side.FATE,
            owner=P2,
            gold_cost=0,
        ),
    )
    state.zones[ZoneKey(P2, ZoneRole.HAND)].add(weapon)
    return EngineSession.start(state, P1)


def _strike_the_duel(session: EngineSession) -> None:
    """Challenge and strike, which runs the duel to the window after its Focus Effects resolve.

    P2 is asked first, and strikes rather than focusing: Poisoned Weapon is the only card in that
    hand, and focusing it would spend the card the duel is being fought to play.
    """
    session.act(P1, ActivateAbility("mine"))
    session.submit(P1, DecisionResponse(("theirs",)))
    session.submit(P2, DecisionResponse((STRIKE,)))


def test_poisoned_weapon_is_offered_only_after_focus_effects_resolve():
    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        session = _poisoned_weapon_duel()
        session.act(P1, ActivateAbility("mine"))
        session.submit(P1, DecisionResponse(("theirs",)))

        # The duel is being focused, which is earlier than the window the card names.
        assert PlayStrategy("poison") not in session.legal_actions(P2)


def test_poisoned_weapon_gives_the_facing_personality_minus_three_chi_and_costs_four_honor():
    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        session = _poisoned_weapon_duel()
        _strike_the_duel(session)

        assert PlayStrategy("poison") in session.legal_actions(P2)
        session.act(P2, PlayStrategy("poison"))

        assert effective_chi(session.game, session.game.table.cards_by_id["mine"]) == 2
        assert session.game.table.seats[P2].honor == -4
        assert replay(session.log).table == session.game.table


def test_poisoned_weapon_killing_a_duelist_ends_the_duel_without_resolution():
    # The reminder in parentheses restates a rule the engine already has: a Personality the Chi
    # loss destroys leaves play, and a duelist leaving ends the duel where it stands.
    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        session = _poisoned_weapon_duel(chi=3)
        _strike_the_duel(session)

        session.act(P2, PlayStrategy("poison"))

        assert "mine" not in {card.id for card in session.game.table.battlefield.cards}
        assert session.game.duel.outcome == DuelOutcome(
            winners=(), losers=(), totals={}, focused={}
        )
        assert replay(session.log).table == session.game.table


def test_poisoned_weapon_is_no_longer_offered_once_the_duel_is_decided():
    # The window the card names closes when the next duel step announces itself. That edge is the
    # half of the reading most likely to rot, since the card stays legal for every window before it
    # only by the latest duel event being the one it asks for.
    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        session = _poisoned_weapon_duel()
        _strike_the_duel(session)
        assert PlayStrategy("poison") in session.legal_actions(P2)

        # Decline the window after the Focus Effects, which lets the duel be decided.
        session.act(P2, Pass())

        assert session.game.duel.outcome is not None
        assert PlayStrategy("poison") not in session.legal_actions(P2)


AMBUSHER = PlayerId.P1
DEFENDER = PlayerId.P2


def _ambush_session(*, attacker_force: int = 4, defender_force: int = 2) -> EngineSession:
    """P1 in its Action Phase holding Ambush, one Personality per seat to name, and a bystander
    the sealed battlefield must refuse."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=AMBUSHER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("ronin", owner=AMBUSHER, force=attacker_force))
    put_in_play(state, personality("victim", owner=DEFENDER, force=defender_force))
    put_in_play(state, personality("bystander", owner=DEFENDER, force=1))
    card = register(
        state,
        L5RCard.of(
            ActionPrint,
            id="ambush-1",
            name="Ambush",
            printed_id="ambush",
            side=Side.FATE,
            owner=AMBUSHER,
            gold_cost=0,
        ),
    )
    state.zones[ZoneKey(AMBUSHER, ZoneRole.HAND)].add(card)
    return EngineSession.start(state, AMBUSHER)


def _play_ambush(session: EngineSession, *, theirs: str = "victim") -> None:
    session.act(AMBUSHER, PlayStrategy("ambush-1"))
    for pick in ("ronin", theirs):
        asked = session.game.pending
        assert isinstance(asked, ChooseAbilityTarget), f"expected targeting, got {asked!r}"
        session.submit(asked.seat, DecisionResponse((pick,)))


def _pass_out_the_battle(session: EngineSession) -> None:
    for _ in range(20):
        attack = session.game.attack
        if attack is None:
            return
        session.act(session.game.round.priority, Pass())
    raise AssertionError("the created battle never ended")


def test_ambush_is_offered_as_an_open_action_from_hand():
    session = _ambush_session()

    assert PlayStrategy("ambush-1") in session.legal_actions(AMBUSHER)


def test_ambush_offers_only_your_unbowed_personalities_to_attack():
    session = _ambush_session()
    session.game.table.cards_by_id["ronin"].bow()

    assert PlayStrategy("ambush-1") not in session.legal_actions(AMBUSHER)


def test_ambush_assigns_the_defender_even_bowed():
    session = _ambush_session()
    session.game.table.cards_by_id["victim"].bow()

    _play_ambush(session)

    victim = session.game.table.cards_by_id["victim"]
    assert victim.bowed
    assert location_of(session.game.table, victim).battlefield == 0


def test_ambush_fights_the_battle_after_the_action_resolves():
    session = _ambush_session()

    _play_ambush(session)

    discard = session.game.table.zones[ZoneKey(AMBUSHER, ZoneRole.FATE_DISCARD)]
    assert [card.id for card in discard.cards] == ["ambush-1"]
    attack = session.game.attack
    assert attack is not None and attack.kind is AttackKind.CREATED
    assert attack.battlefields[0].province is None
    assert attack.battle_segment is BattleSegment.ENGAGE
    assert session.game.round.kind is RoundKind.BATTLE_SEGMENT
    assert session.game.round.priority is DEFENDER
    assert session.game.phase is Phase.ACTION


def test_no_other_personality_can_move_to_the_battlefield():
    session = _ambush_session()
    _play_ambush(session)

    resolve_effects(session.game, [Move("bystander", Location.at_battlefield(0))])

    assert location_of(session.game.table, session.game.table.cards_by_id["bystander"]).is_home


def test_the_battle_resolves_and_the_attack_ceases_to_exist():
    session = _ambush_session()
    _play_ambush(session)

    _pass_out_the_battle(session)

    cards = session.game.table.cards_by_id
    assert all(card.id != "victim" for card in session.game.table.battlefield.cards)
    ronin = cards["ronin"]
    assert ronin.bowed
    assert location_of(session.game.table, ronin).is_home
    assert session.game.attack is None
    assert session.game.phase is Phase.ACTION


def test_the_honor_loss_lands_after_the_battle_ends_not_before():
    session = _ambush_session()
    before = session.game.table.seats[AMBUSHER].honor
    _play_ambush(session)
    assert session.game.table.seats[AMBUSHER].honor == before

    _pass_out_the_battle(session)

    # Winning destroyed one card (+2), then the printed loss (-5).
    assert session.game.table.seats[AMBUSHER].honor == before + 2 - 5
