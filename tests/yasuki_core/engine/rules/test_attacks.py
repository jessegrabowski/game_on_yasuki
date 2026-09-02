import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import DeclareAttack
from yasuki_core.engine.rules.decisions import ChooseBattlefield, DecisionResponse
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
