import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.table import DeckKey, Location, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.rules.vocabulary.actions import (
    ActivateAbility,
    DeclareAttack,
    Pass,
    PlayStrategy,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseAbilityTarget,
    ChooseNextTrigger,
    Confirm,
    DecisionResponse,
)
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.board.queries import has_keyword
from yasuki_core.engine.rules.cards.chaos_reigns_part_ii import (
    HIYAMAKOS_CLAW,
    LESSER_ONI,
    NAGA_FOLLOWER,
    WRATH_FIRE_MODE,
    WRATH_MELEE_MODE,
)
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.stats.card_values import effective_chi, effective_force
from yasuki_core.engine.rules.gold.production import effective_gold_production
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.idioms import register_yu
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.effects import AdjustCounter, Bow, Destroy, GainHonor, Simultaneously
from yasuki_core.game_pieces.counters import counter_from_key
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.rules.battle.resolution import assignment_candidates
from yasuki_core.engine.rules.board.seats import cards_in_hand
from yasuki_core.engine.rules.rulebook.recruit import RECRUIT_WITH_INVEST
from yasuki_core.engine.rules.triggers import fire, resolve_effects
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import ActionPrint, FatePrint, PersonalityPrint, RingPrint

from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    combat_segment,
    end_phase,
    end_turn,
    fate_card,
    holding,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
    stronghold,
    terrain_at,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


def _game():
    """A session in the Action phase with P1's Millet Farm and one other Farm in play. Returns the
    live card objects, since ``EngineSession.start`` rebuilds the table from a snapshot."""
    state = TableState.empty_two_seat()
    put_in_play(
        state, holding("millet", printed_id="millet_farm", keywords=("Farm",), gold_production=1)
    )
    put_in_play(
        state, holding("farm", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )  # no trigger of its own
    session = EngineSession.start(state, P1)
    live = session.game.table.cards_by_id
    return session, live["millet"], live["farm"]


def test_millet_farm_is_activatable_in_the_action_phase():
    session, millet, _ = _game()
    assert ActivateAbility(millet.id) in session.legal_actions(P1)


def test_millet_farm_is_not_activatable_while_bowed():
    session, millet, _ = _game()
    millet.bow()
    assert ActivateAbility(millet.id) not in session.legal_actions(P1)


def test_millet_farm_is_not_activatable_outside_the_action_phase():
    session, millet, _ = _game()
    end_phase(session)  # Action -> Battle
    assert ActivateAbility(millet.id) not in session.legal_actions(P1)


def test_activating_millet_farm_bows_it_and_asks_for_a_farm_target():
    session, millet, farm = _game()
    session.act(P1, ActivateAbility(millet.id))

    assert millet.bowed
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget)
    assert set(pending.candidates) == {
        millet.id,
        farm.id,
    }  # every Farm you control, itself included


def test_millet_farm_gives_its_target_two_gold_production():
    session, millet, farm = _game()
    session.act(P1, ActivateAbility(millet.id))
    session.submit(P1, DecisionResponse((farm.id,)))

    assert session.game.pending is None
    assert effective_gold_production(session.game, farm) == 2 + 2  # base 2 + the +2GP grant


def test_ability_activation_replays_to_the_same_state():
    session, millet, farm = _game()
    session.act(P1, ActivateAbility(millet.id))
    session.submit(P1, DecisionResponse((farm.id,)))

    assert replay(session.log) == session.game


def test_modifier_clear_replays_across_the_turn_boundary():
    session, millet, farm = _game()
    session.act(P1, ActivateAbility(millet.id))
    session.submit(P1, DecisionResponse((farm.id,)))
    for _ in range(3):  # end P1's turn, dropping the UEOT modifier
        end_phase(session)

    assert session.game.ongoing == []  # the grant was cleared
    assert replay(session.log) == session.game  # and the clear rebuilds deterministically


def test_millet_farm_grant_expires_at_end_of_turn():
    session, millet, farm = _game()
    session.act(P1, ActivateAbility(millet.id))
    session.submit(P1, DecisionResponse((farm.id,)))
    assert effective_gold_production(session.game, farm) == 4  # +2 this turn

    for _ in range(3):  # Action -> Battle -> Dynasty -> end of P1's turn
        end_phase(session)
    assert effective_gold_production(session.game, farm) == 2  # the UEOT modifier is gone


def test_modifier_grant_fires_no_counter_trigger():
    # A GP grant is a modifier, not a Wealth token, so a wealth-specific trigger must stay silent.
    # Aoki draws on your Holding's Wealth gain; the +2GP grant must not wake it.
    state = TableState.empty_two_seat()
    put_in_play(
        state, holding("millet", printed_id="millet_farm", keywords=("Farm",), gold_production=1)
    )
    put_in_play(
        state, holding("farm", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )
    put_in_play(
        state,
        L5RCard.of(
            PersonalityPrint,
            id="aoki",
            name="Aoki",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="shosuro_aoki_yoritomo_kayoko_experienced",
        ),
    )
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card("fd", P1))]
    session = EngineSession.start(state, P1)
    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)]
    before = len(hand.cards)

    session.act(P1, ActivateAbility("millet"))
    session.submit(P1, DecisionResponse(("farm",)))

    assert effective_gold_production(session.game, session.game.table.cards_by_id["farm"]) == 4
    assert len(hand.cards) == before  # Aoki did not draw and the grant is a modifier, not a token


# --- Tarkasha ---


def _tarkasha_game(*, fallen=("dead_naga",), spare_follower=False):
    """Tarkasha in play with ``fallen`` Naga Followers in the Fate discard to reshuffle."""
    game = two_seat_game()
    token_template(
        game,
        NAGA_FOLLOWER,
        name="Naga",
        card_type="Follower",
        keywords=("Naga", "Nonhuman"),
        force=1,
    )
    put_in_play(
        game,
        personality(
            "tarkasha", printed_id="tarkasha", force=4, chi=2, keywords=("Commander", "Naga")
        ),
    )
    put_in_play(game, personality("scout", force=1, chi=2, keywords=("Naga",)))
    discard = game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)]
    for card_id in fallen:
        discard.add(
            register(
                game.table,
                attachment(
                    card_id,
                    attachment_type=AttachmentType.FOLLOWER,
                    keywords=("Naga", "Nonhuman"),
                ),
            )
        )
    if spare_follower:
        discard.add(
            register(
                game.table,
                attachment(
                    "ashigaru", attachment_type=AttachmentType.FOLLOWER, keywords=("Ashigaru",)
                ),
            )
        )
    return EngineSession.start(game.table, P1)


def test_tarkasha_reshuffles_a_fallen_naga_to_raise_a_new_one():
    session = _tarkasha_game()

    session.act(P1, ActivateAbility("tarkasha"))
    session.submit(P1, DecisionResponse(("tarkasha",)))  # the Commander, chosen at targeting
    session.submit(P1, DecisionResponse(("dead_naga",)))  # then the reshuffle its text calls for

    game = session.game
    raised = attachments_of(game, game.table.cards_by_id["tarkasha"])[0]
    assert raised.name == "Naga"
    assert [card.id for card in game.table.decks[DeckKey(P1, Side.FATE)].cards] == ["dead_naga"]
    assert game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].cards == []


def test_tarkasha_only_reshuffles_naga_followers():
    """The discard holds an Ashigaru too, and it is no Naga."""
    session = _tarkasha_game(spare_follower=True)

    session.act(P1, ActivateAbility("tarkasha"))
    session.submit(P1, DecisionResponse(("tarkasha",)))

    assert session.game.pending.candidates == ("dead_naga",)


def test_tarkasha_only_mounts_a_commander():
    """ "Your target Commander" and the plain Naga scout does not lead."""
    session = _tarkasha_game()

    session.act(P1, ActivateAbility("tarkasha"))

    assert session.game.pending.candidates == ("tarkasha",)


def test_tarkasha_raises_nothing_with_no_fallen_naga_to_reshuffle():
    """The reshuffle is written into the text, so it is an effect rather than a cost: the ability is
    announced as normal and stops when it finds nothing to reshuffle (CR, Action Sequence)."""
    session = _tarkasha_game(fallen=())

    session.act(P1, ActivateAbility("tarkasha"))
    session.submit(P1, DecisionResponse(("tarkasha",)))

    game = session.game
    assert game.pending is None
    assert attachments_of(game, game.table.cards_by_id["tarkasha"]) == ()


def test_tarkasha_replays_to_the_same_board():
    session = _tarkasha_game()
    session.act(P1, ActivateAbility("tarkasha"))
    session.submit(P1, DecisionResponse(("tarkasha",)))
    session.submit(P1, DecisionResponse(("dead_naga",)))

    assert replay(session.log).table == session.game.table


# --- Tetsuo Hiyamako (Experienced) ---


def _hiyamako_game():
    game = two_seat_game()
    token_template(
        game,
        HIYAMAKOS_CLAW,
        name="Hiyamako's Claw",
        card_type="Item",
        keywords=("Claw", "One-Handed", "Weapon"),
        force=1,
    )
    put_in_play(
        game,
        personality(
            "hiyamako", printed_id="tetsuo_hiyamako_experienced", force=2, chi=2, gold_cost=6
        ),
    )
    return game


def test_hiyamako_arrives_holding_two_claws():
    """Two Weapons where the rules allow one: her text says so, and card text beats the rules (CR,
    Cardinal Rule 1)."""
    game = _hiyamako_game()

    fire(game, EnteredPlay("hiyamako"))

    hiyamako = game.table.cards_by_id["hiyamako"]
    claws = attachments_of(game, hiyamako)
    assert [claw.name for claw in claws] == ["Hiyamako's Claw", "Hiyamako's Claw"]
    assert effective_force(game, hiyamako) == 4  # her two, and one from each Claw


def test_her_claws_are_two_distinct_cards():
    """Each is created in its own right, so destroying one leaves the other."""
    game = _hiyamako_game()
    fire(game, EnteredPlay("hiyamako"))
    first, second = attachments_of(game, game.table.cards_by_id["hiyamako"])

    resolve_effects(game, [Destroy(first.id, P1)])

    assert first.id not in game.table.cards_by_id
    assert attachments_of(game, game.table.cards_by_id["hiyamako"]) == (second,)


def test_another_personality_arriving_arms_nobody():
    game = _hiyamako_game()
    put_in_play(game, personality("bystander", force=2, chi=2))

    fire(game, EnteredPlay("bystander"))

    assert attachments_of(game, game.table.cards_by_id["hiyamako"]) == ()
    assert attachments_of(game, game.table.cards_by_id["bystander"]) == ()


# --- Fortified Farmlands ---


def _farmlands_game(*, other_farms: int = 1):
    """Fortified Farmlands in play, beside ``other_farms`` other Farm Holdings."""
    game = two_seat_game()
    put_in_play(game, holding("farmlands", printed_id="fortified_farmlands", keywords=("Farm",)))
    for index in range(other_farms):
        put_in_play(game, holding(f"farm{index}", keywords=("Farm",)))
    return game


def test_fortified_farmlands_has_renew_beside_another_farm():
    game = _farmlands_game()

    assert "Renew" in effective_keywords(game, game.table.cards_by_id["farmlands"])


def test_fortified_farmlands_has_no_renew_on_its_own():
    """ "Another Farm" excludes the card asking, so a lone Fortified Farmlands does not count itself
    and it carries the Farm keyword and would otherwise always satisfy its own condition."""
    game = _farmlands_game(other_farms=0)

    assert "Renew" not in effective_keywords(game, game.table.cards_by_id["farmlands"])


def test_fortified_farmlands_loses_renew_when_the_other_farm_goes():
    """The grant is read whenever the keyword is asked for, so it comes and goes with the board."""
    game = _farmlands_game()
    farmlands = game.table.cards_by_id["farmlands"]
    assert "Renew" in effective_keywords(game, farmlands)

    game.table.battlefield.remove(game.table.cards_by_id["farm0"])

    assert "Renew" not in effective_keywords(game, farmlands)


# --- Daidoji Kaede ---


def _kaede_defending(*, marked: str | None = "raider") -> EngineSession:
    """P1 attacks with a raider and a scout. P2's Kaede (Force 3) used her Open on ``marked``
    during the Action Phase, then defends against the raider's battlefield. Returns the session at
    the Combat Segment with the Defender holding the opportunity."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=PlayerId.P2, index=0)
    province_card(state, "def-prov1", seat=PlayerId.P2, index=1)
    put_in_play(state, personality("raider", force=2))
    put_in_play(state, personality("scout", force=2))
    put_in_play(state, personality("kaede", owner=PlayerId.P2, printed_id="daidoji_kaede", force=3))
    session = EngineSession.start(state, P1)
    if marked is not None:
        session.act(P1, Pass())
        session.act(PlayerId.P2, ActivateAbility("kaede", ability_key="opposition"))
        session.submit(PlayerId.P2, DecisionResponse((marked,)))
        session.act(P1, Pass())
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("raider@0", "scout@1")))
    session.submit(PlayerId.P2, DecisionResponse(("kaede@0",)))
    session.submit(P1, DecisionResponse(("0",)))
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    return session


def test_kaede_cannot_be_assigned_by_the_attacker():
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=PlayerId.P2, index=0)
    put_in_play(state, personality("kaede", printed_id="daidoji_kaede"))
    put_in_play(state, personality("bushi"))
    session = EngineSession.start(state, P1)
    end_phase(session)

    session.act(P1, DeclareAttack())

    assert assignment_candidates(session.game, P1) == ("bushi@0",)


def test_kaede_gains_force_after_assigning_to_defend():
    session = _kaede_defending(marked=None)

    assert effective_force(session.game, session.game.table.cards_by_id["kaede"]) == 4


def test_kaede_has_the_ranged_attack_while_the_marked_personality_opposes_her():
    session = _kaede_defending(marked="raider")

    session.act(PlayerId.P2, ActivateAbility("kaede", ability_key="ranged"))
    session.submit(PlayerId.P2, DecisionResponse(("raider",)))

    assert "raider" not in [card.id for card in session.game.table.battlefield.cards]


def test_kaede_lacks_the_ranged_attack_when_the_marked_personality_is_elsewhere():
    session = _kaede_defending(marked="scout")  # the scout attacks the other Province

    assert ActivateAbility("kaede", ability_key="ranged") not in session.legal_actions(PlayerId.P2)


def test_kaede_lacks_the_ranged_attack_without_her_open():
    session = _kaede_defending(marked=None)

    assert ActivateAbility("kaede", ability_key="ranged") not in session.legal_actions(PlayerId.P2)


# --- Togashi Bairei ---

BOW_PROBE = "probe_battle_bow_a_personality"


def _bow_a_personality() -> Ability:
    return Ability(
        timings=(ActionTiming.BATTLE,),
        label="Battle: bow a target Personality",
        cost=no_cost,
        targets=lambda game, source: [card.id for card in personalities_in_play(game)],
        effects=lambda game, source, target: [Bow(target.id)],
        targets_any_location=True,
    )


def _bairei_battle() -> EngineSession:
    """Bairei, P1's bowed Monk and P2's guard at the battlefield, P2's sentry at home, and a
    Holding for each seat whose Battle action bows a target Personality anywhere."""
    session = combat_segment(
        [
            personality("bairei", printed_id="togashi_bairei", keywords=("Monk",)),
            personality("monk", keywords=("Monk",)),
            holding("bower", printed_id=BOW_PROBE),
            holding("their_bower", printed_id=BOW_PROBE, owner=PlayerId.P2),
            personality("guard", owner=PlayerId.P2),
            personality("sentry", owner=PlayerId.P2),
        ],
        {"bairei": 0, "monk": 0},
        {"guard": 0},
    )
    session.game.table.cards_by_id["monk"].bow()
    return session


@pytest.mark.parametrize(("bowed", "offered"), [("guard", True), ("sentry", False)])
def test_togashi_bairei_responds_only_to_your_action_bowing_an_enemy_at_its_battlefield(
    bowed, offered
):
    with probe_ability(BOW_PROBE, _bow_a_personality()):
        session = _bairei_battle()

        session.act(P1, ActivateAbility("bower"))
        session.submit(P1, DecisionResponse((bowed,)))

        assert (ActivateAbility("bairei") in session.legal_actions(P1)) is offered


def test_togashi_bairei_ignores_the_opponents_action_bowing_an_enemy():
    with probe_ability(BOW_PROBE, _bow_a_personality()):
        session = _bairei_battle()
        session.act(P1, ActivateAbility("bower"))
        session.submit(P1, DecisionResponse(("sentry",)))

        session.act(PlayerId.P2, ActivateAbility("their_bower"))
        session.submit(PlayerId.P2, DecisionResponse(("guard",)))

        assert session.game.table.cards_by_id["guard"].bowed
        assert ActivateAbility("bairei") not in session.legal_actions(P1)


def test_togashi_bairei_straightens_your_target_monk():
    with probe_ability(BOW_PROBE, _bow_a_personality()):
        session = _bairei_battle()
        session.act(P1, ActivateAbility("bower"))
        session.submit(P1, DecisionResponse(("guard",)))

        session.act(P1, ActivateAbility("bairei"))
        session.submit(P1, DecisionResponse(("monk",)))

        assert session.game.table.cards_by_id["monk"].bowed is False


# --- Wrath of the Shattered Star ---


def _wrath_battle() -> EngineSession:
    """P1's Monk and samurai opposed by P2's 2F guard at the battlefield, and Wrath of the
    Shattered Star in P1's hand."""
    session = combat_segment(
        [
            personality("monk", keywords=(keywords.MONK,)),
            personality("samurai"),
            personality("guard", owner=PlayerId.P2, force=2),
        ],
        {"monk": 0, "samurai": 0},
        {"guard": 0},
    )
    table = session.game.table
    wrath = L5RCard.of(
        FatePrint,
        id="wrath",
        printed_id="wrath_of_the_shattered_star",
        name="Wrath of the Shattered Star",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
        keywords=(keywords.FIRE,),
    )
    table.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(table, wrath))
    return session


def _wrath_with(session: EngineSession, mode: str) -> None:
    session.act(P1, PlayStrategy("wrath"))
    session.submit(P1, DecisionResponse(("monk",)))
    assert session.game.pending.candidates == (WRATH_MELEE_MODE, WRATH_FIRE_MODE)
    session.submit(P1, DecisionResponse((mode,)))


def test_wrath_of_the_shattered_star_bows_the_monk_to_make_a_melee_3():
    session = _wrath_battle()

    _wrath_with(session, WRATH_MELEE_MODE)
    session.submit(P1, DecisionResponse(("guard",)))

    assert session.game.table.cards_by_id["monk"].bowed
    discard = session.game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.DYNASTY_DISCARD)]
    assert "guard" in {card.id for card in discard.cards}


def test_wrath_of_the_shattered_star_gives_two_opposed_personalities_fire_and_force():
    session = _wrath_battle()

    _wrath_with(session, WRATH_FIRE_MODE)
    session.submit(P1, DecisionResponse(("monk", "samurai")))

    for card_id in ("monk", "samurai"):
        card = session.game.table.cards_by_id[card_id]
        assert has_keyword(session.game, card, keywords.FIRE)
        assert effective_force(session.game, card) == 2 + 2


def test_wrath_of_the_shattered_star_from_a_bowed_monk_does_nothing():
    session = _wrath_battle()
    session.game.table.cards_by_id["monk"].bow()

    session.act(P1, PlayStrategy("wrath"))
    session.submit(P1, DecisionResponse(("monk",)))

    assert session.game.pending is None
    assert effective_force(session.game, session.game.table.cards_by_id["samurai"]) == 2


# --- Togashi Chiyo ---


def _chiyo_battle() -> EngineSession:
    """Chiyo at the battlefield against P2's 1F weakling, 1F second and 5F veteran."""
    return combat_segment(
        [
            personality("chiyo", printed_id="togashi_chiyo", force=4),
            personality("weakling", owner=PlayerId.P2, force=1),
            personality("second", owner=PlayerId.P2, force=1),
            personality("veteran", owner=PlayerId.P2, force=5),
        ],
        {"chiyo": 0},
        {"weakling": 0, "second": 0, "veteran": 0},
    )


def _destroyed(session: EngineSession) -> set[str]:
    discard = session.game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.DYNASTY_DISCARD)]
    return {card.id for card in discard.cards}


def test_togashi_chiyo_may_bow_for_a_second_melee_after_the_first_destroys_a_card():
    session = _chiyo_battle()

    session.act(P1, ActivateAbility("chiyo"))
    session.submit(P1, DecisionResponse(("weakling",)))
    session.submit(P1, DecisionResponse(("chiyo",)))  # yes, bow Chiyo
    session.submit(P1, DecisionResponse(("second",)))

    assert session.game.table.cards_by_id["chiyo"].bowed
    assert _destroyed(session) == {"weakling", "second"}


def test_togashi_chiyo_declining_the_second_melee_leaves_him_unbowed():
    session = _chiyo_battle()

    session.act(P1, ActivateAbility("chiyo"))
    session.submit(P1, DecisionResponse(("weakling",)))
    session.submit(P1, DecisionResponse(()))  # no

    assert session.game.pending is None
    assert not session.game.table.cards_by_id["chiyo"].bowed
    assert _destroyed(session) == {"weakling"}


def test_togashi_chiyo_offers_no_second_melee_when_the_first_destroys_nothing():
    session = _chiyo_battle()

    session.act(P1, ActivateAbility("chiyo"))
    session.submit(P1, DecisionResponse(("veteran",)))

    assert session.game.pending is None
    assert not session.game.table.cards_by_id["chiyo"].bowed
    assert _destroyed(session) == set()


# --- Burnt Offering ---


def _burnt_offering_battle(*, ring: bool = False) -> EngineSession:
    """P1's Monk against P2's guard, who carries a Follower and an Item, at the battlefield, and
    Burnt Offering in P1's hand. ``ring`` puts a Ring in P1's play."""
    in_play = [
        personality("monk", keywords=(keywords.MONK,)),
        personality("guard", owner=PlayerId.P2),
    ]
    if ring:
        in_play.append(
            L5RCard.of(
                RingPrint, id="ring", printed_id="ring", name="ring", side=Side.FATE, owner=P1
            )
        )
    session = combat_segment(in_play, {"monk": 0}, {"guard": 0})
    table = session.game.table
    follower = attachment(
        "spear", owner=PlayerId.P2, attachment_type=AttachmentType.FOLLOWER, force=1
    )
    attached(table, follower, "guard")
    attached(table, attachment("helm", owner=PlayerId.P2), "guard")
    offering = L5RCard.of(
        FatePrint,
        id="offering",
        printed_id="burnt_offering",
        name="Burnt Offering",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
        keywords=(keywords.FIRE,),
    )
    table.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(table, offering))
    return session


def _offer(session: EngineSession, destroyed: str) -> L5RCard:
    session.act(P1, PlayStrategy("offering"))
    session.submit(P1, DecisionResponse(("monk",)))
    session.submit(P1, DecisionResponse((destroyed,)))
    return session.game.table.cards_by_id["monk"]


@pytest.mark.parametrize(("destroyed", "force"), [("spear", 4), ("helm", 2)])
def test_burnt_offering_gives_force_only_when_the_personality_is_left_without_followers(
    destroyed, force
):
    session = _burnt_offering_battle()

    monk = _offer(session, destroyed)

    assert effective_force(session.game, monk) == force
    assert effective_chi(session.game, monk) == 3


def test_burnt_offering_gives_chi_while_you_control_a_ring():
    session = _burnt_offering_battle(ring=True)

    monk = _offer(session, "helm")

    assert effective_chi(session.game, monk) == 3 + 2


# --- Matsu Kurutta ---


def test_matsu_kurutta_gives_a_deathseeker_at_his_battlefield_a_force_token_as_he_dies():
    units = [
        personality("attacker", force=5),
        personality(
            "kurutta", owner=PlayerId.P2, printed_id="matsu_kurutta", keywords=("Deathseeker",)
        ),
        personality("comrade", owner=PlayerId.P2, keywords=("Deathseeker",)),
        personality("at_home", owner=PlayerId.P2, keywords=("Deathseeker",)),
    ]
    game = combat_segment(units, {"attacker": 0}, {"kurutta": 0, "comrade": 0}).game
    comrade = game.table.cards_by_id["comrade"]
    force = effective_force(game, comrade)

    resolve_effects(game, [Destroy("kurutta", PlayerId.P1)])
    assert game.pending.seat is PlayerId.P2
    assert set(game.pending.candidates) == {"kurutta", "comrade"}
    submit(game, DecisionResponse(("comrade",)))

    assert comrade.counters == {"plus1f": 1}
    assert effective_force(game, comrade) == force + 1


# --- Akodo Iori ---


def _strategy(card_id, keywords):
    return L5RCard.of(
        ActionPrint,
        id=card_id,
        name=card_id,
        printed_id=card_id,
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
        keywords=keywords,
    )


def _iori_game():
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1, gold_production=12))
    for index in range(1, 4):
        province_card(state, f"filler{index}", seat=P1, index=index)
    sought = (("virtue", ("Bushido Virtue",)), ("tactics", ("Tactical",)), ("plain", ()))
    state.decks[DeckKey(P1, Side.FATE)].cards = [
        register(state, _strategy(card_id, carried)) for card_id, carried in sought
    ]
    iori = register(state, personality("iori", printed_id="akodo_iori", chi=3, gold_cost=4))
    iori.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(iori)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)
    return session


def test_akodo_ioris_invest_finds_a_bushido_virtue_or_a_tactical_strategy():
    session = _iori_game()

    session.act(P1, ActivateAbility("iori", RECRUIT_WITH_INVEST))
    pay(session, P1)
    assert set(session.game.pending.candidates) == {"virtue", "tactics"}
    session.submit(P1, DecisionResponse(("tactics",)))

    assert "tactics" in {card.id for card in cards_in_hand(session.game, P1)}


def test_akodo_iori_permanently_gives_a_personality_at_his_battlefield_tactician_as_he_dies():
    units = [
        personality("attacker", force=5),
        personality("iori", owner=PlayerId.P2, printed_id="akodo_iori"),
        personality("comrade", owner=PlayerId.P2, force=9),
        personality("at_home", owner=PlayerId.P2),
    ]
    session = combat_segment(units, {"attacker": 0}, {"iori": 0, "comrade": 0})
    game = session.game

    resolve_effects(game, [Destroy("iori", P1)])
    assert set(game.pending.candidates) == {"iori", "comrade"}
    submit(game, DecisionResponse(("comrade",)))
    end_turn(session)

    assert has_keyword(game, game.table.cards_by_id["comrade"], keywords.TACTICIAN)


# --- Yabe no Oni, Blessed Abomination (Experienced) ---


def _yabe_game():
    game = two_seat_game()
    token_template(
        game,
        LESSER_ONI,
        name="Lesser Oni",
        card_type="Personality",
        keywords=("Nonhuman", "Oni", "Shadowlands"),
        force=2,
        chi=1,
    )
    yabe = personality(
        "yabe",
        printed_id="yabe_no_oni_blessed_abomination_experienced",
        force=6,
        chi=2,
        keywords=("Nonhuman", "Oni"),
    )
    put_in_play(game, yabe)
    return game


def _lesser_oni(game):
    return [card for card in personalities_in_play(game) if card.name == "Lesser Oni"]


def test_yabe_no_oni_costs_six_honor_as_he_enters_play():
    game = _yabe_game()

    fire(game, EnteredPlay("yabe"))

    assert game.table.seats[P1].honor == -6


@pytest.mark.parametrize(("carried", "created"), [((), 1), (("Oni",), 0)], ids=["human", "oni"])
def test_yabe_no_oni_creates_an_oni_after_a_non_oni_personality_is_destroyed(carried, created):
    game = _yabe_game()
    put_in_play(game, personality("victim", owner=PlayerId.P2, keywords=carried))

    resolve_effects(game, [Destroy("victim", P1)])

    assert len(_lesser_oni(game)) == created


def test_yabe_no_oni_creates_two_oni_as_he_dies_in_battle_resolution():
    game = _yabe_game()

    resolve_effects(game, [Destroy("yabe", Rulebook.BATTLE_RESOLUTION)])

    assert len(_lesser_oni(game)) == 2


# --- Desperate Ground ---


def _desperate_ground_battle(enemy="guard"):
    units = [
        personality("raider"),
        personality("second"),
        personality("guard", owner=PlayerId.P2, printed_id=enemy),
        personality("armed", owner=PlayerId.P2),
    ]
    game = combat_segment(units, {"raider": 0, "second": 0}, {"guard": 0, "armed": 0}).game
    attached(game, attachment("blade", owner=PlayerId.P2), "armed")
    terrain_at(game, "desperate_ground", 0)
    return game


def test_desperate_ground_gives_your_dying_personality_a_yu_against_an_enemy_card():
    game = _desperate_ground_battle()

    resolve_effects(game, [Destroy("raider", PlayerId.P2)])
    assert game.pending.seat is P1
    assert set(game.pending.candidates) == {"guard", "blade"}
    submit(game, DecisionResponse(("guard",)))

    assert "guard" not in {card.id for card in game.table.battlefield.cards}


def test_desperate_ground_gives_your_follower_its_yu_and_your_unit_at_home_none():
    game = _desperate_ground_battle()
    attached(game, attachment("spear", attachment_type=AttachmentType.FOLLOWER), "raider")
    put_in_play(game, personality("home"))

    resolve_effects(game, [Destroy("home", PlayerId.P2)])
    at_home = game.pending
    resolve_effects(game, [Destroy("spear", PlayerId.P2)])

    assert at_home is None
    assert game.pending.seat is P1 and "guard" in game.pending.candidates


def test_desperate_ground_gives_no_yu_to_an_enemy():
    game = _desperate_ground_battle()

    resolve_effects(game, [Destroy("guard", P1)])

    assert game.pending is None


def test_two_personalities_dying_under_desperate_ground_are_ordered_apart():
    game = _desperate_ground_battle()

    resolve_effects(
        game,
        [Simultaneously((Destroy("raider", PlayerId.P2), Destroy("second", PlayerId.P2)))],
    )

    assert isinstance(game.pending, ChooseNextTrigger)
    assert set(game.pending.candidates) == {"raider", "second"}
    submit(game, DecisionResponse(("raider",)))
    submit(game, DecisionResponse(("guard",)))
    submit(game, DecisionResponse(("second",)))
    submit(game, DecisionResponse(("blade",)))

    on_table = {card.id for card in game.table.battlefield.cards}
    assert on_table & {"guard", "blade", "raider", "second"} == set()


def test_a_card_a_yu_destroys_resolves_no_yu_of_its_own():
    game = _desperate_ground_battle(enemy="bayushi_purimu")

    resolve_effects(game, [Destroy("raider", PlayerId.P2)])
    submit(game, DecisionResponse(("guard",)))

    assert "guard" not in {card.id for card in game.table.battlefield.cards}
    assert game.pending is None


def test_a_personality_with_its_own_yu_under_desperate_ground_offers_both_by_their_text():
    kurutta = L5RCard.of(
        PersonalityPrint,
        id="kurutta",
        name="Matsu Kurutta",
        side=Side.DYNASTY,
        owner=P1,
        printed_id="matsu_kurutta",
        force=2,
        chi=3,
        keywords=("Deathseeker",),
        text="Yu: Give your target Deathseeker a +1F token.",
    )
    units = [kurutta, personality("other"), personality("guard", owner=PlayerId.P2)]
    game = combat_segment(units, {"kurutta": 0, "other": 0}, {"guard": 0}).game
    ground = L5RCard.of(
        ActionPrint,
        id="ground",
        name="Desperate Ground",
        side=Side.FATE,
        owner=P1,
        printed_id="desperate_ground",
        keywords=("Terrain",),
        text='Your Followers and Personalities at this battlefield have, "Yu: Destroy a target '
        'enemy card without attachments."',
    )
    put_in_play(game, ground)
    ops.set_location(game.table, ground, Location.at_battlefield(0))

    resolve_effects(game, [Destroy("kurutta", PlayerId.P2)])

    assert game.pending.candidates == ("kurutta#1", "kurutta#2")
    assert set(game.pending.labels) == {
        "Yu: Give your target Deathseeker a +1F token.",
        "Yu: Destroy a target enemy card without attachments.",
    }


# --- The First Kengun ---


def _first_kengun_battle():
    units = [personality("leader"), personality("enemy", owner=PlayerId.P2, force=2)]
    session = combat_segment(units, {"leader": 0}, {"enemy": 0})
    kengun = attachment(
        "kengun",
        printed_id="the_first_kengun",
        attachment_type=AttachmentType.FOLLOWER,
        force=2,
        keywords=("Obsidian Legion",),
    )
    attached(session.game, kengun, "leader")
    attached(session.game, attachment("katana", owner=PlayerId.P2, force=1), "enemy")
    return session


def test_the_first_kengun_gives_your_dying_follower_a_yu_that_adds_a_recruit_token():
    game = _first_kengun_battle().game
    attached(game, attachment("ashigaru", attachment_type=AttachmentType.FOLLOWER), "leader")

    resolve_effects(game, [Destroy("ashigaru", PlayerId.P2)])
    assert game.pending.candidates == ("kengun",)
    submit(game, DecisionResponse(("kengun",)))

    assert game.table.cards_by_id["kengun"].counters.get("recruit") == 1


def test_the_first_kengun_fear_reaches_an_item_with_its_recruit_tokens_and_destroys_it():
    session = _first_kengun_battle()
    resolve_effects(session.game, [AdjustCounter("kengun", counter_from_key("recruit"), 1)])

    session.act(P1, ActivateAbility("kengun"))
    assert set(session.game.pending.candidates) == {"enemy", "katana"}
    session.submit(P1, DecisionResponse(("katana",)))

    assert "katana" not in {card.id for card in session.game.table.battlefield.cards}


def test_the_first_kengun_fear_only_bows_a_personality():
    session = _first_kengun_battle()
    resolve_effects(session.game, [AdjustCounter("kengun", counter_from_key("recruit"), 2)])

    session.act(P1, ActivateAbility("kengun"))
    session.submit(P1, DecisionResponse(("enemy",)))

    assert session.game.table.cards_by_id["enemy"].bowed


# --- The Head of My Enemy (Experienced) ---


def _head_of_my_enemy(state: TableState) -> L5RCard:
    head = L5RCard.of(
        ActionPrint,
        id="head",
        name="The Head of My Enemy",
        printed_id="the_head_of_my_enemy_experienced",
        side=Side.FATE,
        owner=P1,
        text='<b>Engage:</b> Give a target Personality, "Yu: The enemy leader takes :favor: and '
        'gains 2 Honor."',
    )
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, head))
    return head


def test_the_head_of_my_enemy_banishes_a_dead_enemy_to_give_your_personality_a_token():
    state = TableState.empty_two_seat()
    put_in_play(state, personality("mine"))
    fallen = register(state, personality("fallen", owner=PlayerId.P2))
    state.zones[ZoneKey(PlayerId.P2, ZoneRole.DYNASTY_DISCARD)].add(fallen)
    _head_of_my_enemy(state)
    session = EngineSession.start(state, P1)

    session.act(P1, PlayStrategy("head", "banish"))
    session.submit(P1, DecisionResponse(("fallen",)))
    session.submit(P1, DecisionResponse(("mine",)))

    discard = session.game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.DYNASTY_DISCARD)].cards
    assert "fallen" not in {card.id for card in discard}
    assert session.game.table.cards_by_id["mine"].counters == {"plus1f_plus1c": 1}


def _head_of_my_enemy_engaged() -> EngineSession:
    """P1's attack in its Engage Segment, with The Head of My Enemy played on P2's "guard"."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov", seat=P1, index=0)
    province_card(state, "def-prov", seat=PlayerId.P2, index=0)
    put_in_play(state, personality("raider", force=3))
    put_in_play(state, personality("guard", owner=PlayerId.P2))
    put_in_play(state, personality("watch", owner=PlayerId.P2))
    _head_of_my_enemy(state)
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("raider@0",)))
    session.submit(PlayerId.P2, DecisionResponse(("guard@0", "watch@0")))
    session.submit(P1, DecisionResponse(("0",)))
    session.act(PlayerId.P2, Pass())
    session.act(P1, PlayStrategy("head", "yu"))
    session.submit(P1, DecisionResponse(("guard",)))
    return session


def test_the_head_of_my_enemy_gives_a_yu_that_outlasts_the_strategy():
    session = _head_of_my_enemy_engaged()
    honor = session.game.table.seats[P1].honor

    resolve_effects(session.game, [Destroy("guard", P1)])

    assert "head" not in {card.id for card in session.game.table.battlefield.cards}
    assert session.game.favor_holder is P1
    assert session.game.table.seats[P1].honor == honor + 2


def test_the_head_of_my_enemy_gives_its_yu_to_the_target_alone():
    session = _head_of_my_enemy_engaged()
    honor = session.game.table.seats[P1].honor

    resolve_effects(session.game, [Destroy("watch", P1)])

    assert session.game.favor_holder is not P1
    assert session.game.table.seats[P1].honor == honor


# --- Isawa Eijiri, Warmonger ---


def _eijiri_battle():
    units = [
        personality(
            "eijiri", printed_id="isawa_eijiri_warmonger", force=5, keywords=("Shugenja", "Fire")
        ),
        personality("enemy", owner=PlayerId.P2),
    ]
    game = combat_segment(units, {"eijiri": 0}, {"enemy": 0}).game
    blaze = attachment("blaze", attachment_type=AttachmentType.SPELL, keywords=("Fire",))
    attached(game, blaze, "eijiri")
    return game


def _eijiri_empowered(game) -> bool:
    eijiri = game.table.cards_by_id["eijiri"]
    return effective_force(game, eijiri) == 7 and has_keyword(game, eijiri, keywords.CONQUEROR)


def test_isawa_eijiri_gives_his_fire_spell_a_yu_empowering_your_fire_shugenja():
    game = _eijiri_battle()

    resolve_effects(game, [Destroy("blaze", PlayerId.P2)])

    assert _eijiri_empowered(game)


@pytest.mark.parametrize(("answer", "empowered"), [(("blaze",), True), ((), False)])
def test_isawa_eijiri_lets_you_choose_his_spells_yu_when_your_action_destroys_it(answer, empowered):
    game = _eijiri_battle()

    resolve_effects(game, [Destroy("blaze", P1)])
    assert isinstance(game.pending, Confirm) and game.pending.seat is P1
    submit(game, DecisionResponse(answer))

    assert _eijiri_empowered(game) is empowered


# A test-only Spell printing its own Yu, outside the Fire Spells Eijiri gives one to.
register_yu("eijiri_spell_probe", lambda ctx: [GainHonor(ctx.card.owner, 1)])


def test_isawa_eijiri_offers_the_choice_for_any_of_his_spells_with_a_yu():
    game = _eijiri_battle()
    ward = attachment("ward", printed_id="eijiri_spell_probe", attachment_type=AttachmentType.SPELL)
    attached(game, ward, "eijiri")

    resolve_effects(game, [Destroy("ward", P1)])
    submit(game, DecisionResponse(("ward",)))

    assert game.table.seats[P1].honor == 1
