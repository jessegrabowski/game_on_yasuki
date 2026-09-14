from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility, DeclareAttack, Pass
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseAbilityTarget,
    DecisionResponse,
)
from yasuki_core.engine.rules.gold.production import effective_gold_production
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import AttachmentType, Side


from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    fate_card,
    holding,
    personality,
    province_card,
    put_in_play,
    register,
)

P1 = PlayerId.P1
ATTACKER, DEFENDER = PlayerId.P1, PlayerId.P2


def _otokoshi_game():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("oto", printed_id="otokoshi_district", gold_production=2))
    put_in_play(state, holding("mkt", printed_id="market", keywords=("Market",), gold_production=1))
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card("fd", P1))]
    return EngineSession.start(state, P1)


def test_otokoshi_destroys_itself_to_draw_and_seed_a_market():
    session = _otokoshi_game()
    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)]
    before = len(hand.cards)

    session.act(P1, ActivateAbility("oto"))
    session.submit(P1, DecisionResponse(("mkt",)))

    table = session.game.table
    discard = table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert "oto" in {c.id for c in discard.cards}  # destroyed itself as the cost
    assert len(hand.cards) == before + 1  # drew a card
    assert table.cards_by_id["mkt"].counters.get("wealth") == 1  # market seeded a wealth token


def test_otokoshi_is_not_activatable_without_a_market():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("oto", printed_id="otokoshi_district", gold_production=2))
    session = EngineSession.start(state, P1)
    assert ActivateAbility("oto") not in session.legal_actions(P1)


def test_otokoshi_activation_replays_to_the_same_state():
    session = _otokoshi_game()
    session.act(P1, ActivateAbility("oto"))
    session.submit(P1, DecisionResponse(("mkt",)))
    assert replay(session.log) == session.game


def _ichiba_game(fate_cards: int = 1, ports: int = 1) -> EngineSession:
    state = TableState.empty_two_seat()
    put_in_play(
        state, holding("ich", printed_id="ichiba_district", keywords=("Market",), gold_production=1)
    )
    for i in range(ports):
        put_in_play(
            state,
            holding(f"port{i}", printed_id="island_wharf", keywords=("Port",), gold_production=2),
        )
    state.decks[DeckKey(P1, Side.FATE)].cards = [
        register(state, fate_card(f"fd{i}", P1)) for i in range(fate_cards)
    ]
    return EngineSession.start(state, P1)


def test_ichiba_banishes_the_top_fate_card_then_boosts_a_target_port():
    session = _ichiba_game(fate_cards=2, ports=1)
    session.act(P1, ActivateAbility("ich"))

    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget) and pending.candidates == ("port0",)
    table = session.game.table
    banished = table.zones[ZoneKey(P1, ZoneRole.FATE_BANISH)]
    assert [c.id for c in banished.cards] == ["fd1"]  # the top (drawn end), not the bottom
    assert [c.id for c in table.decks[DeckKey(P1, Side.FATE)].cards] == ["fd0"]  # the rest

    session.submit(P1, DecisionResponse(("port0",)))
    assert effective_gold_production(session.game, table.cards_by_id["port0"]) == 3  # base 2 + 1


def test_ichiba_is_not_activatable_with_an_empty_fate_deck():
    session = _ichiba_game(fate_cards=0, ports=1)
    assert ActivateAbility("ich") not in session.legal_actions(P1)


def test_ichiba_is_not_activatable_without_a_port():
    session = _ichiba_game(fate_cards=1, ports=0)
    assert ActivateAbility("ich") not in session.legal_actions(P1)


def test_ichiba_activation_replays_to_the_same_state():
    session = _ichiba_game(fate_cards=2, ports=1)
    session.act(P1, ActivateAbility("ich"))
    session.submit(P1, DecisionResponse(("port0",)))
    assert replay(session.log) == session.game


def _bunrakuken_battle(
    followers: tuple[str, ...] = ("sword",), *, defending_follower_force: int = 2
) -> EngineSession:
    """The Combat Segment of an attack led by Bunrakuken, carrying ``followers`` -- Bunrakuken's
    own attached Followers, the pool "Bunrakuken's target Follower" destroys the cost from. The
    Defender brings a 2F Personality with a Follower at ``defending_follower_force``, default 2,
    which a Ranged 2 destroys."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(
        state, personality("bun", owner=ATTACKER, printed_id="yoritomo_bunrakuken", force=4)
    )
    for follower_id in followers:
        attached(
            state,
            attachment(follower_id, attachment_type=AttachmentType.FOLLOWER, force=1),
            "bun",
        )
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    attached(
        state,
        attachment(
            "ashigaru",
            owner=DEFENDER,
            attachment_type=AttachmentType.FOLLOWER,
            force=defending_follower_force,
        ),
        "guard",
    )
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("bun@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0",)))
    session.submit(ATTACKER, DecisionResponse(("0",)))
    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())
    session.act(DEFENDER, Pass())
    return session


def _in_play(session: EngineSession, card_id: str) -> bool:
    table = session.game.table
    return table.cards_by_id[card_id] in table.battlefield.cards


def test_bunrakuken_destroys_its_own_follower_to_make_the_ranged_attack():
    session = _bunrakuken_battle()

    session.act(ATTACKER, ActivateAbility("bun"))
    session.submit(ATTACKER, DecisionResponse(("ashigaru",)))

    assert not _in_play(session, "sword")  # destroyed to pay the cost
    assert not _in_play(session, "ashigaru")  # the Ranged 2 destroyed the target


def test_bunrakuken_spares_a_follower_the_ranged_2_cannot_reach():
    """Ranged X destroys only a target at X Force or less (CR, Ranged Attack), so a 3F Follower
    survives -- and the Follower Bunrakuken paid is gone either way."""
    session = _bunrakuken_battle(defending_follower_force=3)

    session.act(ATTACKER, ActivateAbility("bun"))
    session.submit(ATTACKER, DecisionResponse(("ashigaru",)))

    assert _in_play(session, "ashigaru")
    assert not _in_play(session, "sword")


def test_bunrakuken_is_not_activatable_with_no_follower_to_destroy():
    session = _bunrakuken_battle(followers=())
    assert ActivateAbility("bun") not in session.legal_actions(ATTACKER)


def test_bunrakuken_lets_the_seat_choose_which_of_his_followers_to_destroy():
    session = _bunrakuken_battle(followers=("sword", "bow"))

    session.act(ATTACKER, ActivateAbility("bun"))
    session.submit(ATTACKER, DecisionResponse(("bow",)))  # which of Bunrakuken's Followers
    session.submit(ATTACKER, DecisionResponse(("ashigaru",)))  # the Ranged Attack's target

    assert not _in_play(session, "bow")
    assert _in_play(session, "sword")  # only the chosen Follower was destroyed
    assert not _in_play(session, "ashigaru")


def test_bunrakuken_activation_replays_to_the_same_state():
    session = _bunrakuken_battle()
    session.act(ATTACKER, ActivateAbility("bun"))
    session.submit(ATTACKER, DecisionResponse(("ashigaru",)))
    assert replay(session.log) == session.game


def _mantis_kama_battle(
    *,
    defender_followers: tuple[str, ...] = ("f1", "f2"),
    home_followers: tuple[str, ...] = (),
) -> EngineSession:
    """The Combat Segment of an attack where the Attacker's Personality wields Mantis Kama, and
    the Defender brings a Personality with ``defender_followers`` -- the pool "one or two target
    Followers" is drawn from. ``home_followers`` go on a second Defender who stays home, so they
    are in play but beyond the battle. Default none."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("wielder", owner=ATTACKER, force=3))
    attached(state, attachment("kama", owner=ATTACKER, printed_id="mantis_kama"), "wielder")
    put_in_play(state, personality("guard", owner=DEFENDER, force=3))
    for follower_id in defender_followers:
        attached(
            state,
            attachment(
                follower_id, owner=DEFENDER, attachment_type=AttachmentType.FOLLOWER, force=3
            ),
            "guard",
        )
    if home_followers:
        put_in_play(state, personality("homebody", owner=DEFENDER, force=3))
        for follower_id in home_followers:
            attached(
                state,
                attachment(
                    follower_id, owner=DEFENDER, attachment_type=AttachmentType.FOLLOWER, force=3
                ),
                "homebody",
            )
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("wielder@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0",)))
    session.submit(ATTACKER, DecisionResponse(("0",)))
    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())
    session.act(DEFENDER, Pass())
    return session


def test_mantis_kama_gives_a_target_personality_minus_two_force():
    session = _mantis_kama_battle(defender_followers=())

    session.act(ATTACKER, ActivateAbility("kama"))
    session.submit(ATTACKER, DecisionResponse(("guard",)))

    table = session.game.table
    assert effective_force(session.game, table.cards_by_id["guard"]) == 1  # base 3 - 2
    assert table.cards_by_id["kama"].bowed  # paid the Battle, Bow cost


def test_mantis_kama_may_hit_a_second_target_follower():
    session = _mantis_kama_battle()

    session.act(ATTACKER, ActivateAbility("kama"))
    session.submit(ATTACKER, DecisionResponse(("f1",)))
    session.submit(ATTACKER, DecisionResponse(("f2",)))

    table = session.game.table
    assert effective_force(session.game, table.cards_by_id["f1"]) == 1  # base 3 - 2
    assert effective_force(session.game, table.cards_by_id["f2"]) == 1  # base 3 - 2


def test_mantis_kama_the_second_follower_is_optional():
    session = _mantis_kama_battle()

    session.act(ATTACKER, ActivateAbility("kama"))
    session.submit(ATTACKER, DecisionResponse(("f1",)))
    session.submit(ATTACKER, DecisionResponse(()))  # decline a second target

    table = session.game.table
    assert effective_force(session.game, table.cards_by_id["f1"]) == 1
    assert effective_force(session.game, table.cards_by_id["f2"]) == 3  # untouched


def test_mantis_kama_does_not_reach_a_second_follower_away_from_the_battle():
    """The second Follower is picked through a Choose the effect raises, which the central target
    filter never sees, so the Rules of Location have to hold here too (CR, Rules of Location)."""
    session = _mantis_kama_battle(defender_followers=("f1",), home_followers=("faraway",))

    session.act(ATTACKER, ActivateAbility("kama"))
    assert "faraway" not in session.game.pending.candidates
    session.submit(ATTACKER, DecisionResponse(("f1",)))

    table = session.game.table
    assert session.game.pending is None  # nothing at the battle left to offer
    assert effective_force(session.game, table.cards_by_id["faraway"]) == 3  # untouched


def test_mantis_kama_is_not_activatable_outside_battle():
    state = TableState.empty_two_seat()
    put_in_play(state, personality("wielder", owner=ATTACKER, force=3))
    attached(state, attachment("kama", owner=ATTACKER, printed_id="mantis_kama"), "wielder")
    session = EngineSession.start(state, ATTACKER)
    assert ActivateAbility("kama") not in session.legal_actions(ATTACKER)


def test_mantis_kama_activation_replays_to_the_same_state():
    session = _mantis_kama_battle()
    session.act(ATTACKER, ActivateAbility("kama"))
    session.submit(ATTACKER, DecisionResponse(("f1",)))
    session.submit(ATTACKER, DecisionResponse(("f2",)))
    assert replay(session.log) == session.game
