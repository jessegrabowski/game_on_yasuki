import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility, DeclareAttack, Equip, Pass
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.decisions import ChooseBattlefield, DecisionResponse
from yasuki_core.engine.rules.abilities import ability_for
from yasuki_core.engine.rules.effects import Fear, MeleeAttack, RangedAttack
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.units import attackable
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    holding,
    pay,
    register,
    personality,
    province_card,
    put_in_play,
)

ATTACKER, DEFENDER = PlayerId.P1, PlayerId.P2


@pytest.fixture
def battle():
    """A battle at the Defender's first Province, both sides holding a plain Personality.

    The Attacker also keeps one at home and the Defender has a second Province, so "the current
    enemy army" can be told from "the enemy's cards".
    """
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    for index in range(2):
        province_card(state, f"def-prov{index}", seat=DEFENDER, index=index)
    put_in_play(state, personality("raider", owner=ATTACKER, force=3))
    put_in_play(state, personality("reserve", owner=ATTACKER, force=2))
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    put_in_play(state, personality("watch", owner=DEFENDER, force=1))
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("raider@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0", "watch@1")))
    choice = session.game.pending
    assert isinstance(choice, ChooseBattlefield)
    session.submit(choice.seat, DecisionResponse(("0",)))
    return session


def _ids(session, seat):
    return {card.id for card in attackable(session.game, seat)}


def test_it_reaches_the_enemy_army_and_not_the_enemys_other_cards(battle):
    """ "In the current enemy army" is one side of one battlefield, so the Defender's unit at its
    other Province is no target even though the Defender controls it."""
    assert _ids(battle, ATTACKER) == {"guard"}


def test_it_reaches_across_the_battle_rather_than_by_seat(battle):
    """The Defender attacks the attacking army, so each seat's targets are the other's."""
    assert _ids(battle, DEFENDER) == {"raider"}


def test_a_personality_carrying_a_follower_is_spared_and_the_follower_is_not(battle):
    """ "A Follower or a Personality without Followers" — the Follower stands in his place rather
    than beside him, so exactly one of the two is a target."""
    attached(
        battle.game.table,
        attachment("ashigaru", attachment_type=AttachmentType.FOLLOWER, force=1),
        "guard",
    )

    assert _ids(battle, ATTACKER) == {"ashigaru"}


def test_an_item_does_not_protect_the_personality_it_is_attached_to(battle):
    """Only a Follower spares him. An Item hands him a modifier rather than standing in the unit,
    so a Personality carrying one is still a target — and the Item itself is not."""
    attached(
        battle.game.table,
        attachment("katana", attachment_type=AttachmentType.ITEM, force=2),
        "guard",
    )

    assert _ids(battle, ATTACKER) == {"guard"}


def test_every_follower_is_a_target_when_a_personality_carries_several(battle):
    """The rule names Followers rather than one of them, so a unit of three offers two targets and
    shields the Personality behind both."""
    for name in ("ashigaru", "spearmen"):
        attached(
            battle.game.table,
            attachment(name, attachment_type=AttachmentType.FOLLOWER, force=1),
            "guard",
        )

    assert _ids(battle, ATTACKER) == {"ashigaru", "spearmen"}


def test_nothing_is_attackable_outside_a_battle():
    """An attack effect names the current enemy army, which does not exist between battles — so the
    predicate is empty rather than falling back to the whole board."""
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    session = EngineSession.start(state, ATTACKER)

    assert attackable(session.game, ATTACKER) == []


def _resolve(session, attack):
    triggers.resolve_effects(session.game, [attack])


def _in_play(session, card_id):
    """Whether the card is still standing on the table. A destroyed card stays in the registry and
    moves to a discard, so the battlefield is what answers."""
    table = session.game.table
    return table.cards_by_id[card_id] in table.battlefield.cards


@pytest.mark.parametrize("attack", [RangedAttack, MeleeAttack])
def test_an_attack_destroys_a_target_at_or_under_its_strength(battle, attack):
    """ "If its Force is equal to or less than X, destroy it." The guard is 2F, so a 2 kills and the
    boundary is inclusive; Melee follows the same rules as Ranged."""
    _resolve(battle, attack(2, "guard", ATTACKER))

    assert not _in_play(battle, "guard")


@pytest.mark.parametrize("attack", [RangedAttack, MeleeAttack])
def test_an_attack_leaves_a_target_above_its_strength(battle, attack):
    _resolve(battle, attack(1, "guard", ATTACKER))

    assert _in_play(battle, "guard")


def test_fear_bows_rather_than_destroying(battle):
    """Fear is the same targeting and comparison with the other consequence."""
    _resolve(battle, Fear(2, "guard", ATTACKER))

    assert _in_play(battle, "guard")
    assert battle.game.table.cards_by_id["guard"].bowed


def test_fear_leaves_a_target_above_its_strength_standing(battle):
    _resolve(battle, Fear(1, "guard", ATTACKER))

    assert not battle.game.table.cards_by_id["guard"].bowed


def test_the_comparison_reads_the_effective_stat_not_the_printed_one(battle):
    """A 2F guard given +2F survives a Ranged 2 that would have killed him as printed — modifiers
    count, so the comparison goes through the same effective read the rest of the engine uses."""
    battle.game.modifiers.append(
        Modifier("banner", "guard", Stat.FORCE, 2, Duration.UNTIL_END_OF_TURN)
    )

    _resolve(battle, RangedAttack(2, "guard", ATTACKER))

    assert _in_play(battle, "guard")


def test_an_attack_may_be_compared_against_another_stat(battle):
    """ "If a Ranged Attack effect ends up being compared against a different stat than Force,
    compare that stat against the strength instead." The guard is 2F/3C, so the same strength 2
    that destroys him on Force — the case above — leaves him standing on Chi."""
    _resolve(battle, RangedAttack(2, "guard", ATTACKER, compared=Stat.CHI))

    assert _in_play(battle, "guard")


def test_an_attack_on_a_card_that_has_already_left_does_nothing(battle):
    """Attacks are announced before they resolve, so the target can be gone by the time one lands.
    Attacking a card already destroyed changes nothing rather than raising."""
    _resolve(battle, RangedAttack(9, "guard", ATTACKER))
    discard = list(battle.game.table.zones[ZoneKey(DEFENDER, ZoneRole.DYNASTY_DISCARD)].cards)

    _resolve(battle, RangedAttack(9, "guard", ATTACKER))

    assert (
        list(battle.game.table.zones[ZoneKey(DEFENDER, ZoneRole.DYNASTY_DISCARD)].cards) == discard
    )


def test_a_melee_attack_is_not_a_ranged_attack():
    """ "Melee Attacks follow the above rules but are not considered Ranged Attacks." Both destroy,
    so the temptation is to make one a subclass of the other; the CR forbids it, and combining
    turns on the two being different kinds."""
    melee = MeleeAttack(3, "guard", ATTACKER)

    assert not isinstance(melee, RangedAttack)
    assert type(melee) is not RangedAttack


def _roburo_battle():
    """A battle with Daigotsu Roburo attacking a 2F defender who carries no Follower."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("roburo", owner=ATTACKER, printed_id="daigotsu_roburo", force=4))
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("roburo@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0",)))
    session.submit(ATTACKER, DecisionResponse(("0",)))
    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())
    session.act(DEFENDER, Pass())
    return session


def test_roburo_bows_a_defender_his_fear_reaches():
    """ "Battle: Fear 4" against a 2F guard — the whole card, and the first one to route an attack
    effect through a real ability."""
    session = _roburo_battle()

    session.act(ATTACKER, ActivateAbility("roburo"))
    session.submit(ATTACKER, DecisionResponse(("guard",)))

    assert session.game.table.cards_by_id["guard"].bowed


def test_roburo_is_offered_only_inside_a_battle():
    """A Battle designator with no battle open is not a legal action, so the ability cannot be
    taken from the Action Phase."""
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("roburo", owner=ATTACKER, printed_id="daigotsu_roburo", force=4))
    session = EngineSession.start(state, ATTACKER)

    assert ActivateAbility("roburo") not in session.legal_actions(ATTACKER)


def test_haramaki_do_attacks_from_the_personality_it_is_attached_to():
    """An Item's ability is taken from the Item, not from its host — so the action names the Item
    even though it is the Personality standing at the battlefield."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("hero", owner=ATTACKER, force=4))
    attached(
        state,
        attachment("armor", attachment_type=AttachmentType.ITEM, printed_id="haramaki_do"),
        "hero",
    )
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("hero@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0",)))
    session.submit(ATTACKER, DecisionResponse(("0",)))
    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())
    session.act(DEFENDER, Pass())

    session.act(ATTACKER, ActivateAbility("armor"))
    session.submit(ATTACKER, DecisionResponse(("guard",)))

    assert session.game.table.cards_by_id["guard"].bowed


def _follower_battle(printed_id, *, follower_force=1):
    """A battle with a Follower carrying ``printed_id`` equipped to an attacking Personality."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("hero", owner=ATTACKER, force=4))
    attached(
        state,
        attachment(
            "troops",
            attachment_type=AttachmentType.FOLLOWER,
            force=follower_force,
            printed_id=printed_id,
        ),
        "hero",
    )
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("hero@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0",)))
    session.submit(ATTACKER, DecisionResponse(("0",)))
    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())
    session.act(DEFENDER, Pass())
    return session


def test_skeletal_troops_fear_bows_a_defender():
    session = _follower_battle("skeletal_troops")

    session.act(ATTACKER, ActivateAbility("troops"))
    session.submit(ATTACKER, DecisionResponse(("guard",)))

    assert session.game.table.cards_by_id["guard"].bowed


def _equip_from_hand(printed_id, *, gold=6):
    """A seat with gold and a Personality in play, holding ``printed_id`` as a Follower in hand.

    Equipping is how a Follower enters play from hand, which is the arrival its enters-play trait
    keys on — building it onto the table directly would skip the trigger entirely.
    """
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, holding("mine", owner=ATTACKER, gold_production=gold))
    put_in_play(state, personality("hero", owner=ATTACKER, force=3))
    troops = attachment(
        "troops", attachment_type=AttachmentType.FOLLOWER, force=1, printed_id=printed_id
    )
    state.zones[ZoneKey(ATTACKER, ZoneRole.HAND)].add(register(state, troops))
    return EngineSession.start(state, ATTACKER)


@pytest.mark.parametrize(
    ("printed_id", "loss"),
    [("tosekiki", 3), ("skeletal_troops", 2), ("questionable_vassal", 1)],
)
def test_a_follower_that_costs_honor_charges_it_as_it_enters_play(printed_id, loss):
    """Each of these prints "after this Follower enters play, lose N Honor", and the trigger only
    fires on a real arrival — so this is what tells the Equip path from a hand-built board."""
    session = _equip_from_hand(printed_id)
    before = session.game.table.seats[ATTACKER].honor

    session.act(ATTACKER, Equip("troops"))
    session.submit(ATTACKER, DecisionResponse(("hero",)))
    pay(session, ATTACKER)

    assert session.game.table.seats[ATTACKER].honor == before - loss


def test_tosekiki_ranged_destroys_a_defender_and_bows_to_pay():
    """ "Battle, Bow: Ranged 4" — the cost is paid as the attack resolves, so the Follower ends
    bowed and the 2F guard is gone."""
    session = _follower_battle("tosekiki")

    session.act(ATTACKER, ActivateAbility("troops"))
    session.submit(ATTACKER, DecisionResponse(("guard",)))

    assert not _in_play(session, "guard")
    assert session.game.table.cards_by_id["troops"].bowed


def test_ashigaru_spearmen_offers_the_draw_only_when_it_arrives_from_hand():
    """ "After this Follower enters play from your hand" — Equipping is that arrival, so the offer
    is put to the seat rather than resolving silently."""
    session = _equip_from_hand("ashigaru_spearmen")

    session.act(ATTACKER, Equip("troops"))
    session.submit(ATTACKER, DecisionResponse(("hero",)))
    pay(session, ATTACKER)

    assert session.game.pending is not None
    assert "additional card" in session.game.pending.prompt()


def test_ashigaru_spearmen_offers_nothing_when_it_arrives_any_other_way():
    """ "...from your hand" is the whole condition. A Follower an effect attaches from a deck or a
    discard arrives the same way as far as the board is concerned, and offers no draw."""
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("hero", owner=ATTACKER, force=3))
    attached(
        state,
        attachment(
            "troops",
            attachment_type=AttachmentType.FOLLOWER,
            force=1,
            printed_id="ashigaru_spearmen",
        ),
        "hero",
    )
    session = EngineSession.start(state, ATTACKER)

    triggers.fire(session.game, EnteredPlay("troops", from_hand=False))

    assert session.game.pending is None


def _melee_battle(printed_id):
    """A battle with an attacking Personality carrying ``printed_id``, against a 2F defender."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("hero", owner=ATTACKER, printed_id=printed_id, force=4))
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("hero@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0",)))
    session.submit(ATTACKER, DecisionResponse(("0",)))
    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())
    session.act(DEFENDER, Pass())
    return session


@pytest.mark.parametrize("printed_id", ["doji_maya_experienced"], ids=["maya"])
def test_a_melee_attack_destroys_the_defender_it_reaches(printed_id):
    """The first cards to carry a Melee Attack. Both print a strength above the 2F guard, so each
    destroys him — which is what tells a Melee that resolves from a Melee that merely exists."""
    session = _melee_battle(printed_id)

    session.act(ATTACKER, ActivateAbility("hero"))
    session.submit(ATTACKER, DecisionResponse(("guard",)))

    assert not _in_play(session, "guard")


@pytest.mark.parametrize("printed_id", ["doji_maya_experienced"], ids=["maya"])
def test_a_melee_card_emits_a_melee_attack_and_not_a_ranged_one(printed_id):
    """Both kinds destroy, so nothing about the board tells them apart until combining exists —
    which is exactly why the card has to name the right one now. A Melee printed as a Ranged would
    combine with the wrong attacks and no test of the outcome would notice."""
    session = _melee_battle(printed_id)
    source = session.game.table.cards_by_id["hero"]
    ability = ability_for(source)

    effects = ability.effects(session.game, source, session.game.table.cards_by_id["guard"])

    assert [type(effect) for effect in effects] == [MeleeAttack]
