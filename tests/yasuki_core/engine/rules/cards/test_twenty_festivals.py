from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    combat_segment,
    flip_stronghold,
    personality,
)

P1, P2 = PlayerId.P1, PlayerId.P2
GRAND_HALLS = "the_grand_halls_of_the_lion"
UNASSAILABLE_FORTRESS = "the_unassailable_fortress_of_the_crab"


def _offered(session: EngineSession) -> bool:
    return ActivateAbility("sh") in session.legal_actions(P1)


def _halls_battle(*, flipped: bool = False) -> EngineSession:
    """P1's Samurai (2F, 3 PH) opposed by P2's guard, the Grand Halls as P1's Stronghold."""
    samurai = personality("samurai", force=2, personal_honor=3, keywords=("Samurai",))
    guard = personality("guard", owner=P2)
    cards = [flip_stronghold(GRAND_HALLS, flipped=flipped), samurai, guard]
    return combat_segment(cards, {"samurai": 0}, {"guard": 0})


def test_the_halls_give_an_opposed_samurai_force_equal_to_his_personal_honor():
    session = _halls_battle()

    session.act(P1, ActivateAbility("sh"))
    session.submit(P1, DecisionResponse(("samurai",)))

    game = session.game
    assert effective_force(game, game.table.cards_by_id["samurai"]) == 5
    assert not game.table.cards_by_id["sh"].bowed


def test_the_halls_target_only_samurai():
    peasant = personality("peasant", personal_honor=3)
    cards = [flip_stronghold(GRAND_HALLS), peasant, personality("guard", owner=P2)]
    session = combat_segment(cards, {"peasant": 0}, {"guard": 0})

    assert not _offered(session)


def test_the_halls_back_is_tireless_where_the_front_is_not():
    front = _halls_battle()
    front.game.table.cards_by_id["sh"].bow()
    assert not _offered(front)

    back = _halls_battle(flipped=True)
    back.game.table.cards_by_id["sh"].bow()
    assert _offered(back)
    back.act(P1, ActivateAbility("sh"))
    back.submit(P1, DecisionResponse(("samurai",)))

    assert effective_force(back.game, back.game.table.cards_by_id["samurai"]) == 5


def _fortress_battle(*, guards: int) -> EngineSession:
    """P1's bowed hero, carrying a bowed Follower, opposed by ``guards`` enemy Personalities."""
    cards = [
        flip_stronghold(UNASSAILABLE_FORTRESS),
        personality("hero", force=3),
        *(personality(f"guard{index}", owner=P2) for index in range(guards)),
    ]
    session = combat_segment(cards, {"hero": 0}, {f"guard{i}": 0 for i in range(guards)})
    game = session.game
    banner = attached(
        game, attachment("banner", attachment_type=AttachmentType.FOLLOWER, force=1), "hero"
    )
    game.table.cards_by_id["hero"].bow()
    banner.bow()
    return session


def test_the_fortress_straightens_the_personality_and_his_attachments_when_outnumbered():
    session = _fortress_battle(guards=2)

    session.act(P1, ActivateAbility("sh"))
    session.submit(P1, DecisionResponse(("hero",)))

    cards = session.game.table.cards_by_id
    assert not cards["hero"].bowed
    assert not cards["banner"].bowed


def test_the_fortress_leaves_the_attachments_bowed_against_an_army_no_larger():
    session = _fortress_battle(guards=1)

    session.act(P1, ActivateAbility("sh"))
    session.submit(P1, DecisionResponse(("hero",)))

    cards = session.game.table.cards_by_id
    assert not cards["hero"].bowed
    assert cards["banner"].bowed
